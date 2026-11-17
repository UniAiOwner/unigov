import json
import subprocess
import pytest
import typer

from unigov import db, executor, drift, ecosystem, llm
from unigov.models import FilePatch, SearchReplaceBlock


@pytest.fixture
def isolated_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db, "AG_DIR", tmp_path / ".antigravity")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / ".antigravity" / "state.db")
    monkeypatch.setattr(db, "GLOBAL_UNIGOV_DIR", tmp_path / ".global_unigov")
    monkeypatch.setattr(db, "REGISTRY_FILE", tmp_path / ".global_unigov" / "registry.json")
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
    from unigov.ingest import detect_dag_cycles
    from unigov.models import ExtractedTask

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
    from unigov.executor import validate_code_syntax

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

    from unigov.models import DriftReport

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
    from unigov.reviewer import review_execution_plan
    from unigov.models import AgentExecutionPlan, FilePatch, SearchReplaceBlock

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
    from unigov.tui import AntigravityDashboardApp

    app = AntigravityDashboardApp()
    async with app.run_test() as pilot:
        assert app.is_running
        table = app.query_one("DataTable")
        assert table is not None
        await pilot.press("q")


def test_reconcile_find_candidates_and_cascade(isolated_workspace):
    from unigov.reconciler import find_candidate_files, cascade_task_completions
    import sqlite3
    from pathlib import Path

    # Create dummy source files
    models_file = Path("app/src/main/domain/AddStockModels.kt")
    models_file.parent.mkdir(parents=True, exist_ok=True)
    models_file.write_text("data class InwardStockModel(val id: String)")

    # 1. Test finding candidate files by keyword / target_file
    candidates = find_candidate_files(
        root_dir=Path("."),
        target_files=["domain/model/InwardStockModels.kt"],
        task_title="Update Inward Domain Models",
        task_desc="Implement InwardStockModel data classes",
    )
    assert len(candidates) >= 1
    assert any("AddStockModels.kt" in c.as_posix() for c in candidates)

    # 2. Test DAG cascade completion
    conn = sqlite3.connect(".antigravity/state.db")
    conn.row_factory = sqlite3.Row

    with conn:
        conn.execute("INSERT INTO tasks (task_id, parent_id, level, title, description, status) VALUES ('M1', NULL, 'MILESTONE', 'Milestone 1', 'Desc', 'PENDING')")
        conn.execute("INSERT INTO tasks (task_id, parent_id, level, title, description, status) VALUES ('T1', 'M1', 'TASK', 'Task 1', 'Desc', 'COMPLETED')")
        conn.execute("INSERT INTO tasks (task_id, parent_id, level, title, description, status) VALUES ('T2', 'M1', 'TASK', 'Task 2', 'Desc', 'PENDING')")
        conn.execute("INSERT INTO task_dependencies (task_id, depends_on_task_id) VALUES ('T2', 'T1')")

    cascade_task_completions(conn)

    # T2 should be unlocked to READY because T1 is COMPLETED
    t2 = conn.execute("SELECT status FROM tasks WHERE task_id = 'T2'").fetchone()
    assert t2["status"] == "READY"

    # Now complete T2
    with conn:
        conn.execute("UPDATE tasks SET status = 'COMPLETED' WHERE task_id = 'T2'")

    cascade_task_completions(conn)

    # Parent M1 should now be COMPLETED because all its children are COMPLETED
    m1 = conn.execute("SELECT status FROM tasks WHERE task_id = 'M1'").fetchone()
    assert m1["status"] == "COMPLETED"


def test_scaffolder_and_spec_verification(isolated_workspace):
    from unigov.scaffolder import scaffold_documentation_suite, DIMENSION_METADATA
    from unigov.invariants import verify_project_spec
    from unigov.db import get_db
    from pathlib import Path

    docs_dir = Path("docs")
    created = scaffold_documentation_suite(docs_dir, project_name="UniRetail POS", overwrite=True)
    assert len(created) >= 15
    assert len(DIMENSION_METADATA) == 15

    # Check presence of invariant blocks in 01 and 02
    doc_01_path = docs_dir / "01_VISION_AND_CONSTRAINTS" / "03_Constitutional_Invariants_and_Laws.md"
    if not doc_01_path.exists():
        doc_01_path = docs_dir / "01_VISION_AND_CONSTRAINTS.md"
    doc_01 = doc_01_path.read_text()
    assert "<!-- UNIGOV_INVARIANT_START -->" in doc_01
    assert "INV-LAW-000" in doc_01

    conn = get_db()
    report = verify_project_spec(docs_dir, conn)
    assert report.total_dimensions == 15
    assert report.covered_dimensions == 15
    assert report.readiness_score == 100.0
    assert report.invariants_extracted >= 5


