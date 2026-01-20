"""
Cortex Runtime Configuration

Mutable runtime defaults and configuration merging logic.
Combines defaults, YAML config, and environment variables.
"""

import os

from src.configs.constants import TIMEOUTS
from src.configs.yaml_config import load_yaml_config

# --- Default Runtime Configuration ---
# Mutable at runtime via get_full_config()

DEFAULT_CONFIG = {
    "min_score": 0.5,
    "verbose": False,
    "enabled": True,
    "top_k_retrieve": 50,
    "top_k_rerank": 5,
    "llm_provider": "none",  # Set dynamically via get_llm_provider()
    "recency_boost": True,
    "recency_half_life_days": 30.0,
    # Type-based scoring (prioritize understanding over navigation)
    "type_boost": True,
    "type_multipliers": {
        "insight": 2.0,
        "note": 1.5,
        "session_summary": 1.5,
        "entry_point": 1.4,
        "file_metadata": 1.3,
        "data_contract": 1.3,
        "dependency": 1.0,
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


def get_llm_provider() -> str:
    """
    Get the configured LLM provider.

    Priority:
    1. CORTEX_LLM_PROVIDER env var
    2. llm.primary_provider from config.yaml
    3. Default: "none"

    Returns:
        Provider name: "anthropic", "claude-cli", "ollama", "openrouter", or "none"
    """
    # Check env var first
    env_provider = os.environ.get("CORTEX_LLM_PROVIDER", "").lower()
    if env_provider in ("anthropic", "claude-cli", "ollama", "openrouter", "none"):
        return env_provider

    # Legacy env var for backward compatibility
    legacy_provider = os.environ.get("CORTEX_HEADER_PROVIDER", "").lower()
    if legacy_provider in ("anthropic", "claude-cli", "none"):
        return legacy_provider

    # Try config.yaml
    yaml_config = load_yaml_config()
    llm_config = yaml_config.get("llm", {})
    config_provider = llm_config.get("primary_provider", "").lower()
    if config_provider in ("anthropic", "claude-cli", "ollama", "openrouter", "none"):
        return config_provider

    return "none"


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

    # Set LLM provider dynamically (checks env var, then config.yaml)
    config["llm_provider"] = get_llm_provider()

    # Environment overrides
    if os.environ.get("CORTEX_MIN_SCORE"):
        try:
            config["min_score"] = float(os.environ["CORTEX_MIN_SCORE"])
        except ValueError:
            pass

    if os.environ.get("CORTEX_VERBOSE"):
        config["verbose"] = os.environ["CORTEX_VERBOSE"].lower() == "true"

    return config
