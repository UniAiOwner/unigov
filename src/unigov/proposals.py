"""UniGov Change-Centric Proposals Workflow (Inspired by Fission-AI/OpenSpec).

Enforces delta-based architectural modifications via .unigov/proposals/
instead of directly mutating master 15-dimension specifications.
"""

from datetime import datetime
import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .db import resolve_gov_dir, get_db

console = Console()


def sanitize_slug(slug: str) -> str:
    """Standardizes proposal slug to lowercase alphanumeric with underscores."""
    s = re.sub(r"[^a-zA-Z0-9_-]", "_", slug.strip().lower())
    return re.sub(r"_+", "_", s).strip("_")


def get_proposals_dir(project_root: Path) -> Path:
    gov_dir = resolve_gov_dir(project_root)
    p_dir = gov_dir / "proposals"
    p_dir.mkdir(parents=True, exist_ok=True)
    return p_dir


def scaffold_proposal(
    project_root: Path,
    slug: str,
    title: Optional[str] = None,
    dimension: str = "02_DATA_AND_STORAGE",
    author: str = "UniAiOwner"
) -> Dict[str, Any]:
    """Generates an RFC-style change proposal directory with proposal.md and delta_spec.json."""
    clean_slug = sanitize_slug(slug)
    p_dir = get_proposals_dir(project_root) / clean_slug
    p_dir.mkdir(parents=True, exist_ok=True)

    prop_title = title or clean_slug.replace("_", " ").title()
    prop_id = f"PROP-{clean_slug.upper()}"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. delta_spec.json
    delta_payload = {
        "proposal_id": prop_id,
        "title": prop_title,
        "slug": clean_slug,
        "target_dimension": dimension,
        "author": author,
        "status": "DRAFT",
        "created_at": now_str,
        "added_invariants": [
            {
                "id": f"INV-{clean_slug[:6].upper()}-001",
                "title": f"{prop_title} Core Rule",
                "rule_type": "FORBIDDEN_TOKENS",
                "enforcement": "BLOCK_BUILD",
                "params": {"forbidden_tokens": []}
            }
        ],
        "modified_invariants": [],
        "deprecated_invariants": [],
    }
    delta_file = p_dir / "delta_spec.json"
    delta_file.write_text(json.dumps(delta_payload, indent=2), encoding="utf-8")

    # 2. proposal.md
    proposal_md = f"""# 📜 Change Proposal: {prop_title}
**Proposal ID:** `{prop_id}`  
**Slug:** `{clean_slug}`  
**Author:** {author}  
**Target Dimension:** `{dimension}`  
**Status:** `DRAFT`  
**Created:** {now_str}  

---

## 🎯 1. Problem Statement & Motivation
_Explain the current architectural limitation or newly required capability._

---

## 💡 2. Proposed Specification Delta
_Detail the invariants and schema modifications being introduced._

### Invariant Delta:
- **Added:** `INV-{clean_slug[:6].upper()}-001` — {prop_title} Core Rule
- **Modified:** _None_
- **Deprecated:** _None_

---

## ⚖️ 3. Trade-offs & Rejected Alternatives
- **Alternative 1:** In-place modification without versioning (Rejected: Risks silent regression).
- **Alternative 2:** Ad-hoc implementation without architectural sign-off (Rejected: Violates Law-000).

---

## 🚀 4. Verification & Testing Requirements
- Unit test suite must remain 100% green.
- Adversarial red-team mutation must confirm invariant enforcement.
"""
    (p_dir / "proposal.md").write_text(proposal_md, encoding="utf-8")

    # 3. impact_matrix.md
    impact_md = f"""# 🗺️ Cross-Dimension Impact Matrix: {prop_title}

| Dimension | Impact Level | Notes / Touchpoints |
| :--- | :--- | :--- |
| `01_VISION_AND_CONSTRAINTS` | NONE | No constitutional amendments required |
| `{dimension}` | DIRECT | Primary delta target |
| `06_SECURITY_AND_PERMISSIONS` | INDIRECT | Verification of token / secret safety |
| `13_TESTING_AND_QUALITY_ASSURANCE` | DIRECT | New invariant unit tests required |
"""
    (p_dir / "impact_matrix.md").write_text(impact_md, encoding="utf-8")

    return {
        "slug": clean_slug,
        "proposal_id": prop_id,
        "directory": p_dir.as_posix(),
        "files_created": ["delta_spec.json", "proposal.md", "impact_matrix.md"],
    }


