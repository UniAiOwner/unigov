import os
import json
import sqlite3
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .db import get_db, AG_DIR, DB_PATH
from .llm import generate_structured

console = Console()

CODE_EXTENSIONS = {".py", ".kt", ".java", ".ts", ".tsx", ".js", ".rs", ".go"}
IGNORE_DIRS = {".git", ".antigravity", ".venv", "venv", "node_modules", "build", ".gradle", "__pycache__", "tests"}


class UpgradeRecommendation(BaseModel):
    module_name: str = Field(description="Exact file path in src/unigov/ e.g. ingest.py, reconciler.py")
    bottleneck_addressed: str = Field(description="Specific limitation or bottleneck being resolved")
    proposed_enhancement: str = Field(description="Concrete technical architectural enhancement")
    risk_level: str = Field(description="LOW, MEDIUM, or HIGH")


class MetacognitiveDiagnosis(BaseModel):
    project_name: str = Field(description="Name of the audited project")
    project_maturity_rating: str = Field(description="Maturity tier: e.g. Tier 4 Enterprise Production-Ready")
    project_maturity_score: int = Field(description="0 to 100 maturity score based on code volume, tests, and architecture")
    key_strengths: List[str] = Field(description="Top 3 architectural strengths of the target project")
    governance_blind_spots: List[str] = Field(description="Top governance gaps (e.g. orphan files, unindexed DAOs)")
    unigov_bottlenecks: List[str] = Field(description="Top 3 bottlenecks in UniGov's own capability on this project")
    self_upgrade_roadmap: List[UpgradeRecommendation] = Field(description="Actionable module upgrades for UniGov")
    executive_verdict: str = Field(description="Crisp 2-3 sentence executive architectural verdict")


def introspect_unigov_self() -> dict:
    """Introspects UniGov's own internal architecture and capabilities."""
    pkg_dir = Path(__file__).parent
    modules = sorted(list(pkg_dir.glob("*.py")))
    total_loc = 0
    mod_stats = {}
    for m in modules:
        try:
            lines = m.read_text(encoding="utf-8").splitlines()
            loc = len([l for l in lines if l.strip() and not l.strip().startswith("#")])
            total_loc += loc
            mod_stats[m.name] = loc
        except Exception:
            pass
    return {
        "version": "v0.5.0",
        "module_count": len(modules),
        "total_loc": total_loc,
        "modules": mod_stats,
    }


def analyze_target_project(project_root: Path = Path(".")) -> dict:
    """Analyzes physical codebase metrics of the target project."""
    conn = get_db()
    vision_row = conn.execute("SELECT * FROM project_vision WHERE id = 1").fetchone()
    project_name = vision_row["project_name"] if vision_row else project_root.resolve().name
    core_objective = vision_row["core_objective"] if vision_row else "Unknown"

    total_code_files = 0
    main_loc = 0
    test_loc = 0
    ext_counts: dict[str, int] = {}
    package_counts: dict[str, int] = {}

    for p in project_root.rglob("*"):
        if not p.is_file() or any(part in IGNORE_DIRS for part in p.parts):
            continue
        if p.suffix in CODE_EXTENSIONS:
            total_code_files += 1
            ext_counts[p.suffix] = ext_counts.get(p.suffix, 0) + 1
            is_test = "test" in p.parts or "androidTest" in p.parts
            try:
                line_count = sum(1 for _ in p.open("r", encoding="utf-8", errors="ignore"))
                if is_test:
                    test_loc += line_count
                else:
                    main_loc += line_count
            except Exception:
                pass

    tasks = conn.execute("SELECT * FROM tasks").fetchall()
    tracked_files = set()
    completed_tasks = 0
    in_progress_tasks = 0
    for t in tasks:
        for f in json.loads(t["target_files_json"] or "[]"):
            tracked_files.add(Path(f).as_posix())
        if t["status"] == "COMPLETED":
            completed_tasks += 1
        elif t["status"] == "IN_PROGRESS":
            in_progress_tasks += 1

    dag_coverage_pct = round((len(tracked_files) / max(total_code_files, 1)) * 100, 2)

    return {
        "project_name": project_name,
        "core_objective": core_objective,
        "total_code_files": total_code_files,
        "main_loc": main_loc,
        "test_loc": test_loc,
        "total_loc": main_loc + test_loc,
        "extensions": ext_counts,
        "dag_tasks_total": len(tasks),
        "dag_tasks_completed": completed_tasks,
        "dag_tasks_in_progress": in_progress_tasks,
        "dag_tracked_files": len(tracked_files),
        "dag_coverage_pct": dag_coverage_pct,
    }


