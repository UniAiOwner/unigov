import sqlite3
from pathlib import Path
import typer
from rich.console import Console

console = Console()

AG_DIR = Path(".antigravity")
DB_PATH = AG_DIR / "state.db"


def get_db(require_init: bool = True) -> sqlite3.Connection:
    if require_init and not DB_PATH.exists():
        console.print("[bold red]Error:[/bold red] Workspace not initialized. Run [cyan]antigravity-pm init[/cyan] first.")
        raise typer.Exit(1)
    AG_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS project_vision (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        project_name TEXT NOT NULL,
        core_objective TEXT NOT NULL,
        hard_constraints_json TEXT NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS ingested_docs (
        doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT UNIQUE NOT NULL,
        file_hash TEXT NOT NULL,
        last_ingested_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS tasks (
        task_id TEXT PRIMARY KEY,
        parent_id TEXT REFERENCES tasks(task_id) ON DELETE CASCADE,
        level TEXT NOT NULL CHECK(level IN ('MILESTONE', 'MODULE', 'TASK')),
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        target_files_json TEXT,
        verify_cmd TEXT,
        status TEXT NOT NULL DEFAULT 'PENDING'
            CHECK(status IN ('PENDING', 'READY', 'IN_PROGRESS', 'VERIFYING', 'COMPLETED', 'FAILED', 'BLOCKED')),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        completed_at DATETIME
    );

    CREATE TABLE IF NOT EXISTS task_dependencies (
        task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
        depends_on_task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
        PRIMARY KEY (task_id, depends_on_task_id),
        CHECK (task_id != depends_on_task_id)
    );

    CREATE TABLE IF NOT EXISTS adr_ledger (
        adr_id TEXT PRIMARY KEY,
        module_tag TEXT NOT NULL,
        decision TEXT NOT NULL,
        rationale TEXT NOT NULL,
        rejected_alternatives TEXT,
        status TEXT DEFAULT 'FINALIZED' CHECK(status IN ('FINALIZED', 'PROPOSED', 'DEPRECATED')),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT REFERENCES tasks(task_id),
        check_type TEXT NOT NULL,
        passed INTEGER NOT NULL CHECK(passed IN (0, 1)),
        output_snippet TEXT,
        checked_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS git_checkpoints (
        checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL REFERENCES tasks(task_id),
        tag_name TEXT UNIQUE NOT NULL,
        commit_hash TEXT NOT NULL,
        had_uncommitted_changes INTEGER NOT NULL DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS api_usage_logs (
        usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
        command_name TEXT NOT NULL,
        model_name TEXT NOT NULL,
        prompt_tokens INTEGER NOT NULL,
        output_tokens INTEGER NOT NULL,
        estimated_cost_usd REAL NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS invariants (
        invariant_id TEXT PRIMARY KEY,
        layer TEXT NOT NULL,
        title TEXT NOT NULL,
        rule_type TEXT NOT NULL,
        file_patterns_json TEXT NOT NULL,
        params_json TEXT NOT NULL,
        enforcement TEXT NOT NULL CHECK(enforcement IN ('BLOCK_BUILD', 'WARN')),
        source_doc TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Ensure tasks table has layer column
    cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    if "layer" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN layer TEXT DEFAULT 'LAYER_1_DOMAIN'")

    conn.commit()
