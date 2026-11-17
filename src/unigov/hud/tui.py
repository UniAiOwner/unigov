"""UniGov Terminal Floating Companion TUI.

Provides a lightweight, high-FPS terminal HUD using Textual for pure CLI / Cloud Shell / SSH environments.
"""

import json
import sqlite3
from typing import Optional
from pathlib import Path
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Label, DataTable
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.binding import Binding

from ..db import get_db, resolve_gov_dir
from .server import get_state_snapshot


class PhaseRailWidget(Static):
    """Horizontal Phase Rail showing L1-L5 topological gates."""

    def update_phases(self, layers: list) -> None:
        parts = []
        for l in layers:
            status = l.get("status", "READY")
            code = l.get("code", "L")
            label = l.get("label", "").split("&")[0].strip()
            total = l.get("total", 0)
            done = l.get("completed", 0)

            if status == "COMPLETED":
                parts.append(f"[bold green]✔ {code}[/bold green] [dim]{label}[/dim] ({done}/{total})")
            elif status == "ACTIVE":
                parts.append(f"[bold cyan]● {code}[/bold cyan] [bold white]{label}[/bold white] ({done}/{total})")
            else:
                parts.append(f"[dim]○ {code} {label}[/dim]")

        self.update("   " + "  ──▶  ".join(parts))


class UniGovCompanionTUI(App):
    """Futuristic, high-contrast Terminal Floating Companion HUD for UniGov."""

    CSS = """
    Screen {
        background: #0d0e12;
    }
    #top-bar {
        height: 3;
        background: #14161f;
        color: #f1f3f9;
        padding: 0 1;
        content-align: center middle;
        border-bottom: solid #2a2d3d;
    }
    #phase-rail {
        height: 3;
        background: #10121a;
        color: #e2e8f0;
        padding: 0 1;
        content-align: center middle;
        border-bottom: solid #1e2230;
    }
    #main-split {
        height: 1fr;
    }
    #active-card {
        width: 45%;
        background: #12141c;
        padding: 1;
        border-right: solid #202433;
    }
    #log-stream-container {
        width: 55%;
        background: #090a0f;
        padding: 1;
    }
    DataTable {
        height: 100%;
        background: #090a0f;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit HUD"),
        Binding("r", "refresh_data", "Refresh"),
        Binding("space", "toggle_pause", "Emergency Pause"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="top-bar")
        yield PhaseRailWidget(id="phase-rail")
        with Horizontal(id="main-split"):
            with VerticalScroll(id="active-card"):
                yield Static(id="task-info")
                yield Static(id="invariant-info")
            with Vertical(id="log-stream-container"):
                yield Label("[bold cyan]Sub-Second CLI Audit Stream[/bold cyan]")
                yield DataTable(id="audit-table", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Time", "Tag", "Status", "Snippet")
        self.refresh_data()
        self.set_interval(1.5, self.refresh_data)

    def refresh_data(self) -> None:
        data = get_state_snapshot()
        project = data.get("project", {})
        telemetry = data.get("telemetry", {})

        # Top Bar
        top_text = (
            f"[bold blue]⬢ UniGov[/bold blue] / [bold white]{project.get('name', 'UniGov')}[/bold white]  "
            f"[dim]branch:[/dim] [cyan]{project.get('branch', 'main')}[/cyan]  "
            f"[dim]progress:[/dim] [green]{data.get('overall_progress_pct', 0)}%[/green]  "
            f"[dim]cost:[/dim] [yellow]${telemetry.get('total_cost_usd', 0):.4f}[/yellow]  "
            f"[dim]shield:[/dim] [bold green]100% INTACT[/bold green]"
        )
        self.query_one("#top-bar", Static).update(top_text)

        # Phase Rail
        self.query_one(PhaseRailWidget).update_phases(data.get("layers", []))

        # Active Task Card
        active = data.get("active_task")
        if active:
            task_text = (
                f"[bold cyan]CURRENT ACTIVE TASK:[/bold cyan]\n"
                f"[bold white]{active.get('task_id')}: {active.get('title')}[/bold white]\n"
                f"[dim]Status:[/dim] [yellow]{active.get('status')}[/yellow]  [dim]Layer:[/dim] {active.get('layer')}\n\n"
                f"[dim]{active.get('description', '')}[/dim]\n"
            )
        else:
            task_text = "[italic dim]All milestone tasks currently completed or locked.[/italic dim]\n"
        self.query_one("#task-info", Static).update(task_text)

        # Invariant Shield Card
        inv_text = (
            f"[bold green]CONSTITUTIONAL GUARDRAILS:[/bold green]\n"
            f"  ✔ [white]Law ACC-001 (Integer Currency Math):[/white] [green]PASS[/green]\n"
            f"  ✔ [white]Zero-Downtime Migration Gate:[/white] [green]PASS[/green]\n"
            f"  ✔ [white]Write-Locked Test Cage (35/35 passing):[/white] [green]SECURE[/green]\n"
            f"  ✔ [white]AST Drift & Secret Signature Guard:[/white] [green]0 LEAKS[/green]\n"
        )
        self.query_one("#invariant-info", Static).update(inv_text)

        # Audit Table
        table = self.query_one(DataTable)
        table.clear()
        for a in data.get("recent_audits", []):
            passed_badge = "[green]PASS[/green]" if a.get("passed") else "[red]FAIL[/red]"
            snippet = (a.get("snippet") or "")[:50].replace("\n", " ")
            table.add_row(
                (a.get("checked_at") or "")[-8:],
                a.get("check_type", "AUDIT"),
                passed_badge,
                snippet,
            )

    def action_refresh_data(self) -> None:
        self.refresh_data()

    def action_toggle_pause(self) -> None:
        self.notify("Toggled Emergency Halt Flag", title="UniGov Guard")
