"""
Initiative Focus Management

Handles the "focused initiative" state for repositories.
The focused initiative is used to auto-tag new notes and session summaries.
"""

from datetime import datetime, timezone
from typing import Optional

from src.configs import get_logger
from src.configs.services import get_collection

logger = get_logger("tools.initiatives.focus")


def set_focus(
    collection,
    repository: str,
    initiative_id: str,
    initiative_name: str,
    timestamp: Optional[str] = None,
) -> dict:
    """
    Set focus to an initiative.

    Args:
        collection: ChromaDB collection
        repository: Repository identifier
        initiative_id: Initiative ID to focus
        initiative_name: Initiative name for display
        timestamp: Optional timestamp (defaults to now)

    Returns:
        Dict with initiative_id and initiative_name
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()

    focus_id = f"{repository}:focus"
    collection.upsert(
        ids=[focus_id],
        documents=[f"Current focus: {initiative_name}"],
        metadatas=[{
            "type": "focus",
            "repository": repository,
            "initiative_id": initiative_id,
            "initiative_name": initiative_name,
            "created_at": timestamp,
            "updated_at": timestamp,
        }],
    )
    return {"initiative_id": initiative_id, "initiative_name": initiative_name}


def get_focus(collection, repository: str) -> Optional[dict]:
    """
    Get current focus for a repository.

    Args:
        collection: ChromaDB collection
        repository: Repository identifier

    Returns:
        Dict with initiative_id and initiative_name, or None if no focus
    """
    try:
        focus_id = f"{repository}:focus"
        result = collection.get(
            ids=[focus_id],
            include=["metadatas"],
        )
        if result["ids"]:
            meta = result["metadatas"][0]
            return {
                "initiative_id": meta.get("initiative_id", ""),
                "initiative_name": meta.get("initiative_name", ""),
            }
    except Exception as e:
        logger.warning(f"Failed to get focus: {e}")
    return None


def get_focus_id(collection, repository: str) -> Optional[str]:
    """
    Get just the focused initiative ID for a repository.

    Lightweight version of get_focus() when you only need the ID.

    Args:
        collection: ChromaDB collection
        repository: Repository identifier

    Returns:
        Initiative ID or None
    """
    try:
        focus_id = f"{repository}:focus"
        result = collection.get(ids=[focus_id], include=["metadatas"])
        if result["ids"]:
            return result["metadatas"][0].get("initiative_id")
    except Exception as e:
        logger.warning(f"Failed to get focused initiative ID: {e}")
    return None


def clear_focus(collection, repository: str) -> None:
    """
    Clear focus for a repository.

    Args:
        collection: ChromaDB collection
        repository: Repository identifier
    """
    try:
        focus_id = f"{repository}:focus"
        collection.delete(ids=[focus_id])
    except Exception as e:
        logger.warning(f"Failed to clear focus: {e}")


def get_focused_initiative(repository: str) -> Optional[dict]:
    """
    Get the currently focused initiative for a repository.

    This is the public API for other tools (notes, memory) to use.
    Handles collection access internally.

    Args:
        repository: Repository identifier

    Returns:
        Dict with initiative_id and initiative_name, or None
    """
    try:
        collection = get_collection()
        return get_focus(collection, repository)
    except Exception as e:
        logger.warning(f"Failed to get focused initiative: {e}")
        return None


def get_focused_initiative_info(repository: str) -> tuple[Optional[str], Optional[str]]:
    """
    Get focused initiative ID and name as a tuple.

    Convenience function that returns (initiative_id, initiative_name).
    Used by resolve_initiative when no explicit initiative is provided.

    Args:
        repository: Repository identifier

    Returns:
        Tuple of (initiative_id, initiative_name), both may be None
    """
    focus = get_focused_initiative(repository)
    if focus:
        return focus.get("initiative_id"), focus.get("initiative_name")
    return None, None


def get_any_focused_repository() -> Optional[str]:
    """
    Get repository name from any focused initiative.

    Used for auto-detecting repository when none is specified and
    the current working directory is not a git repo.

    Returns:
        Repository name from any focus document, or None
    """
    try:
        collection = get_collection()
        focus_results = collection.get(
            where={"type": "focus"},
            include=["metadatas"],
            limit=1,
        )
        if focus_results["ids"] and focus_results["metadatas"]:
            repo = focus_results["metadatas"][0].get("repository")
            if repo:
                logger.debug(f"Auto-detected repository from focused initiative: {repo}")
                return repo
    except Exception as e:
        logger.debug(f"Failed to get repository from focused initiative: {e}")
    return None
