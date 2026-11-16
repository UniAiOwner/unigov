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

