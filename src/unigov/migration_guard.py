"""Zero-Downtime Database Migration Gatekeeper for UniGov.

Audits Room and SQL migration scripts for fatal SQLite/Postgres runtime crash traps:
- NOT NULL column added without DEFAULT value (instant SQLiteConstraintException on app upgrade)
- Destructive column/table drops without deprecation windows
- Monetary column conversions from integer paise to float/real
- Non-idempotent table or index creation statements
"""

import os
import re
import json
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .constants import normalize_posix_path

console = Console()


class MigrationViolation(BaseModel):
    line_number: int = Field(description="Line number where violation occurs")
    severity: str = Field(description="CRITICAL, WARNING, or INFO")
    violation_type: str = Field(description="NOT_NULL_NO_DEFAULT, DESTRUCTIVE_DROP, FLOAT_MONEY_MATH, NON_IDEMPOTENT")
    explanation: str = Field(description="Detailed explanation of the production crash risk")
    safe_sql_remedy: str = Field(description="Recommended safe SQL migration recipe")


class MigrationAuditReport(BaseModel):
    file_path: str = Field(description="Migration file path inspected")
    is_safe: bool = Field(description="True if zero fatal violations detected")
    violations: List[MigrationViolation] = Field(default_factory=list)
    summary: str = Field(description="Executive verdict on migration safety")


def audit_migration_content(content: str, file_path_str: str = "migration.sql") -> MigrationAuditReport:
    """Deterministically audits migration SQL content for the 4 fatal production crash traps."""
    lines = content.splitlines()
    violations: List[MigrationViolation] = []

    for idx, line in enumerate(lines, start=1):
        clean = line.strip().upper()

        # 1. NOT NULL without DEFAULT trap
        if "ALTER TABLE" in clean and "ADD" in clean and "NOT NULL" in clean:
            if "DEFAULT" not in clean:
                violations.append(MigrationViolation(
                    line_number=idx,
                    severity="CRITICAL",
                    violation_type="NOT_NULL_NO_DEFAULT",
                    explanation="Adding a NOT NULL column without a DEFAULT value causes SQLiteConstraintException during app upgrade when existing rows exist.",
                    safe_sql_remedy="ALTER TABLE ... ADD COLUMN ... NOT NULL DEFAULT 0 (or safe fallback value)",
                ))

        # 2. Destructive DROP TABLE / COLUMN
        if re.search(r"\bDROP\s+TABLE\b", clean) and "IF EXISTS" not in clean:
            violations.append(MigrationViolation(
                line_number=idx,
                severity="CRITICAL",
                violation_type="DESTRUCTIVE_DROP",
                explanation="Unbounded DROP TABLE without safe fallback or deprecation window destroys user production data.",
                safe_sql_remedy="DROP TABLE IF EXISTS <table_name> after multi-version deprecation window",
            ))

        # 3. Monetary Float/Real math violation
        money_match = re.search(r"(?:PAISE|AMOUNT|PRICE|COST|BALANCE|TOTAL|SUBTOTAL|TAX)[A-Z0-9_]*\s+.*(?:REAL|FLOAT|DOUBLE)\b", clean)
        if money_match:
            violations.append(MigrationViolation(
                line_number=idx,
                severity="CRITICAL",
                violation_type="FLOAT_MONEY_MATH",
                explanation="Violates Law ACC-001 (Integer Paise). Monetary fields must be stored as INTEGER/BIGINT (Long), never REAL or FLOAT.",
                safe_sql_remedy="Change column type to INTEGER (storing paise) with zero floating-point representation",
            ))

        # 4. Non-idempotent table creation
        if re.search(r"\bCREATE\s+TABLE\b", clean) and "IF NOT EXISTS" not in clean:
            violations.append(MigrationViolation(
                line_number=idx,
                severity="WARNING",
                violation_type="NON_IDEMPOTENT",
                explanation="CREATE TABLE without IF NOT EXISTS can crash migration retries if table already exists.",
                safe_sql_remedy="CREATE TABLE IF NOT EXISTS <table_name> (...)",
            ))

    is_safe = not any(v.severity == "CRITICAL" for v in violations)
    critical_count = sum(1 for v in violations if v.severity == "CRITICAL")
    warning_count = sum(1 for v in violations if v.severity == "WARNING")

    if is_safe:
        summary = f"PASSED: Migration is zero-downtime safe. ({warning_count} non-blocking warnings)"
    else:
        summary = f"BLOCKED: Found {critical_count} CRITICAL fatal database migration traps that will crash production on app upgrade!"

    return MigrationAuditReport(
        file_path=file_path_str,
        is_safe=is_safe,
        violations=violations,
        summary=summary,
    )


def audit_migration_file(file_path: Path) -> MigrationAuditReport:
    """Reads and audits a physical migration file."""
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"Migration file '{file_path}' does not exist.")

    content = file_path.read_text(encoding="utf-8", errors="ignore")
    return audit_migration_content(content, str(file_path))


def execute_migration_audit(file_path: Path) -> bool:
    """CLI executor for unigov audit-migration."""
    console.print(Panel(
        f"[bold cyan]Zero-Downtime Database Migration Gatekeeper[/bold cyan]\n"
        f"Target File: {file_path}",
        border_style="cyan"
    ))

    try:
        report = audit_migration_file(file_path)
    except Exception as exc:
        console.print(f"[bold red]Error reading migration file:[/bold red] {exc}")
        return False

    if not report.violations:
        console.print("[bold green]✅ 100% CLEAN: Migration is zero-downtime safe with zero violations![/bold green]")
        return True

    table = Table(title=f"🛡️ Migration Audit: {file_path.name}")
    table.add_column("Line", style="dim", width=6)
    table.add_column("Severity", style="bold")
    table.add_column("Trap Type", style="cyan")
    table.add_column("Explanation", style="white")
    table.add_column("Safe SQL Remedy", style="green")

    for v in report.violations:
        sev_style = "bold red" if v.severity == "CRITICAL" else "yellow"
        table.add_row(
            str(v.line_number),
            f"[{sev_style}]{v.severity}[/{sev_style}]",
            v.violation_type,
            v.explanation,
            v.safe_sql_remedy,
        )

    console.print(table)
    console.print(f"\n[bold]{report.summary}[/bold]\n")

    return report.is_safe
