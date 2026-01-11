"""
Cortex State Management

Handles loading and saving ingestion state for delta sync.
"""

import json
import os
import shutil
import tempfile
from typing import Any, Optional

from src.config import STATE_FILE


def load_state(state_file: Optional[str] = None) -> dict[str, Any]:
    """
    Load the ingestion state (file hashes) from disk.

    Args:
        state_file: Path to state file (defaults to STATE_FILE)

    Returns:
        State dictionary with file_hashes, indexed_commit, etc.
    """
    path = state_file or STATE_FILE
    if os.path.exists(path):
        with open(path, "r") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    return {}


def save_state(state: dict[str, Any], state_file: Optional[str] = None) -> None:
    """
    Save the ingestion state to disk atomically.

    Uses atomic write (write to temp file, then rename) to prevent corruption.

    Args:
        state: State dictionary to save
        state_file: Path to state file (defaults to STATE_FILE)
    """
    path = state_file or STATE_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Atomic write: write to temp file, then rename
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        shutil.move(tmp_path, path)  # Atomic on POSIX
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def migrate_state(raw_state: dict[str, Any]) -> dict[str, Any]:
    """
    Migrate old state format to new format if needed.

    Old format: {"path1": "hash1", "path2": "hash2"}
    New format: {"indexed_commit": "...", "indexed_at": "...", "file_hashes": {...}}

    Args:
        raw_state: Raw state dictionary from disk

    Returns:
        State in new format
    """
    if not raw_state:
        return {
            "file_hashes": {},
            "indexed_commit": None,
            "indexed_at": None,
        }

    # Check if already in new format
    if "indexed_commit" in raw_state or "file_hashes" in raw_state:
        return raw_state

    # Old format - migrate
    return {
        "file_hashes": raw_state,
        "indexed_commit": None,
        "indexed_at": None,
    }
