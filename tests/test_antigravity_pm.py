import json
import subprocess
import pytest
import typer

from antigravity_pm import db, executor, drift, ecosystem, llm
from antigravity_pm.models import FilePatch, SearchReplaceBlock


@pytest.fixture
def isolated_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db, "AG_DIR", tmp_path / ".antigravity")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / ".antigravity" / "state.db")
    monkeypatch.setattr(ecosystem, "GLOBAL_AG_DIR", tmp_path / ".global_ag")
    monkeypatch.setattr(ecosystem, "ECOSYSTEM_DB_PATH", tmp_path / ".global_ag" / "ecosystem.db")

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@unicore.local"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "UniCore Test"], cwd=tmp_path, check=True)

    conn = db.get_db(require_init=False)
    db.init_schema(conn)
    with conn:
        conn.execute(
            "INSERT INTO project_vision (id, project_name, core_objective, hard_constraints_json) VALUES (1, ?, ?, ?)",
            ("UniRetail", "Offline ERP", json.dumps(["Offline-first", "Atomic SQLite transactions"])),
        )
    return tmp_path, conn


def test_surgical_patch_atomic_validation(isolated_workspace):
    ws, _ = isolated_workspace
    target = ws / "src" / "ledger.py"
    target.parent.mkdir(parents=True)
    target.write_text("def calc_tax(amount):\n    return amount * 0.18\n", encoding="utf-8")

    valid_patch = FilePatch(
        file_path="src/ledger.py",
        is_new_file=False,
        edits=[SearchReplaceBlock(search="return amount * 0.18", replace="return round(amount * 0.18, 2)")],
        explanation="Round GST output",
    )
    executor._apply_surgical_patches([valid_patch])
    assert "round(amount * 0.18, 2)" in target.read_text(encoding="utf-8")

    # Test whitespace-tolerant fallback
    whitespace_patch = FilePatch(
        file_path="src/ledger.py",
        is_new_file=False,
        edits=[SearchReplaceBlock(search="  return   round(amount * 0.18, 2)  ", replace="    return int(amount * 0.18 * 100)")],
        explanation="Convert to paise integer with loose whitespace",
    )
    executor._apply_surgical_patches([whitespace_patch])
    assert "int(amount * 0.18 * 100)" in target.read_text(encoding="utf-8")

    bad_patch = FilePatch(
        file_path="src/ledger.py",
        is_new_file=False,
        edits=[SearchReplaceBlock(search="non_existent_line()", replace="hack()")],
        explanation="Invalid snippet",
    )
    with pytest.raises(ValueError, match="not found"):
        executor._apply_surgical_patches([bad_patch])


def test_dag_cascade_unblocking(isolated_workspace):
    ws, conn = isolated_workspace
    (ws / "schema.sql").write_text("CREATE TABLE items(id INT);", encoding="utf-8")
    (ws / "dao.py").write_text("# DAO code", encoding="utf-8")

    with conn:
        conn.execute(
            "INSERT INTO tasks (task_id, level, title, description, target_files_json, status) VALUES ('T1', 'TASK', 'Schema', 'DB', ?, 'READY')",
            (json.dumps(["schema.sql"]),),
        )
        conn.execute(
            "INSERT INTO tasks (task_id, level, title, description, target_files_json, status) VALUES ('T2', 'TASK', 'DAO', 'Queries', ?, 'PENDING')",
            (json.dumps(["dao.py"]),),
        )
        conn.execute("INSERT INTO task_dependencies (task_id, depends_on_task_id) VALUES ('T2', 'T1')")

    executor.verify_and_unlock("T1")
    assert conn.execute("SELECT status FROM tasks WHERE task_id = 'T1'").fetchone()["status"] == "COMPLETED"
    assert conn.execute("SELECT status FROM tasks WHERE task_id = 'T2'").fetchone()["status"] == "READY"


def test_secret_leak_blocks_staged_diff(isolated_workspace):
    ws, _ = isolated_workspace
    leaked_file = ws / "config.py"
    fake_secret = "AIza" + "SyDummyLeakedSecretKey12345"
    leaked_file.write_text(f'API_KEY = "{fake_secret}"\n', encoding="utf-8")
    subprocess.run(["git", "add", "config.py"], cwd=ws, check=True)

    with pytest.raises(typer.Exit) as exc_info:
        drift.run_drift_check(staged=True, skip_llm=True)
    assert exc_info.value.exit_code == 1


