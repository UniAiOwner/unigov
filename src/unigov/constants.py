import hashlib
import os
from pathlib import Path
from typing import Set

# Canonical programming language file extensions tracked by UniGov
CODE_EXTENSIONS: Set[str] = {
    ".kt", ".java", ".py", ".ts", ".tsx", ".js", ".rs", ".go", ".cpp", ".c", ".h"
}

# Standard directories universally ignored across all scanning and indexing
DEFAULT_IGNORE_DIRS: Set[str] = {
    ".git", ".unigov", ".antigravity", ".venv", "venv", "node_modules",
    "build", ".gradle", "__pycache__", "dist", ".idea", ".pytest_cache",
    ".next", "out", ".turbo", ".expo"
}


def normalize_posix_path(path: str | Path) -> str:
    """Normalizes any relative or string path into a canonical POSIX path.

    Eliminates leading './', resolves redundant segments ('..', '.'),
    and standardizes forward slashes across platforms.
    """
    if isinstance(path, Path):
        raw = path.as_posix()
    else:
        raw = str(path).replace("\\", "/")

    norm = os.path.normpath(raw).replace("\\", "/")
    if norm.startswith("./"):
        norm = norm[2:]
    elif norm == ".":
        norm = ""
    return norm


def compute_file_hash(file_path: Path) -> str:
    """Computes an 8-character cryptographic SHA-256 fingerprint of a file's content.

    Returns '00000000' if unreadable.
    """
    if not file_path.exists() or not file_path.is_file():
        return "00000000"
    try:
        hasher = hashlib.sha256()
        with file_path.open("rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()[:8]
    except Exception:
        return "00000000"


def is_code_file(file_path: Path) -> bool:
    """Checks whether a file path qualifies as a tracked source code file."""
    return file_path.suffix.lower() in CODE_EXTENSIONS
