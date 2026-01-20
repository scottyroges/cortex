"""
Cortex YAML Configuration

Loading, saving, and defaults for ~/.cortex/config.yaml.
"""

from pathlib import Path

from src.configs.paths import ensure_data_dir, get_data_path

# --- Default Config Template ---

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
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
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
