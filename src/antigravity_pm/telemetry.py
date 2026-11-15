import sqlite3
from rich.console import Console
from rich.table import Table

console = Console()

MODEL_PRICING_PER_1M = {
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
}
USD_TO_INR = 84.5


def log_gemini_usage(conn: sqlite3.Connection, command_name: str, model_name: str, response) -> None:
    meta = getattr(response, "usage_metadata", None)
    if not meta:
        return

    prompt_tok = getattr(meta, "prompt_token_count", 0) or 0
    output_tok = getattr(meta, "candidates_token_count", 0) or 0

    rates = MODEL_PRICING_PER_1M.get(model_name, {"input": 0.15, "output": 0.60})
    cost_usd = (prompt_tok / 1_000_000) * rates["input"] + (output_tok / 1_000_000) * rates["output"]

    with conn:
        conn.execute(
            """
            INSERT INTO api_usage_logs (command_name, model_name, prompt_tokens, output_tokens, estimated_cost_usd)
            VALUES (?, ?, ?, ?, ?)
            """,
            (command_name, model_name, prompt_tok, output_tok, round(cost_usd, 6)),
        )


def print_cost_summary(conn: sqlite3.Connection) -> None:
    rows = conn.execute("""
        SELECT command_name, model_name,
               COUNT(*) AS calls,
               SUM(prompt_tokens) AS total_in,
               SUM(output_tokens) AS total_out,
               SUM(estimated_cost_usd) AS total_usd
        FROM api_usage_logs
        GROUP BY command_name, model_name
    """).fetchall()

    if not rows:
        console.print("[yellow]No Gemini API usage logged yet.[/yellow]")
        return

    table = Table(title="Gemini API Token & Cost Telemetry")
    table.add_column("Command", style="cyan")
    table.add_column("Model")
    table.add_column("Calls", justify="right")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Output Tokens", justify="right")
    table.add_column("Est. Cost (USD / INR)", justify="right", style="green")

    grand_usd = 0.0
    for r in rows:
        usd = r["total_usd"] or 0.0
        grand_usd += usd
        table.add_row(
            r["command_name"],
            r["model_name"],
            str(r["calls"]),
            f"{r['total_in']:,}",
            f"{r['total_out']:,}",
            f"${usd:.4f} (₹{usd * USD_TO_INR:.2f})",
        )

    console.print(table)
    console.print(f"[bold]Total Cumulative Spend:[/bold] ${grand_usd:.4f} (~₹{grand_usd * USD_TO_INR:.2f})")
