import json
from pathlib import Path
import pytest
import sqlite3

from unigov.analyzer import (
    extract_invariants_from_markdown,
    scan_specs_in_directory,
    run_artifact_analysis,
)
from unigov.context_bundler import (
    estimate_token_count,
    calculate_token_budget,
    render_budget_badge,
)
from unigov.proposals import (
    sanitize_slug,
    scaffold_proposal,
    list_proposals,
    validate_proposal,
    apply_proposal,
)


def test_spec_kit_invariant_extractor():
    sample_md = """# Spec Document
<!-- UNIGOV_INVARIANT_START -->
[
  {
    "id": "INV-TEST-001",
    "title": "Strict Currency Invariant",
    "rule_type": "FORBIDDEN_TOKENS",
    "enforcement": "BLOCK_BUILD"
  }
]
<!-- UNIGOV_INVARIANT_END -->
"""
    invs = extract_invariants_from_markdown(sample_md)
    assert len(invs) == 1
    assert invs[0]["id"] == "INV-TEST-001"
    assert invs[0]["enforcement"] == "BLOCK_BUILD"


def test_spec_kit_analyzer_consistency(tmp_path):
    # Setup test workspace
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    spec_file = docs_dir / "01_test_spec.md"
    spec_file.write_text("""# Test Spec
<!-- UNIGOV_INVARIANT_START -->
[
  {"id": "INV-ALPHA-001", "title": "Alpha Rule"},
  {"id": "INV-BETA-002", "title": "Beta Rule"}
]
<!-- UNIGOV_INVARIANT_END -->
""", encoding="utf-8")

    # Run analysis without DB
    res_uninit = run_artifact_analysis(tmp_path)
    assert res_uninit["total_specs"] == 1
    assert res_uninit["total_invariants"] == 2
    assert len(res_uninit["orphan_invariants"]) == 2

    # Initialize SQLite state
    gov_dir = tmp_path / ".unigov"
    gov_dir.mkdir(parents=True, exist_ok=True)
    db_file = gov_dir / "state.db"
    conn = sqlite3.connect(db_file)
    conn.execute("""
    CREATE TABLE tasks (
        task_id TEXT PRIMARY KEY,
        parent_id TEXT,
        level TEXT,
        title TEXT,
        description TEXT,
        target_files_json TEXT,
        status TEXT
    )
    """)
    conn.execute("""
    INSERT INTO tasks VALUES (
        'TASK-01', NULL, 'TASK', 'Implement Alpha Rule',
        'Implements INV-ALPHA-001 specification', '["src/alpha.py"]', 'READY'
    )
    """)
    conn.commit()
    conn.close()

    res_with_task = run_artifact_analysis(tmp_path)
    assert res_with_task["total_tasks"] == 1
    assert res_with_task["mapped_invariants"] == 1
    assert res_with_task["consistency_score"] == 50.0
    assert len(res_with_task["orphan_invariants"]) == 1
    assert res_with_task["orphan_invariants"][0]["id"] == "INV-BETA-002"


def test_gsd_token_budget_meter():
    # 1. Test token estimation
    short_text = "def hello_world(): return 42"
    tokens = estimate_token_count(short_text)
    assert tokens > 0
    assert tokens < 20

    # 2. Test Sweet Spot zone (<= 30%)
    budget_sweet = calculate_token_budget("hello world" * 50, context_window=100_000)
    assert budget_sweet["zone"] == "SWEET_SPOT"
    assert budget_sweet["utilization_pct"] <= 30.0
    assert "SWEET SPOT" in render_budget_badge(budget_sweet)

    # 3. Test Caution zone (30-50%)
    budget_caution = calculate_token_budget("x" * 150_000, context_window=100_000)
    assert budget_caution["zone"] in ("CAUTION", "ROT_DANGER")

    # 4. Test Rot Danger zone (> 50%)
    budget_rot = calculate_token_budget("x" * 300_000, context_window=100_000)
    assert budget_rot["zone"] == "ROT_DANGER"
    assert "ROT DANGER" in render_budget_badge(budget_rot)


def test_openspec_proposals_workflow(tmp_path):
    # 1. Slug sanitization
    assert sanitize_slug("Feature 01: Fast Sync!!") == "feature_01_fast_sync"

    # 2. Scaffold proposal
    res = scaffold_proposal(
        tmp_path,
        slug="offline_queue",
        title="Offline Sync Queue",
        dimension="02_DATA_AND_STORAGE",
        author="Shoeb Ahmad"
    )
    assert res["slug"] == "offline_queue"
    assert res["proposal_id"] == "PROP-OFFLINE_QUEUE"
    prop_dir = Path(res["directory"])
    assert (prop_dir / "delta_spec.json").exists()
    assert (prop_dir / "proposal.md").exists()
    assert (prop_dir / "impact_matrix.md").exists()

    # 3. List proposals
    proposals = list_proposals(tmp_path)
    assert len(proposals) == 1
    assert proposals[0]["slug"] == "offline_queue"
    assert proposals[0]["status"] == "DRAFT"

    # 4. Validate proposal
    val = validate_proposal(tmp_path, "offline_queue")
    assert val["valid"] is True
    assert val["proposal"]["target_dimension"] == "02_DATA_AND_STORAGE"

    # 5. Apply proposal with SQLite ADR ledger
    gov_dir = tmp_path / ".unigov"
    gov_dir.mkdir(parents=True, exist_ok=True)
    db_file = gov_dir / "state.db"
    conn = sqlite3.connect(db_file)
    conn.execute("""
    CREATE TABLE adr_ledger (
        adr_id TEXT PRIMARY KEY,
        module_tag TEXT,
        decision TEXT,
        rationale TEXT,
        rejected_alternatives TEXT,
        created_at TEXT
    )
    """)
    conn.commit()
    conn.close()

    applied = apply_proposal(tmp_path, "offline_queue")
    assert applied["success"] is True
    assert applied["status"] == "APPLIED"
    assert applied["adr_recorded"] is True

    # Verify updated status in delta_spec.json
    delta = json.loads((prop_dir / "delta_spec.json").read_text(encoding="utf-8"))
    assert delta["status"] == "APPLIED"
