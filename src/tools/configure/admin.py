"""
Admin Tools

MCP tools for configuration, status, and administration.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from src.configs import get_logger
from src.external.git import get_current_branch
from src.utils.secret_scrubber import scrub_secrets
from src.configs.services import CONFIG, get_collection, get_repo_path, get_searcher

logger = get_logger("tools.admin")


def configure_cortex(
    # Runtime config
    min_score: Optional[float] = None,
    verbose: Optional[bool] = None,
    top_k_retrieve: Optional[int] = None,
    top_k_rerank: Optional[int] = None,
    llm_provider: Optional[str] = None,
    recency_boost: Optional[bool] = None,
    recency_half_life_days: Optional[float] = None,
    enabled: Optional[bool] = None,
    # Repo context (absorbs set_repo_context)
    repository: Optional[str] = None,
    tech_stack: Optional[str] = None,
    # Autocapture config (absorbs configure_autocapture)
    autocapture_enabled: Optional[bool] = None,
    autocapture_llm_provider: Optional[str] = None,
    autocapture_min_tokens: Optional[int] = None,
    autocapture_min_tool_calls: Optional[int] = None,
    autocapture_min_file_edits: Optional[int] = None,
    autocapture_async: Optional[bool] = None,
    # Status query (absorbs get_autocapture_status)
    get_status: bool = False,
) -> str:
    """
    Configure Cortex runtime settings, repository context, and autocapture.

    **When to use this tool:**
    - Setting up a new repository? Provide repository + tech_stack
    - Adjusting search sensitivity? Use min_score
    - Configuring autocapture? Use autocapture_* parameters
    - Checking system status? Use get_status=True

    Args:
        min_score: Minimum relevance score threshold (0.0 to 1.0)
        verbose: Enable verbose output with debug info
        top_k_retrieve: Number of candidates to retrieve before reranking
        top_k_rerank: Number of results to return after reranking
        llm_provider: LLM provider: "anthropic", "claude-cli", "ollama", "openrouter", or "none"
        recency_boost: Enable recency boosting for notes/commits
        recency_half_life_days: Days until recency boost decays to ~0.5
        enabled: Enable or disable Cortex memory system
        repository: Repository to set tech stack for (requires tech_stack)
        tech_stack: Technologies, patterns, architecture description
        autocapture_enabled: Enable or disable auto-capture
        autocapture_llm_provider: LLM provider for autocapture summarization
        autocapture_min_tokens: Minimum token threshold for significant sessions
        autocapture_min_tool_calls: Minimum tool call threshold
        autocapture_min_file_edits: Minimum file edit threshold
        autocapture_async: Run autocapture async (default: True)
        get_status: If True, return full system status including autocapture

    Returns:
        JSON with updated configuration or system status
    """
    # Handle status query
    if get_status:
        return _get_full_status()

    changes = []

    # Runtime config changes
    if enabled is not None:
        CONFIG["enabled"] = enabled
        changes.append(f"enabled={enabled}")
    if min_score is not None:
        CONFIG["min_score"] = max(0.0, min(1.0, min_score))
        changes.append(f"min_score={CONFIG['min_score']}")

    if verbose is not None:
        CONFIG["verbose"] = verbose
        changes.append(f"verbose={verbose}")

    if top_k_retrieve is not None:
        CONFIG["top_k_retrieve"] = max(10, min(200, top_k_retrieve))
        changes.append(f"top_k_retrieve={CONFIG['top_k_retrieve']}")

    if top_k_rerank is not None:
        CONFIG["top_k_rerank"] = max(1, min(50, top_k_rerank))
        changes.append(f"top_k_rerank={CONFIG['top_k_rerank']}")

    if llm_provider is not None:
        if llm_provider in ("anthropic", "claude-cli", "ollama", "openrouter", "none"):
            CONFIG["llm_provider"] = llm_provider
            changes.append(f"llm_provider={llm_provider}")
        else:
            logger.warning(f"Invalid llm_provider: {llm_provider}")

    if recency_boost is not None:
        CONFIG["recency_boost"] = recency_boost
        changes.append(f"recency_boost={recency_boost}")

    if recency_half_life_days is not None:
        CONFIG["recency_half_life_days"] = max(1.0, min(365.0, recency_half_life_days))
        changes.append(f"recency_half_life_days={CONFIG['recency_half_life_days']}")

    # Handle tech stack setting
    if repository and tech_stack:
        result = _set_tech_stack(repository, tech_stack)
        if "error" not in result:
            changes.append(f"tech_stack for {repository}")

    # Handle autocapture configuration
    autocapture_changes = _configure_autocapture(
        enabled=autocapture_enabled,
        llm_provider=autocapture_llm_provider,
        min_tokens=autocapture_min_tokens,
        min_tool_calls=autocapture_min_tool_calls,
        min_file_edits=autocapture_min_file_edits,
        async_mode=autocapture_async,
    )
    if autocapture_changes:
        changes.extend(autocapture_changes)

    if changes:
        logger.info(f"Configuration updated: {', '.join(changes)}")
    else:
        logger.debug("Configure called with no changes")

    return json.dumps({
        "status": "configured",
        "changes": changes,
        "config": CONFIG,
    }, indent=2)


def _set_tech_stack(repository: str, tech_stack: str) -> dict:
    """Set tech stack for a repository."""
    try:
        collection = get_collection()
        repo_path = get_repo_path()
        branch = get_current_branch(repo_path) if repo_path else "unknown"
        timestamp = datetime.now(timezone.utc).isoformat()

        tech_stack_id = f"{repository}:tech_stack"
        collection.upsert(
            ids=[tech_stack_id],
            documents=[scrub_secrets(tech_stack)],
            metadatas=[{
                "type": "tech_stack",
                "repository": repository,
                "branch": branch,
                "created_at": timestamp,
                "updated_at": timestamp,
            }],
        )
        get_searcher().build_index()
        logger.info(f"Tech stack saved for repository '{repository}'")
        return {"status": "saved", "tech_stack_id": tech_stack_id}
    except Exception as e:
        logger.error(f"Set tech stack error: {e}")
        return {"error": str(e)}


def _configure_autocapture(
    enabled: Optional[bool] = None,
    llm_provider: Optional[str] = None,
    min_tokens: Optional[int] = None,
    min_tool_calls: Optional[int] = None,
    min_file_edits: Optional[int] = None,
    async_mode: Optional[bool] = None,
) -> list[str]:
    """Configure autocapture settings and return list of changes."""
    try:
        from src.configs.yaml_config import load_yaml_config, save_yaml_config, create_default_config
    except ImportError:
        return []

    # Skip if no autocapture params provided
    if all(p is None for p in [enabled, llm_provider, min_tokens, min_tool_calls, min_file_edits, async_mode]):
        return []

    try:
        create_default_config()
        config = load_yaml_config()

        if "autocapture" not in config:
            config["autocapture"] = {}
        if "significance" not in config["autocapture"]:
            config["autocapture"]["significance"] = {}
        if "llm" not in config:
            config["llm"] = {}

        changes = []

        if enabled is not None:
            config["autocapture"]["enabled"] = enabled
            changes.append(f"autocapture_enabled={enabled}")

        if llm_provider is not None:
            valid_providers = ["anthropic", "ollama", "openrouter", "claude-cli"]
            if llm_provider in valid_providers:
                config["llm"]["primary_provider"] = llm_provider
                changes.append(f"autocapture_llm_provider={llm_provider}")

        if async_mode is not None:
            config["autocapture"]["auto_commit_async"] = async_mode
            changes.append(f"autocapture_async={async_mode}")

        if min_tokens is not None:
            config["autocapture"]["significance"]["min_tokens"] = min_tokens
            changes.append(f"autocapture_min_tokens={min_tokens}")

        if min_file_edits is not None:
            config["autocapture"]["significance"]["min_file_edits"] = min_file_edits
            changes.append(f"autocapture_min_file_edits={min_file_edits}")

        if min_tool_calls is not None:
            config["autocapture"]["significance"]["min_tool_calls"] = min_tool_calls
            changes.append(f"autocapture_min_tool_calls={min_tool_calls}")

        if changes:
            save_yaml_config(config)

        return changes
    except Exception as e:
        logger.warning(f"Failed to configure autocapture: {e}")
        return []


def _get_full_status() -> str:
    """Get full system status including autocapture."""
    result = {
        "status": "ok",
        "runtime_config": CONFIG,
        "autocapture": {},
        "version": {},
    }

    # Get version info
    result["version"] = {
        "git_commit": os.environ.get("CORTEX_GIT_COMMIT", "unknown"),
        "build_time": os.environ.get("CORTEX_BUILD_TIME", "unknown"),
    }

    # Get autocapture status
    try:
        from src.configs.yaml_config import load_yaml_config, get_config_path
        from src.configs.paths import get_data_path
        from src.integrations.hooks import get_hook_status
        from src.external.llm import get_available_providers

        config = load_yaml_config()
        autocapture_config = config.get("autocapture", {})

        result["autocapture"]["config"] = {
            "enabled": autocapture_config.get("enabled", True),
            "auto_commit_async": autocapture_config.get("auto_commit_async", True),
            "significance_thresholds": autocapture_config.get("significance", {}),
            "llm_provider": config.get("llm", {}).get("primary_provider", "claude-cli"),
        }

        # Hook status
        try:
            hook_status = get_hook_status()
            result["autocapture"]["hooks"] = {
                "claude_code_installed": hook_status.claude_code_installed,
                "hook_script_exists": hook_status.hook_script_exists,
            }
        except Exception as e:
            result["autocapture"]["hooks"] = {"error": str(e)}

        # LLM providers
        try:
            available = get_available_providers(config)
            result["autocapture"]["llm_providers"] = available
        except Exception as e:
            result["autocapture"]["llm_providers"] = {"error": str(e)}

    except Exception as e:
        result["autocapture"]["error"] = str(e)

    return json.dumps(result, indent=2)


def get_cortex_version(expected_commit: Optional[str] = None) -> str:
    """
    Get Cortex daemon build and version information.

    Returns git commit, build time, and startup time to verify the daemon
    is running the expected code version. Pass expected_commit to check if
    a rebuild is needed.

    Args:
        expected_commit: The git commit hash to compare against (e.g., local HEAD).
                        If provided, returns needs_rebuild indicating if daemon is outdated.

    Returns:
        JSON with version info and whether daemon matches local code
    """
    git_commit = os.environ.get("CORTEX_GIT_COMMIT", "unknown")
    build_time = os.environ.get("CORTEX_BUILD_TIME", "unknown")

    # Get startup time from http module
    try:
        from src.controllers.http import get_startup_time
        startup_time = get_startup_time()
    except ImportError:
        startup_time = "unknown"

    result = {
        "git_commit": git_commit,
        "build_time": build_time,
        "startup_time": startup_time,
        "version": "1.0.0",
    }

    # Compare against expected commit if provided
    if expected_commit:
        result["expected_commit"] = expected_commit
        daemon_short = git_commit[:7] if len(git_commit) >= 7 else git_commit
        expected_short = expected_commit[:7] if len(expected_commit) >= 7 else expected_commit
        result["needs_rebuild"] = daemon_short != expected_short
        if result["needs_rebuild"]:
            result["message"] = f"Daemon is outdated. Run 'cortex daemon rebuild' to update from {daemon_short} to {expected_short}."
        else:
            result["message"] = "Daemon is up to date."

    return json.dumps(result, indent=2)
