import json
import re
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .db import get_db, resolve_gov_dir
from .llm import generate_structured
from .constants import normalize_posix_path

console = Console()


class DomainModelSpec(BaseModel):
    model_name: str = Field(description="Name of the model class e.g. InwardBoxUnit")
    layer: str = Field(default="LAYER_1_DOMAIN", description="LAYER_1_DOMAIN, LAYER_2_DATA, or LAYER_3_SURFACES")
    target_file: str = Field(description="Target file relative path e.g. app/src/main/java/com/unicore/uniretail/domain/model/InwardBoxUnit.kt")
    fields: List[str] = Field(description="Key fields with strict integer paise (Long) and types")
    invariants: List[str] = Field(description="Machine/domain invariants e.g. Luhn algorithm validation, zero-float")


class UIStateSpec(BaseModel):
    state_name: str = Field(description="One of the 5 mandatory states: LoadingState, EmptyState, ContentState, ErrorState, OfflineState")
    visual_components: List[str] = Field(description="Composables/UI components rendered in this state")
    actionable_cta: Optional[str] = Field(None, description="Button, retry action, or interaction available")


class UserIntentSpec(BaseModel):
    intent_name: str = Field(description="User event or intent e.g. OnScanBarcode, OnSaveItem")
    parameters: List[str] = Field(description="Parameters carried by this intent")
    outcome: str = Field(description="Expected state transition or mutation")


class BlueprintSpec(BaseModel):
    feature_name: str = Field(description="Canonical feature or screen name e.g. AddStockScreen")
    description: str = Field(description="High-level architectural purpose")
    domain_models: List[DomainModelSpec] = Field(description="Domain models and business logic invariants")
    ui_states: List[UIStateSpec] = Field(description="All 5 mandatory UI states definitions")
    user_intents: List[UserIntentSpec] = Field(description="Exhaustive list of user intents / actions")
    mermaid_flowchart: str = Field(description="Concise terminal-friendly single-pipeline flowchart TD (< 50 cols width) covering happy and sad/chaos paths")


def generate_feature_blueprint(
    feature_name: str,
    project_root: Path = Path("."),
    model: Optional[str] = None,
    provider: Optional[str] = None,
    auto_approve: bool = False,
) -> Optional[BlueprintSpec]:
    """Generates an architectural Blueprint for a feature or screen following the 4-stage pipeline."""
    conn = get_db()
    vision_row = conn.execute("SELECT * FROM project_vision WHERE id = 1").fetchone()
    project_name = vision_row["project_name"] if vision_row else project_root.resolve().name
    constraints = json.loads(vision_row["hard_constraints_json"]) if vision_row else []

    console.print(Panel(
        f"[bold cyan]Feature / Screen:[/bold cyan] {feature_name}\n"
        f"[bold]Target Project:[/bold] {project_name}\n"
        f"[bold]Active Constraints:[/bold] {len(constraints)} locked",
        title="📐 UniGov Autonomous Screen & Feature Architect",
        border_style="cyan"
    ))

    prompt = f"""
    You are the Principal Systems & Mobile UI/UX Architect designing a production-grade feature blueprint.

    TARGET FEATURE: {feature_name}
    PROJECT: {project_name}
    LOCKED CONSTRAINTS:
    {json.dumps(constraints, indent=2)}

    INSTRUCTIONS:
    1. Define Domain Models & Invariants:
       - Follow Law ACC-001 (Integer Paise / Long representation for all monetary fields, zero float).
       - Enforce domain invariant validations (e.g. Luhn algorithm for IMEI, idempotency, immutability).
    2. Define ALL 5 Mandatory UI States:
       - LoadingState (tactile shimmer/skeleton loader)
       - EmptyState (helpful illustration + actionable primary CTA)
       - ContentState (active list, items, summaries)
       - ErrorState (non-destructive error message + retry action)
       - OfflineState (persistent banner + cached local data)
    3. Define User Intents / Events exhaustively.
    4. Generate a concise single vertical pipeline Mermaid flowchart TD (< 50 cols width):
       - Connect nodes directly (A --> B --> C) without subgraphs.
       - Include Happy Path and Chaos/Sad Paths (e.g., duplicate barcode scan, process death, network drop).
    """

    spec: BlueprintSpec = generate_structured(
        conn=conn,
        command_name="blueprint",
        prompt=prompt,
        schema=BlueprintSpec,
        complexity="pro",
        model=model,
        provider=provider,
    )

    # Stage 3: Render and Pause for Human Verification Gate
    _render_blueprint(spec)

    if not auto_approve:
        confirmed = typer.confirm(
            f"\nShoeb Bhai, kya aap is '{feature_name}' ke 5-state structure aur flow ko approve karte hain?",
            default=True
        )
        if not confirmed:
            console.print("[bold yellow]Blueprint aborted by operator. Zero modifications applied.[/bold yellow]")
            return None

    # Stage 4: Persist Artifact and Inject Topological DAG Tasks
    persist_blueprint_and_inject_dag(spec, project_root=project_root)
    return spec


