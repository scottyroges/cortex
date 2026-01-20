"""
Staleness Detection for Notes and Insights

Determines whether stored notes/insights may be out of date based on
file changes and time elapsed since creation/last verification.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.configs import get_logger
from src.configs.runtime import DEFAULT_CONFIG
from src.tools.ingest.walker import compute_file_hash

logger = get_logger("tools.staleness")


def _get_stale_threshold() -> int:
    """Get staleness time threshold from config."""
    return DEFAULT_CONFIG.get("staleness_time_threshold_days", 30)


def _get_very_stale_threshold() -> int:
    """Get very stale time threshold from config."""
    return DEFAULT_CONFIG.get("staleness_very_stale_threshold_days", 90)


def check_insight_staleness(
    metadata: dict[str, Any],
    repo_path: Optional[str] = None,
) -> dict[str, Any]:
    """
    Check if an insight is stale based on file changes and time.

    Args:
        metadata: The insight's metadata dict from ChromaDB
        repo_path: Path to the repository root for file hash comparison

    Returns:
        {
            "level": "fresh|possibly_stale|likely_stale|files_deleted",
            "verification_required": bool,
            "reasons": ["file X modified", ...],
            "files_changed": ["src/auth.py"],
            "files_deleted": ["src/old.py"],
            "days_since_created": int,
            "days_since_verified": int,
        }
    """
    result = {
        "level": "fresh",
        "verification_required": False,
        "reasons": [],
        "files_changed": [],
        "files_deleted": [],
        "days_since_created": 0,
        "days_since_verified": 0,
    }

    # Skip if already deprecated
    if metadata.get("status") == "deprecated":
        result["level"] = "deprecated"
        result["reasons"].append("Insight has been deprecated")
        return result

    # Calculate age
    created_at = metadata.get("created_at", "")
    verified_at = metadata.get("verified_at", created_at)

    now = datetime.now(timezone.utc)

    if created_at:
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            result["days_since_created"] = (now - created).days
        except (ValueError, TypeError):
            pass

    if verified_at:
        try:
            verified = datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
            result["days_since_verified"] = (now - verified).days
        except (ValueError, TypeError):
            pass

    # Check file-based staleness for insights with linked files
    files_json = metadata.get("files", "[]")
    try:
        linked_files = json.loads(files_json) if isinstance(files_json, str) else files_json
    except json.JSONDecodeError:
        linked_files = []

    stored_hashes_json = metadata.get("file_hashes", "{}")
    try:
        stored_hashes = json.loads(stored_hashes_json) if isinstance(stored_hashes_json, str) else stored_hashes_json
    except json.JSONDecodeError:
        stored_hashes = {}

    if linked_files and repo_path:
        for file_path in linked_files:
            full_path = Path(file_path)
            if not full_path.is_absolute():
                full_path = Path(repo_path) / file_path

            if not full_path.exists():
                result["files_deleted"].append(file_path)
                continue

            # Check if file changed (hash-based)
            if stored_hashes:
                try:
                    current_hash = compute_file_hash(full_path)
                    stored_hash = stored_hashes.get(file_path) or stored_hashes.get(str(full_path))
                    if stored_hash and current_hash != stored_hash:
                        result["files_changed"].append(file_path)
                except (OSError, IOError) as e:
                    logger.warning(f"Could not hash file {file_path}: {e}")

    # Determine staleness level based on signals
    if result["files_deleted"]:
        result["level"] = "files_deleted"
        result["reasons"].append(f"Linked file(s) deleted: {', '.join(result['files_deleted'])}")
        result["verification_required"] = True

    elif result["files_changed"]:
        result["level"] = "likely_stale"
        result["reasons"].append(f"Linked file(s) modified: {', '.join(result['files_changed'])}")
        result["verification_required"] = True

    elif result["days_since_verified"] >= _get_very_stale_threshold():
        result["level"] = "possibly_stale"
        result["reasons"].append(f"Not verified in {result['days_since_verified']} days")
        result["verification_required"] = True

    elif result["days_since_verified"] >= _get_stale_threshold():
        result["level"] = "possibly_stale"
        result["reasons"].append(f"Insight is {result['days_since_verified']} days old")
        # Advisory only for time-based staleness at lower threshold
        result["verification_required"] = False

    return result


def check_note_staleness(
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """
    Check if a general note is stale (time-based only since notes don't link to files).

    Args:
        metadata: The note's metadata dict from ChromaDB

    Returns:
        {
            "level": "fresh|possibly_stale",
            "verification_required": bool,
            "reasons": [...],
            "days_since_created": int,
            "days_since_verified": int,
        }
    """
    result = {
        "level": "fresh",
        "verification_required": False,
        "reasons": [],
        "days_since_created": 0,
        "days_since_verified": 0,
    }

    # Skip if already deprecated
    if metadata.get("status") == "deprecated":
        result["level"] = "deprecated"
        result["reasons"].append("Note has been deprecated")
        return result

    created_at = metadata.get("created_at", "")
    verified_at = metadata.get("verified_at", created_at)
    now = datetime.now(timezone.utc)

    if created_at:
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            result["days_since_created"] = (now - created).days
        except (ValueError, TypeError):
            pass

    if verified_at:
        try:
            verified = datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
            result["days_since_verified"] = (now - verified).days
        except (ValueError, TypeError):
            pass

    # Time-based staleness (use higher threshold for notes without file links)
    if result["days_since_verified"] >= _get_very_stale_threshold():
        result["level"] = "possibly_stale"
        result["reasons"].append(f"Note is {result['days_since_verified']} days old")
        result["verification_required"] = True

    return result


def format_verification_warning(
    staleness: dict[str, Any],
    metadata: dict[str, Any],
) -> str:
    """
    Format a human-readable verification warning for Claude.

    Args:
        staleness: Result from check_insight_staleness or check_note_staleness
        metadata: The document's metadata

    Returns:
        Warning message string, or empty string if no warning needed
    """
    level = staleness.get("level", "fresh")

    # Deprecated always gets a warning, even if verification_required is False
    if level == "deprecated":
        doc_type = metadata.get("type", "note")
        superseded_by = metadata.get("superseded_by", "")
        if superseded_by:
            return (
                f"DEPRECATED: This {doc_type} has been marked invalid. "
                f"See replacement: {superseded_by}"
            )
        return f"DEPRECATED: This {doc_type} has been marked invalid."

    if not staleness.get("verification_required"):
        return ""
    doc_type = metadata.get("type", "note")

    if level == "files_deleted":
        files = ", ".join(staleness.get("files_deleted", []))
        return (
            f"VERIFICATION REQUIRED - FILES DELETED: The files this {doc_type} references "
            f"({files}) no longer exist. This {doc_type} may be obsolete. "
            f"DO NOT TRUST without investigation."
        )

    if level == "likely_stale":
        files = ", ".join(staleness.get("files_changed", []))
        return (
            f"VERIFICATION REQUIRED - FILES CHANGED: This {doc_type} references files that have "
            f"been modified since it was created ({files}). "
            f"You MUST re-read these files to verify this analysis is still accurate "
            f"before using this information."
        )

    if level == "possibly_stale":
        days = staleness.get("days_since_verified", 0)
        return (
            f"POSSIBLY OUTDATED: This {doc_type} is {days} days old and has not been verified recently. "
            f"Consider validating before relying on it heavily."
        )

    return ""
