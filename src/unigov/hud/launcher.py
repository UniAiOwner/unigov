"""Environment Detection and Launcher for UniGov Sovereign HUD."""

import asyncio
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel

from .server import HudServer, get_state_snapshot
from .tui import UniGovCompanionTUI

console = Console()


def is_cloud_shell() -> bool:
    """Checks if currently executing in Google Cloud Shell environment."""
    return bool(
        os.environ.get("CLOUD_SHELL")
        or os.environ.get("DEVSHELL_CLIENT_DIR")
        or Path("/google/devshell").exists()
    )


def is_headless() -> bool:
    """Checks if running in a headless shell without local desktop GUI display."""
    if is_cloud_shell():
        return True
    if os.environ.get("SSH_CLIENT") or os.environ.get("SSH_TTY"):
        return True
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return True
    return False


def get_pill_status_line() -> str:
    """Generates a compact, one-line status string suitable for terminal prompts."""
    snap = get_state_snapshot()
    active = snap.get("active_task") or {}
    task_str = f"{active.get('task_id', 'IDLE')} {active.get('title', '')[:16]}".strip()
    pct = snap.get("overall_progress_pct", 0)
    cost = snap.get("telemetry", {}).get("total_cost_usd", 0.0)
    return f"⬢ UniGov • {task_str} ({pct}%) • 🛡️ 100% Invariants • ${cost:.2f}"


def run_hud(
    tui: bool = False,
    port: int = 54321,
    host: str = "127.0.0.1",
    open_browser: bool = True,
    daemon: bool = False,
) -> None:
    """Launches the Sovereign HUD with automated environment detection."""
    if tui:
        app = UniGovCompanionTUI()
        app.run()
        return

    # Start WebSocket & HTTP Server
    server = HudServer(host=host, port=port)
    loop = asyncio.new_event_loop()

    def _server_thread():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.start())
        loop.run_forever()

    t = threading.Thread(target=_server_thread, daemon=True)
    t.start()
    time.sleep(0.3)

    cloud_shell_env = is_cloud_shell()
    headless_env = is_headless()

    url = f"http://{host}:{port}"
    preview_info = (
        "[bold cyan]Google Cloud Shell Detected:[/bold cyan]\n"
        "Click the [bold green]Web Preview[/bold green] icon in the top-right toolbar of Cloud Shell,\n"
        f"select [bold yellow]Change Port -> {port}[/bold yellow], and click [bold green]Change and Preview[/bold green].\n"
        f"Direct Local URL: [underline cyan]{url}[/underline cyan]"
        if cloud_shell_env
        else f"Open in your browser or popup window: [bold cyan]{url}[/bold cyan]"
    )

    console.print(
        Panel.fit(
            f"[bold blue]⬢ UniGov Sovereign HUD v0.9.0[/bold blue]\n"
            f"[dim]Live Execution Companion & Floating Dynamic Island[/dim]\n\n"
            f"• [bold white]Web HUD & REST API:[/bold white] {url}\n"
            f"• [bold white]WebSocket Event Bus:[/bold white] ws://{host}:{port}/ws\n"
            f"• [bold white]Mode:[/bold white] {'Cloud Shell Web Preview' if cloud_shell_env else ('Headless SSH' if headless_env else 'Desktop Popup')}\n\n"
            f"{preview_info}\n\n"
            f"[dim]Press [bold white]Ctrl+C[/bold white] to stop HUD server. Terminal TUI available with [cyan]unigov hud --tui[/cyan][/dim]",
            title="[bold green]Sovereign HUD Online[/bold green]",
            border_style="blue",
        )
    )

    if open_browser and not headless_env and not cloud_shell_env:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    if daemon:
        console.print("[green]HUD server daemonized in background.[/green]")
        return

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping Sovereign HUD server...[/yellow]")
        loop.call_soon_threadsafe(loop.stop)
