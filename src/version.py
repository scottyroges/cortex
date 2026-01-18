"""
Version Management

Handles version checking, comparison, and update detection.
"""

import os
import time
import urllib.request
import json
from typing import Optional

from logging_config import get_logger

logger = get_logger("version")

# Cache for version check results (TTL: 1 hour)
_version_cache: dict = {}
_CACHE_TTL_SECONDS = 3600

# GitHub repository for release checking (set to None to disable)
GITHUB_REPO: Optional[str] = None  # e.g., "anthropics/cortex"


def get_current_version() -> dict:
    """
    Get current daemon version info.

    Returns:
        Dict with git_commit, build_time, version
    """
    return {
        "git_commit": os.environ.get("CORTEX_GIT_COMMIT", "unknown"),
        "build_time": os.environ.get("CORTEX_BUILD_TIME", "unknown"),
        "version": "1.1.0",
    }


def check_for_updates(local_head: Optional[str] = None) -> dict:
    """
    Check if updates are available.

    Strategy:
    1. Try GitHub releases API (if GITHUB_REPO is configured)
    2. Fall back to comparing daemon commit with local git HEAD

    Args:
        local_head: Local git HEAD commit (for fallback comparison)

    Returns:
        Dict with update_available, current_version, latest_version, etc.
    """
    # Check cache
    cache_key = f"update_check_{local_head or 'none'}"
    if cache_key in _version_cache:
        cached_time, cached_result = _version_cache[cache_key]
        if time.time() - cached_time < _CACHE_TTL_SECONDS:
            return cached_result

    current = get_current_version()
    result = {
        "update_available": False,
        "current_version": current["version"],
        "current_commit": current["git_commit"],
        "latest_version": current["version"],
        "latest_commit": current["git_commit"],
        "check_method": "none",
        "message": None,
    }

    # Try GitHub API first (if configured)
    if GITHUB_REPO:
        github_result = _check_github_releases()
        if github_result:
            result.update(github_result)
            result["check_method"] = "github_releases"
            _version_cache[cache_key] = (time.time(), result)
            return result

    # Fall back to local HEAD comparison
    if local_head:
        daemon_commit = current["git_commit"]
        daemon_short = daemon_commit[:7] if len(daemon_commit) >= 7 else daemon_commit
        local_short = local_head[:7] if len(local_head) >= 7 else local_head

        if daemon_short != "unknown" and daemon_short != local_short:
            result["update_available"] = True
            result["latest_commit"] = local_head
            result["check_method"] = "local_head"
            result["message"] = f"Local code ({local_short}) differs from daemon ({daemon_short}). Run 'cortex update' to update."

    # Cache result
    _version_cache[cache_key] = (time.time(), result)

    return result


def _check_github_releases() -> Optional[dict]:
    """
    Check GitHub releases API for newer versions.

    Returns:
        Dict with update info, or None if check fails
    """
    if not GITHUB_REPO:
        return None

    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

    try:
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "Cortex"},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read())
            latest_tag = data.get("tag_name", "")
            current = get_current_version()

            # Simple version comparison (assumes semver tags like "v1.0.0")
            latest_version = latest_tag.lstrip("v")
            current_version = current["version"]

            if latest_version and latest_version != current_version:
                return {
                    "update_available": True,
                    "latest_version": latest_version,
                    "message": f"New version available: {latest_version} (current: {current_version}). Run 'cortex update' to update.",
                }
            return {
                "update_available": False,
                "latest_version": latest_version or current_version,
            }
    except Exception as e:
        logger.debug(f"GitHub releases check failed: {e}")
        return None


def clear_version_cache() -> None:
    """Clear the version check cache."""
    global _version_cache
    _version_cache = {}
