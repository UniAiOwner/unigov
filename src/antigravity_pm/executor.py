import json
import time
import subprocess
from pathlib import Path
import typer
from rich.console import Console
from rich.panel import Panel

from .db import get_db
from .llm import generate_structured
from .models import AgentExecutionPlan

console = Console()


def create_git_checkpoint(conn, task_id: str) -> str:
    in_git = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
    if in_git.returncode != 0:
        return ""

    head_check = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], capture_output=True, text=True)
    if head_check.returncode != 0:
        # Initial empty commit to anchor HEAD if repo has zero commits
        subprocess.run(["git", "commit", "--allow-empty", "-m", "chore(antigravity): initial empty root commit"], capture_output=True)
        head_check = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], capture_output=True, text=True)
        if head_check.returncode != 0:
            return ""

    status_proc = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    dirty = 1 if status_proc.stdout.strip() else 0
    if dirty:
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(
            ["git", "commit", "-m", f"chore(antigravity): pre-execution snapshot for {task_id}"],
            capture_output=True,
            check=True,
        )
        head_check = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)

    head_hash = head_check.stdout.strip()
    tag_name = f"ag-chk-{task_id}-{int(time.time())}"
    subprocess.run(["git", "tag", tag_name, head_hash], check=True)

    with conn:
        conn.execute(
            "INSERT INTO git_checkpoints (task_id, tag_name, commit_hash, had_uncommitted_changes) VALUES (?, ?, ?, ?)",
            (task_id, tag_name, head_hash, dirty),
        )
    return tag_name


def rollback_task(task_id: str) -> None:
    conn = get_db()
    chk = conn.execute(
        "SELECT * FROM git_checkpoints WHERE task_id = ? ORDER BY checkpoint_id DESC LIMIT 1",
        (task_id,),
    ).fetchone()

    if not chk:
        console.print(f"[bold red]Error:[/bold red] No Git checkpoint found for task '{task_id}'.")
        raise typer.Exit(1)

    console.print(f"[yellow]Found checkpoint:[/yellow] {chk['tag_name']} ({chk['commit_hash'][:8]})")
    if not typer.confirm("Discard uncommitted changes and reset tracked files to this checkpoint?"):
        console.print("[yellow]Rollback aborted.[/yellow]")
        return

    subprocess.run(["git", "reset", "--hard", chk["tag_name"]], check=True)
    subprocess.run(["git", "clean", "-fd"], check=True)

    with conn:
        conn.execute("UPDATE tasks SET status = 'READY' WHERE task_id = ?", (task_id,))
        conn.execute(
            "INSERT INTO audit_logs (task_id, check_type, passed, output_snippet) VALUES (?, 'ROLLBACK', 1, ?)",
            (task_id, f"Reverted to {chk['tag_name']}"),
        )
    console.print(f"[bold green]Rolled back '{task_id}' to {chk['tag_name']}. Status reset to READY.[/bold green]")


def pick_next_ready_task() -> None:
    conn = get_db()
    vision = conn.execute("SELECT * FROM project_vision WHERE id = 1").fetchone()
    task = conn.execute("SELECT * FROM tasks WHERE level = 'TASK' AND status = 'READY' LIMIT 1").fetchone()

    if not task:
        console.print("[yellow]No READY atomic tasks available. Check dependencies or ingest docs.[/yellow]")
        return

    conn.execute("UPDATE tasks SET status = 'IN_PROGRESS' WHERE task_id = ?", (task["task_id"],))
    conn.commit()

    bundle = (
        f"PROJECT: {vision['project_name']}\n"
        f"CONSTRAINTS: {vision['hard_constraints_json']}\n"
        f"TASK ID: {task['task_id']} — {task['title']}\n"
        f"SPECIFICATION: {task['description']}\n"
        f"TARGET FILES: {task['target_files_json']}\n"
        f"VERIFY CMD: {task['verify_cmd'] or 'None'}"
    )
    console.print(Panel(bundle, title="Zero-Noise Context Bundle (Status -> IN_PROGRESS)", border_style="cyan"))