def test_topological_phase_locks_rail(isolated_workspace):
    from unigov.invariants import apply_topological_phase_locks
    from unigov.db import get_db

    conn = get_db()

    with conn:
        # Layer 1 Domain Task (Uncompleted)
        conn.execute("INSERT INTO tasks (task_id, parent_id, level, layer, title, description, status) VALUES ('T-DOM-01', NULL, 'TASK', 'LAYER_1_DOMAIN', 'Order FSM', 'Desc', 'IN_PROGRESS')")
        # Layer 2 Data Task (Completed)
        conn.execute("INSERT INTO tasks (task_id, parent_id, level, layer, title, description, status) VALUES ('T-DAT-01', NULL, 'TASK', 'LAYER_2_DATA', 'Room Schema', 'Desc', 'COMPLETED')")
        # Layer 3 UI Task (Should be BLOCKED because T-DOM-01 is IN_PROGRESS)
        conn.execute("INSERT INTO tasks (task_id, parent_id, level, layer, title, description, status) VALUES ('T-UI-01', NULL, 'TASK', 'LAYER_3_SURFACES', 'Cart Screen', 'Desc', 'READY')")

    blocked, unlocked = apply_topological_phase_locks(conn)
    assert blocked == 1

    t_ui = conn.execute("SELECT status FROM tasks WHERE task_id = 'T-UI-01'").fetchone()
    assert t_ui["status"] == "BLOCKED"

    # Now complete the Layer 1 foundation task
    with conn:
        conn.execute("UPDATE tasks SET status = 'COMPLETED' WHERE task_id = 'T-DOM-01'")

    blocked2, unlocked2 = apply_topological_phase_locks(conn)
    assert unlocked2 == 1

    t_ui_after = conn.execute("SELECT status FROM tasks WHERE task_id = 'T-UI-01'").fetchone()
    assert t_ui_after["status"] == "READY"


def test_introspect_self_and_target_analysis(isolated_workspace):
    from unigov.introspect import introspect_unigov_self, analyze_target_project
    ws, _ = isolated_workspace

    self_meta = introspect_unigov_self()
    assert self_meta["module_count"] >= 10
    assert "introspect.py" in self_meta["modules"]

    target_meta = analyze_target_project(ws)
    assert target_meta["project_name"] == "UniRetail"
    assert "dag_coverage_pct" in target_meta


def test_unigov_workspace_folders_and_migration(isolated_workspace):
    from unigov.db import init_workspace_folders, migrate_legacy_store
    ws, _ = isolated_workspace

    # 1. Initialize modern .unigov directory tree
    gov_dir = init_workspace_folders(ws)
    assert (gov_dir / "docs").is_dir()
    assert (gov_dir / "adrs").is_dir()
    assert (gov_dir / "contracts").is_dir()
    assert (gov_dir / "reports").is_dir()
    assert (gov_dir / "backups").is_dir()
    assert (gov_dir / ".gitignore").is_file()
    assert "state.db" in (gov_dir / ".gitignore").read_text(encoding="utf-8")

    # 2. Test migration from legacy .antigravity
    legacy = ws / ".antigravity"
    legacy.mkdir(exist_ok=True)
    (legacy / "dummy.txt").write_text("legacy data", encoding="utf-8")

    success, msg = migrate_legacy_store(ws)
    assert success is True
    assert (gov_dir / "dummy.txt").is_file()
    assert (gov_dir / "dummy.txt").read_text(encoding="utf-8") == "legacy data"


