import os
import json
import re
import sqlite3
from pathlib import Path
from typing import List, Optional
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .llm import generate_structured
from .models import TaskReconciliationResult, ReconciliationSummary

console = Console()

IGNORED_DIRS = {
    ".git", ".antigravity", "build", "node_modules", "dist",
    "__pycache__", ".gradle", ".idea", ".agents", "backups",
}


def find_candidate_files(root_dir: Path, target_files: List[str], task_title: str, task_desc: str) -> List[Path]:
    """Finds exact or fuzzy-matched files in the project corresponding to a task using path and content indexing."""
    candidates: List[Path] = []
    seen = set()

    # 1. Exact or relative path check
    for tf in target_files:
        p = root_dir / tf
        if p.exists() and p.is_file():
            candidates.append(p)
            seen.add(p.resolve())

    # 2. Determine primary source directory to search first
    src_roots = []
    for cand_dir in [root_dir / "app" / "src" / "main", root_dir / "src", root_dir / "lib"]:
        if cand_dir.exists() and cand_dir.is_dir():
            src_roots.append(cand_dir)
    if not src_roots:
        src_roots = [root_dir]

    # 3. Extract alphanumeric tokens from target files, title and description
    tokens = set()
    for tf in target_files:
        stem = Path(tf).stem
        for p in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)", stem):
            if len(p) >= 3 and p.lower() not in {"file", "test", "impl", "class"}:
                tokens.add(p)

    for word in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)", f"{task_title} {task_desc}"):
        if len(word) >= 4 and word.lower() not in {"build", "update", "implement", "create", "test", "task", "handle", "atomic"}:
            tokens.add(word)

    # 4. Use ripgrep (rg) if available to locate relevant files by content tokens
    exts = {".kt", ".java", ".py", ".ts", ".tsx", ".rs", ".go", ".cpp", ".c", ".h"}
    rg_matches = []
    if tokens:
        pattern = "|".join(re.escape(t) for t in tokens if len(t) >= 3)
        try:
            import subprocess
            for sroot in src_roots:
                cmd = ["rg", "-l", "-i", pattern, str(sroot)]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                for line in res.stdout.splitlines():
                    lp = Path(line.strip())
                    if lp.is_file() and lp.suffix in exts and lp.resolve() not in seen:
                        rg_matches.append(lp)
        except Exception:
            pass

    # 5. Score candidates by token match density
    scored = []
    for p in (candidates + rg_matches):
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            # Base score: name match = 3, content token matches = 1 each
            name_score = sum(3 for t in tokens if t.lower() in p.name.lower())
            body_score = sum(1 for t in tokens if t.lower() in content.lower())
            scored.append((name_score + body_score, p))
        except Exception:
            scored.append((1, p))

    # Also search by basename if still empty
    if not scored:
        stem_keywords = {t.lower() for t in tokens}
        for sroot in src_roots:
            for path in sroot.rglob("*"):
                if any(ignored in path.parts for ignored in IGNORED_DIRS):
                    continue
                if path.is_file() and path.suffix in exts:
                    if path.resolve() in seen:
                        continue
                    matches = [kw for kw in stem_keywords if kw in path.name.lower()]
                    if matches:
                        scored.append((len(matches), path))
                        seen.add(path.resolve())
                        if len(scored) >= 6:
                            break

    scored.sort(key=lambda x: x[0], reverse=True)
    final_candidates = []
    for _, path in scored:
        if path.resolve() not in seen:
            seen.add(path.resolve())
            final_candidates.append(path)
        if len(final_candidates) >= 5:
            break

    return final_candidates or candidates


def extract_code_excerpts(files: List[Path], max_chars: int = 5000) -> str:
    """Reads structural definitions (classes, functions, interfaces) from candidate files."""
    excerpts = []
    for f in files:
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            # Limit per file to avoid context bloat
            snippet = content[:max_chars]
            rel_path = f.as_posix()
            excerpts.append(f"--- FILE: {rel_path} ---\n{snippet}\n")
        except Exception:
            continue
    return "\n".join(excerpts)


