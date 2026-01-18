"""
Initiative Utilities

Shared helper functions for initiative management across tools.
Consolidates duplicated logic from initiatives.py, notes.py, and recall.py.
"""

from datetime import datetime, timezone
from typing import Optional

from logging_config import get_logger

logger = get_logger("tools.initiative_utils")


def find_initiative(
    collection,
    repository: Optional[str],
    initiative: str,
) -> Optional[dict]:
    """
    Find an initiative by ID or name.

    Args:
        collection: ChromaDB collection
        repository: Optional repository filter
        initiative: Initiative ID (e.g., "initiative:abc123") or name

    Returns:
        Dict with id, document, and metadata if found, else None
    """
    # Try direct ID lookup first
    if initiative.startswith("initiative:"):
        result = collection.get(
            ids=[initiative],
            include=["documents", "metadatas"],
        )
        if result["ids"]:
            return {
                "id": result["ids"][0],
                "document": result["documents"][0],
                "metadata": result["metadatas"][0],
            }

    # Search by name
    where_filter = {"$and": [{"type": "initiative"}, {"name": initiative}]}
    if repository:
        where_filter["$and"].append({"repository": repository})

    result = collection.get(
        where=where_filter,
        include=["documents", "metadatas"],
    )

    if result["ids"]:
        return {
            "id": result["ids"][0],
            "document": result["documents"][0],
            "metadata": result["metadatas"][0],
        }

    return None


def resolve_initiative(
    collection,
    repository: str,
    initiative: Optional[str],
    get_focused_fn: callable,
) -> tuple[Optional[str], Optional[str]]:
    """
    Resolve initiative parameter to (initiative_id, initiative_name).

    Handles three cases:
    1. Explicit initiative ID provided (starts with "initiative:")
    2. Explicit initiative name provided (look up by name)
    3. No initiative provided (use focused initiative)

    Args:
        collection: ChromaDB collection
        repository: Repository identifier
        initiative: Initiative ID, name, or None
        get_focused_fn: Function to get focused initiative info, returns (id, name) tuple

    Returns:
        Tuple of (initiative_id, initiative_name), both may be None
    """
    if initiative:
        # Explicit initiative specified
        if initiative.startswith("initiative:"):
            initiative_id = initiative
            init_data = find_initiative(collection, repository, initiative)
            initiative_name = init_data["metadata"].get("name", "") if init_data else ""
            return initiative_id, initiative_name
        else:
            # Assume it's a name, look up the ID
            init_data = find_initiative(collection, repository, initiative)
            if init_data:
                return init_data["id"], init_data["metadata"].get("name", "")
            return None, None
    else:
        # Use focused initiative
        return get_focused_fn(repository)


def calculate_duration(start_timestamp: str, end_timestamp: str) -> str:
    """
    Calculate human-readable duration between two timestamps.

    Args:
        start_timestamp: ISO format start timestamp
        end_timestamp: ISO format end timestamp

    Returns:
        Human-readable duration string (e.g., "3 days", "2 weeks")
    """
    try:
        start = datetime.fromisoformat(start_timestamp.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_timestamp.replace("Z", "+00:00"))
        delta = end - start

        days = delta.days
        if days == 0:
            hours = delta.seconds // 3600
            if hours == 0:
                return "less than 1 hour"
            return f"{hours} hour{'s' if hours != 1 else ''}"
        elif days == 1:
            return "1 day"
        elif days < 7:
            return f"{days} days"
        elif days < 30:
            weeks = days // 7
            return f"{weeks} week{'s' if weeks != 1 else ''}"
        else:
            months = days // 30
            return f"{months} month{'s' if months != 1 else ''}"
    except Exception:
        return "unknown"


def calculate_duration_from_now(start_timestamp: str) -> str:
    """
    Calculate human-readable duration from a timestamp to now.

    Args:
        start_timestamp: ISO format start timestamp

    Returns:
        Human-readable duration string
    """
    return calculate_duration(start_timestamp, datetime.now(timezone.utc).isoformat())