def _render_blueprint(spec: BlueprintSpec) -> None:
    """Renders the blueprint in rich console tables and panels."""
    t_models = Table(title="🏛️ 1. Domain Models & Mathematical Invariants", border_style="cyan")
    t_models.add_column("Model Name", style="bold cyan")
    t_models.add_column("Layer", style="magenta")
    t_models.add_column("Target File", style="dim")
    t_models.add_column("Key Fields & Invariants", style="green")

    for m in spec.domain_models:
        details = ", ".join(m.fields[:3])
        if m.invariants:
            details += f"\n[yellow]Invariants: {'; '.join(m.invariants)}[/yellow]"
        t_models.add_row(m.model_name, m.layer, Path(m.target_file).name, details)
    console.print(t_models)

    t_states = Table(title="📱 2. All 5 Mandatory UI States", border_style="green")
    t_states.add_column("State Name", style="bold yellow")
    t_states.add_column("Components Rendered", style="white")
    t_states.add_column("Actionable CTA", style="cyan")

    for s in spec.ui_states:
        t_states.add_row(s.state_name, ", ".join(s.visual_components), s.actionable_cta or "—")
    console.print(t_states)

    t_intents = Table(title="⚡ 3. User Intents & Event Handlers", border_style="magenta")
    t_intents.add_column("Intent", style="bold magenta")
    t_intents.add_column("Parameters", style="dim")
    t_intents.add_column("Expected Outcome", style="white")

    for i in spec.user_intents:
        t_intents.add_row(i.intent_name, ", ".join(i.parameters) or "None", i.outcome)
    console.print(t_intents)

    console.print(Panel(
        f"[dim]{spec.mermaid_flowchart}[/dim]",
        title="🔀 4. Navigational & Chaos Flow (Mermaid)",
        border_style="blue"
    ))


