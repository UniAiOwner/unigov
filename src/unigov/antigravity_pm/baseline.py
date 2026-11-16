import fnmatch
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

CODE_EXTENSIONS = {".kt", ".java", ".py", ".ts", ".tsx", ".js", ".rs", ".go", ".cpp", ".c", ".h"}
DEFAULT_IGNORE_DIRS = {
    ".git", ".unigov", ".antigravity", ".venv", "venv", "node_modules",
    "build", ".gradle", "__pycache__", "dist", ".idea", ".pytest_cache"
}


def load_unigovernor_ignores(project_root: Path) -> List[str]:
    """Loads custom ignore patterns from .unigovernor file if present."""
    gov_file = project_root / ".unigovernor"
    patterns = []
    if gov_file.exists():
        for line in gov_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
    return patterns


def should_ignore_path(path: Path, ignore_patterns: List[str]) -> bool:
    """Checks whether a path matches default or user-defined ignore rules."""
    parts = set(path.parts)
    if parts.intersection(DEFAULT_IGNORE_DIRS):
        return True
    posix_path = path.as_posix()
    for pattern in ignore_patterns:
        if fnmatch.fnmatch(posix_path, pattern) or fnmatch.fnmatch(path.name, pattern):
            return True
    return False


def classify_source_file(rel_posix: str) -> Tuple[str, str, str]:
    """
    Deterministically classifies a source file into a Clean Architecture subsystem.
    Returns: (subsystem_id, subsystem_title, layer)
    """
    lower = rel_posix.lower()

    # 1. Tests (Layer 4 Security & Verification)
    if "test" in lower or lower.endswith("test.kt") or lower.endswith("spec.ts"):
        return (
            "M0-BASE-TEST",
            "Unit & Integration Test Verification Suites",
            "LAYER_4_SECURITY",
        )

    # 2. Database Migrations (Layer 2 Data)
    if "migration" in lower or "schema_migration" in lower:
        return (
            "M0-BASE-MIGRATIONS",
            "Database Schema Migration Chains",
            "LAYER_2_DATA",
        )

    # 3. DAOs & Local Queries (Layer 2 Data)
    if "/dao/" in lower or lower.endswith("dao.kt") or "queries" in lower:
        return (
            "M0-BASE-DAO",
            "Local Persistence DAOs & Queries",
            "LAYER_2_DATA",
        )

    # 4. Entities & Database Schemas (Layer 2 Data)
    if "/entity/" in lower or lower.endswith("entity.kt") or "schema" in lower:
        return (
            "M0-BASE-SCHEMA",
            "Local Schema Entities & Foreign Keys",
            "LAYER_2_DATA",
        )

    # 5. Repositories, Outbox & Cloud Sync (Layer 2 Data)
    if "repository" in lower or "sync" in lower or "outbox" in lower or "network" in lower:
        return (
            "M0-BASE-SYNC",
            "Data Repositories, Outbox & Cloud Sync",
            "LAYER_2_DATA",
        )

    # 6. Hardware, Sensors & Thermal Printing (Layer 3 Surfaces)
    if "hardware" in lower or "printer" in lower or "bluetooth" in lower or "scanner" in lower:
        return (
            "M0-BASE-HW",
            "Hardware Peripherals, Sensors & Drivers",
            "LAYER_3_SURFACES",
        )

    # 7. Cloud Functions & Serverless (Layer 2 Data)
    if "functions/" in lower or "serverless" in lower or "backend" in lower:
        return (
            "M0-BASE-CLOUD",
            "Cloud Functions & Serverless Handlers",
            "LAYER_2_DATA",
        )

    # 8. Domain Layer (Layer 1 Domain)
    if "/domain/" in lower or "model" in lower or "fsm" in lower or "money" in lower:
        return (
            "M0-BASE-DOM",
            "Domain Core Models, Math & Rules",
            "LAYER_1_DOMAIN",
        )

    # 9. UI Features (Layer 3 Surfaces)
    if "/ui/" in lower or "screens/" in lower or "views/" in lower or "components/" in lower:
        parts = rel_posix.split("/")
        feature_name = "general"
        if "ui" in parts:
            idx = parts.index("ui")
            if idx + 1 < len(parts) and not parts[idx + 1].endswith((".kt", ".java", ".ts", ".tsx")):
                feature_name = parts[idx + 1]
        slug = "".join(c for c in feature_name if c.isalnum()).upper()
        return (
            f"M0-BASE-FEAT-{slug}",
            f"Feature Presentation: {feature_name.capitalize()}",
            "LAYER_3_SURFACES",
        )

    # 10. Platform Foundation
    return (
        "M0-BASE-PLATFORM",
        "Application Foundation & Entry Points",
        "LAYER_1_DOMAIN",
    )


