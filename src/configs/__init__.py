"""
Cortex Configuration Module

Re-exports commonly used functions for cleaner imports across the codebase.
"""

# Logging (most commonly used)
from src.configs.logging import get_logger, setup_logging

# Paths
from src.configs.paths import get_data_path, ensure_data_dir, DB_PATH

# Constants
from src.configs.constants import (
    BINARY_EXTENSIONS,
    MAX_FILE_SIZE,
    TIMEOUTS,
    get_timeout,
)

# Ignore patterns
from src.configs.ignore_patterns import (
    DEFAULT_IGNORE_PATTERNS,
    GLOBAL_CORTEXIGNORE_TEMPLATE,
    load_ignore_patterns,
)

# YAML config
from src.configs.yaml_config import (
    DEFAULT_CONFIG_YAML,
    get_config_path,
    load_yaml_config,
    save_yaml_config,
    create_default_config,
)

# Runtime (lazy-loaded to avoid circular imports with services)
from src.configs.runtime import (
    DEFAULT_CONFIG,
    get_llm_provider,
    get_full_config,
)

# Note: services.py is NOT imported here to avoid circular imports.
# Services should be imported directly: from src.configs.services import ...

__all__ = [
    # Logging
    "get_logger",
    "setup_logging",
    # Paths
    "get_data_path",
    "ensure_data_dir",
    "DB_PATH",
    # Constants
    "BINARY_EXTENSIONS",
    "MAX_FILE_SIZE",
    "TIMEOUTS",
    "get_timeout",
    # Ignore patterns
    "DEFAULT_IGNORE_PATTERNS",
    "GLOBAL_CORTEXIGNORE_TEMPLATE",
    "load_ignore_patterns",
    # YAML config
    "DEFAULT_CONFIG_YAML",
    "get_config_path",
    "load_yaml_config",
    "save_yaml_config",
    "create_default_config",
    # Runtime
    "DEFAULT_CONFIG",
    "get_llm_provider",
    "get_full_config",
]
