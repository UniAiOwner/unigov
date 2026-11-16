import json
import sqlite3
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .db import AG_DIR, DB_PATH, get_db
from .ecosystem import check_ecosystem_sync

console = Console()

CODE_EXTENSIONS = {".py", ".kt", ".java", ".ts", ".tsx", ".js", ".rs", ".go", ".cpp", ".c", ".h"}
IGNORE_DIRS = {".git", ".antigravity", ".venv", "venv", "node_modules", "build", ".gradle", "__pycache__", "tests"}


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
            tracked_files.add(Path(f).as_posix())
        if t["status"] == "IN_PROGRESS":
            stale_tasks.append(f"{t['task_id']} ({t['title']})")
        elif t["status"] == "FAILED":
            failed_tasks.append(f"{t['task_id']} ({t['title']})")

    from .baseline import load_unigovernor_ignores, should_ignore_path
    ignore_patterns = load_unigovernor_ignores(project_root)

    orphan_files: list[str] = []
    for path in project_root.rglob("*"):
        if not path.is_file():
            continue
        rel_path = path.relative_to(project_root)
        if should_ignore_path(rel_path, ignore_patterns):
            continue
        if path.suffix in CODE_EXTENSIONS:
            rel_posix = rel_path.as_posix()
            if rel_posix not in tracked_files:
                orphan_files.append(rel_posix)

    contract_alerts = check_ecosystem_sync(vision["project_name"])

    console.print(Panel(
        f"[bold green]Backup Created:[/bold green] {backup_path.as_posix()}\n"
        f"[bold]Tracked Files in DAG:[/bold] {len(tracked_files)} | "
        f"[bold]Orphan Code Files:[/bold] {len(orphan_files)} | "
        f"[bold]Stale Tasks:[/bold] {len(stale_tasks)} | "
        f"[bold]Upstream Contract Alerts:[/bold] {len(contract_alerts)}",
        title=f"Offline Health Audit: {vision['project_name']}",
        border_style="cyan",
    ))

    if contract_alerts:
        for alert in contract_alerts:
            console.print(f"[bold red]• {alert}[/bold red]")

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
