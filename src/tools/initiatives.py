"""
Initiative Management Tools

MCP tools for managing multi-session initiatives (epics, migrations, features).
Initiatives track work across sessions and tag commits/notes for context restoration.
"""

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from logging_config import get_logger
from src.git import get_current_branch
from src.tools.services import get_collection, get_repo_path, get_searcher

logger = get_logger("tools.initiatives")

# Completion signal keywords
COMPLETION_SIGNALS = [
    "complete", "completed", "done", "finished", "final",
    "shipped", "merged", "released", "wrapped up", "closes",
]

# Default stale threshold in days
STALE_THRESHOLD_DAYS = 5


def create_initiative(
    repository: str,
    name: str,
    goal: str = "",
    auto_focus: bool = True,
) -> str:
    """
    Create a new initiative for a repository.

    Initiatives track multi-session work like epics, migrations, or features.
    New commits and notes are tagged with the focused initiative.

    Args:
        repository: Repository identifier (e.g., "Cortex", "my-app")
        name: Initiative name (e.g., "Auth Migration", "Performance Optimization")
        goal: Optional goal/description for the initiative
        auto_focus: Whether to focus this initiative on creation (default: True)

    Returns:
        JSON with created initiative details
    """
    if not repository:
        return json.dumps({"error": "Repository name is required"})

    if not name:
        return json.dumps({"error": "Initiative name is required"})

    logger.info(f"Creating initiative '{name}' for repository: {repository}")

    try:
        collection = get_collection()
        repo_path = get_repo_path()
        branch = get_current_branch(repo_path) if repo_path else "unknown"
        timestamp = datetime.now(timezone.utc).isoformat()

        # Generate unique ID
        initiative_id = f"initiative:{uuid.uuid4().hex[:8]}"

        # Build document content
        doc_content = name
        if goal:
            doc_content += f"\n\nGoal: {goal}"

        # Save initiative
        collection.upsert(
            ids=[initiative_id],
            documents=[doc_content],
            metadatas=[{
                "type": "initiative",
                "repository": repository,
                "name": name,
                "goal": goal or "",
                "status": "active",
                "completion_summary": "",
                "branch": branch,
                "created_at": timestamp,
                "updated_at": timestamp,
                "completed_at": "",
            }],
        )

        logger.info(f"Initiative created: {initiative_id}")

        # Auto-focus if requested
        focus_result = None
        if auto_focus:
            focus_result = _set_focus(collection, repository, initiative_id, name, timestamp)

        # Rebuild search index
        get_searcher().build_index()

        response = {
            "status": "created",
            "initiative_id": initiative_id,
            "name": name,
            "goal": goal,
            "repository": repository,
        }

        if focus_result:
            response["focused"] = True

        return json.dumps(response, indent=2)

    except Exception as e:
        logger.error(f"Create initiative error: {e}")
        return json.dumps({"status": "error", "error": str(e)})


def list_initiatives(
    repository: str,
    status: str = "all",
) -> str:
    """
    List all initiatives for a repository.

    Args:
        repository: Repository identifier
        status: Filter by status - "all", "active", or "completed"

    Returns:
        JSON with list of initiatives and current focus
    """
    if not repository:
        return json.dumps({"error": "Repository name is required"})

    logger.info(f"Listing initiatives for repository: {repository}, status={status}")

    try:
        collection = get_collection()

        # Build filter
        where_filter = {
            "$and": [
                {"type": "initiative"},
                {"repository": repository},
            ]
        }

        if status == "active":
            where_filter["$and"].append({"status": "active"})
        elif status == "completed":
            where_filter["$and"].append({"status": "completed"})

        # Query initiatives
        results = collection.get(
            where=where_filter,
            include=["documents", "metadatas"],
        )

        # Get current focus
        focus = _get_focus(collection, repository)

        # Get commit/note counts for each initiative
        initiatives = []
        for i, doc_id in enumerate(results.get("ids", [])):
            meta = results["metadatas"][i] if results.get("metadatas") else {}

            # Count commits/notes for this initiative
            commit_count, note_count = _count_initiative_items(collection, doc_id)

            initiatives.append({
                "id": doc_id,
                "name": meta.get("name", ""),
                "goal": meta.get("goal", ""),
                "status": meta.get("status", "active"),
                "created_at": meta.get("created_at", ""),
                "updated_at": meta.get("updated_at", ""),
                "completed_at": meta.get("completed_at", ""),
                "commit_count": commit_count,
                "note_count": note_count,
            })

        # Sort by updated_at descending
        initiatives.sort(key=lambda x: x.get("updated_at", ""), reverse=True)

        response = {
            "repository": repository,
            "focused": focus,
            "initiatives": initiatives,
            "total": len(initiatives),
        }

        return json.dumps(response, indent=2)

    except Exception as e:
        logger.error(f"List initiatives error: {e}")
        return json.dumps({"status": "error", "error": str(e)})


