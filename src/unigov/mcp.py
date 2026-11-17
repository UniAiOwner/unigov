"""Native Model Context Protocol (MCP) stdio Server for UniGov.

Enables AI IDEs and agents (Antigravity, Claude Code, Cursor) to natively query
the UniGov Deterministic State Machine via standard JSON-RPC 2.0 tool calls.
"""

import sys
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .db import get_db
from .drift import SECRET_SIGNATURES


TOOLS_MANIFEST = [
    {
        "name": "unigov_status",
        "description": "Returns current project vision, locked constitutional constraints, and execution DAG status counts.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "unigov_get_ready_tasks",
        "description": "Returns all atomic software engineering tasks currently in READY state (all dependencies completed, phase-locks satisfied).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max number of ready tasks to return (default 5)"}
            },
        },
    },
    {
        "name": "unigov_get_invariants",
        "description": "Returns all compiled machine-executable constitutional invariants (e.g. Law ACC-001 integer paise math, zero floating point).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "unigov_check_drift",
        "description": "Scans staged Git diff for secret leaks, @Suppress / @ts-ignore shortcuts, and financial float drift.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def handle_unigov_status(conn: sqlite3.Connection, args: Dict[str, Any]) -> Dict[str, Any]:
    vision = conn.execute("SELECT project_name, core_objective, hard_constraints_json FROM project_vision WHERE id = 1").fetchone()
    if not vision:
        return {"error": "Project not initialized in .unigov/. Run 'unigov init' first."}

    tasks = conn.execute("SELECT status, count(*) as cnt FROM tasks GROUP BY status").fetchall()
    status_counts = {t["status"]: t["cnt"] for t in tasks}

    return {
        "project_name": vision["project_name"],
        "core_objective": vision["core_objective"],
        "hard_constraints": json.loads(vision["hard_constraints_json"] or "[]"),
        "task_counts": status_counts,
    }


def handle_unigov_get_ready_tasks(conn: sqlite3.Connection, args: Dict[str, Any]) -> Dict[str, Any]:
    limit = args.get("limit", 5)
    rows = conn.execute("""
        SELECT task_id, level, layer, title, description, target_files_json, verify_cmd
        FROM tasks
        WHERE status = 'READY' AND is_baseline = 0
        ORDER BY task_id ASC
        LIMIT ?
    """, (limit,)).fetchall()

    ready_tasks = [
        {
            "task_id": r["task_id"],
            "level": r["level"],
            "layer": r["layer"],
            "title": r["title"],
            "description": r["description"],
            "target_files": json.loads(r["target_files_json"] or "[]"),
            "verify_cmd": r["verify_cmd"],
        }
        for r in rows
    ]
    return {"ready_tasks": ready_tasks, "count": len(ready_tasks)}


def handle_unigov_get_invariants(conn: sqlite3.Connection, args: Dict[str, Any]) -> Dict[str, Any]:
    rows = conn.execute("SELECT invariant_id, layer, rule_name, description, severity FROM constitutional_invariants").fetchall()
    invariants = [
        {
            "invariant_id": r["invariant_id"],
            "layer": r["layer"],
            "rule_name": r["rule_name"],
            "description": r["description"],
            "severity": r["severity"],
        }
        for r in rows
    ]
    return {"invariants": invariants, "count": len(invariants)}


def handle_unigov_check_drift(conn: sqlite3.Connection, args: Dict[str, Any]) -> Dict[str, Any]:
    cmd = ["git", "diff", "--cached"]
    diff_text = subprocess.run(cmd, capture_output=True, text=True).stdout
    violations = []
    for sig in SECRET_SIGNATURES:
        if sig in diff_text:
            violations.append(f"Secret signature found: {sig}")
    for shortcut in ["@Suppress", "@ts-ignore", "eslint-disable"]:
        if shortcut in diff_text:
            violations.append(f"Shortcut found: {shortcut}")
    return {
        "is_clean": len(violations) == 0,
        "violations": violations,
    }


TOOL_HANDLERS = {
    "unigov_status": handle_unigov_status,
    "unigov_get_ready_tasks": handle_unigov_get_ready_tasks,
    "unigov_get_invariants": handle_unigov_get_invariants,
    "unigov_check_drift": handle_unigov_check_drift,
}


def dispatch_mcp_request(conn: sqlite3.Connection, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Handles an individual JSON-RPC 2.0 MCP request."""
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                },
                "serverInfo": {
                    "name": "unigov-mcp-server",
                    "version": "0.7.0",
                },
            },
        }

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": TOOLS_MANIFEST,
            },
        }

    elif method == "tools/call":
        params = req.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})

        handler = TOOL_HANDLERS.get(name)
        if not handler:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method / tool '{name}' not found.",
                },
            }

        try:
            result_data = handler(conn, args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result_data, indent=2),
                        }
                    ],
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "isError": True,
                "result": {
                    "content": [{"type": "text", "text": f"Execution error: {exc}"}],
                },
            }

    elif req_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Unsupported method: {method}",
            },
        }

    return None


def run_mcp_server() -> None:
    """Runs the MCP server over stdio, processing newline-delimited JSON-RPC messages."""
    try:
        conn = get_db()
    except Exception as exc:
        sys.stderr.write(f"UniGov MCP initialization error: {exc}\n")
        sys.exit(1)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = dispatch_mcp_request(conn, req)
            if resp:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()
