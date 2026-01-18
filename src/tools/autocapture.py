"""
Auto-Capture MCP Tools

Tools for checking status and configuring the auto-capture system.
"""

from typing import Optional

from src.config import (
    load_yaml_config,
    save_yaml_config,
    get_config_path,
    get_data_path,
    create_default_config,
)
from src.install import get_hook_status
from src.llm import get_available_providers

from logging_config import get_logger

logger = get_logger("tools.autocapture")


def get_autocapture_status() -> str:
    """
    Get status of the auto-capture system.

    Returns configuration, hook installation status, LLM provider availability,
    and recent capture statistics.

    Returns:
        JSON status report
    """
    import json
    from pathlib import Path

    result = {
        "status": "ok",
        "config": {},
        "hooks": {},
        "llm_providers": {},
        "statistics": {},
    }

    # Load configuration
    try:
        config = load_yaml_config()
        result["config"] = {
            "autocapture_enabled": config.get("autocapture", {}).get("enabled", True),
            "significance_thresholds": config.get("autocapture", {}).get("significance", {}),
            "llm_primary_provider": config.get("llm", {}).get("primary_provider", "claude-cli"),
            "config_path": str(get_config_path()),
            "config_exists": get_config_path().exists(),
        }
    except Exception as e:
        result["config"]["error"] = str(e)

    # Check hook installation
    try:
        hook_status = get_hook_status()
        result["hooks"] = {
            "claude_code_installed": hook_status.claude_code_installed,
            "claude_code_available": hook_status.claude_code_available,
            "hook_script_exists": hook_status.hook_script_exists,
            "details": hook_status.details,
        }
        if hook_status.errors:
            result["hooks"]["errors"] = hook_status.errors
    except Exception as e:
        result["hooks"]["error"] = str(e)

    # Check LLM providers
    try:
        available = get_available_providers(config)
        result["llm_providers"] = {
            "available": available,
            "configured_primary": config.get("llm", {}).get("primary_provider", "claude-cli"),
        }
    except Exception as e:
        result["llm_providers"]["error"] = str(e)

    # Get capture statistics
    try:
        cortex_data = get_data_path()
        captured_file = cortex_data / "captured_sessions.json"
        hook_log = cortex_data / "hook.log"

        stats = {
            "captured_sessions_count": 0,
            "last_hook_logs": [],
        }

        if captured_file.exists():
            data = json.loads(captured_file.read_text())
            stats["captured_sessions_count"] = len(data.get("captured", []))

        if hook_log.exists():
            lines = hook_log.read_text().strip().split("\n")
            stats["last_hook_logs"] = lines[-5:] if lines else []

        result["statistics"] = stats
    except Exception as e:
        result["statistics"]["error"] = str(e)

    return json.dumps(result, indent=2)


def configure_autocapture(
    enabled: Optional[bool] = None,
    llm_provider: Optional[str] = None,
    min_tokens: Optional[int] = None,
    min_file_edits: Optional[int] = None,
    min_tool_calls: Optional[int] = None,
) -> str:
    """
    Configure auto-capture settings.

    Changes are persisted to ~/.cortex/config.yaml.

    Args:
        enabled: Enable or disable auto-capture
        llm_provider: Primary LLM provider (anthropic, ollama, openrouter, claude-cli)
        min_tokens: Minimum token threshold for significant sessions
        min_file_edits: Minimum file edit threshold
        min_tool_calls: Minimum tool call threshold

    Returns:
        JSON response with updated configuration
    """
    import json

    # Create default config if it doesn't exist
    create_default_config()

    # Load existing config
    config = load_yaml_config()

    # Ensure sections exist
    if "autocapture" not in config:
        config["autocapture"] = {}
    if "significance" not in config["autocapture"]:
        config["autocapture"]["significance"] = {}
    if "llm" not in config:
        config["llm"] = {}

    changes = []

    # Apply changes
    if enabled is not None:
        config["autocapture"]["enabled"] = enabled
        changes.append(f"enabled={enabled}")

    if llm_provider is not None:
        valid_providers = ["anthropic", "ollama", "openrouter", "claude-cli"]
        if llm_provider not in valid_providers:
            return json.dumps({
                "status": "error",
                "error": f"Invalid provider. Must be one of: {valid_providers}",
            })
        config["llm"]["primary_provider"] = llm_provider
        changes.append(f"llm_provider={llm_provider}")

    if min_tokens is not None:
        config["autocapture"]["significance"]["min_tokens"] = min_tokens
        changes.append(f"min_tokens={min_tokens}")

    if min_file_edits is not None:
        config["autocapture"]["significance"]["min_file_edits"] = min_file_edits
        changes.append(f"min_file_edits={min_file_edits}")

    if min_tool_calls is not None:
        config["autocapture"]["significance"]["min_tool_calls"] = min_tool_calls
        changes.append(f"min_tool_calls={min_tool_calls}")

    # Save if changes were made
    if changes:
        if save_yaml_config(config):
            return json.dumps({
                "status": "success",
                "changes": changes,
                "config_path": str(get_config_path()),
            })
        else:
            return json.dumps({
                "status": "error",
                "error": "Failed to save configuration. PyYAML may not be installed.",
            })

    return json.dumps({
        "status": "no_changes",
        "message": "No configuration changes specified",
    })
