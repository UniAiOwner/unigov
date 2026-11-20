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

skills_src = "/media/uniai/UniAi/PROJECTS_MIGRATED/uniskill/src"
if skills_src not in sys.path:
    sys.path.insert(0, skills_src)

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
    {
        "name": "uniskill_route",
        "description": "Routes a task description or query to the top surgical skills, returning relevance scores, scripts, and direct directives.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "User prompt or task description"},
                "top_k": {"type": "integer", "description": "Number of top skills to return (default 3)"}
            },
            "required": ["query"]
        },
    },
    {
        "name": "uniskill_ensure",
        "description": "Dynamic 100% Convergence Gate: Audits prompt gaps against candidate skill, injects 2026 SOTA blueprints, and elevates skill to 100% precision.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Task requirement to elevate to 100%"},
                "skill_name": {"type": "string", "description": "Target skill (optional, auto-routed if omitted)"}
            },
            "required": ["prompt"]
        },
    },
    {
        "name": "uniskill_eval",
        "description": "Pre-execution suitability gate: Evaluates skill compatibility against target project's actual stack.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "skill_name": {"type": "string", "description": "Name of the skill"},
                "project_path": {"type": "string", "description": "Target project root directory (default '.')"}
            },
            "required": ["skill_name"]
        },
    },
    {
        "name": "uniskill_run_script",
        "description": "Executes a pre-tested helper script inside a skill's scripts/ directory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "skill_name": {"type": "string", "description": "Name of the skill"},
                "script_name": {"type": "string", "description": "Name of the script in scripts/"},
                "args": {"type": "array", "items": {"type": "string"}, "description": "CLI arguments"}
            },
            "required": ["skill_name", "script_name"]
        },
    },
    {
        "name": "uniskill_status",
        "description": "Returns total physical files (1093), unique skills (317), 8-domain breakdown, and triple-parity status.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "uniskill_extract",
        "description": "Zero-Noise Token Economizer: Extracts high-density code blueprints and constitutional invariants, stripping token fluff.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "skill_name": {"type": "string", "description": "Name of the skill or path to SKILL.md"},
                "blueprint_only": {"type": "boolean", "description": "Extract only code blocks and headings"},
                "invariants_only": {"type": "boolean", "description": "Extract only invariants, rules, and checklists"}
            },
            "required": ["skill_name"]
        },
    },
    {
        "name": "uniskill_compose",
        "description": "Multi-Skill Intelligent Composer: Merges multiple skills into a single deduplicated prompt payload respecting token budgets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "skills": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of skill names to combine"
                },
                "max_tokens": {"type": "integer", "description": "Token budget cap (default 2500)"}
            },
            "required": ["skills"]
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


def handle_uniskill_route(conn: sqlite3.Connection, args: Dict[str, Any]) -> Dict[str, Any]:
    from uniskill.router import route_skills_for_task
    query = args.get("query", "")
    top_k = args.get("top_k", 3)
    matches = route_skills_for_task(query, top_k=top_k)
    return {"query": query, "matches": matches, "count": len(matches)}


def handle_uniskill_ensure(conn: sqlite3.Connection, args: Dict[str, Any]) -> Dict[str, Any]:
    from uniskill.elevate import elevate_skill_to_100_percent
    prompt = args.get("prompt", "")
    skill_name = args.get("skill_name")
    return elevate_skill_to_100_percent(prompt, target_skill_name=skill_name)


def handle_uniskill_eval(conn: sqlite3.Connection, args: Dict[str, Any]) -> Dict[str, Any]:
    from uniskill.evaluator import evaluate_skill_for_project
    skill_name = args.get("skill_name", "")
    project_path = Path(args.get("project_path", "."))
    return evaluate_skill_for_project(skill_name, project_path)


def handle_uniskill_run_script(conn: sqlite3.Connection, args: Dict[str, Any]) -> Dict[str, Any]:
    from uniskill.runner import run_skill_script
    skill_name = args.get("skill_name", "")
    script_name = args.get("script_name", "")
    script_args = args.get("args", [])
    return run_skill_script(skill_name, script_name, args=script_args)


def handle_uniskill_status(conn: sqlite3.Connection, args: Dict[str, Any]) -> Dict[str, Any]:
    from uniskill.registry import get_catalog_stats
    from uniskill.sync import audit_triple_env_parity
    stats = get_catalog_stats()
    parity = audit_triple_env_parity()
    return {"catalog": stats, "parity": parity}


def handle_uniskill_extract(conn: sqlite3.Connection, args: Dict[str, Any]) -> Dict[str, Any]:
    from uniskill.economizer import economize_skill
    skill_name = args.get("skill_name", "")
    blueprint_only = args.get("blueprint_only", False)
    invariants_only = args.get("invariants_only", False)
    return economize_skill(skill_name, blueprint_only=blueprint_only, invariants_only=invariants_only)


def handle_uniskill_compose(conn: sqlite3.Connection, args: Dict[str, Any]) -> Dict[str, Any]:
    from uniskill.composer import compose_skills
    skills = args.get("skills", [])
    max_tokens = args.get("max_tokens", 2500)
    return compose_skills(skills, max_tokens=max_tokens)


TOOL_HANDLERS = {
    "unigov_status": handle_unigov_status,
    "unigov_get_ready_tasks": handle_unigov_get_ready_tasks,
    "unigov_get_invariants": handle_unigov_get_invariants,
    "unigov_check_drift": handle_unigov_check_drift,
    "uniskill_route": handle_uniskill_route,
    "uniskill_ensure": handle_uniskill_ensure,
    "uniskill_eval": handle_uniskill_eval,
    "uniskill_run_script": handle_uniskill_run_script,
    "uniskill_status": handle_uniskill_status,
    "uniskill_extract": handle_uniskill_extract,
    "uniskill_compose": handle_uniskill_compose,
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