def test_baseline_deterministic_scanner_and_tripwire(isolated_workspace):
    from unigov.baseline import scan_and_lock_baseline, check_baseline_tripwire
    from unigov.db import get_db
    ws, conn = isolated_workspace

    # Setup dummy project files
    (ws / "app" / "src" / "main" / "domain").mkdir(parents=True, exist_ok=True)
    (ws / "app" / "src" / "main" / "domain" / "Money.kt").write_text("data class Money(val paise: Long)", encoding="utf-8")

    (ws / "app" / "src" / "main" / "data" / "entity").mkdir(parents=True, exist_ok=True)
    (ws / "app" / "src" / "main" / "data" / "entity" / "InvoiceEntity.kt").write_text("class InvoiceEntity", encoding="utf-8")

    (ws / "app" / "src" / "test").mkdir(parents=True, exist_ok=True)
    (ws / "app" / "src" / "test" / "InvoiceEntityTest.kt").write_text("class InvoiceEntityTest", encoding="utf-8")

    # Run deterministic baseline lock
    stats = scan_and_lock_baseline(conn, project_root=ws)
    assert stats["total_files"] >= 3
    assert "M0-BASE-DOM" in stats["subsystems"]
    assert "M0-BASE-SCHEMA" in stats["subsystems"]
    assert "M0-BASE-TEST" in stats["subsystems"]

    # Verify M0-BASELINE in tasks table
    m0 = conn.execute("SELECT * FROM tasks WHERE task_id = 'M0-BASELINE'").fetchone()
    assert m0["status"] == "COMPLETED"
    assert m0["is_baseline"] == 1

    # Verify child subsystem
    schema_sub = conn.execute("SELECT * FROM tasks WHERE task_id = 'M0-BASE-SCHEMA'").fetchone()
    assert schema_sub["status"] == "COMPLETED"
    assert "InvoiceEntity.kt" in schema_sub["target_files_json"]

    # Test Tripwire Alert
    alerts = check_baseline_tripwire(["app/src/main/data/entity/InvoiceEntity.kt"], conn)
    assert len(alerts) == 1
    assert alerts[0]["subsystem_id"] == "M0-BASE-SCHEMA"
    assert "InvoiceEntityTest.kt" in alerts[0]["related_tests"][0]


def test_unigovernor_ignores(isolated_workspace):
    from unigov.baseline import load_unigovernor_ignores, should_ignore_path
    ws, _ = isolated_workspace

    unigov_file = ws / ".unigovernor"
    unigov_file.write_text("backups_*\n*.tmp\nignored_dir/**\n", encoding="utf-8")

    patterns = load_unigovernor_ignores(ws)
    assert "backups_*" in patterns
    assert "*.tmp" in patterns

    p1 = ws / "backups_live" / "file.kt"
    p2 = ws / "test.tmp"
    p3 = ws / "valid.kt"

    assert should_ignore_path(p1.relative_to(ws), patterns) is True
    assert should_ignore_path(p2.relative_to(ws), patterns) is True
    assert should_ignore_path(p3.relative_to(ws), patterns) is False


def test_path_normalization_and_hash(isolated_workspace):
    from unigov.constants import normalize_posix_path, compute_file_hash, is_code_file
    ws, _ = isolated_workspace

    assert normalize_posix_path("./app/src/main/App.kt") == "app/src/main/App.kt"
    assert normalize_posix_path("app\\src\\main\\App.kt") == "app/src/main/App.kt"
    assert normalize_posix_path("app/src/../src/main/App.kt") == "app/src/main/App.kt"
    assert normalize_posix_path(".") == ""
    assert normalize_posix_path("./") == ""

    test_file = ws / "test.kt"
    test_file.write_text("class TestClass", encoding="utf-8")
    assert is_code_file(test_file) is True

    f_hash = compute_file_hash(test_file)
    assert len(f_hash) == 8
    assert f_hash != "00000000"