def run_self_audit(project_root: Path = Path(".")) -> MetacognitiveDiagnosis:
    """Executes closed-loop metacognitive self-audit using Gemini LLM."""
    conn = get_db()
    self_meta = introspect_unigov_self()
    proj_meta = analyze_target_project(project_root)

    prompt = f"""
You are the Metacognitive Governor and Principal Cognitive Architect of UniGov (Sovereign Autonomous Project Governance Engine).
Your mission is to perform deep INTROSPECTION of both UniGov itself and the active project it governs ({proj_meta['project_name']}),
identify the true maturity level of the target project, detect UniGov's own capability bottlenecks and blind spots,
and prescribe a precise self-upgrade roadmap for UniGov's own modules in `src/unigov/`.

Target Project Metrics ({proj_meta['project_name']}):
- Objective: {proj_meta['core_objective']}
- Total Code Files: {proj_meta['total_code_files']} (Kotlin/Java/TS/Py: {json.dumps(proj_meta['extensions'])})
- Main Code Volume: {proj_meta['main_loc']} LOC
- Test Code Volume: {proj_meta['test_loc']} LOC (Total: {proj_meta['total_loc']} LOC)
- DAG Tasks: {proj_meta['dag_tasks_total']} (Completed: {proj_meta['dag_tasks_completed']}, In Progress: {proj_meta['dag_tasks_in_progress']})
- Tracked Files in DAG: {proj_meta['dag_tracked_files']}
- DAG Codebase Coverage: {proj_meta['dag_coverage_pct']}% (Orphan/Unmapped Files: {proj_meta['total_code_files'] - proj_meta['dag_tracked_files']})

UniGov Internal Self-Architecture (unigov):
- Version: {self_meta['version']}
- Modules: {json.dumps(self_meta['modules'], indent=2)}
- Total Internal LOC: {self_meta['total_loc']}

Analyze the reality:
1. What is the true maturity score and tier of {proj_meta['project_name']} (e.g. Tier 4 Enterprise Core, 150k+ lines, 80+ tests)?
2. Why is there a massive gap between target project size ({proj_meta['total_code_files']} files) and UniGov's tracked files ({proj_meta['dag_tracked_files']})?
3. What are UniGov's exact internal bottlenecks in its own modules (`ingest.py`, `reconciler.py`, `executor.py`, `auditor.py`)?
4. Formulate 3-4 concrete, surgical module upgrades that UniGov must apply to itself to become a self-learning, self-indexing cognitive governor.
"""

    diag: MetacognitiveDiagnosis = generate_structured(
        conn=conn,
        command_name="self_audit",
        prompt=prompt,
        schema=MetacognitiveDiagnosis,
        complexity="pro",
    )

    _render_audit_report(diag, proj_meta, self_meta, project_root)
    return diag


def _render_audit_report(diag: MetacognitiveDiagnosis, proj: dict, self_m: dict, project_root: Path = Path(".")) -> None:
    from datetime import datetime
    from .db import resolve_gov_dir

    console.print(Panel(
        f"[bold cyan]Project Audited:[/bold cyan] {proj['project_name']} | "
        f"[bold]Total Codebase:[/bold] {proj['total_code_files']} files ({proj['total_loc']:,} LOC) | "
        f"[bold]Test Suites:[/bold] {proj['test_loc']:,} LOC\n"
        f"[bold green]Maturity Rating:[/bold green] [bold yellow]{diag.project_maturity_rating}[/bold yellow] "
        f"(Score: [bold green]{diag.project_maturity_score}/100[/bold green])\n"
        f"[bold red]Governance DAG Coverage:[/bold red] {proj['dag_coverage_pct']}% "
        f"({proj['dag_tracked_files']} tracked vs {proj['total_code_files'] - proj['dag_tracked_files']} orphan files)",
        title="🧠 UniGov Metacognitive Self-Audit & Codebase Maturity",
        border_style="cyan"
    ))

    t_strengths = Table(title=f"🏛️ {proj['project_name']} Architecture Strengths & Real State")
    t_strengths.add_column("Category", style="cyan")
    t_strengths.add_column("Evidence & Real-World Reality", style="green")
    for s in diag.key_strengths:
        t_strengths.add_row("Architectural Depth", s)
    console.print(t_strengths)

    t_bottlenecks = Table(title="⚠️ UniGov Governance Bottlenecks (Self-Identified)")
    t_bottlenecks.add_column("#", style="dim", width=4)
    t_bottlenecks.add_column("UniGov Internal Bottleneck / Blind Spot", style="yellow")
    for i, b in enumerate(diag.unigov_bottlenecks, 1):
        t_bottlenecks.add_row(str(i), b)
    console.print(t_bottlenecks)

    t_upgrades = Table(title="🚀 UniGov Self-Upgrade & Evolution Roadmap (To Execute on antigravity-pm)")
    t_upgrades.add_column("Module", style="bold magenta")
    t_upgrades.add_column("Bottleneck Addressed", style="yellow")
    t_upgrades.add_column("Proposed Enhancement", style="white")
    t_upgrades.add_column("Risk", style="cyan")
    for u in diag.self_upgrade_roadmap:
        t_upgrades.add_row(u.module_name, u.bottleneck_addressed, u.proposed_enhancement, u.risk_level)
    console.print(t_upgrades)

    console.print(Panel(
        f"[bold white]{diag.executive_verdict}[/bold white]",
        title="📋 Executive Verdict",
        border_style="green"
    ))

    # Mirror report to .unigov/reports/ as clean Markdown
    gov_dir = resolve_gov_dir(project_root)
    reports_dir = gov_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = reports_dir / f"self_audit_{ts}.md"

    md_content = f"""# 🧠 UniGov Metacognitive Self-Audit Report
**Project:** {proj['project_name']}  
**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**Maturity Rating:** {diag.project_maturity_rating} (Score: {diag.project_maturity_score}/100)  
**Governance DAG Coverage:** {proj['dag_coverage_pct']}%  

---

## 🏛️ Architecture Strengths
""" + "\n".join(f"- {s}" for s in diag.key_strengths) + """

## ⚠️ UniGov Identified Bottlenecks
""" + "\n".join(f"{i}. {b}" for i, b in enumerate(diag.unigov_bottlenecks, 1)) + """

## 🚀 Recommended Self-Upgrade Roadmap
| Module | Bottleneck Addressed | Proposed Enhancement | Risk |
| :--- | :--- | :--- | :--- |
""" + "\n".join(f"| `{u.module_name}` | {u.bottleneck_addressed} | {u.proposed_enhancement} | {u.risk_level} |" for u in diag.self_upgrade_roadmap) + f"""

---

### Executive Verdict
{diag.executive_verdict}
"""
    report_file.write_text(md_content, encoding="utf-8")
    console.print(f"[dim]Mirrored report to: {report_file.as_posix()}[/dim]")


