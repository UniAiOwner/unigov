"""Smart Test Impact Analysis (TIA) and Targeted Test Runner for UniGov."""

import re
from pathlib import Path
from typing import List, Optional, Set
from .constants import normalize_posix_path


def find_impacted_tests(root_dir: Path, changed_files: List[str]) -> List[Path]:
    """Finds test files that directly verify the changed source files."""
    impacted: List[Path] = []
    seen: Set[Path] = set()

    for cf in changed_files:
        norm = normalize_posix_path(cf)
        p = root_dir / norm
        stem = p.stem

        # Case 1: The changed file itself is already a test file
        if "test" in stem.lower() or stem.endswith("_test") or stem.endswith("Test"):
            if p.is_file() and p.resolve() not in seen:
                impacted.append(p)
                seen.add(p.resolve())
            continue

        # Search candidates
        candidates = [
            f"test_{stem}.py",
            f"{stem}_test.py",
            f"test_{stem}.ts",
            f"{stem}.test.ts",
            f"{stem}.test.tsx",
            f"{stem}.spec.ts",
            f"{stem}.spec.tsx",
            f"{stem}Test.kt",
            f"{stem}Test.java",
            f"{stem}_test.go",
        ]

        for cand_name in candidates:
            for found in root_dir.rglob(cand_name):
                if found.is_file() and found.resolve() not in seen:
                    impacted.append(found)
                    seen.add(found.resolve())

    return impacted


def get_targeted_verification_command(
    root_dir: Path,
    changed_files: List[str],
    fallback_cmd: Optional[str] = None
) -> str:
    """Generates an optimized, targeted test execution command for the changed files.

    Falls back to fallback_cmd if no specific test mapping is found.
    """
    tests = find_impacted_tests(root_dir, changed_files)
    if not tests:
        return fallback_cmd or "echo 'No targeted test suite found.'"

    # Check project type
    first_test = tests[0]
    rel_tests = [normalize_posix_path(t.relative_to(root_dir) if t.is_relative_to(root_dir) else t) for t in tests]

    if first_test.suffix == ".py":
        # Pytest targeted runner
        test_args = " ".join(rel_tests)
        return f"pytest -v {test_args}"

    elif first_test.suffix in {".kt", ".java"}:
        # Gradle targeted runner
        class_filters = " ".join(f"--tests *{t.stem}*" for t in tests)
        gradle_wrapper = "./gradlew" if (root_dir / "gradlew").exists() else "gradle"
        return f"{gradle_wrapper} testDebugUnitTest {class_filters}"

    elif first_test.suffix in {".ts", ".tsx", ".js"}:
        # Jest / Vitest / NPM test runner
        test_args = " ".join(rel_tests)
        if (root_dir / "pnpm-lock.yaml").exists():
            return f"pnpm test {test_args}"
        elif (root_dir / "yarn.lock").exists():
            return f"yarn test {test_args}"
        return f"npm test -- {test_args}"

    elif first_test.suffix == ".go":
        # Go test runner
        dirs = {str(t.parent) for t in tests}
        return f"go test -v {' '.join(dirs)}"

    return fallback_cmd or f"pytest -v {' '.join(rel_tests)}"