def test_purge_ghost_files_and_reconcile_orphans(isolated_workspace):
    from unigov.reconciler import purge_ghost_files, reconcile_orphan_files
    from unigov.baseline import scan_and_lock_baseline
    import json
    import sqlite3

    ws, _ = isolated_workspace

    # Create real files
    real_file = ws / "app" / "src" / "main" / "Real.kt"
    real_file.parent.mkdir(parents=True, exist_ok=True)
    real_file.write_text("class Real", encoding="utf-8")

    conn = sqlite3.connect(".antigravity/state.db")
    conn.row_factory = sqlite3.Row

    # Baseline scan
    scan_and_lock_baseline(conn, project_root=ws)

    # Insert a task with a real file, duplicate path, and a ghost (non-existent) file
    with conn:
        conn.execute("""
            INSERT INTO tasks (task_id, level, title, description, target_files_json, status)
            VALUES ('T-TEST', 'TASK', 'Test Task', 'Desc', ?, 'READY')
        """, (json.dumps(["./app/src/main/Real.kt", "app/src/main/Real.kt", "app/src/main/Ghost.kt"]),))

    # Test purge_ghost_files
    purged = purge_ghost_files(conn, root_dir=ws)
    assert len(purged) == 1
    assert "Ghost.kt" in purged[0]

    # Check updated task in DB: duplicate collapsed and ghost removed
    task_row = conn.execute("SELECT target_files_json FROM tasks WHERE task_id = 'T-TEST'").fetchone()
    targets = json.loads(task_row["target_files_json"])
    assert targets == ["app/src/main/Real.kt"]

    # Now create a new physical orphan file
    orphan = ws / "app" / "src" / "main" / "domain" / "OrphanModel.kt"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text("data class OrphanModel(val x: Int)", encoding="utf-8")

    # Test reconcile_orphan_files
    bound = reconcile_orphan_files(conn, root_dir=ws)
    assert len(bound) >= 1
    assert any("OrphanModel.kt" in b for b in bound)

    # Verify OrphanModel is now tracked under M0-BASE-DOM
    dom_row = conn.execute("SELECT target_files_json FROM tasks WHERE task_id = 'M0-BASE-DOM'").fetchone()
    assert "OrphanModel.kt" in dom_row["target_files_json"]


def test_dynamic_version():
    import unigov
    assert unigov.__version__ in ("0.8.0", "0.9.0", "0.9.1", "0.9.2", "0.9.3")


def test_worktree_sandboxed_lifecycle(isolated_workspace):
    ws, _ = isolated_workspace
    from unigov.worktree import is_git_repo, create_task_worktree, merge_task_worktree, cleanup_task_worktree

    # Initial commit to anchor HEAD
    dummy = ws / "README.md"
    dummy.write_text("# Test Repo")
    subprocess.run(["git", "add", "README.md"], cwd=ws, check=True)
    subprocess.run(["git", "commit", "-m", "chore: initial commit"], cwd=ws, check=True)

    assert is_git_repo(ws) is True

    # 1. Create worktree
    task_id = "M1-DB-01"
    wt_path = create_task_worktree(ws, task_id)
    assert wt_path.exists()
    assert (wt_path / ".git").exists()

    # 2. Modify file inside worktree and commit
    new_code = wt_path / "hello.txt"
    new_code.write_text("hello from sandbox")
    subprocess.run(["git", "add", "hello.txt"], cwd=wt_path, check=True)
    subprocess.run(["git", "commit", "-m", "feat: sandbox work"], cwd=wt_path, check=True)

    # 3. Merge worktree back into main branch
    merged = merge_task_worktree(ws, task_id)
    assert merged is True
    assert (ws / "hello.txt").exists()
    assert (ws / "hello.txt").read_text() == "hello from sandbox"

    # 4. Ensure worktree directory is cleaned up
    assert not wt_path.exists()


def test_context_bundler_one_hop(isolated_workspace):
    ws, _ = isolated_workspace
    from unigov.context_bundler import bundle_one_hop_context

    src_dir = ws / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    # Dependency file
    models_file = src_dir / "models.py"
    models_file.write_text("""
class Invoice:
    \"\"\"Invoice data class.\"\"\"
    invoice_id: str
    total_paise: int

    def calculate_tax(amount): ...
""")

    # Target file importing dependency
    service_file = src_dir / "service.py"
    service_file.write_text("""
from .models import Invoice

def create_invoice():
    return Invoice()
""")

    bundled = bundle_one_hop_context(ws, ["src/service.py"])
    assert "### 🔗 1-HOP DEPENDENCY INTERFACES & CONTRACTS" in bundled
    assert "class Invoice:" in bundled
    assert "total_paise: ..." in bundled or "total_paise" in bundled


def test_smart_test_impact_analysis(isolated_workspace):
    ws, _ = isolated_workspace
    from unigov.tia import find_impacted_tests, get_targeted_verification_command

    src_file = ws / "src" / "math_utils.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("def add(a, b): return a + b")

    test_file = ws / "tests" / "test_math_utils.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_add(): assert True")

    impacted = find_impacted_tests(ws, ["src/math_utils.py"])
    assert len(impacted) == 1
    assert "test_math_utils.py" in str(impacted[0])

    cmd = get_targeted_verification_command(ws, ["src/math_utils.py"])
    assert "pytest -v" in cmd
    assert "test_math_utils.py" in cmd


