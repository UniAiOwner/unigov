# 🏛️ UniGov v0.8.0 Sovereign Upgrade Specification

## Vision & Objective
Elevate UniGov into a fully autonomous, zero-shortcut project governance operating system with:
1. **Adversarial Invariant Breaker** (`unigov stress-test`)
2. **Zero-Downtime Migration Gatekeeper** (`unigov audit-migration`)
3. **Locked-Test Self-Healing Cage** (`unigov fix --strict`)
4. **Reverse ADR Auto-Synthesis** (`unigov adr --from-git`)
5. **GitHub Actions Sovereign Gate** (`unigov init-ci`)

---

## 5-Layer Topological WBS Plan

### Layer 4 / Security & Verification
- **`M1-STRESS-01`**: Adversarial Invariant Breaker Engine
  - Module: `src/unigov/stress.py`
  - Command: `unigov stress-test <task_id>`
  - Generates evil edge-case unit tests from domain invariants to catch bugs before deployment.

- **`M3-HEAL-01`**: Write-Locked Test Cage for Self-Healing
  - Module: `src/unigov/executor.py`
  - Enforces write-lock on test files during self-healing loops to prevent AI test adulteration.

### Layer 2 / Data & Schema Integrity
- **`M2-MIG-01`**: Zero-Downtime Migration Gatekeeper
  - Module: `src/unigov/migration_guard.py`
  - Command: `unigov audit-migration <file_or_version>`
  - Audits Room/SQL migrations for missing DEFAULT on NOT NULL, dropped columns, and float conversions.

### Layer 5 / Intelligence & Continuous Telemetry
- **`M4-ADR-01`**: Reverse ADR Auto-Synthesis
  - Module: `src/unigov/cli.py`
  - Command: `unigov adr --from-git`
  - Reverse-engineers immutable ADRs directly from staged git diffs.

- **`M4-CI-01`**: GitHub Actions Sovereign Gate Generator
  - Module: `src/unigov/cli.py`
  - Command: `unigov init-ci`
  - Emits `.github/workflows/unigov-gate.yml` for pull-request drift, secret, and invariant verification.
