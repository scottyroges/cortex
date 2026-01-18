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


def get_timeout(key: str, default: int | float | None = None) -> int | float:
    """
    Get a timeout value by key.

    Args:
        key: Timeout key from TIMEOUTS dict
        default: Default value if key not found

    Returns:
        Timeout value in seconds (or milliseconds for hook_execution_ms)
    """
    if default is None:
        default = TIMEOUTS.get("http_default", 10)
    return TIMEOUTS.get(key, default)


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


# --- Timeout Configuration ---
# Centralized timeout values (in seconds unless noted)

TIMEOUTS = {
    # Git operations
    "git_command": 10,         # Default git command timeout
    "git_diff": 30,            # Git diff for large repos
    # HTTP requests
    "http_default": 10,        # Default HTTP request timeout
    "http_health_check": 5,    # Health check endpoints
    "http_llm_request": 120,   # LLM API requests (can be slow)
    # LLM providers
    "llm_availability_check": 5,   # Provider availability check
    # Ingest operations
    "ingest_headers": 30,      # Header provider timeout
    "ingest_skeleton": 10,     # Skeleton generation
    # Summarization
    "summarize_session": 60,   # Session summarization
    # Hook execution (milliseconds)
    "hook_execution_ms": 15000,  # Claude Code hook timeout
}

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
    # Type-based scoring (prioritize understanding over code)
    "type_boost": True,
    "type_multipliers": {
        "insight": 2.0,
        "note": 1.5,
        "commit": 1.5,
        "code": 1.0,
        "skeleton": 1.0,
        "tech_stack": 1.2,
        "initiative": 1.0,
    },
    # Staleness detection
    "staleness_check_enabled": True,
    "staleness_check_limit": 10,  # Only check top N results for staleness
    "staleness_time_threshold_days": 30,
    "staleness_very_stale_threshold_days": 90,
    # Timeouts (can be overridden)
    "timeouts": TIMEOUTS,
}


# --- YAML Configuration ---

# Default config.yaml template
DEFAULT_CONFIG_YAML = """\
# Cortex Configuration
# Edit this file to customize Cortex behavior.

# Daemon Settings
# Directories containing code to index (mounted into Docker)
code_paths:
  # - ~/Projects
  # - ~/Work

# Daemon port for MCP communication
daemon_port: 8000

# HTTP debug server port (for CLI search, web browser, and auto-capture)
http_port: 8080

# Enable debug logging
debug: false

# LLM Provider Configuration
# Used for session summarization and code header generation
llm:
  # Primary provider: anthropic, ollama, openrouter, claude-cli
  primary_provider: "claude-cli"

  # Fallback chain (tried in order if primary fails)
  fallback_chain:
    - "anthropic"
    - "ollama"

  # Provider-specific settings
  anthropic:
    model: "claude-3-haiku-20240307"
    # API key read from ANTHROPIC_API_KEY env var

  ollama:
    model: "llama3.2"
    base_url: "http://localhost:11434"

  openrouter:
    model: "anthropic/claude-3-haiku"
    # API key read from OPENROUTER_API_KEY env var

  claude_cli:
    model: "haiku"

# Auto-Capture Configuration
autocapture:
  # Enable auto-capture on session end
  enabled: true

  # Async mode (default): hook exits fast, daemon processes in background
  # Sync mode: hook waits for LLM summary + commit to complete (10-30s delay)
  auto_commit_async: true

  # Timeout for sync mode in seconds (how long hook waits before fallback)
  sync_timeout: 60

  # Significance thresholds (session is significant if ANY threshold is met)
  significance:
    min_tokens: 5000         # Minimum token count
    min_file_edits: 1        # Minimum files edited
    min_tool_calls: 3        # Minimum tool calls

# Runtime Settings
runtime:
  min_score: 0.5
  verbose: false
  recency_boost: true
  recency_half_life_days: 30.0
"""


def get_config_path() -> Path:
    """Get the path to config.yaml."""
    return get_data_path() / "config.yaml"


def load_yaml_config() -> dict:
    """
    Load configuration from ~/.cortex/config.yaml.

    Returns:
        Configuration dictionary (empty if file doesn't exist)
    """
    config_path = get_config_path()
    if not config_path.exists():
        return {}

    try:
        import yaml
        content = config_path.read_text()
        return yaml.safe_load(content) or {}
    except ImportError:
        # PyYAML not installed - try simple parsing for basic cases
        return _parse_simple_yaml(config_path.read_text())
    except Exception:
        return {}


def _parse_simple_yaml(content: str) -> dict:
    """
    Simple YAML parser for basic key-value pairs.
    Fallback when PyYAML is not available.
    """
    result: dict = {}
    current_section = result

    for line in content.split("\n"):
        line = line.rstrip()

        # Skip comments and empty lines
        if not line or line.strip().startswith("#"):
            continue

        # Check indentation level
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        # Top-level key
        if indent == 0 and ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value:
                # Simple value
                result[key] = _parse_yaml_value(value)
            else:
                # Section header
                result[key] = {}
                current_section = result[key]

        # Nested key (simple one-level nesting)
        elif indent > 0 and ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value:
                current_section[key] = _parse_yaml_value(value)

    return result


def _parse_yaml_value(value: str):
    """Parse a simple YAML value."""
    value = value.strip()

    # Remove quotes
    if (value.startswith('"') and value.endswith('"')) or \
       (value.startswith("'") and value.endswith("'")):
        return value[1:-1]

    # Boolean
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False

    # Number
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        pass

    return value


def save_yaml_config(config: dict) -> bool:
    """
    Save configuration to ~/.cortex/config.yaml.

    Args:
        config: Configuration dictionary to save

    Returns:
        True if successful
    """
    config_path = get_config_path()
    ensure_data_dir()

    try:
        import yaml
        content = yaml.safe_dump(config, default_flow_style=False, sort_keys=False)
        config_path.write_text(content)
        return True
    except ImportError:
        # Can't save without PyYAML
        return False
    except Exception:
        return False


def create_default_config() -> bool:
    """
    Create default config.yaml if it doesn't exist.

    Returns:
        True if file was created, False if it already exists
    """
    config_path = get_config_path()
    if config_path.exists():
        return False

    ensure_data_dir()
    config_path.write_text(DEFAULT_CONFIG_YAML)
    return True


def get_full_config() -> dict:
    """
    Get full configuration merged from defaults, YAML, and environment.

    Priority (highest wins):
    1. Environment variables
    2. YAML config file
    3. DEFAULT_CONFIG

    Returns:
        Merged configuration dictionary
    """
    # Start with defaults
    config = dict(DEFAULT_CONFIG)

    # Merge YAML config
    yaml_config = load_yaml_config()

    # Merge runtime section from YAML
    if "runtime" in yaml_config:
        for key, value in yaml_config["runtime"].items():
            if key in config:
                config[key] = value

    # Add full YAML config for access to llm, autocapture sections
    config["_yaml"] = yaml_config

    # Environment overrides
    if os.environ.get("CORTEX_MIN_SCORE"):
        try:
            config["min_score"] = float(os.environ["CORTEX_MIN_SCORE"])
        except ValueError:
            pass

    if os.environ.get("CORTEX_VERBOSE"):
        config["verbose"] = os.environ["CORTEX_VERBOSE"].lower() == "true"

    return config