def test_cross_project_contract_lifecycle(isolated_workspace, monkeypatch):
    ws, _ = isolated_workspace
    contract_file = ws / "stock_contract.json"
    contract_file.write_text('{"version": 1, "fields": ["imei", "model"]}', encoding="utf-8")

    ecosystem.publish_contract("UniParts", "uniparts.stock.v1", contract_file, "1.0.0")
    ecosystem.subscribe_contract("UniRetail", "uniparts.stock.v1")
    assert ecosystem.check_ecosystem_sync("UniRetail") == []

    contract_file.write_text('{"version": 2, "fields": ["imei", "model", "gst_hsn"]}', encoding="utf-8")
    ecosystem.publish_contract("UniParts", "uniparts.stock.v1", contract_file, "2.0.0", notes="Added gst_hsn")
    assert len(ecosystem.check_ecosystem_sync("UniRetail")) == 1

    monkeypatch.setattr(typer, "confirm", lambda msg: True)
    ecosystem.acknowledge_contract("UniRetail", "uniparts.stock.v1")
    assert ecosystem.check_ecosystem_sync("UniRetail") == []


def test_clean_json_str_with_fences():
    fenced_1 = "```json\n{\"key\": \"val\"}\n```"
    assert llm._clean_json_str(fenced_1) == '{"key": "val"}'

    fenced_2 = "```\n{\"key\": \"val\"}\n```"
    assert llm._clean_json_str(fenced_2) == '{"key": "val"}'

    unfenced = '{"key": "val"}'
    assert llm._clean_json_str(unfenced) == '{"key": "val"}'


def test_extract_actionable_error_log():
    # Long log with error buried in the middle and generic summary at tail
    simulated_log = (
        "Starting Gradle Build...\n"
        + "Running task :app:compileDebugKotlin\n"
        + "app/src/main/kotlin/com/uniai/pos/Cart.kt:42:15: error: unresolved reference: calculatePaiseInteger\n"
        + "    val total = calculatePaiseInteger(cartItems)\n"
        + "                ^\n"
        + "Finished compilation in 1.4s\n"
        + "\n".join(f"Info line {i}: scanning module dependencies" for i in range(100))
        + "\nBUILD FAILED in 3s\n"
        + "2 actionable tasks: 1 executed, 1 failed\n"
    )

    extracted = executor.extract_actionable_error_log(simulated_log, max_chars=1000)
    assert "app/src/main/kotlin/com/uniai/pos/Cart.kt:42:15: error:" in extracted
    assert "unresolved reference: calculatePaiseInteger" in extracted


def test_dag_cycle_detection():
    from antigravity_pm.ingest import detect_dag_cycles
    from antigravity_pm.models import ExtractedTask

    # 1. Clean Acyclic Graph: T1 -> T2 -> T3
    clean_tasks = [
        ExtractedTask(task_id="T1", level="TASK", title="Task 1", description="", target_files=[], depends_on=[]),
        ExtractedTask(task_id="T2", level="TASK", title="Task 2", description="", target_files=[], depends_on=["T1"]),
        ExtractedTask(task_id="T3", level="TASK", title="Task 3", description="", target_files=[], depends_on=["T2"]),
    ]
    assert detect_dag_cycles(clean_tasks) == []

    # 2. Circular Graph: T1 -> T2 -> T1
    cyclic_tasks_2 = [
        ExtractedTask(task_id="T1", level="TASK", title="Task 1", description="", target_files=[], depends_on=["T2"]),
        ExtractedTask(task_id="T2", level="TASK", title="Task 2", description="", target_files=[], depends_on=["T1"]),
    ]
    cycles_2 = detect_dag_cycles(cyclic_tasks_2)
    assert len(cycles_2) >= 1
    assert "T1" in cycles_2[0] and "T2" in cycles_2[0]

    # 3. 3-Node Cycle: T1 -> T2 -> T3 -> T1
    cyclic_tasks_3 = [
        ExtractedTask(task_id="T1", level="TASK", title="Task 1", description="", target_files=[], depends_on=["T3"]),
        ExtractedTask(task_id="T2", level="TASK", title="Task 2", description="", target_files=[], depends_on=["T1"]),
        ExtractedTask(task_id="T3", level="TASK", title="Task 3", description="", target_files=[], depends_on=["T2"]),
    ]
    cycles_3 = detect_dag_cycles(cyclic_tasks_3)
    assert len(cycles_3) >= 1
    flat_cycle = cycles_3[0]
    assert flat_cycle[0] == flat_cycle[-1]  # Forms a closed loop


def test_validate_code_syntax():
    from pathlib import Path
    from antigravity_pm.executor import validate_code_syntax

    # 1. Valid Python
    validate_code_syntax(Path("test.py"), "def foo():\n    return 42\n")

    # 2. Invalid Python syntax raises ValueError
    with pytest.raises(ValueError, match="AST Syntax Validation Error"):
        validate_code_syntax(Path("broken.py"), "def foo(:\n    return 42\n")

    # 3. Valid JSON
    validate_code_syntax(Path("data.json"), '{"name": "UniRetail", "active": true}')

    # 4. Invalid JSON raises ValueError
    with pytest.raises(ValueError, match="JSON Syntax Validation Error"):
        validate_code_syntax(Path("bad.json"), '{"name": "UniRetail", broken}')

    # 5. Valid Kotlin / TS with nested strings and comments
    kt_code = """
    // Single line comment with unclosed {
    /* Block comment with unclosed ( */
    fun calculateTotal(items: List<Item>): Int {
        val note = "String literal with unmatched } and )"
        return items.sumOf { it.price }
    }
    """
    validate_code_syntax(Path("App.kt"), kt_code)

    # 6. Unmatched bracket in TS/Kotlin raises ValueError
    with pytest.raises(ValueError, match="Unclosed bracket|Mismatched bracket"):
        validate_code_syntax(Path("App.tsx"), "export const View = () => { return (<div>; }")


