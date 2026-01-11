"""
Admin Tools

MCP tools for configuration, status, and administration.
"""

import json
import os
from typing import Optional

from logging_config import get_logger
from src.git import get_current_branch
from src.tools.services import CONFIG, get_collection, get_repo_path

logger = get_logger("tools.admin")


def configure_cortex(
    min_score: Optional[float] = None,
    verbose: Optional[bool] = None,
    top_k_retrieve: Optional[int] = None,
    top_k_rerank: Optional[int] = None,
    header_provider: Optional[str] = None,
    recency_boost: Optional[bool] = None,
    recency_half_life_days: Optional[float] = None,
    enabled: Optional[bool] = None,
) -> str:
    """
    Configure Cortex runtime settings.

    Args:
        min_score: Minimum relevance score threshold (0.0 to 1.0)
        verbose: Enable verbose output with debug info
        top_k_retrieve: Number of candidates to retrieve before reranking
        top_k_rerank: Number of results to return after reranking
        header_provider: Provider for contextual headers: "anthropic", "claude-cli", or "none"
        recency_boost: Enable recency boosting for notes/commits (newer = higher rank)
        recency_half_life_days: Days until recency boost decays to ~0.5 (default 30)
        enabled: Enable or disable Cortex memory system (for A/B testing)

    Returns:
        JSON with updated configuration
    """
    changes = []

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

    if header_provider is not None:
        if header_provider in ("anthropic", "claude-cli", "none"):
            CONFIG["header_provider"] = header_provider
            changes.append(f"header_provider={header_provider}")
        else:
            logger.warning(f"Invalid header_provider: {header_provider}. Use 'anthropic', 'claude-cli', or 'none'")

    if recency_boost is not None:
        CONFIG["recency_boost"] = recency_boost
        changes.append(f"recency_boost={recency_boost}")

    if recency_half_life_days is not None:
        CONFIG["recency_half_life_days"] = max(1.0, min(365.0, recency_half_life_days))
        changes.append(f"recency_half_life_days={CONFIG['recency_half_life_days']}")

    if changes:
        logger.info(f"Configuration updated: {', '.join(changes)}")
    else:
        logger.debug("Configure called with no changes")

    return json.dumps({
        "status": "configured",
        "config": CONFIG,
    }, indent=2)


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
        from src.http import get_startup_time
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


def get_skeleton(
    project: Optional[str] = None,
) -> str:
    """
    Get the file tree structure for a project.

    Returns the stored skeleton (tree output) for file-path grounding.
    The skeleton is auto-generated during ingest_code_into_cortex.

    Args:
        project: Project name (required)

    Returns:
        JSON with tree structure and metadata
    """
    if not project:
        return json.dumps({
            "error": "Project name is required",
            "hint": "Provide the project name used during ingestion",
        })

    logger.info(f"Getting skeleton for project: {project}")

    try:
        collection = get_collection()
        repo_path = get_repo_path()
        branch = get_current_branch(repo_path) if repo_path else "unknown"

        # Try current branch first, then fall back to any branch
        doc_id = f"{project}:skeleton:{branch}"
        result = collection.get(ids=[doc_id], include=["documents", "metadatas"])

        if not result["documents"]:
            # Try to find skeleton for any branch
            all_results = collection.get(
                where={"$and": [{"type": "skeleton"}, {"project": project}]},
                include=["documents", "metadatas"],
            )
            if all_results["documents"]:
                result = {
                    "documents": [all_results["documents"][0]],
                    "metadatas": [all_results["metadatas"][0]],
                }

        if not result["documents"]:
            return json.dumps({
                "error": f"No skeleton found for project '{project}'",
                "hint": "Run ingest_code_into_cortex first to generate the skeleton",
            })

        metadata = result["metadatas"][0]
        tree = result["documents"][0]

        logger.info(f"Skeleton found: {metadata.get('total_files', 0)} files, {metadata.get('total_dirs', 0)} dirs")

        return json.dumps({
            "project": project,
            "branch": metadata.get("branch", "unknown"),
            "generated_at": metadata.get("generated_at", "unknown"),
            "total_files": metadata.get("total_files", 0),
            "total_dirs": metadata.get("total_dirs", 0),
            "tree": tree,
        }, indent=2)

    except Exception as e:
        logger.error(f"Get skeleton error: {e}")
        return json.dumps({"error": str(e)})
