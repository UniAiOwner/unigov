import re
import ast
import json
import time
import subprocess
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel

from .db import get_db
from .llm import generate_structured
from .models import AgentExecutionPlan
from .reviewer import review_execution_plan, print_quality_gate_table

console = Console()

ERROR_SIGNALS = [
    re.compile(r"\b(?:error|ERROR|Error)\b:?"),
    re.compile(r"\b(?:fatal|FATAL|Fatal)\b:?"),
    re.compile(r"\b(?:FAILED|FAIL)\b"),
    re.compile(r"\bTraceback \(most recent call last\):"),
    re.compile(r"\b(?:Exception|AssertionError|NullPointerException|TypeError|ValueError|KeyError|IndexError|AttributeError)\b"),
    re.compile(r"^\s*E\s+.*", re.MULTILINE),
    re.compile(r"FAILED\s+tests/"),
    re.compile(r"\b[\w./\\-]+\.(?:py|kt|java|ts|tsx|rs|go|cpp|c|h):\d+(?::\d+)?"),
    re.compile(r"\bBUILD FAILED\b"),
]


def extract_actionable_error_log(raw_output: str, max_chars: int = 2500) -> str:
    """Intelligently scrapes compiler, test, and runtime failure logs to surface root causes

    instead of blindly truncating the tail of stdout/stderr.
    """
    if not raw_output:
        return ""

    text = raw_output.strip()
    if len(text) <= max_chars:
        return text

    lines = text.splitlines()
    matching_indices: set[int] = set()

    for idx, line in enumerate(lines):
        for pattern in ERROR_SIGNALS:
            if pattern.search(line):
                matching_indices.add(idx)
                break

    if not matching_indices:
        return text[-max_chars:]

    extracted_indices: set[int] = set()
    for idx in matching_indices:
        start = max(0, idx - 3)
        end = min(len(lines), idx + 6)
        for i in range(start, end):
            extracted_indices.add(i)

    sorted_indices = sorted(extracted_indices)
    blocks: list[list[str]] = []
    current_block: list[str] = []
    prev_idx = None

    for i in sorted_indices:
        if prev_idx is not None and i > prev_idx + 1:
            if current_block:
                blocks.append(current_block)
                current_block = []
        current_block.append(lines[i])
        prev_idx = i
    if current_block:
        blocks.append(current_block)

    formatted_blocks = ["\n".join(b) for b in blocks]
    combined = "\n\n--- [Diagnostics Context] ---\n\n".join(formatted_blocks)

    if len(combined) > max_chars:
        return combined[:max_chars] + "\n...[truncated]"
    return combined


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
    from .invariants import apply_topological_phase_locks
    apply_topological_phase_locks(conn)
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


def _check_balanced_brackets(file_path: Path, code: str) -> None:
    stack = []
    pairs = {")": "(", "}": "{", "]": "["}
    opening = set(pairs.values())
    closing = set(pairs.keys())

    in_single_str = False
    in_double_str = False
    in_backtick = False
    in_line_comment = False
    in_block_comment = False

    i = 0
    n = len(code)
    line = 1

    while i < n:
        c = code[i]
        if c == "\n":
            line += 1
            in_line_comment = False
            i += 1
            continue

        if in_line_comment:
            i += 1
            continue

        if in_block_comment:
            if c == "*" and i + 1 < n and code[i + 1] == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if in_single_str:
            if c == "\\":
                i += 2
                continue
            if c == "'":
                in_single_str = False
            i += 1
            continue

        if in_double_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_double_str = False
            i += 1
            continue

        if in_backtick:
            if c == "\\":
                i += 2
                continue
            if c == "`":
                in_backtick = False
            i += 1
            continue

        # Comments
        if c == "/" and i + 1 < n:
            next_c = code[i + 1]
            if next_c == "/":
                in_line_comment = True
                i += 2
                continue
            elif next_c == "*":
                in_block_comment = True
                i += 2
                continue

        # Strings
        if c == '"':
            in_double_str = True
            i += 1
            continue
        elif c == "'":
            in_single_str = True
            i += 1
            continue
        elif c == "`":
            in_backtick = True
            i += 1
            continue

        # Brackets
        if c in opening:
            stack.append((c, line))
        elif c in closing:
            expected = pairs[c]
            if not stack:
                raise ValueError(f"Unmatched closing '{c}' at line {line} in '{file_path}'")
            last_op, op_line = stack.pop()
            if last_op != expected:
                raise ValueError(
                    f"Mismatched bracket in '{file_path}': expected closing for '{last_op}' (opened at line {op_line}), got '{c}' at line {line}"
                )

        i += 1

    if stack:
        unclosed, op_line = stack[-1]
        raise ValueError(f"Unclosed bracket '{unclosed}' opened at line {op_line} in '{file_path}'")


def validate_code_syntax(file_path: Path, code: str) -> None:
    """Pre-validates modified code syntax before saving to disk to prevent corrupting files."""
    suffix = file_path.suffix.lower()

    if suffix == ".py":
        try:
            ast.parse(code, filename=str(file_path))
        except SyntaxError as e:
            raise ValueError(f"AST Syntax Validation Error in '{file_path}': Line {e.lineno}: {e.msg}") from e

    elif suffix == ".json":
        try:
            json.loads(code)
        except Exception as e:
            raise ValueError(f"JSON Syntax Validation Error in '{file_path}': {e}") from e

    elif suffix in {".kt", ".java", ".ts", ".tsx", ".js", ".rs", ".go", ".c", ".cpp", ".h"}:
        _check_balanced_brackets(file_path, code)


