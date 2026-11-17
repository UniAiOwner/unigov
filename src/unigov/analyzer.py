"""UniGov Cross-Artifact Consistency Guard & Architectural Analyzer (Inspired by GitHub Spec-Kit).

Audits 1-to-1 parity between 15-dimension markdown specs, 7-layer feature plans,
and SQLite WBS tasks to prevent orphaned specifications and ghost tasks.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Set

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .db import resolve_gov_dir, get_db
from .constants import normalize_posix_path

console = Console()

INVARIANT_PATTERN = re.compile(
    r"<!-- UNIGOV_INVARIANT_START -->\s*([\s\S]*?)\s*<!-- UNIGOV_INVARIANT_END -->"
)


def extract_invariants_from_markdown(content: str) -> List[Dict[str, Any]]:
    """Extracts machine-readable JSON invariants embedded in markdown specification files."""
    invariants: List[Dict[str, Any]] = []
    matches = INVARIANT_PATTERN.findall(content)
    for m in matches:
        m_str = m.strip()
        if not m_str:
            continue
        try:
            parsed = json.loads(m_str)
            if isinstance(parsed, list):
                invariants.extend(parsed)
            elif isinstance(parsed, dict):
                invariants.append(parsed)
        except Exception:
            # Fallback regex search for invariant IDs like INV-XXX-000 or LAW-000
            ids = re.findall(r"\b(INV-[A-Z0-9_-]+|LAW-[A-Z0-9_-]+)\b", m_str)
            for inv_id in ids:
                invariants.append({"id": inv_id, "title": inv_id, "fallback": True})
    return invariants


def scan_specs_in_directory(root_dir: Path) -> List[Dict[str, Any]]:
    """Scans docs/, PLANNING/, and .unigov/docs/ for specification files and embedded invariants."""
    spec_files: List[Dict[str, Any]] = []
    scan_folders = ["docs", "PLANNING", ".unigov/docs"]

    for folder_name in scan_folders:
        folder_path = root_dir / folder_name
        if not folder_path.is_dir():
            continue

        for md_file in folder_path.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                invs = extract_invariants_from_markdown(content)
                rel_path = md_file.relative_to(root_dir).as_posix()
                spec_files.append({
                    "path": rel_path,
                    "invariants": invs,
                    "title": md_file.stem.replace("_", " ").title(),
                })
            except Exception:
                continue

    return spec_files


def run_artifact_analysis(project_root: Optional[Path] = None) -> Dict[str, Any]:
    """Performs deep cross-artifact consistency analysis between specs and SQLite tasks."""
    root = (project_root or Path.cwd()).resolve()
    gov_dir = resolve_gov_dir(root)
    state_db = gov_dir / "state.db"

    spec_files = scan_specs_in_directory(root)
    all_invariants: Dict[str, Dict[str, Any]] = {}

    for sf in spec_files:
        for inv in sf["invariants"]:
            inv_id = inv.get("id") or inv.get("rule_id") or "UNKNOWN"
            if inv_id not in all_invariants:
                all_invariants[inv_id] = {
                    "id": inv_id,
                    "title": inv.get("title", inv_id),
                    "file": sf["path"],
                    "enforcement": inv.get("enforcement", "BLOCK_BUILD"),
                }

    if not state_db.exists():
        return {
            "project_name": root.name,
            "total_specs": len(spec_files),
            "total_invariants": len(all_invariants),
            "total_tasks": 0,
            "mapped_invariants": 0,
            "orphan_invariants": list(all_invariants.keys()),
            "ghost_tasks": [],
            "consistency_score": 0.0,
            "status": "UNINITIALIZED",
        }

    conn = get_db(root)
    tasks = conn.execute("SELECT * FROM tasks ORDER BY rowid ASC").fetchall()
    total_tasks = len(tasks)

    task_corpus: Dict[str, str] = {}
    for t in tasks:
        text = f"{t['task_id']} {t['title']} {t['description'] or ''} {t['target_files_json'] or ''}"
        task_corpus[t["task_id"]] = text.lower()

    # Match invariants against tasks
    mapped_invariants: Set[str] = set()
    orphan_invariants: List[Dict[str, Any]] = []

    for inv_id, inv_meta in all_invariants.items():
        inv_clean = inv_id.lower()
        matched = False
        for tid, corpus in task_corpus.items():
            if inv_clean in corpus or inv_clean.replace("inv-", "") in corpus:
                matched = True
                mapped_invariants.add(inv_id)
                break
        if not matched:
            orphan_invariants.append(inv_meta)

    # Detect ghost tasks (leaf tasks that don't reference any spec dimension or rule)
    ghost_tasks: List[str] = []
    spec_basenames = [Path(sf["path"]).stem.lower() for sf in spec_files]

    for t in tasks:
        if t["level"] == "TASK":
            tid = t["task_id"]
            corpus = task_corpus[tid]
            has_spec_anchor = False
            for inv_id in all_invariants:
                if inv_id.lower() in corpus or inv_id.lower().replace("inv-", "") in corpus:
                    has_spec_anchor = True
                    break
            if not has_spec_anchor:
                # Check if target files exist in spec basenames
                for sb in spec_basenames:
                    if sb in corpus:
                        has_spec_anchor = True
                        break
            if not has_spec_anchor and total_tasks > 5 and len(all_invariants) > 0:
                ghost_tasks.append(tid)

    total_inv_count = len(all_invariants)
    if total_inv_count == 0:
        score = 100.0 if total_tasks > 0 else 0.0
    else:
        score = round((len(mapped_invariants) / total_inv_count) * 100, 1)

    return {
        "project_name": root.name,
        "total_specs": len(spec_files),
        "total_invariants": total_inv_count,
        "total_tasks": total_tasks,
        "mapped_invariants": len(mapped_invariants),
        "orphan_invariants": orphan_invariants,
        "ghost_tasks": ghost_tasks,
        "consistency_score": score,
        "status": "PASS" if score >= 90.0 and len(ghost_tasks) == 0 else "DRIFT_DETECTED",
    }


def print_analysis_report(result: Dict[str, Any], console_instance: Optional[Console] = None) -> None:
    """Renders a high-density, professional terminal report for unigov analyze."""
    c = console_instance or console
    score = result["consistency_score"]
    color = "green" if score >= 90 else ("yellow" if score >= 70 else "red")

    summary_table = Table(title="📐 Cross-Artifact Consistency Matrix (Spec-Kit SDD)", box=None)
    summary_table.add_column("Dimension", style="cyan", no_wrap=True)
    summary_table.add_column("Count", style="bold white")
    summary_table.add_column("Status / Health", style="dim")

    summary_table.add_row("Specification Docs", str(result["total_specs"]), "Tracked in docs/ & PLANNING/")
    summary_table.add_row("Machine Invariants", str(result["total_invariants"]), "<!-- UNIGOV_INVARIANT --> blocks")
    summary_table.add_row("WBS Tasks in DB", str(result["total_tasks"]), "SQLite state machine tasks")
    summary_table.add_row("Mapped Invariants", str(result["mapped_invariants"]), "Covered by active tasks")
    summary_table.add_row("Orphan Invariants", str(len(result["orphan_invariants"])), "Declared in specs but unassigned")
    summary_table.add_row("Ghost Tasks", str(len(result["ghost_tasks"])), "Tasks lacking spec anchors")
    summary_table.add_row(
        "Parity Score",
        f"[{color}]{score}%[/{color}]",
        "Target: >= 90.0% for CI gate pass"
    )

    c.print(Panel(summary_table, border_style=color, title=f"⬢ UniGov Spec-Kit Analyzer — {result['project_name']}"))

    if result["orphan_invariants"]:
        orphan_table = Table(title="⚠️ Orphan Invariants (Declared in Specs with 0 Assigned Tasks)", box=None)
        orphan_table.add_column("Invariant ID", style="bold yellow")
        orphan_table.add_column("Title", style="white")
        orphan_table.add_column("Source Spec", style="dim cyan")
        orphan_table.add_column("Enforcement", style="red")

        for oi in result["orphan_invariants"][:10]:
            orphan_table.add_row(oi["id"], oi["title"], oi["file"], oi["enforcement"])
        c.print(orphan_table)

    if result["ghost_tasks"]:
        c.print(f"[bold red]❌ Ghost Tasks Detected ({len(result['ghost_tasks'])}):[/bold red] {', '.join(result['ghost_tasks'][:8])}")