def reconcile_single_task(
    conn: sqlite3.Connection,
    task_row: sqlite3.Row,
    root_dir: Path = Path("."),
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> TaskReconciliationResult:
    task_id = task_row["task_id"]
    title = task_row["title"]
    desc = task_row["description"]
    target_files = json.loads(task_row["target_files_json"] or "[]")

    candidates = find_candidate_files(root_dir, target_files, title, desc)
    if not candidates:
        return TaskReconciliationResult(
            task_id=task_id,
            status="MISSING",
            matched_files=[],
            evidence="No matching source files found in the repository.",
            missing_items=target_files or [title],
        )

    code_context = extract_code_excerpts(candidates)
    if not code_context.strip():
        return TaskReconciliationResult(
            task_id=task_id,
            status="MISSING",
            matched_files=[c.as_posix() for c in candidates],
            evidence="Matched files are empty or unreadable.",
            missing_items=target_files or [title],
        )

    prompt = f"""
    You are a Principal Software Auditor verifying whether an engineering task is ALREADY implemented in this codebase.

    TASK DEFINITION:
    - ID: {task_id}
    - Title: {title}
    - Description: {desc}
    - Expected Target Files: {target_files}

    EXISTING CODE EXCERPTS FOUND IN WORKSPACE:
    {code_context}

    EVALUATE STRICTLY BASED ON CODE EVIDENCE:
    1. status: Must be strictly one of:
       - 'COMPLETED' (The domain model, function, DAO, UI component, or logic described is already genuinely present)
       - 'PARTIAL' (Some related files or stubs exist, but core functions/classes are missing)
       - 'MISSING' (The existing files do not satisfy this task)
    2. matched_files: list of relative file paths that satisfy this task.
    3. evidence: concrete, concise explanation naming classes, methods, or entities found.
    4. missing_items: list of things missing if status is PARTIAL or MISSING.
    """

    res = generate_structured(
        conn,
        "reconcile",
        prompt,
        TaskReconciliationResult,
        complexity="fast",
        model=model,
        provider=provider,
    )
    res.task_id = task_id
    if not res.matched_files:
        res.matched_files = [c.as_posix() for c in candidates]
    return res


def cascade_task_completions(conn: sqlite3.Connection) -> None:
    """Updates parent modules/milestones and unblocks ready dependent tasks."""
    # 1. If all children of a parent are COMPLETED, mark parent COMPLETED
    parents = conn.execute("SELECT DISTINCT parent_id FROM tasks WHERE parent_id IS NOT NULL").fetchall()
    for p in parents:
        pid = p["parent_id"]
        children = conn.execute("SELECT status FROM tasks WHERE parent_id = ?", (pid,)).fetchall()
        if children and all(c["status"] == "COMPLETED" for c in children):
            conn.execute("UPDATE tasks SET status = 'COMPLETED', completed_at = CURRENT_TIMESTAMP WHERE task_id = ?", (pid,))

    # 2. Promote PENDING tasks whose dependencies are all COMPLETED to READY
    pending_tasks = conn.execute("SELECT task_id FROM tasks WHERE status = 'PENDING' AND level = 'TASK'").fetchall()
    for pt in pending_tasks:
        tid = pt["task_id"]
        deps = conn.execute("SELECT depends_on_task_id FROM task_dependencies WHERE task_id = ?", (tid,)).fetchall()
        if deps:
            dep_statuses = [
                conn.execute("SELECT status FROM tasks WHERE task_id = ?", (d["depends_on_task_id"],)).fetchone()["status"]
                for d in deps
            ]
            if all(s == "COMPLETED" for s in dep_statuses):
                conn.execute("UPDATE tasks SET status = 'READY' WHERE task_id = ?", (tid,))
        else:
            conn.execute("UPDATE tasks SET status = 'READY' WHERE task_id = ?", (tid,))


def reconcile_project(
    conn: sqlite3.Connection,
    root_dir: Path = Path("."),
    model: Optional[str] = None,
    provider: Optional[str] = None,
    auto_apply: bool = False,
) -> ReconciliationSummary:
    """Audits existing workspace files against WBS tasks and reconciles actual implementation state."""
    tasks = conn.execute("SELECT * FROM tasks WHERE level = 'TASK' ORDER BY rowid ASC").fetchall()
    if not tasks:
        console.print("[yellow]No leaf TASK items found in .antigravity/state.db.[/yellow]")
        return ReconciliationSummary(total_tasks=0, completed_tasks=0, partial_tasks=0, missing_tasks=0, results=[])

    console.print(f"[cyan]Auditing codebase reality across {len(tasks)} task(s)...[/cyan]")
    results: List[TaskReconciliationResult] = []

    for idx, t in enumerate(tasks, 1):
        console.print(f" • [{idx}/{len(tasks)}] Evaluating [bold cyan]{t['task_id']}[/bold cyan]: {t['title']}...")
        res = reconcile_single_task(conn, t, root_dir=root_dir, model=model, provider=provider)
        results.append(res)

    completed_cnt = sum(1 for r in results if r.status == "COMPLETED")
    partial_cnt = sum(1 for r in results if r.status == "PARTIAL")
    missing_cnt = sum(1 for r in results if r.status == "MISSING")

    table = Table(title="Autonomous Codebase Reality Reconciliation", border_style="cyan")
    table.add_column("Task ID", style="bold cyan")
    table.add_column("Level / Title", style="white")
    table.add_column("Status", style="bold")
    table.add_column("Evidence & Matched Files", style="dim")

    for r in results:
        t_row = conn.execute("SELECT title, level FROM tasks WHERE task_id = ?", (r.task_id,)).fetchone()
        color = "green" if r.status == "COMPLETED" else ("yellow" if r.status == "PARTIAL" else "red")
        files_str = ", ".join(Path(f).name for f in r.matched_files[:2])
        ev_summary = f"{r.evidence}"
        if files_str:
            ev_summary += f" [cyan]({files_str})[/cyan]"
        table.add_row(
            r.task_id,
            f"({t_row['level']}) {t_row['title']}",
            f"[{color}]{r.status}[/{color}]",
            ev_summary,
        )

    console.print(table)

    pct = round((completed_cnt / len(tasks)) * 100, 1) if tasks else 0
    summary_panel = Panel(
        f"[bold]Total Tasks Analyzed:[/bold] {len(tasks)}\n"
        f"• [green]Already Implemented & Completed:[/green] {completed_cnt} ({pct}%)\n"
        f"• [yellow]Partially Implemented (Gaps):[/yellow] {partial_cnt}\n"
        f"• [red]Missing / Remaining To Build:[/red] {missing_cnt}\n",
        title="Project Reality Reconciliation Summary",
        border_style="green" if missing_cnt == 0 else "yellow",
    )
    console.print(summary_panel)

    if not auto_apply:
        if not typer.confirm("Apply these reconciled reality statuses to .antigravity/state.db?", default=True):
            console.print("[yellow]Reconciliation changes skipped by user.[/yellow]")
            return ReconciliationSummary(
                total_tasks=len(tasks),
                completed_tasks=completed_cnt,
                partial_tasks=partial_cnt,
                missing_tasks=missing_cnt,
                results=results,
            )

    with conn:
        for r in results:
            if r.status == "COMPLETED":
                conn.execute(
                    "UPDATE tasks SET status = 'COMPLETED', completed_at = CURRENT_TIMESTAMP WHERE task_id = ?",
                    (r.task_id,),
                )
                conn.execute(
                    "INSERT INTO audit_logs (task_id, check_type, passed, output_snippet) VALUES (?, 'reconciliation', 1, ?)",
                    (r.task_id, r.evidence),
                )
            elif r.status == "PARTIAL":
                conn.execute(
                    "UPDATE tasks SET status = 'IN_PROGRESS' WHERE task_id = ? AND status != 'COMPLETED'",
                    (r.task_id,),
                )
        cascade_task_completions(conn)
        from .invariants import apply_topological_phase_locks
        apply_topological_phase_locks(conn)

    console.print("[bold green]Success:[/bold green] .antigravity/state.db synchronized with codebase reality.")
    return ReconciliationSummary(
        total_tasks=len(tasks),
        completed_tasks=completed_cnt,
        partial_tasks=partial_cnt,
        missing_tasks=missing_cnt,
        results=results,
    )