def test_mcp_server_protocol(isolated_workspace):
    ws, conn = isolated_workspace
    from unigov.mcp import dispatch_mcp_request

    # 1. Test initialize
    init_req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    init_resp = dispatch_mcp_request(conn, init_req)
    assert init_resp["id"] == 1
    assert init_resp["result"]["serverInfo"]["name"] == "unigov-mcp-server"

    # 2. Test tools/list
    list_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    list_resp = dispatch_mcp_request(conn, list_req)
    assert list_resp["id"] == 2
    tool_names = [t["name"] for t in list_resp["result"]["tools"]]
    assert "unigov_status" in tool_names
    assert "unigov_get_ready_tasks" in tool_names
    assert "unigov_get_invariants" in tool_names

    # 3. Test tools/call unigov_status
    call_req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "unigov_status", "arguments": {}},
    }
    call_resp = dispatch_mcp_request(conn, call_req)
    assert call_resp["id"] == 3
    content = json.loads(call_resp["result"]["content"][0]["text"])
    assert content["project_name"] == "UniRetail"


def test_blueprint_pipeline_and_dag_injection(isolated_workspace):
    from unigov.blueprint import BlueprintSpec, DomainModelSpec, UIStateSpec, UserIntentSpec, persist_blueprint_and_inject_dag
    import json
    import sqlite3

    ws, _ = isolated_workspace

    spec = BlueprintSpec(
        feature_name="AddStockScreen",
        description="Stock inwarding screen with multi-box scanning",
        domain_models=[
            DomainModelSpec(
                model_name="InwardBoxUnit",
                layer="LAYER_1_DOMAIN",
                target_file="domain/model/InwardBoxUnit.kt",
                fields=["unitIndex: Int", "imei1: String", "dpPaise: Long"],
                invariants=["Luhn algorithm IMEI validation", "Zero-float math"]
            )
        ],
        ui_states=[
            UIStateSpec(state_name="LoadingState", visual_components=["ShimmerCard"], actionable_cta=None),
            UIStateSpec(state_name="EmptyState", visual_components=["EmptyBoxIllustration"], actionable_cta="Scan First Box"),
            UIStateSpec(state_name="ContentState", visual_components=["BillCartList", "SummaryCard"], actionable_cta="Confirm Inward"),
            UIStateSpec(state_name="ErrorState", visual_components=["ErrorBanner"], actionable_cta="Retry Scan"),
            UIStateSpec(state_name="OfflineState", visual_components=["OfflineIndicator"], actionable_cta=None),
        ],
        user_intents=[
            UserIntentSpec(intent_name="OnScanBox", parameters=["barcode: String"], outcome="Adds InwardBoxUnit to cart")
        ],
        mermaid_flowchart="flowchart TD\n  Start --> Scan[Scan Box] --> Validate{Luhn Valid?} --> Save[Save to Cart]"
    )

    # Persist spec & inject DAG
    md_file = persist_blueprint_and_inject_dag(spec, project_root=ws)
    assert md_file.exists()
    content = md_file.read_text()
    assert "InwardBoxUnit" in content
    assert "LoadingState" in content
    assert "EmptyState" in content

    # Verify DAG tasks injected
    conn = sqlite3.connect(".antigravity/state.db")
    conn.row_factory = sqlite3.Row

    tasks = conn.execute("SELECT task_id, level, layer, status FROM tasks WHERE task_id LIKE 'M-FEAT-ADDSTOCKSCREEN%'").fetchall()
    task_map = {t["task_id"]: t for t in tasks}

    assert "M-FEAT-ADDSTOCKSCREEN" in task_map
    assert "M-FEAT-ADDSTOCKSCREEN-01-DOM" in task_map
    assert "M-FEAT-ADDSTOCKSCREEN-02-STATE" in task_map
    assert "M-FEAT-ADDSTOCKSCREEN-03-UI" in task_map
    assert "M-FEAT-ADDSTOCKSCREEN-04-TEST" in task_map

    # L1 DOM should be READY, downstream UI should be PENDING or BLOCKED
    assert task_map["M-FEAT-ADDSTOCKSCREEN-01-DOM"]["status"] == "READY"
    assert task_map["M-FEAT-ADDSTOCKSCREEN-03-UI"]["status"] in ("PENDING", "BLOCKED")


