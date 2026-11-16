import os
import json
from pathlib import Path
from typing import Dict, List
import typer
from rich.console import Console
from rich.panel import Panel

console = Console()

DIMENSION_METADATA = [
    {
        "index": 1,
        "filename": "01_VISION_AND_CONSTRAINTS.md",
        "title": "Vision, Personas & Constitutional Hard Constraints",
        "layer": "LAYER_1_DOMAIN",
        "description": "Core problem statement, target personas, non-goals, and non-negotiable architectural laws.",
        "invariants": [
            {
                "id": "INV-LAW-000",
                "layer": "LAYER_1_DOMAIN",
                "title": "Constitutional Zero-Shortcut Rule",
                "rule_type": "FORBIDDEN_TOKENS",
                "file_patterns": ["**/*.kt", "**/*.ts", "**/*.py"],
                "params": {"forbidden_tokens": ["@Suppress(\"ALL\")", "@Suppress(\"UNCHECKED_CAST\")"]},
                "enforcement": "BLOCK_BUILD",
            }
        ]
    },
    {
        "index": 2,
        "filename": "02_DOMAIN_RULES_AND_FSM.md",
        "title": "Domain Rules, Financial Math & Finite State Machines",
        "layer": "LAYER_1_DOMAIN",
        "description": "Strict business logic, tax calculation invariants, integer math, and entity FSM transitions.",
        "invariants": [
            {
                "id": "INV-FIN-001",
                "layer": "LAYER_1_DOMAIN",
                "title": "Law ACC-001 Zero Float Financial Math",
                "rule_type": "FORBIDDEN_TOKENS",
                "file_patterns": ["**/billing/**", "**/ledger/**", "**/domain/inventory/**", "**/pos/**"],
                "params": {"forbidden_tokens": ["Float", "Double", "BigDecimal.toFloat", "0.18f"]},
                "enforcement": "BLOCK_BUILD",
            }
        ]
    },
    {
        "index": 3,
        "filename": "03_USER_WORKFLOWS_AND_CHAOS.md",
        "title": "User Workflows, Sad Paths & Chaos Recovery",
        "layer": "LAYER_1_DOMAIN",
        "description": "Happy user journeys mapped alongside mid-transaction app kills, rapid double-taps, and low battery.",
        "invariants": []
    },
    {
        "index": 4,
        "filename": "04_DATA_SCHEMA_AND_MIGRATIONS.md",
        "title": "Data Schema, Indexes & Zero-Downtime Migrations",
        "layer": "LAYER_2_DATA",
        "description": "Normalized SQL/Room tables, foreign keys, compound indexes, and tested schema migration plans.",
        "invariants": []
    },
    {
        "index": 5,
        "filename": "05_OFFLINE_SYNC_AND_IDEMPOTENCY.md",
        "title": "Offline Sync, Idempotency & Conflict Resolution",
        "layer": "LAYER_2_DATA",
        "description": "Client-generated UUID idempotency keys, append-only event ledgers, and background sync workers.",
        "invariants": [
            {
                "id": "INV-SYNC-001",
                "layer": "LAYER_2_DATA",
                "title": "Mandatory Client Idempotency Key",
                "rule_type": "REQUIRED_COLUMNS",
                "file_patterns": ["**/data/local/entity/**", "**/models/**"],
                "params": {"required_columns": ["idempotency_key", "sync_status"]},
                "enforcement": "BLOCK_BUILD",
            }
        ]
    },
    {
        "index": 6,
        "filename": "06_ARCHITECTURE_AND_ADRS.md",
        "title": "Clean Architecture Boundaries & ADR Ledger",
        "layer": "LAYER_2_DATA",
        "description": "Strict module boundaries (:core:domain, :core:data, :feature:*), DI graph, and Architecture Decision Records.",
        "invariants": []
    },
    {
        "index": 7,
        "filename": "07_DESIGN_SYSTEM_AND_5_STATES.md",
        "title": "Design System Tokens & 5 Mandatory UI States",
        "layer": "LAYER_3_SURFACES",
        "description": "Color/typography tokens and strict enforcement of 5 UI states: Loading, Empty, Error, Offline, Populated.",
        "invariants": [
            {
                "id": "INV-UI-001",
                "layer": "LAYER_3_SURFACES",
                "title": "Mandatory 5-State Screen Handling",
                "rule_type": "MANDATORY_UI_STATES",
                "file_patterns": ["**/ui/**/*.kt", "**/components/**/*.kt", "**/screens/**/*.tsx"],
                "params": {"required_states": ["Loading", "Empty", "Error", "Offline", "Populated"]},
                "enforcement": "WARN",
            }
        ]
    },
    {
        "index": 8,
        "filename": "08_HARDWARE_PERIPHERALS_AND_OS.md",
        "title": "Hardware Peripherals, Drivers & OS Contracts",
        "layer": "LAYER_3_SURFACES",
        "description": "CameraX scanner latency, raw ESC/POS thermal printer byte protocols, Bluetooth queues, and OS permissions.",
        "invariants": []
    },
    {
        "index": 9,
        "filename": "09_SECURITY_RBAC_AND_KEYSTORE.md",
        "title": "Security, RBAC & Android Keystore Encryption",
        "layer": "LAYER_4_SECURITY",
        "description": "AES-256 GCM Keystore keys, SQLCipher local database encryption, PII masking in logs, and role-based access.",
        "invariants": [
            {
                "id": "INV-SEC-001",
                "layer": "LAYER_4_SECURITY",
                "title": "Zero Hardcoded Secret Tokens",
                "rule_type": "FORBIDDEN_TOKENS",
                "file_patterns": ["**/*.kt", "**/*.ts", "**/*.py"],
                "params": {"forbidden_patterns": ["AIza[0-9A-Za-z-_]{35}", "ghp_[0-9A-Za-z]{36}"]},
                "enforcement": "BLOCK_BUILD",
            }
        ]
    },
    {
        "index": 10,
        "filename": "10_TEST_PYRAMID_AND_SLAS.md",
        "title": "Test Strategy, Performance Budgets & SLAs",
        "layer": "LAYER_4_SECURITY",
        "description": "Cold start SLAs (< 800ms), 60/120fps UI render budgets, Room migration tests, and E2E verification test suites.",
        "invariants": []
    },
    {
        "index": 11,
        "filename": "11_OBSERVABILITY_AND_ROLLOUT.md",
        "title": "Observability, Telemetry & Staged Rollout",
        "layer": "LAYER_4_SECURITY",
        "description": "Structured breadcrumb crash logging (zero PII leaks), local diagnostic log bundles, and staged feature rollout flags.",
        "invariants": []
    },
    {
        "index": 12,
        "filename": "12_ON_DEVICE_AI_AND_SLM_LIMITS.md",
        "title": "On-Device SLM Intelligence & Memory Ceilings",
        "layer": "LAYER_5_INTELLIGENCE",
        "description": "Quantized SLM models, maximum RAM ceiling (<= 350MB), inference latency SLAs (< 400ms), and low-battery safety switches.",
        "invariants": [
            {
                "id": "INV-AI-001",
                "layer": "LAYER_5_INTELLIGENCE",
                "title": "On-Device AI Memory & Battery Guardrail",
                "rule_type": "LATENCY_BUDGET",
                "file_patterns": ["**/cortex/**", "**/ai/**", "**/slm/**"],
                "params": {"max_ram_mb": 350, "max_latency_ms": 400},
                "enforcement": "WARN",
            }
        ]
    },
    {
        "index": 13,
        "filename": "13_TAMPER_PROOF_AUDIT_LEDGER.md",
        "title": "Cryptographic Audit Ledger & Fraud Prevention",
        "layer": "LAYER_5_INTELLIGENCE",
        "description": "Merkle-tree hash chained audit entries for every transaction, discount, or cancellation to detect employee theft.",
        "invariants": []
    },
    {
        "index": 14,
        "filename": "14_DISASTER_RECOVERY_60S_SWAP.md",
        "title": "60-Second Disaster Recovery & Hardware Swap Protocol",
        "layer": "LAYER_5_INTELLIGENCE",
        "description": "Encrypted P2P local Wi-Fi / BLE hot-standby sync, allowing instant replacement and recovery if a phone breaks.",
        "invariants": []
    },
    {
        "index": 15,
        "filename": "15_SELF_HEALING_AND_RESILIENCE.md",
        "title": "Self-Healing App Architecture & Safe Mode",
        "layer": "LAYER_5_INTELLIGENCE",
        "description": "Automatic migration rollback, corrupted transaction isolation (quarantine), and non-fatal fallback recovery.",
        "invariants": []
    }
]


