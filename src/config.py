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
        cortexignore_path.write_text(GLOBAL_CORTEXIGNORE_TEMPLATE)

    return data_path


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

# Template for global ~/.cortex/cortexignore (created on first use)
GLOBAL_CORTEXIGNORE_TEMPLATE = """\
# Cortex global ignore patterns
# These apply to all projects. Edit as needed.

# Large data files
*.csv
*.parquet
*.pkl
*.h5
*.hdf5

# ML/AI artifacts
*.pt
*.pth
*.onnx
*.safetensors
checkpoints/
wandb/
mlruns/

# Logs and databases
*.log
*.sqlite
*.db

# OS files
.DS_Store
Thumbs.db

# Archives
*.zip
*.tar
*.tar.gz
*.tgz

# Lock files
package-lock.json
yarn.lock
pnpm-lock.yaml
poetry.lock
Cargo.lock
Gemfile.lock
"""


def _load_ignore_file(path: Path) -> set[str]:
    """Load patterns from an ignore file (like .gitignore format)."""
    if not path.exists():
        return set()
    patterns = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.add(line)
    return patterns


def load_ignore_patterns(root_path: str, use_cortexignore: bool = True) -> set[str]:
    """Load and merge ignore patterns from global + project cortexignore files.

    Merge order (all patterns combined):
    1. DEFAULT_IGNORE_PATTERNS (hardcoded sensible defaults)
    2. Global ~/.cortex/cortexignore (user's smart defaults)
    3. Project <root>/.cortexignore (project-specific)

    Args:
        root_path: Root path of the project being indexed
        use_cortexignore: If False, only return DEFAULT_IGNORE_PATTERNS

    Returns:
        Set of ignore patterns to use for filtering
    """
    patterns = set(DEFAULT_IGNORE_PATTERNS)

    if not use_cortexignore:
        return patterns

    # Global: ~/.cortex/cortexignore (created with defaults if not exists)
    global_ignore = ensure_data_dir() / "cortexignore"
    patterns.update(_load_ignore_file(global_ignore))

    # Project: <root>/.cortexignore
    project_ignore = Path(root_path) / ".cortexignore"
    patterns.update(_load_ignore_file(project_ignore))

    return patterns


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
    # Staleness detection
    "staleness_check_enabled": True,
    "staleness_check_limit": 10,  # Only check top N results for staleness
    "staleness_time_threshold_days": 30,
    "staleness_very_stale_threshold_days": 90,
}