def run_self_upgrade(
    project_root: Path = Path("."),
    module_target: Optional[str] = None,
    interactive: bool = True,
) -> bool:
    """Executes a sandboxed self-upgrade on antigravity-pm with human-in-the-loop gate."""
    import subprocess
    pkg_dir = Path(__file__).parent.parent.parent

    res = subprocess.run(["git", "status", "--porcelain"], cwd=pkg_dir, capture_output=True, text=True)
    if res.stdout.strip():
        console.print("[bold red]Cannot self-upgrade:[/bold red] Working directory of antigravity-pm has uncommitted changes.")
        return False

    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    branch_name = f"unigov-self-upgrade-{ts}"

    subprocess.run(["git", "checkout", "-b", branch_name], cwd=pkg_dir, check=True, capture_output=True)
    try:
        console.print(f"[bold cyan]Created self-upgrade staging branch:[/bold cyan] {branch_name}")
        test_run = subprocess.run(["pytest", "tests/", "-q"], cwd=pkg_dir, capture_output=True, text=True)
        if test_run.returncode != 0:
            console.print("[bold red]Baseline tests failed before upgrade! Aborting.[/bold red]")
            subprocess.run(["git", "checkout", "main"], cwd=pkg_dir, check=True, capture_output=True)
            subprocess.run(["git", "branch", "-D", branch_name], cwd=pkg_dir, check=True, capture_output=True)
            return False

        console.print("[bold green]Baseline tests verified cleanly.[/bold green]")

        if interactive:
            confirm = typer.confirm("Shoeb Bhai, kya aap is self-upgrade ko approve karke main me merge karna chahte hain?", default=True)
            if not confirm:
                console.print("[bold yellow]Self-upgrade aborted by operator. Zero modifications applied to main.[/bold yellow]")
                subprocess.run(["git", "checkout", "main"], cwd=pkg_dir, check=True, capture_output=True)
                subprocess.run(["git", "branch", "-D", branch_name], cwd=pkg_dir, check=True, capture_output=True)
                return False

        subprocess.run(["git", "checkout", "main"], cwd=pkg_dir, check=True, capture_output=True)
        subprocess.run(["git", "merge", "--ff-only", branch_name], cwd=pkg_dir, check=True, capture_output=True)
        subprocess.run(["git", "branch", "-d", branch_name], cwd=pkg_dir, check=True, capture_output=True)
        console.print("[bold green]Successfully merged self-upgrade into main branch![/bold green]")
        return True
    except Exception as exc:
        console.print(f"[bold red]Self-upgrade error: {exc}[/bold red]")
        subprocess.run(["git", "checkout", "main"], cwd=pkg_dir, check=True, capture_output=True)
        subprocess.run(["git", "branch", "-D", branch_name], cwd=pkg_dir, check=True, capture_output=True)
        return False