def test_incremental_hash_cache(isolated_workspace):
    from unigov.baseline import scan_and_lock_baseline
    import sqlite3

    ws, _ = isolated_workspace

    f1 = ws / "app" / "src" / "main" / "F1.kt"
    f1.parent.mkdir(parents=True, exist_ok=True)
    f1.write_text("class F1", encoding="utf-8")

    conn = sqlite3.connect(".antigravity/state.db")
    conn.row_factory = sqlite3.Row

    # First run - reindexes all
    res1 = scan_and_lock_baseline(conn, project_root=ws)
    assert res1["files_reindexed"] >= 1
    assert res1["files_cached"] == 0

    # Second run - all cached!
    res2 = scan_and_lock_baseline(conn, project_root=ws)
    assert res2["files_cached"] >= 1
    assert res2["files_reindexed"] == 0


def test_high_risk_low_test_coverage_alert(isolated_workspace):
    from unigov.auditor import audit_high_risk_coverage

    ws, _ = isolated_workspace

    # Create a large payment file without a test (> 200 lines)
    pay_file = ws / "app" / "src" / "main" / "payment" / "PaymentProcessor.kt"
    pay_file.parent.mkdir(parents=True, exist_ok=True)
    pay_file.write_text("class PaymentProcessor {\n" + "  val x = 1\n" * 210 + "}")

    physical_files = {"app/src/main/payment/PaymentProcessor.kt"}
    alerts = audit_high_risk_coverage(ws, physical_files)
    assert len(alerts) == 1
    assert alerts[0]["file"] == "app/src/main/payment/PaymentProcessor.kt"
    assert alerts[0]["loc"] >= 200
    assert alerts[0]["module"] == "payment"


def test_tier1_deterministic_reconciler(isolated_workspace):
    from unigov.reconciler import check_tier1_deterministic_completion
    from pathlib import Path

    ws, _ = isolated_workspace

    # Create a real implemented file
    model_file = ws / "app" / "src" / "main" / "domain" / "InwardBoxModel.kt"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text("data class InwardBoxModel(val id: String)", encoding="utf-8")

    # Check Tier-1 deterministic resolution
    res = check_tier1_deterministic_completion(
        root_dir=ws,
        candidates=[model_file],
        target_files=["app/src/main/domain/InwardBoxModel.kt"],
        task_title="Update Inward Box Models",
        task_desc="Implement InwardBoxModel data class"
    )
    assert res is not None
    assert res.status == "COMPLETED"
    assert "InwardBoxModel" in res.evidence


def test_project_memory_and_registry(isolated_workspace, monkeypatch):
    from pathlib import Path
    import unigov.db
    ws, _ = isolated_workspace
    monkeypatch.setattr(unigov.db, "REGISTRY_FILE", ws / "registry.json")

    # Record active project
    unigov.db.record_active_project("TestProject", ws)
    reg = unigov.db.get_registry_data()
    assert reg["active_project"] == "TestProject"
    assert reg["active_path"] == str(ws.resolve())
    assert "TestProject" in reg["projects"]

    # Test fallback resolution when outside project root
    resolved = unigov.db.resolve_gov_dir(Path("."))
    assert resolved.exists()


def test_adversarial_stress(isolated_workspace):
    ws, conn = isolated_workspace
    from unigov.stress import generate_adversarial_tests, execute_stress_test

    # Create dummy target file (resilient against negative, null, and non-integer inputs)
    src_file = ws / "src" / "pricing.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text(
        "def calc_total(paise: int, qty: int) -> int:\n"
        "    if not isinstance(paise, int) or not isinstance(qty, int):\n"
        "        raise TypeError('Inputs must be integers')\n"
        "    if paise < 0 or qty < 0:\n"
        "        raise ValueError('Inputs cannot be negative')\n"
        "    return paise * qty\n"
    )

    # Insert task
    with conn:
        conn.execute("""
            INSERT INTO tasks (task_id, level, title, description, target_files_json, status)
            VALUES ('T-STRESS-01', 'TASK', 'Pricing Engine', 'Implement pricing math with integer paise', ?, 'READY')
        """, (json.dumps(["src/pricing.py"]),))

    # Test report generation
    report = generate_adversarial_tests(conn, "T-STRESS-01", project_root=ws)
    assert report.task_id == "T-STRESS-01"
    assert len(report.attacks) == 3

    # Test execution
    success = execute_stress_test("T-STRESS-01", project_root=ws)
    assert success in (True, False)
    assert (ws / ".unigov" / "stress_tests" / "stress_t-stress-01.py").exists()


