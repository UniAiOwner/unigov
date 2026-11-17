import json
import sqlite3
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .db import AG_DIR, DB_PATH, get_db
from .ecosystem import check_ecosystem_sync
from .constants import CODE_EXTENSIONS, DEFAULT_IGNORE_DIRS, normalize_posix_path, is_code_file

console = Console()


def backup_state_db() -> Path:
    backup_dir = AG_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"state_{ts}.db"

    src_conn = sqlite3.connect(DB_PATH)
    dst_conn = sqlite3.connect(dest)
    with dst_conn:
        src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()

    backups = sorted(backup_dir.glob("state_*.db"))
    for old in backups[:-10]:
        old.unlink(missing_ok=True)
    return dest


def run_offline_audit(project_root: Path = Path(".")) -> None:
    conn = get_db()
    vision = conn.execute("SELECT * FROM project_vision WHERE id = 1").fetchone()
    tasks = conn.execute("SELECT * FROM tasks").fetchall()

    backup_path = backup_state_db()

    tracked_files: set[str] = set()
    stale_tasks: list[str] = []
    failed_tasks: list[str] = []

    for t in tasks:
        for f in json.loads(t["target_files_json"] or "[]"):
            norm = normalize_posix_path(f)
            if norm:
                tracked_files.add(norm)
        if t["status"] == "IN_PROGRESS":
            stale_tasks.append(f"{t['task_id']} ({t['title']})")
        elif t["status"] == "FAILED":
            failed_tasks.append(f"{t['task_id']} ({t['title']})")

    from .baseline import load_unigovernor_ignores, should_ignore_path
    ignore_patterns = load_unigovernor_ignores(project_root)

    physical_code_files: set[str] = set()
    for path in project_root.rglob("*"):
        if not path.is_file() or not is_code_file(path):
            continue
        rel_path = path.relative_to(project_root)
        if should_ignore_path(rel_path, ignore_patterns):
            continue
        norm_p = normalize_posix_path(rel_path)
        if norm_p:
            physical_code_files.add(norm_p)

    orphan_files = sorted(list(physical_code_files - tracked_files))
    ghost_files = sorted(list(tracked_files - physical_code_files))

    contract_alerts = check_ecosystem_sync(vision["project_name"])

    console.print(Panel(
        f"[bold green]Backup Created:[/bold green] {backup_path.as_posix()}\n"
        f"[bold]Physical Code Files:[/bold] {len(physical_code_files)} | "
        f"[bold]Tracked in DAG:[/bold] {len(tracked_files)} | "
        f"[bold]Orphan Code Files:[/bold] {len(orphan_files)} | "
        f"[bold]Ghost Files in DAG:[/bold] {len(ghost_files)} | "
        f"[bold]Stale Tasks:[/bold] {len(stale_tasks)} | "
        f"[bold]Upstream Contract Alerts:[/bold] {len(contract_alerts)}",
        title=f"Offline Health Audit: {vision['project_name']}",
        border_style="cyan",
    ))

    high_risk = audit_high_risk_coverage(project_root, physical_code_files)

    if contract_alerts:
        for alert in contract_alerts:
            console.print(f"[bold red]• {alert}[/bold red]")

    if high_risk:
        t_risk = Table(title="⚠️ High Risk / Low Test Coverage (Critical Modules > 200 LOC Without Direct Test)", border_style="red")
        t_risk.add_column("Source File", style="bold red")
        t_risk.add_column("Category", style="yellow")
        t_risk.add_column("LOC", style="white", justify="right")
        t_risk.add_column("Action Needed", style="dim")
        for hr in high_risk[:8]:
            t_risk.add_row(
                hr["file"],
                hr["module"].upper(),
                f"{hr['loc']:,}",
                "Author unit test asserting monetary/schema invariants"
            )
        console.print(t_risk)

    if stale_tasks or failed_tasks:
        table = Table(title="Tasks Requiring Attention")
        table.add_column("Category", style="yellow")
        table.add_column("Task")
        for s in stale_tasks:
            table.add_row("STALE (IN_PROGRESS)", s)
        for f in failed_tasks:
            table.add_row("FAILED", f)
        console.print(table)

    if orphan_files:
        console.print("\n[bold yellow]Orphan Source Files (Not mapped to any DAG task):[/bold yellow]")
        for of in sorted(orphan_files)[:25]:
            console.print(f"  - {of}")


CRITICAL_FINANCIAL_MODULES = {
    "money", "ledger", "payment", "billing", "discount", "tradein",
    "pricing", "invoice", "dao", "migration", "cashdrawer", "stockinward"
}


def audit_high_risk_coverage(project_root: Path, physical_files: set[str]) -> list[dict]:
    """Cross-references critical financial/accounting/transaction code files against test suites.
    Flags any file > 200 LOC with zero matching unit test file.
    """
    all_test_files = {f.lower() for f in physical_files if "test" in f.lower() or "spec" in f.lower()}
    high_risk_alerts: list[dict] = []

    for rel_posix in physical_files:
        lower = rel_posix.lower()
        if any(k in lower for k in CRITICAL_FINANCIAL_MODULES) and not ("test" in lower or "spec" in lower):
            p = project_root / rel_posix
            try:
                loc = sum(1 for l in p.open("r", encoding="utf-8", errors="ignore") if l.strip() and not l.strip().startswith("//"))
            except Exception:
                loc = 0

            if loc >= 200:
                stem = p.stem.lower()
                has_test = any(stem in tf for tf in all_test_files)
                if not has_test:
                    high_risk_alerts.append({
                        "file": rel_posix,
                        "loc": loc,
                        "module": next(k for k in CRITICAL_FINANCIAL_MODULES if k in lower),
                    })

    return sorted(high_risk_alerts, key=lambda x: x["loc"], reverse=True)
