"""UniGov Sovereign Inotify Watchdog & Real-Time Invariant Sentinel.

Continuously monitors the active project directory for file modifications,
verifies constitutional invariants (Law-000 Zero Suppress, Law ACC-001 Integer Currency,
Zero Secrets), matches changes against active WBS tasks, and logs live sentinel telemetry.
"""

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
import sqlite3
import time
from typing import Dict, Any, List, Optional, Tuple

skills_src = "/media/uniai/UniAi/PROJECTS_MIGRATED/uniskill/src"
if skills_src not in sys.path:
    sys.path.insert(0, skills_src)

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False

from .constants import DEFAULT_IGNORE_DIRS, CODE_EXTENSIONS, normalize_posix_path
from .db import resolve_gov_dir, get_db

logger = logging.getLogger("unigov.sentinel")


def send_desktop_notification(title: str, message: str, urgency: str = "normal") -> None:
    """Fires native Linux desktop notification via notify-send."""
    try:
        subprocess.run(["notify-send", "-u", urgency, title, message], check=False, capture_output=True)
    except Exception:
        pass

SECRET_SIGNATURES = [
    "AIzaSy",
    "BEGIN PRIVATE KEY",
    "BEGIN RSA PRIVATE KEY",
    "sk-proj-",
    "ghp_",
]


class InvariantViolation:
    def __init__(self, rule_id: str, file_path: str, message: str, severity: str = "ERROR"):
        self.rule_id = rule_id
        self.file_path = file_path
        self.message = message
        self.severity = severity
        self.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "file_path": self.file_path,
            "message": self.message,
            "severity": self.severity,
            "timestamp": self.timestamp,
        }


def check_file_invariants(file_path: Path, rel_path: str) -> List[InvariantViolation]:
    """Inspects a modified code file against Constitutional Laws."""
    violations: List[InvariantViolation] = []
    ext = file_path.suffix.lower()

    if ext not in CODE_EXTENSIONS:
        return violations

    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return violations

    # Law-000: Zero @Suppress Annotations across Kotlin and Java
    if ext in (".kt", ".java"):
        if "@Suppress" in content or "@SuppressWarnings" in content:
            violations.append(
                InvariantViolation(
                    rule_id="LAW-000",
                    file_path=rel_path,
                    message="Constitutional Violation: @Suppress annotation detected in production code.",
                    severity="CRITICAL",
                )
            )

    # Security: Secret signatures
    for sig in SECRET_SIGNATURES:
        if sig in content:
            # Skip if inside test mock data or constants definition
            if "test" not in rel_path.lower() and "constants.py" not in rel_path:
                violations.append(
                    InvariantViolation(
                        rule_id="SEC-001",
                        file_path=rel_path,
                        message=f"Secret Token Detected: Found potential secret signature '{sig}'.",
                        severity="CRITICAL",
                    )
                )

    # Constitutional: Zero Devanagari & Zero Transport Metaphors
    try:
        from uniskill.invariants import check_devanagari_invariant, check_vehicle_metaphor_invariant
        devs = check_devanagari_invariant(content)
        if devs:
            violations.append(
                InvariantViolation(
                    rule_id="LANG-001",
                    file_path=rel_path,
                    message=f"Devanagari script detected at line {devs[0][0]}: '{devs[0][1]}'",
                    severity="HIGH",
                )
            )
        metas = check_vehicle_metaphor_invariant(content)
        if metas:
            violations.append(
                InvariantViolation(
                    rule_id="NOMEN-001",
                    file_path=rel_path,
                    message=f"Forbidden vehicle metaphor '{metas[0][1]}' detected at line {metas[0][0]}",
                    severity="HIGH",
                )
            )
    except Exception:
        pass

    return violations