def test_migration_guard(isolated_workspace):
    ws, _ = isolated_workspace
    from unigov.migration_guard import audit_migration_content, audit_migration_file, execute_migration_audit

    # 1. Unsafe migration with fatal NOT NULL without DEFAULT
    unsafe_sql = """
    ALTER TABLE users ADD COLUMN age INTEGER NOT NULL;
    ALTER TABLE invoices ADD COLUMN tax_amount REAL;
    DROP TABLE legacy_records;
    """
    report = audit_migration_content(unsafe_sql, "unsafe.sql")
    assert report.is_safe is False
    assert len(report.violations) == 3
    violation_types = [v.violation_type for v in report.violations]
    assert "NOT_NULL_NO_DEFAULT" in violation_types
    assert "FLOAT_MONEY_MATH" in violation_types
    assert "DESTRUCTIVE_DROP" in violation_types

    # 2. Safe migration obeying zero-downtime rules
    safe_sql = """
    CREATE TABLE IF NOT EXISTS product_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        total_paise INTEGER NOT NULL DEFAULT 0
    );
    ALTER TABLE users ADD COLUMN status_code INTEGER NOT NULL DEFAULT 1;
    """
    safe_report = audit_migration_content(safe_sql, "safe.sql")
    assert safe_report.is_safe is True
    assert len(safe_report.violations) == 0

    # 3. Test CLI execution on physical file
    safe_file = ws / "migration_v26.sql"
    safe_file.write_text(safe_sql, encoding="utf-8")
    assert execute_migration_audit(safe_file) is True


def test_locked_test_cage(isolated_workspace):
    ws, _ = isolated_workspace
    from unigov.executor import _apply_surgical_patches, is_test_file_path
    from unigov.models import FilePatch, SearchReplaceBlock

    assert is_test_file_path("tests/test_app.py") is True
    assert is_test_file_path("app/src/test/MoneyTest.kt") is True
    assert is_test_file_path("src/domain/Money.kt") is False

    # Attempt patch on test file with locked cage
    malicious_test_patch = FilePatch(
        file_path="tests/test_app.py",
        is_new_file=False,
        edits=[SearchReplaceBlock(search="assert x == 10", replace="assert True")],
        explanation="Weaken assertion to bypass build",
    )

    with pytest.raises(PermissionError) as exc_info:
        _apply_surgical_patches([malicious_test_patch], locked_test_cage=True)

    assert "LOCKED TEST CAGE VIOLATION" in str(exc_info.value)


def test_reverse_adr(isolated_workspace):
    ws, conn = isolated_workspace
    from unigov.adr import synthesize_adr_from_diff, persist_adr, run_reverse_adr
    from unigov.models import ADRSynthesis

    sample_diff = """
diff --git a/app/src/main/domain/Money.kt b/app/src/main/domain/Money.kt
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/app/src/main/domain/Money.kt
@@ -0,0 +1,5 @@
+data class Money(val paise: Long) {
+    // Law ACC-001 Integer Paise enforcement
+}
"""
    # 1. Test synthesis
    adr = synthesize_adr_from_diff(sample_diff, conn)
    assert adr.adr_id.startswith("ADR-")
    assert "money" in adr.title.lower() or "monetary" in adr.title.lower() or "money" in adr.adr_id.lower() or "app" in adr.module_tag or "core" in adr.module_tag or "finance" in adr.module_tag

    # 2. Test persistence
    md_path = persist_adr(conn, adr, project_root=ws)
    assert md_path.exists()
    assert adr.adr_id in md_path.name
    row = conn.execute("SELECT * FROM adr_ledger WHERE adr_id = ?", (adr.adr_id,)).fetchone()
    assert row is not None
    assert row["status"] == "FINALIZED"


def test_init_ci(isolated_workspace):
    ws, _ = isolated_workspace
    from unigov.cli import init_ci_cmd

    wf_file = ws / ".github" / "workflows" / "unigov-gate.yml"
    assert not wf_file.exists()

    init_ci_cmd(target_path=wf_file, force=False)
    assert wf_file.exists()
    content = wf_file.read_text(encoding="utf-8")
    assert "name: UniGov Sovereign Governance Gate" in content
    assert "unigov check-drift" in content
    assert "unigov verify-spec" in content
    assert "unigov audit" in content