def generate_scaffold_markdown(meta: dict, project_name: str) -> str:
    invariants_blocks = ""
    for inv in meta.get("invariants", []):
        invariants_blocks += f"""
<!-- UNIGOV_INVARIANT_START -->
{json.dumps(inv, indent=2)}
<!-- UNIGOV_INVARIANT_END -->
"""

    return f"""# 📑 {meta['filename']} — {meta['title']}
**Project:** {project_name}  
**Architectural Layer:** `{meta['layer']}`  
**Standard Version:** 2026 SOTA Production Specification

---

## 🎯 1. Overview & Objective
{meta['description']}

---

## 🔒 2. Architectural Invariants (Machine-Executable Contracts)
The following invariant blocks are machine-compiled and enforced by `unigov` during build and commit phases:
{invariants_blocks or "*No automated machine invariants currently active for this dimension.*"}

---

## 📝 3. Detailed Specification & Production Implementation Rules
*(Fill out specific project domain schemas, FSM state tables, or hardware pinouts below)*

### Core Invariants:
1. All changes must pass verified CI/CD gates before merging.
2. Zero shortcut implementations (Law-000).
3. Zero silent error suppression.

---
*Created automatically by UniGov v0.5.0 Scaffolder*
"""


def scaffold_documentation_suite(target_dir: Path, project_name: str = "Enterprise Mobile OS", overwrite: bool = False) -> List[Path]:
    """Generates the full 15-file architectural documentation suite."""
    target_dir.mkdir(parents=True, exist_ok=True)
    created_files = []

    for meta in DIMENSION_METADATA:
        file_path = target_dir / meta["filename"]
        if file_path.exists() and not overwrite:
            continue
        content = generate_scaffold_markdown(meta, project_name)
        file_path.write_text(content, encoding="utf-8")
        created_files.append(file_path)

    return created_files