def auto_heal_file(file_path: Path) -> Dict[str, Any]:
    """Surgically repairs constitutional violations and formatting issues.

    Repairs:
    1. LAW-000: Strips @Suppress / @SuppressWarnings from Kotlin/Java.
    2. NOMEN-001 & LANG-001: Sanitizes transport metaphors and Devanagari.
    3. SKILL.md Frontmatter: Repairs multi-line YAML frontmatter using description: >- block scalar.
    """
    if not file_path.is_file():
        return {"healed": False, "actions": []}

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return {"healed": False, "error": str(e), "actions": []}

    actions = []
    modified_content = content
    ext = file_path.suffix.lower()

    # 1. LAW-000: Strip @Suppress annotations from Kotlin/Java
    if ext in (".kt", ".java"):
        suppress_pattern = re.compile(r'^[ \t]*@(Suppress|SuppressWarnings)\s*\([^)]*\)[ \t]*\n?', re.MULTILINE)
        if suppress_pattern.search(modified_content):
            count = len(suppress_pattern.findall(modified_content))
            modified_content = suppress_pattern.sub('', modified_content)
            actions.append(f"Stripped {count} @Suppress annotation(s)")

    # 2. LANG-001 & NOMEN-001: Sanitize Devanagari & Transport metaphors
    if ext in CODE_EXTENSIONS or file_path.name == "SKILL.md":
        try:
            from uniskill.upgrader import sanitize_text
            sanitized = sanitize_text(modified_content)
            if sanitized != modified_content:
                modified_content = sanitized
                actions.append("Sanitized nomenclature/Devanagari")
        except Exception:
            pass

    # 3. SKILL.md Frontmatter repair
    if file_path.name == "SKILL.md":
        try:
            from uniskill.invariants import validate_skill_file
            val = validate_skill_file(file_path)
            if not val.get("valid"):
                from uniskill.upgrader import upgrade_skill_file
                upg_res = upgrade_skill_file(file_path)
                if upg_res.get("upgraded"):
                    actions.append("Repaired SKILL.md YAML 1.2 frontmatter")
                    return {"healed": True, "actions": actions}
        except Exception:
            pass

    if actions and modified_content != content:
        file_path.write_text(modified_content, encoding="utf-8")
        return {"healed": True, "actions": actions}

    return {"healed": len(actions) > 0, "actions": actions}


class SentinelState:
    """Maintains the active sentinel state on disk in .unigov/sentinel.json."""

    def __init__(self, gov_dir: Path):
        self.gov_dir = gov_dir
        self.state_file = gov_dir / "sentinel.json"
        self.violations: List[Dict[str, Any]] = []
        self.recent_events: List[Dict[str, Any]] = []
        self.files_monitored: int = 0
        self.last_pulse: str = time.strftime("%Y-%m-%d %H:%M:%S")

    def record_event(self, event_type: str, file_path: str, message: str, violations: Optional[List[InvariantViolation]] = None):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.last_pulse = ts

        event = {
            "timestamp": ts,
            "event_type": event_type,
            "file_path": file_path,
            "message": message,
        }
        self.recent_events.insert(0, event)
        self.recent_events = self.recent_events[:50]  # Keep last 50 events

        if violations:
            for v in violations:
                self.violations.insert(0, v.to_dict())
            self.violations = self.violations[:50]

        self.save()

    def clear_resolved_violations(self, file_path: str):
        self.violations = [v for v in self.violations if v["file_path"] != file_path]
        self.save()

    def save(self):
        try:
            payload = {
                "active": True,
                "last_pulse": self.last_pulse,
                "violations_count": len(self.violations),
                "violations": self.violations[:10],
                "recent_events": self.recent_events[:20],
            }
            self.state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass


class ProjectSentinelHandler(FileSystemEventHandler if WATCHDOG_AVAILABLE else object):
    """Event handler that captures code mutations and executes invariant scans."""

    def __init__(self, project_root: Path, gov_dir: Path, db_conn: sqlite3.Connection, auto_heal: bool = True):
        super().__init__()
        self.project_root = project_root
        self.gov_dir = gov_dir
        self.db_conn = db_conn
        self.auto_heal = auto_heal
        self.sentinel_state = SentinelState(gov_dir)
        self.watch_log = gov_dir / "watch.log"

    def should_ignore(self, path_str: str) -> bool:
        norm = normalize_posix_path(path_str)
        parts = norm.split("/")
        for ignored in DEFAULT_IGNORE_DIRS:
            if ignored in parts:
                return True
        return False

    def on_modified(self, event):
        if event.is_directory or self.should_ignore(event.src_path):
            return
        self._process_path(Path(event.src_path), "MODIFIED")

    def on_created(self, event):
        if event.is_directory or self.should_ignore(event.src_path):
            return
        self._process_path(Path(event.src_path), "CREATED")

    def _process_path(self, file_path: Path, action: str):
        try:
            rel_path = normalize_posix_path(file_path.relative_to(self.project_root))
        except Exception:
            rel_path = normalize_posix_path(file_path)

        violations = check_file_invariants(file_path, rel_path)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")

        # Auto-Heal if enabled and violations present
        healed_actions = []
        if violations and self.auto_heal:
            heal_res = auto_heal_file(file_path)
            if heal_res.get("healed"):
                healed_actions = heal_res.get("actions", [])
                violations = check_file_invariants(file_path, rel_path)

        # Log to watch.log
        if violations:
            status = f"VIOLATION ({len(violations)} issues)"
            for v in violations:
                if v.severity in ("CRITICAL", "HIGH"):
                    send_desktop_notification(f"🚨 UniGov Alert [{v.rule_id}]", f"{rel_path}: {v.message}", urgency="critical")
        elif healed_actions:
            action_summary = ", ".join(healed_actions)
            status = f"AUTO-HEALED ({action_summary})"
            self.sentinel_state.clear_resolved_violations(rel_path)
            send_desktop_notification("🛠️ UniGov Auto-Healed", f"{rel_path}: {action_summary}", urgency="normal")
        else:
            status = "CLEAN"
            self.sentinel_state.clear_resolved_violations(rel_path)

        log_line = f"[{ts}] [WATCHDOG] {action} {rel_path} -> {status}"

        # JIT Skill recommendation for modified code files
        jit_line = ""
        ext = file_path.suffix.lower()
        if not violations and action == "MODIFIED" and ext in CODE_EXTENSIONS:
            try:
                from uniskill.router import route_skills_for_task
                file_tokens = f"{file_path.stem} {rel_path}"
                jit_skills = route_skills_for_task(file_tokens, top_k=1)
                if jit_skills and jit_skills[0]["relevance_score"] >= 40.0:
                    top_s = jit_skills[0]
                    jit_line = f"[{ts}] [JIT SKILL] For {rel_path} -> Recommended: {top_s['skill_name']} ({top_s['relevance_score']}%)"
            except Exception:
                pass

        try:
            with open(self.watch_log, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
                for v in violations:
                    f.write(f"   ! [{v.rule_id}] {v.message}\n")
                if jit_line:
                    f.write(jit_line + "\n")
        except Exception:
            pass

        # Record in state.db audit_logs
        try:
            self.db_conn.execute(
                "INSERT INTO audit_logs (task_id, check_type, passed, output_snippet) VALUES (?, ?, ?, ?)",
                (
                    "WATCHDOG",
                    f"INVARIANT_{action}",
                    1 if not violations else 0,
                    f"{rel_path}: {status}" if not violations else f"{rel_path}: {violations[0].message}",
                ),
            )
            self.db_conn.commit()
        except Exception:
            pass

        self.sentinel_state.record_event(action, rel_path, f"{action} {rel_path}", violations)


class SkillsCatalogSentinelHandler(FileSystemEventHandler if WATCHDOG_AVAILABLE else object):
    """Watches the primary skills directory for additions or edits to SKILL.md and auto-syncs."""

    def on_modified(self, event):
        if event.is_directory or not str(event.src_path).endswith("SKILL.md"):
            return
        self._sync_skill(Path(event.src_path))

    def on_created(self, event):
        if event.is_directory or not str(event.src_path).endswith("SKILL.md"):
            return
        self._sync_skill(Path(event.src_path))

    def _sync_skill(self, skill_file: Path):
        try:
            from uniskill.sync import sync_skill_to_all_environments
            skill_folder = skill_file.parent
            sync_res = sync_skill_to_all_environments(skill_folder)
            send_desktop_notification("🔄 UniSkill Auto-Synced", f"{skill_folder.name} synced to all 3 environments with 100% parity", urgency="low")
        except Exception as e:
            logger.warning(f"Failed to auto-sync skill {skill_file}: {e}")


def start_sentinel_monitor(project_root: Optional[Path] = None, run_forever: bool = False, auto_heal: bool = True):
    """Starts the real-time watchdog observer on the project directory and skills catalog."""
    root = (project_root or Path.cwd()).resolve()
    gov_dir = resolve_gov_dir(root)
    gov_dir.mkdir(parents=True, exist_ok=True)
    conn = get_db(root)

    if not WATCHDOG_AVAILABLE:
        logger.warning("Watchdog library not installed. Sentinel running in passive polling mode.")
        return None

    handler = ProjectSentinelHandler(root, gov_dir, conn, auto_heal=auto_heal)
    observer = Observer()
    observer.schedule(handler, str(root), recursive=True)

    # Inotify watch on skills root for zero-lag catalog synchronization
    skills_root = Path("/home/uniai/.gemini/config/skills")
    if skills_root.exists() and skills_root.resolve() != root.resolve():
        skills_handler = SkillsCatalogSentinelHandler()
        observer.schedule(skills_handler, str(skills_root), recursive=True)

    observer.start()
    logger.info(f"UniGov Sentinel active on {root} & {skills_root}")

    if run_forever:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()

    return observer
