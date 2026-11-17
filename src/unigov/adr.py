"""Reverse ADR (Architecture Decision Record) Synthesizer for UniGov.

Auto-synthesizes immutable architectural decisions directly from Git diffs
so repository documentation never suffers from amnesia.
"""

import os
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel

from .db import get_db, resolve_gov_dir
from .models import ADRSynthesis
from .llm import generate_structured

console = Console()


def synthesize_adr_from_diff(
    diff_text: str,
    conn: sqlite3.Connection,
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> ADRSynthesis:
    """Synthesizes an architectural decision record from a git diff."""
    count_row = conn.execute("SELECT count(*) as cnt FROM adr_ledger").fetchone()
    next_idx = (count_row["cnt"] if count_row else 0) + 1
    default_adr_id = f"ADR-{next_idx:03d}-AUTO-DECISION"

    # Check for API key / LLM availability
    api_key = os.environ.get("GEMINI_API_KEY", "")
    has_secret_file = (Path.home() / ".agents" / "secrets" / "gemini_api_key.env").exists()
    has_ollama = (os.environ.get("ANTIGRAVITY_PROVIDER") == "ollama")

    if not api_key and not has_secret_file and not has_ollama:
        # Deterministic offline synthesis
        lines = diff_text.strip().splitlines()
        first_file = "core:system"
        for l in lines:
            if l.startswith("diff --git"):
                parts = l.split()
                if len(parts) >= 3:
                    raw_path = parts[2]
                    if raw_path.startswith("a/"):
                        raw_path = raw_path[2:]
                    first_file = raw_path.split("/")[0]
                    break

        return ADRSynthesis(
            adr_id=default_adr_id,
            module_tag=first_file,
            title=f"Architectural Modification in {first_file}",
            decision=f"Updated structural code and contracts across {first_file}.",
            rationale="Automated reverse-synthesis from Git diff to preserve architectural memory.",
            rejected_alternatives="Manual unrecorded code changes with zero architectural lineage.",
        )

    prompt = f"""
    You are a Principal Software Architect reverse-engineering an Architecture Decision Record (ADR) from a Git diff.

    GIT DIFF:
    {diff_text[:16000]}

    INSTRUCTIONS:
    1. Formulate a crisp ADR ID formatted as: ADR-{next_idx:03d}-<SLUG> (e.g. ADR-{next_idx:03d}-ROOM-MIGRATION-SAFETY).
    2. Identify the primary module or subsystem tag (e.g. core:data:schema, domain:pos).
    3. Document the precise architectural decision taken.
    4. Articulate the technical rationale and justification.
    5. State plausible alternatives that were considered and rejected.
    """

    return generate_structured(
        conn,
        "adr-synthesis",
        prompt,
        ADRSynthesis,
        complexity="pro",
        model=model,
        provider=provider,
    )


def persist_adr(conn: sqlite3.Connection, adr_item: ADRSynthesis, project_root: Path = Path(".")) -> Path:
    """Saves ADR into SQLite ledger and writes Markdown artifact into .unigov/adrs/."""
    gov_dir = resolve_gov_dir(project_root)
    adrs_dir = gov_dir / "adrs"
    adrs_dir.mkdir(parents=True, exist_ok=True)

    with conn:
        conn.execute("""
            INSERT OR REPLACE INTO adr_ledger (adr_id, module_tag, decision, rationale, rejected_alternatives, status)
            VALUES (?, ?, ?, ?, ?, 'FINALIZED')
        """, (adr_item.adr_id, adr_item.module_tag, adr_item.decision, adr_item.rationale, adr_item.rejected_alternatives))

    md_path = adrs_dir / f"{adr_item.adr_id}.md"
    content = f"""# {adr_item.adr_id}: {adr_item.title}

- **Status:** FINALIZED
- **Module Tag:** `{adr_item.module_tag}`
- **Architectural Authority:** UniGov Sovereign Governance Engine

---

## 1. Context & Architectural Decision
{adr_item.decision}

---

## 2. Technical & Business Rationale
{adr_item.rationale}

---

## 3. Rejected Alternatives & Trade-offs
{adr_item.rejected_alternatives}
"""
    md_path.write_text(content, encoding="utf-8")
    return md_path


def run_reverse_adr(
    project_root: Path = Path("."),
    staged: bool = True,
    yes: bool = False,
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> bool:
    """Reverse-synthesizes an ADR from current staged git diff or recent commit."""
    conn = get_db()

    # Get diff
    cmd = ["git", "diff", "--cached"] if staged else ["git", "diff", "HEAD~1"]
    res = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True)
    diff_text = res.stdout.strip()

    if not diff_text:
        # Fallback to last commit diff
        last_commit = subprocess.run(["git", "show", "HEAD"], cwd=project_root, capture_output=True, text=True)
        diff_text = last_commit.stdout.strip()

    if not diff_text:
        console.print("[yellow]No git diff detected to synthesize ADR from.[/yellow]")
        return False

    console.print("[cyan]Reverse-synthesizing ADR from Git diff...[/cyan]")
    adr_item = synthesize_adr_from_diff(diff_text, conn, model=model, provider=provider)

    console.print(Panel(
        f"[bold cyan]ADR ID:[/bold cyan] {adr_item.adr_id}\n"
        f"[bold]Module Tag:[/bold] {adr_item.module_tag}\n"
        f"[bold]Decision:[/bold] {adr_item.decision}\n\n"
        f"[bold]Rationale:[/bold] {adr_item.rationale}\n\n"
        f"[bold red]Rejected Alternatives:[/bold red] {adr_item.rejected_alternatives}",
        title="📝 Synthesized Architecture Decision Record",
        border_style="cyan"
    ))

    if not yes and not typer.confirm("Record this ADR in ledger and .unigov/adrs/?"):
        console.print("[yellow]Discarded by user.[/yellow]")
        return False

    md_path = persist_adr(conn, adr_item, project_root)
    console.print(f"[bold green]Successfully recorded ADR to:[/bold green] `{md_path}`")
    return True