def scan_and_lock_baseline(conn: sqlite3.Connection, project_root: Path = Path(".")) -> dict:
    """
    Deterministic zero-LLM AST/Package scanner.
    Indexes all existing production files into M0-BASELINE (STATUS = COMPLETED).
    """
    from .db import resolve_gov_dir

    ignore_patterns = load_unigovernor_ignores(project_root)
    gov_dir = resolve_gov_dir(project_root)

    subsystems: Dict[str, Dict] = {}
    total_files = 0

    for path in project_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in CODE_EXTENSIONS:
            continue
        rel_path = path.relative_to(project_root)
        if should_ignore_path(rel_path, ignore_patterns):
            continue

        rel_posix = rel_path.as_posix()
        sub_id, sub_title, layer = classify_source_file(rel_posix)

        if sub_id not in subsystems:
            subsystems[sub_id] = {
                "id": sub_id,
                "title": sub_title,
                "layer": layer,
                "files": [],
            }
        subsystems[sub_id]["files"].append(rel_posix)
        total_files += 1

    with conn:
        # 1. Upsert Parent Milestone M0-BASELINE
        conn.execute("""
            INSERT OR REPLACE INTO tasks (
                task_id, parent_id, level, layer, title, description,
                target_files_json, verify_cmd, status, completed_at, is_baseline
            ) VALUES (
                'M0-BASELINE', NULL, 'MILESTONE', 'LAYER_1_DOMAIN',
                'Verified Legacy & Production Core',
                'Deterministic Baseline snapshot of all verified production files prior to active sprint.',
                ?, 'echo "Baseline Verified"', 'COMPLETED', CURRENT_TIMESTAMP, 1
            )
        """, (json.dumps([]),))

        # 2. Insert or Update Child Module Tasks for each Subsystem
        for sub_id, sub_data in subsystems.items():
            conn.execute("""
                INSERT OR REPLACE INTO tasks (
                    task_id, parent_id, level, layer, title, description,
                    target_files_json, verify_cmd, status, completed_at, is_baseline, subsystem
                ) VALUES (
                    ?, 'M0-BASELINE', 'MODULE', ?, ?, ?, ?, 'echo "Subsystem Verified"', 'COMPLETED', CURRENT_TIMESTAMP, 1, ?
                )
            """, (
                sub_id,
                sub_data["layer"],
                sub_data["title"],
                f"Subsystem covering {len(sub_data['files'])} verified production files.",
                json.dumps(sorted(sub_data["files"])),
                sub_id,
            ))

    # Save subsystems.json in .unigov
    subsystems_file = gov_dir / "subsystems.json"
    gov_dir.mkdir(parents=True, exist_ok=True)
    subsystems_file.write_text(json.dumps({
        "total_files": total_files,
        "subsystem_count": len(subsystems),
        "subsystems": subsystems,
    }, indent=2), encoding="utf-8")

    return {
        "total_files": total_files,
        "subsystem_count": len(subsystems),
        "subsystems": subsystems,
    }


def check_baseline_tripwire(modified_files: List[str], conn: sqlite3.Connection) -> List[Dict]:
    """
    Checks if any modified files touch the M0-BASELINE.
    If so, returns tripwire alerts and identifies associated regression tests.
    """
    baseline_modules = conn.execute("""
        SELECT task_id, title, layer, target_files_json, subsystem 
        FROM tasks 
        WHERE is_baseline = 1 AND level = 'MODULE'
    """).fetchall()

    test_task = conn.execute("SELECT target_files_json FROM tasks WHERE task_id = 'M0-BASE-TEST'").fetchone()
    all_tests = json.loads(test_task["target_files_json"]) if test_task and test_task["target_files_json"] else []

    alerts = []
    for mf in modified_files:
        norm_mf = Path(mf).as_posix()
        for b in baseline_modules:
            files = json.loads(b["target_files_json"] or "[]")
            if norm_mf in files:
                # Find potentially related tests
                stem = Path(norm_mf).stem.lower().replace("entity", "").replace("dao", "").replace("repository", "")
                related_tests = [t for t in all_tests if stem and stem in t.lower()][:3]
                alerts.append({
                    "file": norm_mf,
                    "subsystem": b["title"],
                    "subsystem_id": b["task_id"],
                    "layer": b["layer"],
                    "related_tests": related_tests,
                })
                break

    return alerts
