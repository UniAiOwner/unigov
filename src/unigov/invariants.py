import os
import json
import re
import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .models import ArchitecturalInvariant, DimensionCoverage, SpecVerificationReport
from .scaffolder import DIMENSION_METADATA

console = Console()

LAYER_HIERARCHY = [
    "LAYER_1_DOMAIN",
    "LAYER_2_DATA",
    "LAYER_3_SURFACES",
    "LAYER_4_SECURITY",
    "LAYER_5_INTELLIGENCE",
]


def extract_invariants_from_text(text: str, source_doc: str = "") -> List[ArchitecturalInvariant]:
    """Scrapes machine-executable <!-- UNIGOV_INVARIANT_START --> blocks from documentation."""
    invariants = []
    matches = re.findall(r"<!--\s*UNIGOV_INVARIANT_START\s*-->([\s\S]*?)<!--\s*UNIGOV_INVARIANT_END\s*-->", text)
    for raw in matches:
        try:
            data = json.loads(raw.strip())
            inv = ArchitecturalInvariant(
                invariant_id=data["id"],
                layer=data.get("layer", "LAYER_1_DOMAIN"),
                title=data.get("title", data["id"]),
                rule_type=data.get("rule_type", "FORBIDDEN_TOKENS"),
                file_patterns=data.get("file_patterns", []),
                params=data.get("params", {}),
                enforcement=data.get("enforcement", "BLOCK_BUILD"),
                source_doc=source_doc,
            )
            invariants.append(inv)
        except Exception as exc:
            console.print(f"[yellow]Warning: Could not parse invariant block in {source_doc}: {exc}[/yellow]")
    return invariants


