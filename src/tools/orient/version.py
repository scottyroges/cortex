"""
Version Management

Handles version checking, comparison, and update detection.
"""

import os
import re
import time
from typing import Optional

from src import __version__
from src.configs import get_logger
from src.utils.http_client import http_json_get

logger = get_logger("version")

# Cache for version check results (TTL: 1 hour)
_version_cache: dict = {}
_CACHE_TTL_SECONDS = 3600

# GHCR image for update checking
GHCR_IMAGE = "ghcr.io/scottyroges/cortex"


def get_current_version() -> dict:
    """
    Get current daemon version info.

    Returns:
        Dict with git_commit, build_time, version
    """
    return {
        "git_commit": os.environ.get("CORTEX_GIT_COMMIT", "unknown"),
        "build_time": os.environ.get("CORTEX_BUILD_TIME", "unknown"),
        "version": __version__,
    }


def check_for_updates(local_head: Optional[str] = None) -> dict:
    """
    Check if updates are available.

    Strategy:
    1. Check GHCR for latest Docker image version
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

    # Try GHCR check first
    ghcr_result = _check_ghcr_latest()
    if ghcr_result:
        result.update(ghcr_result)
        result["check_method"] = "ghcr"
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


def _check_ghcr_latest() -> Optional[dict]:
    """
    Check GHCR for the latest available Docker image version.

    Uses GitHub's container registry API to list package versions.

    Returns:
        Dict with update info, or None if check fails
    """
    # GitHub packages API endpoint for container versions
    # Format: /users/{owner}/packages/container/{package}/versions
    url = "https://api.github.com/users/scottyroges/packages/container/cortex/versions"

    try:
        data = http_json_get(
            url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "Cortex",
            },
            timeout=5,
        )

        if not data or not isinstance(data, list):
            return None

        # Find the latest semver tag (exclude 'latest', 'sha-*', etc.)
        semver_pattern = re.compile(r"^\d+\.\d+\.\d+$")
        latest_version = None

        for version in data:
            tags = version.get("metadata", {}).get("container", {}).get("tags", [])
            for tag in tags:
                if semver_pattern.match(tag):
                    if latest_version is None or _compare_versions(tag, latest_version) > 0:
                        latest_version = tag

        if not latest_version:
            return None

        current = get_current_version()
        current_version = current["version"]

        if _compare_versions(latest_version, current_version) > 0:
            return {
                "update_available": True,
                "latest_version": latest_version,
                "message": f"New version available: {latest_version} (current: {current_version}). Run 'cortex update' to update.",
            }

        return {
            "update_available": False,
            "latest_version": latest_version,
        }

    except Exception as e:
        logger.debug(f"GHCR version check failed: {e}")
        return None


def _compare_versions(v1: str, v2: str) -> int:
    """
    Compare two semver version strings.

    Returns:
        1 if v1 > v2, -1 if v1 < v2, 0 if equal
    """
    try:
        parts1 = [int(x) for x in v1.split(".")]
        parts2 = [int(x) for x in v2.split(".")]

        for p1, p2 in zip(parts1, parts2):
            if p1 > p2:
                return 1
            if p1 < p2:
                return -1

        # Handle different lengths (e.g., 1.0 vs 1.0.0)
        if len(parts1) > len(parts2):
            return 1
        if len(parts1) < len(parts2):
            return -1

        return 0
    except (ValueError, AttributeError):
        return 0


def clear_version_cache() -> None:
    """Clear the version check cache."""
    global _version_cache
    _version_cache = {}
