import hashlib
import sqlite3
from pathlib import Path
import typer
from rich.console import Console

console = Console()

GLOBAL_AG_DIR = Path.home() / ".antigravity"
ECOSYSTEM_DB_PATH = GLOBAL_AG_DIR / "ecosystem.db"


def get_ecosystem_db() -> sqlite3.Connection:
    GLOBAL_AG_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ECOSYSTEM_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS published_contracts (
        contract_id TEXT PRIMARY KEY,
        producer_project TEXT NOT NULL,
        contract_file_path TEXT NOT NULL,
        schema_hash TEXT NOT NULL,
        version TEXT NOT NULL,
        breaking_notes TEXT,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS contract_subscriptions (
        consumer_project TEXT NOT NULL,
        consumer_root_path TEXT NOT NULL,
        contract_id TEXT NOT NULL REFERENCES published_contracts(contract_id) ON DELETE CASCADE,
        acknowledged_hash TEXT NOT NULL,
        subscribed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (consumer_project, contract_id)
    );
    """)
    conn.commit()
    return conn


def publish_contract(project_name: str, contract_id: str, schema_file: Path, version: str, notes: str = "") -> None:
    if not schema_file.exists():
        console.print(f"[bold red]Error:[/bold red] Schema file not found: {schema_file}")
        raise typer.Exit(1)

    abs_path = schema_file.resolve()
    schema_hash = hashlib.sha256(abs_path.read_bytes()).hexdigest()
    eco_conn = get_ecosystem_db()

    with eco_conn:
        eco_conn.execute(
            """
            INSERT INTO published_contracts (contract_id, producer_project, contract_file_path, schema_hash, version, breaking_notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(contract_id) DO UPDATE SET
                contract_file_path = excluded.contract_file_path,
                schema_hash = excluded.schema_hash,
                version = excluded.version,
                breaking_notes = excluded.breaking_notes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (contract_id, project_name, str(abs_path), schema_hash, version, notes),
        )
    console.print(f"[bold green]Published Contract:[/bold green] {contract_id} (v{version}, hash: {schema_hash[:10]})")


def subscribe_contract(consumer_project: str, contract_id: str) -> None:
    eco_conn = get_ecosystem_db()
    row = eco_conn.execute("SELECT * FROM published_contracts WHERE contract_id = ?", (contract_id,)).fetchone()
    if not row:
        console.print(f"[bold red]Error:[/bold red] Contract '{contract_id}' does not exist in global registry.")
        raise typer.Exit(1)

    with eco_conn:
        eco_conn.execute(
            """
            INSERT OR REPLACE INTO contract_subscriptions (consumer_project, consumer_root_path, contract_id, acknowledged_hash)
            VALUES (?, ?, ?, ?)
            """,
            (consumer_project, str(Path.cwd().resolve()), contract_id, row["schema_hash"]),
        )
    console.print(f"[bold cyan]Subscribed:[/bold cyan] '{consumer_project}' is now tracking '{contract_id}' (v{row['version']}).")


def acknowledge_contract(consumer_project: str, contract_id: str) -> None:
    eco_conn = get_ecosystem_db()
    row = eco_conn.execute(
        """
        SELECT cs.acknowledged_hash, pc.producer_project, pc.schema_hash, pc.version, pc.breaking_notes
        FROM contract_subscriptions cs
        JOIN published_contracts pc ON cs.contract_id = pc.contract_id
        WHERE cs.consumer_project = ? AND cs.contract_id = ?
        """,
        (consumer_project, contract_id),
    ).fetchone()

    if not row:
        console.print(f"[bold red]Error:[/bold red] '{consumer_project}' is not subscribed to '{contract_id}'.")
        raise typer.Exit(1)

    if row["acknowledged_hash"] == row["schema_hash"]:
        console.print(f"[green]Already up to date:[/green] '{contract_id}' (v{row['version']}) is already acknowledged.")
        return

    console.print(f"[yellow]Upstream Update:[/yellow] {row['producer_project']} -> v{row['version']} ({row['breaking_notes'] or 'no notes'})")
    if not typer.confirm(f"Confirm that '{consumer_project}' code has been updated to match '{contract_id}' v{row['version']}?"):
        console.print("[yellow]Acknowledgement cancelled.[/yellow]")
        return

    with eco_conn:
        eco_conn.execute(
            """
            UPDATE contract_subscriptions
            SET acknowledged_hash = ?, subscribed_at = CURRENT_TIMESTAMP
            WHERE consumer_project = ? AND contract_id = ?
            """,
            (row["schema_hash"], consumer_project, contract_id),
        )
    console.print(f"[bold green]Acknowledged:[/bold green] '{contract_id}' synced to v{row['version']}.")


def check_ecosystem_sync(consumer_project: str) -> list[str]:
    eco_conn = get_ecosystem_db()
    subs = eco_conn.execute(
        """
        SELECT cs.contract_id, cs.acknowledged_hash, pc.producer_project, pc.schema_hash, pc.version, pc.breaking_notes
        FROM contract_subscriptions cs
        JOIN published_contracts pc ON cs.contract_id = pc.contract_id
        WHERE cs.consumer_project = ?
        """,
        (consumer_project,),
    ).fetchall()

    alerts = []
    for s in subs:
        if s["acknowledged_hash"] != s["schema_hash"]:
            alerts.append(
                f"CONTRACT DRIFT: '{s['contract_id']}' from {s['producer_project']} updated to v{s['version']} "
                f"(notes: {s['breaking_notes'] or 'none'}). Run 'antigravity-pm contract-ack {s['contract_id']}' after syncing."
            )
    return alerts