def persist_blueprint_and_inject_dag(spec: BlueprintSpec, project_root: Path = Path(".")) -> Path:
    """Saves the approved blueprint markdown to .unigov/docs/ and injects topological DAG tasks."""
    conn = get_db()
    gov_dir = resolve_gov_dir(project_root)
    docs_dir = gov_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    slug = re.sub(r"[^A-Za-z0-9]+", "_", spec.feature_name).strip("_")
    md_file = docs_dir / f"blueprint_{slug}.md"

    # 1. Format Markdown Spec
    content = f"""# 📐 Architectural Blueprint: {spec.feature_name}
_{spec.description}_

---

## 1. Domain Models & Invariants
"""
    for m in spec.domain_models:
        content += f"\n### `{m.model_name}`\n"
        content += f"- **Layer:** `{m.layer}`\n"
        content += f"- **Target File:** `{m.target_file}`\n"
        content += "- **Fields:**\n" + "\n".join(f"  * `{f}`" for f in m.fields) + "\n"
        content += "- **Invariants:**\n" + "\n".join(f"  * {inv}" for inv in m.invariants) + "\n"

    content += "\n## 2. All 5 Mandatory UI States\n"
    for s in spec.ui_states:
        content += f"\n### `{s.state_name}`\n"
        content += f"- **Components:** {', '.join(s.visual_components)}\n"
        if s.actionable_cta:
            content += f"- **Actionable CTA:** {s.actionable_cta}\n"

    content += "\n## 3. User Intents & State Transitions\n"
    for i in spec.user_intents:
        content += f"- **`{i.intent_name}`** (`{', '.join(i.parameters)}`): {i.outcome}\n"

    content += f"""
## 4. Navigational & Chaos Flow
```mermaid
{spec.mermaid_flowchart}
```
"""

    md_file.write_text(content, encoding="utf-8")
    console.print(f"[bold green]Saved blueprint artifact:[/bold green] {md_file.as_posix()}")

    # 2. Inject Topological DAG Tasks into state.db
    m_id = f"M-FEAT-{slug.upper()}"
    t_dom = f"{m_id}-01-DOM"
    t_state = f"{m_id}-02-STATE"
    t_ui = f"{m_id}-03-UI"
    t_test = f"{m_id}-04-TEST"

    dom_files = [normalize_posix_path(m.target_file) for m in spec.domain_models]
    state_file = f"app/src/main/java/com/unicore/uniretail/ui/{slug.lower()}/{spec.feature_name}ViewModel.kt"
    ui_file = f"app/src/main/java/com/unicore/uniretail/ui/{slug.lower()}/{spec.feature_name}.kt"
    test_file = f"app/src/test/java/com/unicore/uniretail/{spec.feature_name}Test.kt"

    with conn:
        # Milestone
        conn.execute("""
            INSERT OR REPLACE INTO tasks (task_id, parent_id, level, layer, title, description, target_files_json, verify_cmd, status)
            VALUES (?, NULL, 'MILESTONE', 'LAYER_1_DOMAIN', ?, ?, ?, 'echo "Feature Milestone Verified"', 'PENDING')
        """, (m_id, f"Feature: {spec.feature_name}", spec.description, json.dumps([])))

        # L1: Domain Models (READY immediately)
        conn.execute("""
            INSERT OR REPLACE INTO tasks (task_id, parent_id, level, layer, title, description, target_files_json, verify_cmd, status)
            VALUES (?, ?, 'TASK', 'LAYER_1_DOMAIN', ?, ?, ?, 'echo "Domain Models Verified"', 'READY')
        """, (t_dom, m_id, f"Implement {spec.feature_name} Domain Models & Invariants", "Pure Kotlin domain models with integer paise math", json.dumps(dom_files)))

        # L2: ViewModel & State Machine (PENDING, depends on L1)
        conn.execute("""
            INSERT OR REPLACE INTO tasks (task_id, parent_id, level, layer, title, description, target_files_json, verify_cmd, status)
            VALUES (?, ?, 'TASK', 'LAYER_2_DATA', ?, ?, ?, 'echo "ViewModel Verified"', 'PENDING')
        """, (t_state, m_id, f"Build {spec.feature_name} ViewModel & FSM", "State machine with 5 UI states and intent reducers", json.dumps([normalize_posix_path(state_file)])))

        # L3: UI Components (PENDING, depends on L2)
        conn.execute("""
            INSERT OR REPLACE INTO tasks (task_id, parent_id, level, layer, title, description, target_files_json, verify_cmd, status)
            VALUES (?, ?, 'TASK', 'LAYER_3_SURFACES', ?, ?, ?, 'echo "UI Verified"', 'PENDING')
        """, (t_ui, m_id, f"Assemble {spec.feature_name} Compose Surfaces", "Jetpack Compose surfaces rendering all 5 mandatory states", json.dumps([normalize_posix_path(ui_file)])))

        # L4: Test Suites (PENDING, depends on L3)
        conn.execute("""
            INSERT OR REPLACE INTO tasks (task_id, parent_id, level, layer, title, description, target_files_json, verify_cmd, status)
            VALUES (?, ?, 'TASK', 'LAYER_4_SECURITY', ?, ?, ?, 'echo "Tests Verified"', 'PENDING')
        """, (t_test, m_id, f"Verify {spec.feature_name} Regression Tests", "Unit and Robolectric tests asserting all invariants and states", json.dumps([normalize_posix_path(test_file)])))

        # Wire strict topological dependency chain: L1 -> L2 -> L3 -> L4
        conn.execute("INSERT OR IGNORE INTO task_dependencies (task_id, depends_on_task_id) VALUES (?, ?)", (t_state, t_dom))
        conn.execute("INSERT OR IGNORE INTO task_dependencies (task_id, depends_on_task_id) VALUES (?, ?)", (t_ui, t_state))
        conn.execute("INSERT OR IGNORE INTO task_dependencies (task_id, depends_on_task_id) VALUES (?, ?)", (t_test, t_ui))

    from .invariants import apply_topological_phase_locks
    apply_topological_phase_locks(conn)

    console.print(Panel(
        f"• Task 1 [READY]: [bold cyan]{t_dom}[/bold cyan] (L1 Domain Models)\n"
        f"• Task 2 [BLOCKED]: [bold yellow]{t_state}[/bold yellow] (L2 ViewModel & FSM)\n"
        f"• Task 3 [BLOCKED]: [bold yellow]{t_ui}[/bold yellow] (L3 Compose UI Surfaces)\n"
        f"• Task 4 [BLOCKED]: [bold yellow]{t_test}[/bold yellow] (L4 Verification Tests)",
        title="Topological DAG Tasks Injected",
        border_style="green"
    ))
    return md_file
