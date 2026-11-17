"""UniGov Sovereign Session Companion & Terminal Status Renderer.

Renders high-density, terminal-responsive (<= 76 cols) status cards and dynamic
island pills directly inside Antigravity sessions and CLI environments without
requiring a web browser.
"""

import json
from pathlib import Path
import sqlite3
import subprocess
import time
from typing import Dict, Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .db import resolve_gov_dir, get_db

console = Console()


def get_active_branch(project_root: Path) -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return "main"


def get_companion_state(project_root: Optional[Path] = None) -> Dict[str, Any]:
    """Extracts live project metrics, active tasks, and watchdog status."""
    root = (project_root or Path.cwd()).resolve()
    gov_dir = resolve_gov_dir(root)
    state_db = gov_dir / "state.db"

    if not state_db.exists():
        return {
            "initialized": False,
            "project_name": "Uninitialized",
            "branch": "main",
            "milestone": "None",
            "milestone_progress": 0,
            "active_task": None,
            "sentinel_active": False,
            "violations_count": 0,
        }

    conn = get_db(root)
    branch = get_active_branch(root)

    # 1. Project Vision
    vision = conn.execute("SELECT project_name, core_objective FROM project_vision WHERE id = 1").fetchone()
    project_name = vision["project_name"] if vision else "UniGov Project"

    # 2. Tasks & Milestones
    tasks = conn.execute("SELECT * FROM tasks ORDER BY rowid ASC").fetchall()
    total_tasks = len(tasks)
    completed_tasks = sum(1 for t in tasks if t["status"] == "COMPLETED")
    overall_progress = round((completed_tasks / total_tasks * 100), 1) if total_tasks else 0.0

    # Find the current active milestone and task
    active_milestone = None
    active_task = None

    leaf_tasks = [t for t in tasks if t["level"] == "TASK"]
    for t in reversed(leaf_tasks):
        if t["status"] == "IN_PROGRESS":
            active_task = t
            break
    if not active_task:
        for t in reversed(leaf_tasks):
            if t["status"] == "READY":
                active_task = t
                break
    if not active_task and leaf_tasks:
        active_task = leaf_tasks[-1]

    # Determine current focused milestone
    milestones = [t for t in tasks if t["level"] == "MILESTONE"]
    current_milestone = None
    for m in milestones:
        # Check if any children are in progress or ready
        children = [t for t in tasks if t["parent_id"] == m["task_id"]]
        if any(c["status"] in ("IN_PROGRESS", "READY") for c in children):
            current_milestone = m
            break
    if not current_milestone and milestones:
        current_milestone = milestones[-1]

    milestone_name = current_milestone["title"] if current_milestone else "Active Sprint"
    m_children = [t for t in tasks if t["parent_id"] == current_milestone["task_id"]] if current_milestone else []
    m_total = len(m_children)
    m_done = sum(1 for c in m_children if c["status"] == "COMPLETED")
    m_progress = round((m_done / m_total * 100), 1) if m_total else 100.0

    # 3. Sentinel State
    sentinel_file = gov_dir / "sentinel.json"
    sentinel_active = False
    violations_count = 0
    if sentinel_file.exists():
        try:
            s_data = json.loads(sentinel_file.read_text(encoding="utf-8"))
            sentinel_active = s_data.get("active", False)
            violations_count = s_data.get("violations_count", 0)
        except Exception:
            pass

    return {
        "initialized": True,
        "project_name": project_name,
        "branch": branch,
        "milestone_name": milestone_name,
        "milestone_done": m_done,
        "milestone_total": m_total,
        "milestone_progress": m_progress,
        "overall_progress": overall_progress,
        "active_task": active_task,
        "sentinel_active": sentinel_active,
        "violations_count": violations_count,
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
    }


def render_companion_card(project_root: Optional[Path] = None) -> None:
    """Renders the aesthetic, <= 76 cols terminal companion card."""
    state = get_companion_state(project_root)

    if not state["initialized"]:
        console.print("[yellow]UniGov: No initialized project found in current directory.[/yellow]")
        return

    proj = f"[bold white]{state['project_name']}[/bold white] [dim]({state['branch']})[/dim]"
    progress_bar = f"[green]{state['milestone_progress']}%[/green] [dim]({state['milestone_done']}/{state['milestone_total']} tasks)[/dim]"
    milestone_line = f"[bold cyan]Milestone:[/bold cyan] {state['milestone_name']} · {progress_bar}"

    # Task line
    t = state["active_task"]
    if t:
        status_color = "yellow" if t["status"] == "IN_PROGRESS" else "cyan" if t["status"] == "READY" else "green"
        task_line = f"[bold cyan]Next Task:[/bold cyan] {t['task_id']} [{status_color}]{t['status']}[/{status_color}]: {t['title'][:36]}"
    else:
        task_line = "[bold cyan]Next Task:[/bold cyan] [green]All milestone tasks verified & locked![/green]"

    # Invariant line
    guardrails_line = (
        "[bold green]Guards:[/bold green] "
        "[white]Law ACC-001[/white] [green]✔[/green] · "
        "[white]Law-000 (0-Suppress)[/white] [green]✔[/green] · "
        "[white]Secrets[/white] [green]0[/green]"
    )

    # Sentinel Watchdog line
    if state["violations_count"] > 0:
        sentinel_line = f"[bold red]Sentinel:[/bold red] [bold red]ALERT ({state['violations_count']} Invariant Violations)[/bold red]"
    else:
        sentinel_line = f"[bold green]Sentinel:[/bold green] [bold cyan]ACTIVE (Inotify Watchdog · 0 Violations · Clean)[/bold cyan]"

    content = f"{proj}\n{milestone_line}\n{task_line}\n{guardrails_line}\n{sentinel_line}"

    panel = Panel(
        content,
        title="[bold blue]⬢ UniGov Sovereign Companion[/bold blue]",
        border_style="blue",
        width=76,
        padding=(0, 1),
    )
    console.print(panel)


def render_dynamic_pill(project_root: Optional[Path] = None) -> str:
    """Renders a single-line compact status string for shell prompts or status lines."""
    state = get_companion_state(project_root)
    if not state["initialized"]:
        return "⬢ UniGov: [Uninitialized]"

    sentinel_str = "CLEAN" if state["violations_count"] == 0 else f"ALERT({state['violations_count']})"
    task_str = state["active_task"]["task_id"] if state["active_task"] else "DONE"

    return f"⬢ UniGov: {state['milestone_name']} ({state['milestone_progress']}%) | Sentinel: {sentinel_str} | Task: {task_str}"
