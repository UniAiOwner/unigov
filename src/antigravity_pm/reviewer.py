import re
from pathlib import Path
from dataclasses import dataclass
from typing import List
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .models import AgentExecutionPlan

console = Console()

SUPPRESSION_SIGNALS = [
    re.compile(r"@Suppress\b"),
    re.compile(r"//\s*@ts-ignore\b"),
    re.compile(r"//\s*@ts-nocheck\b"),
    re.compile(r"//\s*eslint-disable\b"),
    re.compile(r"#\s*noqa\b"),
    re.compile(r"#\s*pylint:\s*disable\b"),
    re.compile(r"#\s*type:\s*ignore\b"),
]

SECRET_SIGNATURES = [
    "AIzaSy",
    "BEGIN PRIVATE KEY",
    "BEGIN RSA PRIVATE KEY",
    "sk-proj-",
    "ghp_",
    r"AKIA[0-9A-Z]{16}",
]

FINANCIAL_PATH_KEYWORDS = {
    "pos", "retail", "invoice", "billing", "cart",
    "payment", "ledger", "accounting", "money", "paise", "price", "tax"
}


@dataclass
class QualityGateResult:
    files_touched: int
    insertions: int
    deletions: int
    suppression_violations: List[str]
    secret_violations: List[str]
    financial_violations: List[str]
    risk_level: str

    @property
    def passed(self) -> bool:
        return len(self.suppression_violations) == 0 and len(self.secret_violations) == 0


def review_execution_plan(plan: AgentExecutionPlan) -> QualityGateResult:
    """Pre-apply automated code review checking:
    1. Constitutional Law-000: Zero @Suppress / ignore / noqa shortcuts.
    2. Zero Secret Leaks.
    3. Law ACC-001: Integer paise financial invariants.
    4. Blast-radius and insertion/deletion accounting.
    """
    files_touched = len(plan.patches)
    insertions = 0
    deletions = 0
    suppression_violations: List[str] = []
    secret_violations: List[str] = []
    financial_violations: List[str] = []

    for patch in plan.patches:
        file_path_lower = patch.file_path.lower()
        is_financial = any(k in file_path_lower for k in FINANCIAL_PATH_KEYWORDS)

        all_added_text = []
        if patch.is_new_file and patch.new_file_content:
            all_added_text.append(patch.new_file_content)
            insertions += len(patch.new_file_content.splitlines())
        else:
            for edit in patch.edits:
                deletions += len(edit.search.splitlines())
                insertions += len(edit.replace.splitlines())
                all_added_text.append(edit.replace)

        content_to_check = "\n".join(all_added_text)

        # 1. Check for suppressions & shortcuts (Constitutional Law-000)
        for pat in SUPPRESSION_SIGNALS:
            for match in pat.finditer(content_to_check):
                suppression_violations.append(f"{patch.file_path}: Found shortcut '{match.group(0)}'")

        # 2. Check for secret signatures
        for sig in SECRET_SIGNATURES:
            if sig.startswith("AKIA"):
                if re.search(sig, content_to_check):
                    secret_violations.append(f"{patch.file_path}: Potential AWS Access Key")
            elif sig in content_to_check:
                secret_violations.append(f"{patch.file_path}: Potential secret signature '{sig}'")

        # 3. Check for floating-point math in financial files (Law ACC-001)
        if is_financial:
            float_mult = re.findall(r"[\w.]+\s*\*\s*0\.\d+", content_to_check)
            if float_mult:
                financial_violations.append(
                    f"{patch.file_path}: Law ACC-001 Warning - Floating point multiplication detected ({', '.join(float_mult)}). Use integer paise math."
                )

    # Determine blast radius risk level
    if suppression_violations or secret_violations:
        risk_level = "HIGH"
    elif files_touched > 3 or insertions > 150:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    return QualityGateResult(
        files_touched=files_touched,
        insertions=insertions,
        deletions=deletions,
        suppression_violations=suppression_violations,
        secret_violations=secret_violations,
        financial_violations=financial_violations,
        risk_level=risk_level,
    )


def print_quality_gate_table(res: QualityGateResult) -> None:
    table = Table(title="Pre-Apply Quality Gate & Blast Radius", border_style="cyan")
    table.add_column("Metric / Check", style="bold")
    table.add_column("Status / Measurement", style="white")

    risk_style = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "bold red"}.get(res.risk_level, "white")
    table.add_row("Blast Radius Risk", f"[{risk_style}]{res.risk_level}[/{risk_style}]")
    table.add_row("Files Touched", str(res.files_touched))
    table.add_row("Code Delta", f"[green]+{res.insertions}[/green] / [red]-{res.deletions}[/red]")

    # Suppressions
    if res.suppression_violations:
        table.add_row("Law-000 Zero-Shortcut", f"[bold red]FAILED ({len(res.suppression_violations)} shortcuts found)[/bold red]")
    else:
        table.add_row("Law-000 Zero-Shortcut", "[green]PASSED (Zero shortcuts)[/green]")

    # Secrets
    if res.secret_violations:
        table.add_row("Secret Signature Scan", f"[bold red]FAILED ({len(res.secret_violations)} signatures found)[/bold red]")
    else:
        table.add_row("Secret Signature Scan", "[green]PASSED (Zero secrets)[/green]")

    # Financial Invariants
    if res.financial_violations:
        table.add_row("Law ACC-001 (Integer Paise)", f"[yellow]WARNING ({len(res.financial_violations)} float operations)[/yellow]")
    else:
        table.add_row("Law ACC-001 (Integer Paise)", "[green]PASSED[/green]")

    console.print(table)

    if res.suppression_violations:
        console.print(Panel("\n".join(f"• {v}" for v in res.suppression_violations), title="[bold red]Shortcut Violations Blocked[/bold red]", border_style="red"))
    if res.secret_violations:
        console.print(Panel("\n".join(f"• {v}" for v in res.secret_violations), title="[bold red]Secret Signatures Blocked[/bold red]", border_style="red"))
    if res.financial_violations:
        console.print(Panel("\n".join(f"• {v}" for v in res.financial_violations), title="[yellow]Financial Float Warnings[/yellow]", border_style="yellow"))
