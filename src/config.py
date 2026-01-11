"""
Cortex Configuration

Central configuration for constants, patterns, and defaults.
"""

import os
from pathlib import Path

# --- Data Paths ---

DEFAULT_DATA_PATH = Path.home() / ".cortex"


def get_data_path() -> Path:
    """Get the Cortex data directory path."""
    data_path = os.environ.get("CORTEX_DATA_PATH")
    if data_path:
        return Path(data_path).expanduser()
    return DEFAULT_DATA_PATH


def get_default_db_path() -> str:
    """Get the default database path, expanding ~ to home directory."""
    env_path = os.environ.get("CORTEX_DB_PATH")
    if env_path:
        return os.path.expanduser(env_path)
    # Default: ~/.cortex/db (or /app/cortex_db in Docker)
    if os.path.exists("/app") and os.access("/app", os.W_OK):
        return "/app/cortex_db"
    return os.path.expanduser("~/.cortex/db")


DB_PATH = get_default_db_path()


def get_default_state_file() -> str:
    """Get the default state file path."""
    env_path = os.environ.get("CORTEX_STATE_FILE")
    if env_path:
        return os.path.expanduser(env_path)
    return os.path.join(DB_PATH, "ingest_state.json")


STATE_FILE = get_default_state_file()

# --- Ignore Patterns ---

DEFAULT_IGNORE_PATTERNS = {
    # Version control
    ".git",
    ".svn",
    ".hg",
    # Dependencies
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    # Build outputs
    "dist",
    "build",
    "out",
    ".next",
    ".nuxt",
    "target",
    # IDE
    ".idea",
    ".vscode",
    # Misc
    ".cache",
    "coverage",
    ".coverage",
    ".tox",
    ".eggs",
    "*.egg-info",
}

# --- Binary Extensions ---

BINARY_EXTENSIONS = {
    ".exe",
    ".bin",
    ".so",
    ".dylib",
    ".dll",
    ".o",
    ".a",
    ".lib",
    # Images
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".svg",
    ".webp",
    # Media
    ".mp3",
    ".mp4",
    ".wav",
    ".avi",
    ".mov",
    ".webm",
    # Archives
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".7z",
    ".rar",
    # Documents
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    # Fonts
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".eot",
    # Databases
    ".db",
    ".sqlite",
    ".sqlite3",
}

# --- File Size Limits ---

MAX_FILE_SIZE = 1_000_000  # 1MB max file size

# --- Runtime Configuration ---


def get_default_header_provider() -> str:
    """Get header provider from env var or default to 'none'."""
    provider = os.environ.get("CORTEX_HEADER_PROVIDER", "none").lower()
    if provider in ("anthropic", "claude-cli", "none"):
        return provider
    return "none"


# Default runtime config (mutable at runtime)
DEFAULT_CONFIG = {
    "min_score": 0.5,
    "verbose": False,
    "enabled": True,
    "top_k_retrieve": 50,
    "top_k_rerank": 5,
    "header_provider": get_default_header_provider(),
    "recency_boost": True,
    "recency_half_life_days": 30.0,
}