def sync_invariants_to_db(conn: sqlite3.Connection, invariants: List[ArchitecturalInvariant]) -> None:
    """Stores parsed machine-executable invariants into SQLite invariants table."""
    with conn:
        for inv in invariants:
            conn.execute("""
                INSERT OR REPLACE INTO invariants (
                    invariant_id, layer, title, rule_type, file_patterns_json, params_json, enforcement, source_doc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                inv.invariant_id,
                inv.layer,
                inv.title,
                inv.rule_type,
                json.dumps(inv.file_patterns),
                json.dumps(inv.params),
                inv.enforcement,
                inv.source_doc,
            ))


def apply_topological_phase_locks(conn: sqlite3.Connection) -> Tuple[int, int]:
    """Enforces Constitutional Layer Gating:
    No task in LAYER_3_SURFACES (UI/Hardware) or higher can be READY
    until ALL tasks in LAYER_1_DOMAIN and LAYER_2_DATA are COMPLETED!
    
    Returns (num_blocked, num_unlocked).
    """
    with conn:
        # Check foundation health: Are all L1 and L2 tasks completed?
        uncompleted_foundation = conn.execute("""
            SELECT COUNT(*) AS cnt FROM tasks 
            WHERE layer IN ('LAYER_1_DOMAIN', 'LAYER_2_DATA') 
              AND level = 'TASK' 
              AND status != 'COMPLETED'
        """).fetchone()["cnt"]

        blocked_count = 0
        unlocked_count = 0

        surface_tasks = conn.execute("""
            SELECT task_id, status FROM tasks 
            WHERE layer IN ('LAYER_3_SURFACES', 'LAYER_4_SECURITY', 'LAYER_5_INTELLIGENCE')
              AND level = 'TASK'
        """).fetchall()

        for t in surface_tasks:
            tid = t["task_id"]
            current_status = t["status"]

            if uncompleted_foundation > 0:
                # Foundation is NOT fully completed -> Surfaces MUST be BLOCKED
                if current_status in ("READY", "IN_PROGRESS"):
                    conn.execute("UPDATE tasks SET status = 'BLOCKED' WHERE task_id = ?", (tid,))
                    blocked_count += 1
            else:
                # Foundation IS completed -> Surfaces can transition to READY if dependencies are met
                if current_status == "BLOCKED":
                    # Check task dependencies
                    deps = conn.execute("SELECT depends_on_task_id FROM task_dependencies WHERE task_id = ?", (tid,)).fetchall()
                    if not deps:
                        conn.execute("UPDATE tasks SET status = 'READY' WHERE task_id = ?", (tid,))
                        unlocked_count += 1
                    else:
                        dep_statuses = [
                            conn.execute("SELECT status FROM tasks WHERE task_id = ?", (d["depends_on_task_id"],)).fetchone()["status"]
                            for d in deps
                        ]
                        if all(s == "COMPLETED" for s in dep_statuses):
                            conn.execute("UPDATE tasks SET status = 'READY' WHERE task_id = ?", (tid,))
                            unlocked_count += 1

    return blocked_count, unlocked_count


def verify_project_spec(docs_dir: Path, conn: sqlite3.Connection) -> SpecVerificationReport:
    """Audits the 15-file architectural suite and verifies machine invariants."""
    if not docs_dir.exists():
        console.print(f"[bold red]Error:[/bold red] Documentation directory not found: {docs_dir}")
        return SpecVerificationReport(
            total_dimensions=15,
            covered_dimensions=0,
            readiness_score=0.0,
            dimensions=[],
            invariants_extracted=0,
        )

    all_md_files = [f for f in docs_dir.glob("**/*.md")]
    coverage_list: List[DimensionCoverage] = []
    all_invariants: List[ArchitecturalInvariant] = []

    for meta in DIMENSION_METADATA:
        matched = False
        target_path = None
        inv_count = 0
        dim_idx_prefix = f"{meta['index']:02d}"
        folder_match_name = meta.get("folder_name", "").lower()
        file_match_name = meta.get("filename", "").lower()

        # Match files directly or within modular dimension folder
        matching_files = []
        for ef in all_md_files:
            rel_parts = [p.lower() for p in ef.relative_to(docs_dir).parts]
            # Check if any path part or filename matches this dimension index or name
            if any(part.startswith(dim_idx_prefix) or (folder_match_name and folder_match_name in part) for part in rel_parts) or ef.name.lower().startswith(dim_idx_prefix) or file_match_name in ef.name.lower():
                matching_files.append(ef)

        if matching_files:
            matched = True
            target_path = matching_files[0].parent.as_posix() if len(matching_files) > 1 else matching_files[0].as_posix()
            for mf in matching_files:
                f_text = mf.read_text(encoding="utf-8", errors="ignore")
                extracted = extract_invariants_from_text(f_text, source_doc=mf.as_posix())
                all_invariants.extend(extracted)
                inv_count += len(extracted)

        coverage_list.append(DimensionCoverage(
            dimension_index=meta["index"],
            dimension_name=meta["title"],
            layer=meta["layer"],
            present=matched,
            file_path=target_path,
            invariants_count=inv_count,
        ))

    sync_invariants_to_db(conn, all_invariants)
    covered_cnt = sum(1 for c in coverage_list if c.present)
    score = round((covered_cnt / len(DIMENSION_METADATA)) * 100, 1)

    # Render Rich Scorecard Table
    table = Table(title="15-Dimension Architectural Specification Scorecard", border_style="cyan")
    table.add_column("#", style="bold cyan", width=3)
    table.add_column("Layer", style="dim", width=18)
    table.add_column("Dimension / Architecture Standard", style="white")
    table.add_column("Status", style="bold", width=12)
    table.add_column("Invariants", style="green", width=10)

    for c in coverage_list:
        status_str = "[green]COVERED[/green]" if c.present else "[red]MISSING[/red]"
        inv_str = f"{c.invariants_count} active" if c.invariants_count > 0 else "—"
        table.add_row(
            f"{c.dimension_index:02d}",
            c.layer.replace("LAYER_", "L").replace("_", " "),
            c.dimension_name,
            status_str,
            inv_str,
        )

    console.print(table)

    summary_panel = Panel(
        f"[bold]Total Architectural Dimensions:[/bold] {len(DIMENSION_METADATA)}\n"
        f"• [green]Covered Dimensions:[/green] {covered_cnt} ({score}%)\n"
        f"• [red]Missing Dimensions:[/red] {len(DIMENSION_METADATA) - covered_cnt}\n"
        f"• [cyan]Machine Invariants Compiled:[/cyan] {len(all_invariants)}\n",
        title="UniGov v0.5.0 Specification Readiness Verdict",
        border_style="green" if score >= 80 else ("yellow" if score >= 40 else "red"),
    )
    console.print(summary_panel)

    return SpecVerificationReport(
        total_dimensions=len(DIMENSION_METADATA),
        covered_dimensions=covered_cnt,
        readiness_score=score,
        dimensions=coverage_list,
        invariants_extracted=len(all_invariants),
    )