def _apply_surgical_patches(patches) -> None:
    staged_writes: dict[Path, str] = {}

    for patch in patches:
        p = Path(patch.file_path)
        if patch.is_new_file:
            if patch.new_file_content is None:
                raise ValueError(f"Patch for new file '{patch.file_path}' missing new_file_content.")
            staged_writes[p] = patch.new_file_content
            continue

        if not p.exists():
            raise FileNotFoundError(f"Target file '{patch.file_path}' does not exist for Search/Replace.")

        content = staged_writes.get(p, p.read_text(encoding="utf-8"))
        for idx, block in enumerate(patch.edits, 1):
            count = content.count(block.search)
            if count == 1:
                content = content.replace(block.search, block.replace, 1)
                continue
            if count > 1:
                raise ValueError(f"Block #{idx} SEARCH snippet matched {count} times in '{patch.file_path}'. Needs more context.")

            # Resilient fallback: Try line-by-line whitespace-trimmed match
            search_lines = [" ".join(l.split()) for l in block.search.splitlines() if l.strip()]
            if not search_lines:
                raise ValueError(f"Block #{idx} SEARCH snippet is empty.")

            file_lines = content.splitlines(keepends=True)
            matched_indices = []
            for i in range(len(file_lines) - len(search_lines) + 1):
                window = [" ".join(file_lines[i + k].split()) for k in range(len(search_lines))]
                if window == search_lines:
                    matched_indices.append(i)

            if len(matched_indices) == 1:
                start_i = matched_indices[0]
                end_i = start_i + len(search_lines)
                new_lines = block.replace.splitlines(keepends=True)
                file_lines[start_i:end_i] = new_lines
                content = "".join(file_lines)
            elif len(matched_indices) > 1:
                raise ValueError(f"Block #{idx} SEARCH snippet matched {len(matched_indices)} times after whitespace normalization in '{patch.file_path}'. Needs more context.")
            else:
                raise ValueError(f"Block #{idx} SEARCH snippet not found in '{patch.file_path}'. Aborting write.")

        staged_writes[p] = content

    for path_obj, final_text in staged_writes.items():
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        path_obj.write_text(final_text, encoding="utf-8")
        console.print(f"[green]Patched:[/green] {path_obj.as_posix()}")


def _preview_and_apply_plan(conn, task_id: str, plan: AgentExecutionPlan) -> bool:
    console.print(Panel(f"[bold]Agent Reasoning:[/bold]\n{plan.reasoning}", title=f"Surgical Proposal: {task_id}"))

    for patch in plan.patches:
        console.print(f"\n[bold yellow]File:[/bold yellow] {patch.file_path} — [italic]{patch.explanation}[/italic]")
        if patch.is_new_file:
            preview = (patch.new_file_content or "")[:1200]
            console.print(Panel(preview, title="NEW FILE", border_style="green"))
        else:
            for idx, b in enumerate(patch.edits, 1):
                diff_view = f"[red]<<<<<<< SEARCH[/red]\n{b.search}\n[yellow]=======[/yellow]\n{b.replace}\n[green]>>>>>>> REPLACE[/green]"
                console.print(Panel(diff_view, title=f"Hunk #{idx}", border_style="blue"))

    if not typer.confirm("\nApprove and apply these surgical patches?"):
        console.print("[yellow]Discarded by user. Disk untouched.[/yellow]")
        return False

    tag = create_git_checkpoint(conn, task_id)
    if tag:
        console.print(f"[cyan]Git Checkpoint Created:[/cyan] {tag}")

    try:
        _apply_surgical_patches(plan.patches)
    except Exception as exc:
        console.print(f"[bold red]Patch Validation Failed:[/bold red] {exc}")
        return False

    conn.execute("UPDATE tasks SET status = 'IN_PROGRESS' WHERE task_id = ?", (task_id,))
    conn.commit()
    return True


