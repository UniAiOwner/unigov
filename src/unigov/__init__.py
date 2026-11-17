"""UniGov Sovereign Autonomous Project Governance Engine & Deterministic State Machine."""

try:
    from importlib.metadata import version
    __version__ = version("unigov")
except Exception:
    __version__ = "0.7.0"
