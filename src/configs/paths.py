"""
Cortex Data Paths

Manages data directory and database locations for Cortex storage.
Auto-detects Docker environment for appropriate path selection.
"""

import os
from pathlib import Path

DEFAULT_DATA_PATH = Path.home() / ".cortex"


def get_data_path() -> Path:
    """Get the Cortex data directory path.

    Auto-detects environment:
    - Docker: /app/cortex_data (when /app exists and is writable)
    - Host: ~/.cortex

    Returns:
        Path to the data directory
    """
    # Docker detection: if /app exists and is writable, use container path
    if os.path.exists("/app") and os.access("/app", os.W_OK):
        return Path("/app/cortex_data")
    return DEFAULT_DATA_PATH


def ensure_data_dir() -> Path:
    """Ensure ~/.cortex directory exists with default files.

    Creates:
    - ~/.cortex/ directory
    - ~/.cortex/cortexignore with sensible defaults (if not exists)

    Returns:
        Path to data directory
    """
    data_path = get_data_path()
    data_path.mkdir(parents=True, exist_ok=True)

    # Create global cortexignore with defaults if it doesn't exist
    cortexignore_path = data_path / "cortexignore"
    if not cortexignore_path.exists():
        # Lazy import to avoid circular dependency during module split
        from src.configs.ignore_patterns import GLOBAL_CORTEXIGNORE_TEMPLATE

        cortexignore_path.write_text(GLOBAL_CORTEXIGNORE_TEMPLATE)

    return data_path


def get_default_db_path() -> str:
    """Get the default database path.

    Auto-detects environment:
    - Docker: /app/cortex_db (when /app exists and is writable)
    - Host: ~/.cortex/db

    Returns:
        Database path as string
    """
    # Docker detection
    if os.path.exists("/app") and os.access("/app", os.W_OK):
        return "/app/cortex_db"
    return os.path.expanduser("~/.cortex/db")


DB_PATH = get_default_db_path()
