"""Unit and integration test suite for UniGov Sovereign Live HUD & Floating Companion."""

import asyncio
import json
import socket
import urllib.request
import pytest
import websockets

from unigov.hud.server import HudServer, get_state_snapshot, broadcast_event, post_cli_event
from unigov.hud.launcher import get_pill_status_line, is_headless, is_cloud_shell


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def test_hud_state_snapshot_structure():
    snapshot = get_state_snapshot()
    assert isinstance(snapshot, dict)
    assert "project" in snapshot
    assert "layers" in snapshot
    assert "telemetry" in snapshot
    assert "tasks" in snapshot

    telemetry = snapshot["telemetry"]
    assert "total_cost_usd" in telemetry
    assert "tests_passing" in telemetry
    assert "emergency_halt" in telemetry


def test_hud_pill_output():
    line = get_pill_status_line()
    assert "UniGov" in line
    assert "Invariants" in line


def test_environment_detection():
    # Should evaluate without raising exceptions
    headless = is_headless()
    cloud = is_cloud_shell()
    assert isinstance(headless, bool)
    assert isinstance(cloud, bool)


@pytest.mark.anyio
async def test_hud_server_lifecycle_and_endpoints():
    port = find_free_port()
    server = HudServer(host="127.0.0.1", port=port)
    await server.start()

    def do_get(url: str):
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            return resp.status, resp.read().decode("utf-8")

    def do_post(url: str, data: bytes = b"{}"):
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            return resp.status, resp.read().decode("utf-8")

    try:
        base_url = f"http://127.0.0.1:{port}"

        # 1. Test HTTP GET /
        status, content = await asyncio.to_thread(do_get, f"{base_url}/")
        assert status == 200
        assert "UniGov Sovereign HUD" in content
        assert "minimized-pill" in content
        assert "maximized-modal" in content

        # 2. Test HTTP GET /api/snapshot
        status, snap_raw = await asyncio.to_thread(do_get, f"{base_url}/api/snapshot")
        assert status == 200
        snap_data = json.loads(snap_raw)
        assert "project" in snap_data
        assert "layers" in snap_data

        # 3. Test HTTP GET /api/halt
        status, halt_raw = await asyncio.to_thread(do_get, f"{base_url}/api/halt")
        assert status == 200
        halt_data = json.loads(halt_raw)
        assert "emergency_halt" in halt_data

        # 4. Test WebSocket /ws connection
        ws_url = f"ws://127.0.0.1:{port}/ws"
        async with websockets.connect(ws_url) as ws:
            raw_msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
            msg = json.loads(raw_msg)
            assert msg["type"] == "SNAPSHOT"
            assert "payload" in msg

            # Broadcast event test
            await broadcast_event("LOG_STREAM", {"tag": "PYTEST", "message": "All 35 tests passed"})
            bcast_raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
            bcast_msg = json.loads(bcast_raw)
            assert bcast_msg["type"] == "LOG_STREAM"
            assert bcast_msg["payload"]["tag"] == "PYTEST"

    finally:
        await server.stop()
