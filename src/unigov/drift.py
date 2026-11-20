import json
import subprocess
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel

from .db import get_db
from .llm import generate_structured
from .models import DriftReport

console = Console()

SECRET_SIGNATURES = [
    "AIzaSy",
    "BEGIN PRIVATE KEY",
    "BEGIN RSA PRIVATE KEY",
    "sk-proj-",
    "ghp_",
]


def run_drift_check(
    staged: bool = True,
    skip_llm: bool = False,
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> None:
    conn = get_db()
    vision = conn.execute("SELECT * FROM project_vision WHERE id = 1").fetchone()
    constraints = json.loads(vision["hard_constraints_json"])
    adrs = conn.execute("SELECT adr_id, decision, rationale FROM adr_ledger WHERE status = 'FINALIZED'").fetchall()

    cmd = ["git", "diff", "--cached"] if staged else ["git", "diff"]
    diff_text = subprocess.run(cmd, capture_output=True, text=True).stdout

    if not diff_text.strip():
        console.print("[green]Drift Check:[/green] No pending diff to inspect.")
        return

    for sig in SECRET_SIGNATURES:
        if sig in diff_text:
            conn.execute(
                "INSERT INTO audit_logs (check_type, passed, output_snippet) VALUES ('SECURITY_SCAN', 0, ?)",
                (f"Detected signature: {sig}",),
            )
            conn.commit()
            console.print(f"[bold red]SECURITY BLOCK:[/bold red] Potential secret signature '{sig}' found in git diff!")
            raise typer.Exit(1)

    if skip_llm:
        console.print("[green]Deterministic Security Scan Passed.[/green]")
        return

    adr_summary = "\n".join(f"- {r['adr_id']}: {r['decision']} (Rationale: {r['rationale']})" for r in adrs) or "None"
    prompt = f"""
    Audit the following git diff against the project's Locked Constraints and Architecture Decision Records (ADRs).
    Flag drift_detected=true ONLY if the diff directly violates a hard constraint or finalized ADR.

    LOCKED CONSTRAINTS:
    {json.dumps(constraints, indent=2)}

    FINALIZED ADRs:
    {adr_summary}

    GIT DIFF (truncated to 16k chars):
    {diff_text[:16000]}
    """

    report = generate_structured(
        conn,
        "check-drift",
        prompt,
        DriftReport,
        complexity="fast",
        model=model,
        provider=provider,
    )

    if report.drift_detected:
        conn.execute(
            "INSERT INTO audit_logs (check_type, passed, output_snippet) VALUES ('DRIFT_CHECK', 0, ?)",
            (report.explanation[:500],),
        )
        conn.commit()
        console.print(Panel(
            f"[bold red]ARCHITECTURE DRIFT DETECTED![/bold red]\n\n"
            f"[bold]Violated Rules:[/bold] {', '.join(report.violated_constraints)}\n"
            f"[bold]Explanation:[/bold] {report.explanation}",
            border_style="red",
        ))
        raise typer.Exit(1)

    conn.execute("INSERT INTO audit_logs (check_type, passed, output_snippet) VALUES ('DRIFT_CHECK', 1, 'Clean')")
    conn.commit()
    console.print("[bold green]Drift Check Passed:[/bold green] Changes comply with Vision & ADRs.")


def install_pre_commit_hook() -> None:
    hook_path = Path(".git/hooks/pre-commit")
    if not hook_path.parent.exists():
        console.print("[bold red]Error:[/bold red] Current directory is not a Git repository.")
        raise typer.Exit(1)

    script = """#!/bin/sh
# ⬢ UniGov & UniSkill Sovereign Dual Invariant Pre-Commit Gate
set -e

# 1. UniGov Drift Check
if command -v unigov >/dev/null 2>&1; then
    unigov check-drift --staged
fi

# 2. UniSkill Constitutional Invariants Audit
if command -v uniskill >/dev/null 2>&1; then
    uniskill audit
fi

echo "✔ Pre-commit Gate Passed: Clean Architecture & 0-Suppress Invariants."
"""
    hook_path.write_text(script, encoding="utf-8")
    hook_path.chmod(0o755)
    console.print(f"[bold green]Installed Unified Sovereign Pre-commit hook:[/bold green] {hook_path}")
