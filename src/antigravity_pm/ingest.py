import json
import hashlib
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel

from .db import get_db
from .llm import generate_structured
from .models import MultiDocAnalysis

console = Console()


def detect_dag_cycles(tasks: list) -> list[list[str]]:
    """Detects circular dependency paths in WBS tasks.

    Returns a list of cycle paths, e.g. [['T1', 'T2', 'T1']].
    """
    adj: dict[str, list[str]] = {t.task_id: list(t.depends_on) for t in tasks}
    cycles: list[list[str]] = []
    visited: dict[str, int] = {}  # 0: unvisited, 1: visiting (stack), 2: visited
    path_stack: list[str] = []

    def dfs(node: str):
        visited[node] = 1
        path_stack.append(node)

        for dep in adj.get(node, []):
            if visited.get(dep, 0) == 0:
                dfs(dep)
            elif visited.get(dep, 0) == 1:
                # Cycle found
                if dep in path_stack:
                    cycle_start = path_stack.index(dep)
                    cycle_path = path_stack[cycle_start:] + [dep]
                    cycles.append(cycle_path)

        path_stack.pop()
        visited[node] = 2

    for t in tasks:
        if visited.get(t.task_id, 0) == 0:
            dfs(t.task_id)

    return cycles


def ingest_path(
    target: Path,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    auto_approve: bool = False,
) -> None:
    if not target.exists():
        console.print(f"[bold red]Error:[/bold red] Path not found: {target}")
        raise typer.Exit(1)

    md_files = sorted(target.rglob("*.md")) if target.is_dir() else [target]
    if not md_files:
        console.print("[yellow]No markdown (.md) files found to ingest.[/yellow]")
        return

    conn = get_db()
    combined_corpus = []
    changed_files = []

    for f in md_files:
        text = f.read_text(encoding="utf-8")
        f_hash = hashlib.sha256(text.encode()).hexdigest()
        row = conn.execute("SELECT file_hash FROM ingested_docs WHERE file_path = ?", (f.as_posix(),)).fetchone()
        if not row or row["file_hash"] != f_hash:
            changed_files.append((f, f_hash))
        combined_corpus.append(f"=== FILE: {f.as_posix()} ===\n{text}\n")

    if not changed_files:
        console.print("[green]All documentation is up to date. Zero changes detected.[/green]")
        return

    console.print(f"[cyan]Auditing {len(md_files)} doc(s) ({len(changed_files)} changed)...[/cyan]")
    prompt = f"""
    You are a Principal Software Architect analyzing project documentation.
    1. Cross-reference all documents below and detect any CONTRADICTIONS between files.
    2. Extract non-negotiable architectural hard constraints.
    3. Decompose the plan into a deduplicated hierarchical Work Breakdown Structure (MILESTONE -> MODULE -> TASK).
    4. Leaf TASK items must be atomic (1-3 files) with clear target_files and shell verify_cmd where applicable.

    DOCUMENTATION SUITE:
    {''.join(combined_corpus)}
    """

    analysis = generate_structured(
        conn,
        "ingest",
        prompt,
        MultiDocAnalysis,
        complexity="fast",
        model=model,
        provider=provider,
    )

    if analysis.conflicts:
        console.print(Panel("[bold red]CROSS-DOCUMENT CONFLICTS DETECTED[/bold red]", border_style="red"))
        for idx, c in enumerate(analysis.conflicts, 1):
            console.print(f"\n[bold yellow]{idx}. {c.topic}[/bold yellow]")
            console.print(f"   • [cyan]{c.doc_a}[/cyan]: {c.claim_a}")
            console.print(f"   • [cyan]{c.doc_b}[/cyan]: {c.claim_b}")
            console.print(f"   • [green]Recommended Resolution[/green]: {c.recommended_resolution}")

        if not auto_approve and not typer.confirm("\nAccept recommended resolutions and continue?"):
            console.print("[yellow]Aborted. Update your docs manually and re-run ingest.[/yellow]")
            raise typer.Exit(1)

    cycles = detect_dag_cycles(analysis.tasks)
    if cycles:
        console.print(Panel("[bold red]DAG DEPENDENCY CYCLE DETECTED[/bold red]", border_style="red"))
        for idx, c in enumerate(cycles, 1):
            cycle_str = " -> ".join(c)
            console.print(f"[bold yellow]{idx}. Cycle detected:[/bold yellow] [red]{cycle_str}[/red]")

        console.print("\n[yellow]Circular dependencies will cause a permanent deadlock in the execution state machine.[/yellow]")
        if auto_approve or typer.confirm("Automatically break circular dependency back-edges?", default=True):
            for c in cycles:
                if len(c) >= 2:
                    from_task, to_task = c[-2], c[-1]
                    for t in analysis.tasks:
                        if t.task_id == from_task and to_task in t.depends_on:
                            t.depends_on.remove(to_task)
                            console.print(f"[green]Auto-Resolved:[/green] Removed circular back-edge: {from_task} -> {to_task}")
        else:
            console.print("[yellow]Aborted. Please resolve circular dependencies in documentation.[/yellow]")
            raise typer.Exit(1)

    console.print(Panel(
        "[bold]Extracted Hard Constraints:[/bold]\n" +
        ("\n".join(f"• {c}" for c in analysis.hard_constraints) or "None") +
        f"\n\n[bold]Extracted WBS Nodes:[/bold] {len(analysis.tasks)}",
        title="Plan Preview (Human Always Decides)",
        border_style="cyan",
    ))

    if not auto_approve and not typer.confirm("Commit these constraints and DAG tasks to .antigravity/state.db?"):
        console.print("[yellow]Aborted by user.[/yellow]")
        return

    with conn:
        old_row = conn.execute("SELECT hard_constraints_json FROM project_vision WHERE id = 1").fetchone()
        merged_constraints = sorted(list(set(json.loads(old_row["hard_constraints_json"]) + analysis.hard_constraints)))
        conn.execute(
            "UPDATE project_vision SET hard_constraints_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
            (json.dumps(merged_constraints),),
        )

        for t in analysis.tasks:
            existing = conn.execute("SELECT status FROM tasks WHERE task_id = ?", (t.task_id,)).fetchone()
            if existing and existing["status"] == "COMPLETED":
                continue
            status = "READY" if (t.level == "TASK" and not t.depends_on) else "PENDING"
            conn.execute("""
                INSERT OR REPLACE INTO tasks (task_id, parent_id, level, title, description, target_files_json, verify_cmd, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (t.task_id, t.parent_id, t.level, t.title, t.description, json.dumps(t.target_files), t.verify_cmd, status))

        for t in analysis.tasks:
            for dep in t.depends_on:
                conn.execute("INSERT OR IGNORE INTO task_dependencies (task_id, depends_on_task_id) VALUES (?, ?)", (t.task_id, dep))

        for f, f_hash in changed_files:
            conn.execute(
                "INSERT OR REPLACE INTO ingested_docs (file_path, file_hash, last_ingested_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (f.as_posix(), f_hash),
            )

    console.print("[bold green]Success:[/bold green] Project Knowledge & DAG synchronized.")