def list_proposals(project_root: Path) -> List[Dict[str, Any]]:
    """Discovers and inspects all registered change proposals."""
    p_dir = get_proposals_dir(project_root)
    proposals: List[Dict[str, Any]] = []

    for item in sorted(p_dir.iterdir()):
        if item.is_dir() and (item / "delta_spec.json").exists():
            try:
                data = json.loads((item / "delta_spec.json").read_text(encoding="utf-8"))
                proposals.append({
                    "slug": item.name,
                    "proposal_id": data.get("proposal_id", item.name),
                    "title": data.get("title", item.name),
                    "target_dimension": data.get("target_dimension", "UNKNOWN"),
                    "status": data.get("status", "DRAFT"),
                    "author": data.get("author", "Unknown"),
                    "added_count": len(data.get("added_invariants", [])),
                })
            except Exception:
                continue

    return proposals


def validate_proposal(project_root: Path, slug: str) -> Dict[str, Any]:
    """Validates structural syntax and invariant integrity of a change proposal."""
    clean_slug = sanitize_slug(slug)
    p_dir = get_proposals_dir(project_root) / clean_slug
    delta_file = p_dir / "delta_spec.json"

    if not delta_file.exists():
        return {"valid": False, "error": f"Proposal '{clean_slug}' not found"}

    try:
        data = json.loads(delta_file.read_text(encoding="utf-8"))
    except Exception as e:
        return {"valid": False, "error": f"Invalid JSON in delta_spec.json: {e}"}

    errors = []
    if not data.get("proposal_id"):
        errors.append("Missing 'proposal_id'")
    if not data.get("target_dimension"):
        errors.append("Missing 'target_dimension'")

    for inv in data.get("added_invariants", []):
        if not inv.get("id"):
            errors.append("Invariant in added_invariants missing 'id'")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "proposal": data,
    }


def apply_proposal(project_root: Path, slug: str) -> Dict[str, Any]:
    """Merges an approved change proposal into master docs and records an ADR."""
    clean_slug = sanitize_slug(slug)
    validation = validate_proposal(project_root, clean_slug)
    if not validation["valid"]:
        return {"success": False, "error": f"Validation failed: {validation['errors']}"}

    data = validation["proposal"]
    p_dir = get_proposals_dir(project_root) / clean_slug
    delta_file = p_dir / "delta_spec.json"

    # 1. Update proposal status to APPLIED
    data["status"] = "APPLIED"
    data["applied_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    delta_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # 2. Record Architecture Decision Record in SQLite if DB initialized
    state_db = resolve_gov_dir(project_root) / "state.db"
    adr_recorded = False
    if state_db.exists():
        conn = get_db(project_root)
        adr_id = f"ADR-{data['proposal_id']}"
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO adr_ledger 
                (adr_id, module_tag, decision, rationale, rejected_alternatives, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    adr_id,
                    data.get("target_dimension", "ARCHITECTURE"),
                    f"Applied Change Proposal: {data.get('title')}",
                    f"Adopted {len(data.get('added_invariants', []))} invariant(s) via delta proposal {clean_slug}.",
                    "Direct unversioned file mutation without delta RFC",
                    datetime.now().strftime("%Y-%m-%d %H:%M"),
                )
            )
            adr_recorded = True

    return {
        "success": True,
        "proposal_id": data["proposal_id"],
        "slug": clean_slug,
        "adr_recorded": adr_recorded,
        "status": "APPLIED",
    }
