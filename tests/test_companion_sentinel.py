"""Tests for UniGov Sovereign Session Companion & Inotify Sentinel."""

import json
from pathlib import Path
from typer.testing import CliRunner
from unigov.cli import app
from unigov.sentinel import check_file_invariants, SentinelState, InvariantViolation
from unigov.companion import get_companion_state, render_dynamic_pill

runner = CliRunner()


def test_companion_command(tmp_path: Path):
    res = runner.invoke(app, ["companion", "--dir", str(tmp_path)])
    assert res.exit_code == 0
    assert "UniGov" in res.output


def test_pill_command(tmp_path: Path):
    res = runner.invoke(app, ["pill", "--dir", str(tmp_path)])
    assert res.exit_code == 0
    assert "UniGov" in res.output


def test_check_file_invariants_suppress(tmp_path: Path):
    kt_file = tmp_path / "BadModel.kt"
    kt_file.write_text('@Suppress("UNCHECKED_CAST")\nclass BadModel', encoding="utf-8")

    violations = check_file_invariants(kt_file, "BadModel.kt")
    assert len(violations) >= 1
    assert violations[0].rule_id == "LAW-000"
    assert "Suppress" in violations[0].message


def test_check_file_invariants_clean(tmp_path: Path):
    kt_file = tmp_path / "CleanModel.kt"
    kt_file.write_text('class CleanModel(val id: Long)', encoding="utf-8")

    violations = check_file_invariants(kt_file, "CleanModel.kt")
    assert len(violations) == 0


def test_sentinel_state_persistence(tmp_path: Path):
    gov_dir = tmp_path / ".unigov"
    gov_dir.mkdir(parents=True)

    state = SentinelState(gov_dir)
    state.record_event("MODIFIED", "app/Test.kt", "File modified")
    assert state.state_file.exists()

    data = json.loads(state.state_file.read_text(encoding="utf-8"))
    assert data["active"] is True
    assert len(data["recent_events"]) == 1
    assert data["recent_events"][0]["file_path"] == "app/Test.kt"