def focus_initiative(
    repository: str,
    initiative: str,
) -> str:
    """
    Set focus to an initiative. New commits/notes will be tagged with this initiative.

    Args:
        repository: Repository identifier
        initiative: Initiative ID or name

    Returns:
        JSON with focused initiative details and recent context
    """
    if not repository:
        return json.dumps({"error": "Repository name is required"})

    if not initiative:
        return json.dumps({"error": "Initiative ID or name is required"})

    logger.info(f"Focusing initiative '{initiative}' for repository: {repository}")

    try:
        collection = get_collection()
        timestamp = datetime.now(timezone.utc).isoformat()

        # Find the initiative
        init_data = _find_initiative(collection, repository, initiative)
        if not init_data:
            return json.dumps({
                "error": f"Initiative '{initiative}' not found in repository '{repository}'",
            })

        initiative_id = init_data["id"]
        meta = init_data["metadata"]

        # Check if completed
        if meta.get("status") == "completed":
            return json.dumps({
                "error": f"Cannot focus completed initiative '{meta.get('name')}'",
                "hint": "Create a new initiative or reopen this one",
            })

        # Set focus
        _set_focus(collection, repository, initiative_id, meta.get("name", ""), timestamp)

        # Get recent context (commits/notes from this initiative)
        recent_context = _get_recent_context(collection, initiative_id, limit=5)

        response = {
            "status": "focused",
            "initiative_id": initiative_id,
            "name": meta.get("name", ""),
            "goal": meta.get("goal", ""),
            "repository": repository,
            "recent_context": recent_context,
        }

        return json.dumps(response, indent=2)

    except Exception as e:
        logger.error(f"Focus initiative error: {e}")
        return json.dumps({"status": "error", "error": str(e)})


def complete_initiative(
    initiative: str,
    summary: str,
    repository: Optional[str] = None,
) -> str:
    """
    Mark an initiative as completed with a summary.

    Args:
        initiative: Initiative ID or name
        summary: Completion summary (required)
        repository: Repository identifier (optional if initiative ID is provided)

    Returns:
        JSON with completion status and archive summary
    """
    if not initiative:
        return json.dumps({"error": "Initiative ID or name is required"})

    if not summary:
        return json.dumps({"error": "Completion summary is required"})

    logger.info(f"Completing initiative: {initiative}")

    try:
        collection = get_collection()
        timestamp = datetime.now(timezone.utc).isoformat()

        # Find the initiative
        init_data = _find_initiative(collection, repository, initiative)
        if not init_data:
            return json.dumps({
                "error": f"Initiative '{initiative}' not found",
            })

        initiative_id = init_data["id"]
        meta = init_data["metadata"]
        repo = meta.get("repository", repository)

        # Check if already completed
        if meta.get("status") == "completed":
            return json.dumps({
                "error": f"Initiative '{meta.get('name')}' is already completed",
            })

        # Update initiative status
        doc_content = f"{meta.get('name', '')}\n\nGoal: {meta.get('goal', '')}\n\nCompletion Summary: {summary}"

        collection.upsert(
            ids=[initiative_id],
            documents=[doc_content],
            metadatas=[{
                **meta,
                "status": "completed",
                "completion_summary": summary,
                "updated_at": timestamp,
                "completed_at": timestamp,
            }],
        )

        # Clear focus if this was focused
        focus = _get_focus(collection, repo)
        if focus and focus.get("initiative_id") == initiative_id:
            _clear_focus(collection, repo)

        # Get archive stats
        commit_count, note_count = _count_initiative_items(collection, initiative_id)

        # Calculate duration
        created_at = meta.get("created_at", "")
        duration = _calculate_duration(created_at, timestamp)

        # Rebuild search index
        get_searcher().build_index()

        response = {
            "status": "completed",
            "initiative_id": initiative_id,
            "name": meta.get("name", ""),
            "repository": repo,
            "summary": summary,
            "archive": {
                "commit_count": commit_count,
                "note_count": note_count,
                "duration": duration,
            },
        }

        return json.dumps(response, indent=2)

    except Exception as e:
        logger.error(f"Complete initiative error: {e}")
        return json.dumps({"status": "error", "error": str(e)})


