"""
Backward-compatibility alias shim: antigravity_pm -> unigov
Officially renamed to UniGov by Founder Shoeb Ahmad.
"""
import sys
import unigov
from unigov import *

# Register aliases in sys.modules so imports like `from antigravity_pm import db` resolve to `unigov.db`
for attr in (
    "db", "cli", "executor", "ingest", "models", "reconciler", "reviewer",
    "scaffolder", "invariants", "baseline", "introspect", "auditor", "drift",
    "ecosystem", "llm", "telemetry", "tui", "worktree", "context_bundler", "tia", "mcp", "blueprint", "stress", "migration_guard", "adr"
):
    try:
        mod = getattr(unigov, attr, None)
        if mod is None:
            import importlib
            mod = importlib.import_module(f"unigov.{attr}")
        sys.modules[f"antigravity_pm.{attr}"] = mod
    except Exception:
        pass