def is_test_file_path(file_path: str | Path) -> bool:
    """Checks whether a path belongs to a test suite."""
    norm = str(file_path).replace("\\", "/")
    stem = Path(norm).stem
    return (
        norm.startswith("tests/")
        or "/tests/" in norm
        or "/test/" in norm
        or stem.startswith("test_")
        or stem.endswith("_test")
        or stem.endswith("Test")
    )


def _apply_surgical_patches(patches, locked_test_cage: bool = False) -> None:
    if locked_test_cage:
        for patch in patches:
            if is_test_file_path(patch.file_path):
                raise PermissionError(
                    f"LOCKED TEST CAGE VIOLATION: Patch on '{patch.file_path}' blocked! "
                    "Tests are strictly write-locked during self-healing repair."
                )

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

    # Phase 2 AST Pre-validation: Verify syntax for ALL files before touching disk
    for path_obj, final_text in staged_writes.items():
        validate_code_syntax(path_obj, final_text)

    for path_obj, final_text in staged_writes.items():
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        path_obj.write_text(final_text, encoding="utf-8")
        console.print(f"[green]Patched:[/green] {path_obj.as_posix()}")


def _preview_and_apply_plan(conn, task_id: str, plan: AgentExecutionPlan, locked_test_cage: bool = False) -> bool:
    console.print(Panel(f"[bold]Agent Reasoning:[/bold]\n{plan.reasoning}", title=f"Surgical Proposal: {task_id}"))

    # Automated Quality Gate Review (Law-000, Secrets, ACC-001, Blast Radius)
    gate_res = review_execution_plan(plan)
    print_quality_gate_table(gate_res)

    if not gate_res.passed:
        console.print("[bold red]Pre-Apply Quality Gate FAILED (Law-000 or Secret violation). Patch application blocked.[/bold red]")
        return False

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
        _apply_surgical_patches(plan.patches, locked_test_cage=locked_test_cage)
    except Exception as exc:
        console.print(f"[bold red]Patch Validation Failed:[/bold red] {exc}")
        return False

    conn.execute("UPDATE tasks SET status = 'IN_PROGRESS' WHERE task_id = ?", (task_id,))
    conn.commit()
    return True


def execute_task_with_agent(
    task_id: str,
    error_feedback: str = "",
    model: Optional[str] = None,
    provider: Optional[str] = None,
    locked_test_cage: bool = False,
) -> bool:
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

    from .context_bundler import bundle_one_hop_context
    one_hop_context = bundle_one_hop_context(Path("."), target_files)

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
    {one_hop_context}
    """

    console.print(f"[cyan]Generating surgical patches for {task_id}...[/cyan]")
    plan = generate_structured(
        conn,
        "execute",
        prompt,
        AgentExecutionPlan,
        complexity="pro",
        model=model,
        provider=provider,
    )
    return _preview_and_apply_plan(conn, task_id, plan, locked_test_cage=locked_test_cage)


def verify_and_unlock(
    task_id: str,
    auto_fix: bool = False,
    strict_cage: bool = True,
    max_retries: int = 2,
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> None:
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
                if execute_task_with_agent(task_id, error_feedback=err_msg, model=model, provider=provider):
                    continue
            conn.execute("UPDATE tasks SET status = 'FAILED' WHERE task_id = ?", (task_id,))
            conn.commit()
            raise typer.Exit(1)

        verify_cmd = task["verify_cmd"]
        if verify_cmd:
            from .tia import get_targeted_verification_command
            targeted_cmd = get_targeted_verification_command(Path("."), target_files, fallback_cmd=verify_cmd)
            exec_cmd = targeted_cmd if targeted_cmd else verify_cmd
            if exec_cmd != verify_cmd:
                console.print(f"[cyan]Smart TIA (Attempt {attempt + 1}):[/cyan] {exec_cmd}")
            else:
                console.print(f"[cyan]Running Gate 2 (Attempt {attempt + 1}):[/cyan] {exec_cmd}")

            proc = subprocess.run(exec_cmd, shell=True, capture_output=True, text=True)
            if proc.returncode != 0:
                full_raw = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
                err_out = extract_actionable_error_log(full_raw)
                console.print(Panel(err_out, title="Gate 2 Failed: Actionable Diagnostics", border_style="red"))
                with conn:
                    conn.execute(
                        "INSERT INTO audit_logs (task_id, check_type, passed, output_snippet) VALUES (?, 'BUILD_TEST', 0, ?)",
                        (task_id, err_out[:1000]),
                    )
                if auto_fix and attempt < max_retries:
                    console.print(f"[yellow]Triggering Self-Healing Fix ({attempt + 1}/{max_retries})...[/yellow]")
                    if execute_task_with_agent(task_id, error_feedback=err_out, model=model, provider=provider, locked_test_cage=strict_cage):
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