def execute_task_with_agent(task_id: str, error_feedback: str = "") -> bool:
    conn = get_db()
    task = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    vision = conn.execute("SELECT * FROM project_vision WHERE id = 1").fetchone()

    if not task:
        console.print(f"[bold red]Error:[/bold red] Task '{task_id}' not found.")
        raise typer.Exit(1)

    target_files = json.loads(task["target_files_json"] or "[]")
    current_files = {
        f: (Path(f).read_text(encoding="utf-8") if Path(f).exists() else "<NEW_FILE>")
        for f in target_files
    }

    feedback_section = f"\nPREVIOUS VERIFICATION FAILURE LOG (FIX THIS):\n{error_feedback}\n" if error_feedback else ""
    prompt = f"""
    Implement or fix the following atomic software engineering task while obeying all Locked Constraints.
    RULES:
    - For existing files, set is_new_file=false and provide exact verbatim SEARCH/REPLACE blocks with enough surrounding lines to be unique.
    - Never rewrite an entire existing file; output only minimal surgical edits.
    - For brand-new files, set is_new_file=true and populate new_file_content.

    PROJECT: {vision['project_name']}
    LOCKED CONSTRAINTS: {vision['hard_constraints_json']}
    TASK ID: {task['task_id']} — {task['title']}
    SPECIFICATION: {task['description']}
    {feedback_section}
    CURRENT FILE STATES:
    {json.dumps(current_files)}
    """

    console.print(f"[cyan]Generating surgical patches for {task_id}...[/cyan]")
    plan = generate_structured(conn, "execute", prompt, AgentExecutionPlan, complexity="pro")
    return _preview_and_apply_plan(conn, task_id, plan)


def verify_and_unlock(task_id: str, auto_fix: bool = False, max_retries: int = 2) -> None:
    conn = get_db()
    task = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    if not task:
        console.print(f"[bold red]Error:[/bold red] Task '{task_id}' not found.")
        raise typer.Exit(1)

    for attempt in range(max_retries + 1):
        target_files = json.loads(task["target_files_json"] or "[]")
        missing = [f for f in target_files if not Path(f).exists()]
        if missing:
            err_msg = f"Missing target files: {missing}"
            console.print(f"[bold red]Gate 1 Failed:[/bold red] {err_msg}")
            if auto_fix and attempt < max_retries:
                if execute_task_with_agent(task_id, error_feedback=err_msg):
                    continue
            conn.execute("UPDATE tasks SET status = 'FAILED' WHERE task_id = ?", (task_id,))
            conn.commit()
            raise typer.Exit(1)

        if task["verify_cmd"]:
            console.print(f"[cyan]Running Gate 2 (Attempt {attempt + 1}):[/cyan] {task['verify_cmd']}")
            proc = subprocess.run(task["verify_cmd"], shell=True, capture_output=True, text=True)
            if proc.returncode != 0:
                err_out = (proc.stderr or proc.stdout)[-1500:]
                console.print(Panel(err_out, title="Gate 2 Failed: Build/Test Error", border_style="red"))
                with conn:
                    conn.execute(
                        "INSERT INTO audit_logs (task_id, check_type, passed, output_snippet) VALUES (?, 'BUILD_TEST', 0, ?)",
                        (task_id, err_out),
                    )
                if auto_fix and attempt < max_retries:
                    console.print(f"[yellow]Triggering Self-Healing Fix ({attempt + 1}/{max_retries})...[/yellow]")
                    if execute_task_with_agent(task_id, error_feedback=err_out):
                        continue
                conn.execute("UPDATE tasks SET status = 'FAILED' WHERE task_id = ?", (task_id,))
                conn.commit()
                raise typer.Exit(1)

        with conn:
            conn.execute("UPDATE tasks SET status = 'COMPLETED', completed_at = CURRENT_TIMESTAMP WHERE task_id = ?", (task_id,))
            conn.execute("INSERT INTO audit_logs (task_id, check_type, passed, output_snippet) VALUES (?, 'VERIFIED', 1, 'Passed')", (task_id,))

            dependents = conn.execute("SELECT task_id FROM task_dependencies WHERE depends_on_task_id = ?", (task_id,)).fetchall()
            for row in dependents:
                cand_id = row["task_id"]
                unmet = conn.execute("""
                    SELECT COUNT(*) AS cnt FROM task_dependencies td
                    JOIN tasks t ON td.depends_on_task_id = t.task_id
                    WHERE td.task_id = ? AND t.status != 'COMPLETED'
                """, (cand_id,)).fetchone()["cnt"]
                if unmet == 0:
                    conn.execute("UPDATE tasks SET status = 'READY' WHERE task_id = ? AND status = 'PENDING'", (cand_id,))
                    console.print(f"[green]DAG Unlocked:[/green] {cand_id} is now READY.")

        console.print(f"[bold green]Task {task_id} VERIFIED & LOCKED![/bold green]")
        return
