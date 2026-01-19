"""
Initiative Management Tools

MCP tools for managing multi-session initiatives (epics, migrations, features).
Initiatives track work across sessions and tag commits/notes for context restoration.
"""

import json
import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from logging_config import get_logger
from src.git import get_current_branch
from src.tools.initiative_utils import calculate_duration, calculate_duration_from_now, find_initiative
from src.tools.services import get_collection, get_repo_path, get_searcher

logger = get_logger("tools.initiatives")

# Completion signal keywords
COMPLETION_SIGNALS = [
    "complete", "completed", "done", "finished", "final",
    "shipped", "merged", "released", "wrapped up", "closes",
]

# Default stale threshold in days
STALE_THRESHOLD_DAYS = 5


def manage_initiative(
    action: Literal["create", "list", "focus", "complete", "summarize"],
    repository: str,
    name: Optional[str] = None,
    initiative: Optional[str] = None,
    goal: Optional[str] = None,
    auto_focus: bool = True,
    summary: Optional[str] = None,
    status: Literal["all", "active", "completed"] = "all",
) -> str:
    """
    Manage multi-session initiatives (epics, migrations, features).

    **When to use this tool:**
    - Starting a new multi-session project? action="create"
    - Need to see what initiatives exist? action="list"
    - Switching focus to different work? action="focus"
    - Finished an initiative? action="complete"
    - Want a progress summary? action="summarize"

    Args:
        action: Operation to perform ("create", "list", "focus", "complete", "summarize")
        repository: Repository identifier (required for all actions)
        name: Initiative name (required for "create")
        initiative: Initiative ID or name (required for "focus", "complete", "summarize")
        goal: Optional goal description (for "create")
        auto_focus: Auto-focus after create (default: True)
        summary: Completion summary (required for "complete")
        status: Filter for "list" - "all", "active", or "completed"

    Returns:
        JSON with action result
    """
    if not repository:
        return json.dumps({"error": "Repository name is required"})

    if action == "create":
        if not name:
            return json.dumps({"error": "Initiative name is required for create action"})
        return _create_initiative(repository, name, goal or "", auto_focus)

    elif action == "list":
        return _list_initiatives(repository, status)

    elif action == "focus":
        if not initiative:
            return json.dumps({"error": "Initiative ID or name is required for focus action"})
        return _focus_initiative(repository, initiative)

    elif action == "complete":
        if not initiative:
            return json.dumps({"error": "Initiative ID or name is required for complete action"})
        if not summary:
            return json.dumps({"error": "Completion summary is required for complete action"})
        return _complete_initiative(initiative, summary, repository)

    elif action == "summarize":
        if not initiative:
            return json.dumps({"error": "Initiative ID or name is required for summarize action"})
        return _summarize_initiative(initiative, repository)

    else:
        return json.dumps({"error": f"Unknown action: {action}. Valid actions: create, list, focus, complete, summarize"})


