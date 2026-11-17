import json
import pytest
from pathlib import Path
from typer.testing import CliRunner

from unigov.feature_scaffolder import (
    sanitize_feature_slug,
    scaffold_feature_suite,
    list_project_features,
    FEATURE_LAYERS,
)
from unigov.cli import app

runner = CliRunner(env={"COLUMNS": "160"})


def test_sanitize_feature_slug():
    assert sanitize_feature_slug("Repair Lab") == "repair_lab"
    assert sanitize_feature_slug("POS--Billing!!") == "pos_billing"
    assert sanitize_feature_slug("  Add_Stock_Inward  ") == "add_stock_inward"


def test_scaffold_feature_suite_creates_all_layers(tmp_path):
    target = tmp_path / "PLANNING"
    res = scaffold_feature_suite("repair_parts", "Repair Spare Parts", target)

    assert res["feature_slug"] == "repair_parts"
    assert res["total_created"] > 0
    assert res["total_skipped"] == 0

    # Verify each layer directory exists
    for layer in FEATURE_LAYERS:
        folder = target / layer["folder"] / "repair_parts"
        assert folder.exists()
        assert folder.is_dir()
        for doc in layer["files"]:
            file_path = folder / doc["filename"]
            assert file_path.exists()
            content = file_path.read_text(encoding="utf-8")
            assert "Repair Spare Parts" in content


def test_feature_invariants_valid_json(tmp_path):
    target = tmp_path / "PLANNING"
    scaffold_feature_suite("pos_billing", "Point of Sale Billing", target)

    financial_file = target / "01_DOMAIN_AND_RULES" / "pos_billing" / "03_financial_math.md"
    assert financial_file.exists()
    content = financial_file.read_text(encoding="utf-8")

    # Check for invariant block
    assert "<!-- UNIGOV_INVARIANT_START -->" in content
    assert "<!-- UNIGOV_INVARIANT_END -->" in content

    # Extract and parse JSON
    start = content.index("<!-- UNIGOV_INVARIANT_START -->") + len("<!-- UNIGOV_INVARIANT_START -->")
    end = content.index("<!-- UNIGOV_INVARIANT_END -->")
    inv_json = json.loads(content[start:end].strip())
    assert isinstance(inv_json, list)
    assert inv_json[0]["id"] == "INV-FIN-001"
    assert inv_json[0]["params"]["forbidden_tokens"] == ["Float", "Double", "0.18f", "BigDecimal.toFloat"]


def test_list_project_features(tmp_path):
    target = tmp_path / "PLANNING"
    scaffold_feature_suite("repair_lab", "Repair Lab", target)
    scaffold_feature_suite("add_stock", "Add Stock Inward", target)

    features = list_project_features(target)
    assert len(features) == 2
    slugs = [f["feature_slug"] for f in features]
    assert "repair_lab" in slugs
    assert "add_stock" in slugs


def test_cli_plan_feature_and_list_features(tmp_path):
    target = tmp_path / "PLANNING"

    # Run plan-feature via CLI
    res = runner.invoke(app, ["plan-feature", "catalog_manager", "--title", "Catalog Manager", "--dir", str(target)])
    assert res.exit_code == 0
    assert "Successfully scaffolded 7-Layer Architecture Suite" in res.output

    # Run list-features via CLI
    res_list = runner.invoke(app, ["list-features", "--dir", str(target)])
    assert res_list.exit_code == 0
    assert "catalog_manager" in res_list.output