# --- Helper Functions ---


def _set_focus(
    collection,
    repository: str,
    initiative_id: str,
    initiative_name: str,
    timestamp: str,
) -> dict:
    """Set focus to an initiative."""
    focus_id = f"{repository}:focus"
    collection.upsert(
        ids=[focus_id],
        documents=[f"Current focus: {initiative_name}"],
        metadatas=[{
            "type": "focus",
            "repository": repository,
            "initiative_id": initiative_id,
            "initiative_name": initiative_name,
            "updated_at": timestamp,
        }],
    )
    return {"initiative_id": initiative_id, "initiative_name": initiative_name}


def _get_focus(collection, repository: str) -> Optional[dict]:
    """Get current focus for a repository."""
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


def _clear_focus(collection, repository: str) -> None:
    """Clear focus for a repository."""
    try:
        focus_id = f"{repository}:focus"
        collection.delete(ids=[focus_id])
    except Exception as e:
        logger.warning(f"Failed to clear focus: {e}")


def _find_initiative(
    collection,
    repository: Optional[str],
    initiative: str,
) -> Optional[dict]:
    """Find an initiative by ID or name."""
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


def _count_initiative_items(collection, initiative_id: str) -> tuple[int, int]:
    """Count commits and notes for an initiative."""
    commit_count = 0
    note_count = 0

    try:
        # Count commits
        commit_result = collection.get(
            where={"$and": [{"type": "commit"}, {"initiative_id": initiative_id}]},
        )
        commit_count = len(commit_result.get("ids", []))

        # Count notes
        note_result = collection.get(
            where={"$and": [{"type": "note"}, {"initiative_id": initiative_id}]},
        )
        note_count = len(note_result.get("ids", []))

    except Exception as e:
        logger.warning(f"Failed to count initiative items: {e}")

    return commit_count, note_count


def _get_recent_context(collection, initiative_id: str, limit: int = 5) -> list:
    """Get recent commits/notes for an initiative."""
    context = []

    try:
        # Get commits and notes for this initiative
        result = collection.get(
            where={
                "$and": [
                    {"initiative_id": initiative_id},
                    {"type": {"$in": ["commit", "note"]}},
                ]
            },
            include=["documents", "metadatas"],
        )

        for i, doc_id in enumerate(result.get("ids", [])):
            meta = result["metadatas"][i] if result.get("metadatas") else {}
            doc = result["documents"][i] if result.get("documents") else ""

            context.append({
                "id": doc_id,
                "type": meta.get("type", ""),
                "created_at": meta.get("created_at", ""),
                "preview": doc[:200] + "..." if len(doc) > 200 else doc,
            })

        # Sort by created_at descending and limit
        context.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        context = context[:limit]

    except Exception as e:
        logger.warning(f"Failed to get recent context: {e}")

    return context


def _calculate_duration(created_at: str, completed_at: str) -> str:
    """Calculate human-readable duration between timestamps."""
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        delta = completed - created

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


def get_focused_initiative(repository: str) -> Optional[dict]:
    """
    Get the currently focused initiative for a repository.

    This is a utility function for other tools (commit, note) to use.

    Args:
        repository: Repository identifier

    Returns:
        Dict with initiative_id and initiative_name, or None
    """
    try:
        collection = get_collection()
        return _get_focus(collection, repository)
    except Exception as e:
        logger.warning(f"Failed to get focused initiative: {e}")
        return None


def detect_completion_signals(text: str) -> bool:
    """
    Detect if text contains completion signals.

    Args:
        text: Text to check (e.g., commit summary)

    Returns:
        True if completion signals detected
    """
    text_lower = text.lower()
    for signal in COMPLETION_SIGNALS:
        # Match word boundaries
        if re.search(rf"\b{re.escape(signal)}\b", text_lower):
            return True
    return False


def check_initiative_staleness(
    updated_at: str,
    threshold_days: int = STALE_THRESHOLD_DAYS,
) -> tuple[bool, int]:
    """
    Check if an initiative is stale (inactive for too long).

    Args:
        updated_at: Last update timestamp (ISO format)
        threshold_days: Number of days before considered stale

    Returns:
        Tuple of (is_stale, days_inactive)
    """
    try:
        updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - updated
        days_inactive = delta.days

        return (days_inactive >= threshold_days, days_inactive)
    except Exception:
        return (False, 0)