def _create_initiative(
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


def _list_initiatives(
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

            # Count session summaries/notes for this initiative
            session_count, note_count = _count_initiative_items(collection, doc_id)

            initiatives.append({
                "id": doc_id,
                "name": meta.get("name", ""),
                "goal": meta.get("goal", ""),
                "status": meta.get("status", "active"),
                "created_at": meta.get("created_at", ""),
                "updated_at": meta.get("updated_at", ""),
                "completed_at": meta.get("completed_at", ""),
                "session_count": session_count,
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


def _focus_initiative(
    repository: str,
    initiative: str,
) -> str:
    """
    Set focus to an initiative. New session summaries/notes will be tagged with this initiative.

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
        init_data = find_initiative(collection, repository, initiative)
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


def _complete_initiative(
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
        init_data = find_initiative(collection, repository, initiative)
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
        session_count, note_count = _count_initiative_items(collection, initiative_id)

        # Calculate duration
        created_at = meta.get("created_at", "")
        duration = calculate_duration(created_at, timestamp)

        # Rebuild search index
        get_searcher().build_index()

        response = {
            "status": "completed",
            "initiative_id": initiative_id,
            "name": meta.get("name", ""),
            "repository": repo,
            "summary": summary,
            "archive": {
                "session_count": session_count,
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
            "created_at": timestamp,
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


# Backwards compatibility alias
_find_initiative = find_initiative


def _count_initiative_items(collection, initiative_id: str) -> tuple[int, int]:
    """Count session summaries and notes for an initiative."""
    session_count = 0
    note_count = 0

    try:
        # Count session summaries
        session_result = collection.get(
            where={"$and": [{"type": "session_summary"}, {"initiative_id": initiative_id}]},
        )
        session_count = len(session_result.get("ids", []))

        # Count notes
        note_result = collection.get(
            where={"$and": [{"type": "note"}, {"initiative_id": initiative_id}]},
        )
        note_count = len(note_result.get("ids", []))

    except Exception as e:
        logger.warning(f"Failed to count initiative items: {e}")

    return session_count, note_count


def _get_recent_context(collection, initiative_id: str, limit: int = 5) -> list:
    """Get recent session summaries/notes for an initiative."""
    context = []

    try:
        # Get session summaries and notes for this initiative
        result = collection.get(
            where={
                "$and": [
                    {"initiative_id": initiative_id},
                    {"type": {"$in": ["session_summary", "note"]}},
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


# Backwards compatibility alias
_calculate_duration = calculate_duration


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


def _summarize_initiative(
    initiative: str,
    repository: Optional[str] = None,
) -> str:
    """
    Generate a narrative summary of an initiative's progress.

    Gathers all session summaries and notes tagged with the initiative and synthesizes
    a timeline with key decisions, problems solved, and current state.

    Args:
        initiative: Initiative ID or name
        repository: Repository identifier (optional if using initiative ID)

    Returns:
        JSON with initiative summary including timeline, stats, and narrative
    """
    if not initiative:
        return json.dumps({"error": "Initiative ID or name is required"})

    logger.info(f"Summarizing initiative: {initiative}")

    try:
        collection = get_collection()

        # Find the initiative
        init_data = find_initiative(collection, repository, initiative)
        if not init_data:
            return json.dumps({
                "error": f"Initiative '{initiative}' not found",
            })

        initiative_id = init_data["id"]
        init_meta = init_data["metadata"]
        repo = init_meta.get("repository", repository)

        # Get all session summaries and notes for this initiative
        results = collection.get(
            where={
                "$and": [
                    {"initiative_id": initiative_id},
                    {"type": {"$in": ["session_summary", "note"]}},
                ]
            },
            include=["documents", "metadatas"],
        )

        # Build items list
        items = []
        for i, doc_id in enumerate(results.get("ids", [])):
            meta = results["metadatas"][i] if results.get("metadatas") else {}
            doc = results["documents"][i] if results.get("documents") else ""

            created_at = meta.get("created_at", "")

            items.append({
                "id": doc_id,
                "type": meta.get("type", ""),
                "created_at": created_at,
                "title": meta.get("title", ""),
                "files": json.loads(meta.get("files", "[]")) if meta.get("files") else [],
                "content": doc,
            })

        # Sort chronologically
        items.sort(key=lambda x: x.get("created_at", ""))

        # Build timeline with phases
        timeline = []
        all_files = set()
        session_count = 0
        note_count = 0

        for item in items:
            if item["type"] == "session_summary":
                session_count += 1
                all_files.update(item.get("files", []))
            else:
                note_count += 1

            # Parse date
            created_at = item.get("created_at", "")
            try:
                parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                display_date = parsed.strftime("%b %d, %Y")
            except (ValueError, TypeError):
                display_date = "Unknown"

            timeline.append({
                "date": display_date,
                "type": item["type"],
                "title": item.get("title", ""),
                "summary": item["content"][:300] + "..." if len(item["content"]) > 300 else item["content"],
            })

        # Calculate duration (use completed_at if available, otherwise now)
        created_at = init_meta.get("created_at", "")
        completed_at = init_meta.get("completed_at")
        if completed_at:
            duration = calculate_duration(created_at, completed_at)
        else:
            duration = calculate_duration_from_now(created_at)

        # Build narrative summary
        narrative = _build_initiative_narrative(init_meta, items, session_count, note_count)

        response = {
            "initiative": {
                "id": initiative_id,
                "name": init_meta.get("name", ""),
                "goal": init_meta.get("goal", ""),
                "status": init_meta.get("status", "active"),
                "repository": repo,
            },
            "stats": {
                "session_summaries": session_count,
                "notes": note_count,
                "files_touched": len(all_files),
                "duration": duration,
            },
            "timeline": timeline,
            "narrative": narrative,
        }

        if init_meta.get("status") == "completed":
            response["initiative"]["completed_at"] = init_meta.get("completed_at", "")
            response["initiative"]["completion_summary"] = init_meta.get("completion_summary", "")

        logger.info(f"Summarized initiative: {session_count} session summaries, {note_count} notes")
        return json.dumps(response, indent=2)

    except Exception as e:
        logger.error(f"Summarize initiative error: {e}")
        return json.dumps({"status": "error", "error": str(e)})


def _build_initiative_narrative(meta: dict, items: list, session_count: int, note_count: int) -> str:
    """Build a narrative summary of the initiative."""
    name = meta.get("name", "This initiative")
    goal = meta.get("goal", "")
    status = meta.get("status", "active")

    parts = []

    # Opening
    if goal:
        parts.append(f"**{name}**: {goal}")
    else:
        parts.append(f"**{name}**")

    # Activity summary
    if session_count > 0 or note_count > 0:
        activity = []
        if session_count > 0:
            activity.append(f"{session_count} session summar{'ies' if session_count != 1 else 'y'}")
        if note_count > 0:
            activity.append(f"{note_count} note{'s' if note_count != 1 else ''}")
        parts.append(f"Activity: {' and '.join(activity)} recorded.")

    # Status
    if status == "completed":
        completion_summary = meta.get("completion_summary", "")
        if completion_summary:
            parts.append(f"Completed: {completion_summary}")
        else:
            parts.append("Status: Completed")
    else:
        parts.append("Status: Active")

    # Recent activity hint
    if items:
        last_item = items[-1]
        try:
            last_date = datetime.fromisoformat(last_item.get("created_at", "").replace("Z", "+00:00"))
            days_ago = (datetime.now(timezone.utc) - last_date).days
            if days_ago == 0:
                parts.append("Last activity: Today")
            elif days_ago == 1:
                parts.append("Last activity: Yesterday")
            else:
                parts.append(f"Last activity: {days_ago} days ago")
        except (ValueError, TypeError):
            pass

    return "\n\n".join(parts)


# --- Backward Compatibility Aliases (for tests and internal use) ---
# These aliases are NOT exported via __all__ but can be imported directly

def create_initiative(
    repository: str,
    name: str,
    goal: str = "",
    auto_focus: bool = True,
) -> str:
    """Backward-compatible alias for _create_initiative."""
    return _create_initiative(repository, name, goal, auto_focus)


def list_initiatives(
    repository: str,
    status: str = "all",
) -> str:
    """Backward-compatible alias for _list_initiatives."""
    return _list_initiatives(repository, status)


def focus_initiative(
    repository: str,
    initiative: str,
) -> str:
    """Backward-compatible alias for _focus_initiative."""
    return _focus_initiative(repository, initiative)


def complete_initiative(
    initiative: str,
    summary: str,
    repository: Optional[str] = None,
) -> str:
    """Backward-compatible alias for _complete_initiative."""
    return _complete_initiative(initiative, summary, repository)


def summarize_initiative(
    initiative: str,
    repository: Optional[str] = None,
) -> str:
    """Backward-compatible alias for _summarize_initiative."""
    return _summarize_initiative(initiative, repository)