def test_dynamic_model_and_provider_routing(monkeypatch):
    captured_calls = []

    def mock_call_gemini(conn, command_name, prompt, schema, complexity, model=None):
        captured_calls.append(("gemini", model, complexity))
        return schema(
            drift_detected=False,
            violated_constraints=[],
            explanation="Clean mock",
        )

    def mock_call_ollama(prompt, schema, complexity, model=None):
        captured_calls.append(("ollama", model, complexity))
        return schema(
            drift_detected=False,
            violated_constraints=[],
            explanation="Clean mock",
        )

    monkeypatch.setattr(llm, "_call_gemini", mock_call_gemini)
    monkeypatch.setattr(llm, "_call_ollama", mock_call_ollama)

    from antigravity_pm.models import DriftReport

    # Call with Gemini default
    llm.generate_structured(None, "test", "prompt", DriftReport)
    assert captured_calls[-1] == ("gemini", None, "fast")

    # Call with Gemini explicit model
    llm.generate_structured(None, "test", "prompt", DriftReport, model="gemini-3.8-flash")
    assert captured_calls[-1] == ("gemini", "gemini-3.8-flash", "fast")

    # Call with Ollama provider & model
    llm.generate_structured(None, "test", "prompt", DriftReport, provider="ollama", model="qwen2.5-coder:32b")
    assert captured_calls[-1] == ("ollama", "qwen2.5-coder:32b", "fast")


def test_pre_apply_code_reviewer():
    from antigravity_pm.reviewer import review_execution_plan
    from antigravity_pm.models import AgentExecutionPlan, FilePatch, SearchReplaceBlock

    # 1. Clean Plan
    clean_plan = AgentExecutionPlan(
        reasoning="Clean patch",
        patches=[
            FilePatch(
                file_path="src/dao.py",
                is_new_file=False,
                edits=[SearchReplaceBlock(search="x = 1", replace="x = 2")],
                explanation="Update variable",
            )
        ],
    )
    clean_res = review_execution_plan(clean_plan)
    assert clean_res.passed is True
    assert clean_res.risk_level == "LOW"

    # 2. Plan with Constitutional Law-000 Violation (@Suppress)
    suppress_plan = AgentExecutionPlan(
        reasoning="Dirty patch with suppression",
        patches=[
            FilePatch(
                file_path="src/Cart.kt",
                is_new_file=False,
                edits=[SearchReplaceBlock(search="val x = 1", replace='@Suppress("UNCHECKED_CAST")\nval x = 1')],
                explanation="Add suppress hack",
            )
        ],
    )
    suppress_res = review_execution_plan(suppress_plan)
    assert suppress_res.passed is False
    assert len(suppress_res.suppression_violations) >= 1
    assert suppress_res.risk_level == "HIGH"

    # 3. Plan with Secret Leak
    secret_plan = AgentExecutionPlan(
        reasoning="Leaked secret",
        patches=[
            FilePatch(
                file_path="src/config.py",
                is_new_file=False,
                edits=[SearchReplaceBlock(search="# key", replace='KEY = "AIzaSyFakeSecretToken12345"')],
                explanation="Add leaked key",
            )
        ],
    )
    secret_res = review_execution_plan(secret_plan)
    assert secret_res.passed is False
    assert len(secret_res.secret_violations) >= 1
    assert secret_res.risk_level == "HIGH"

    # 4. Plan with Law ACC-001 Financial Float Warning
    float_plan = AgentExecutionPlan(
        reasoning="Float math in financial file",
        patches=[
            FilePatch(
                file_path="src/pos_cart.py",
                is_new_file=False,
                edits=[SearchReplaceBlock(search="total = 0", replace="total = amount * 0.18")],
                explanation="Calculate GST using float multiplier",
            )
        ],
    )
    float_res = review_execution_plan(float_plan)
    assert len(float_res.financial_violations) >= 1
    assert "Law ACC-001" in float_res.financial_violations[0]


@pytest.mark.anyio
async def test_dashboard_app_headless(isolated_workspace):
    from antigravity_pm.tui import AntigravityDashboardApp

    app = AntigravityDashboardApp()
    async with app.run_test() as pilot:
        assert app.is_running
        table = app.query_one("DataTable")
        assert table is not None
        await pilot.press("q")

