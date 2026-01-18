"""
Recall Tools

MCP tools for recalling recent work and summarizing initiatives.
Addresses the core goal: "What did I work on yesterday/last week?"
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from logging_config import get_logger
from src.tools.initiative_utils import calculate_duration, calculate_duration_from_now, find_initiative
from src.tools.services import get_collection

logger = get_logger("tools.recall")


def recall_recent_work(
    repository: str,
    days: int = 7,
    limit: int = 20,
    include_code: bool = False,
) -> str:
    """
    Recall recent commits and notes for a repository.

    Returns a timeline view of recent work, grouped by day, with initiative context.
    Answers "What did I work on this week?" without manual search queries.

    Args:
        repository: Repository identifier
        days: Number of days to look back (default: 7)
        limit: Maximum number of items to return (default: 20)
        include_code: Include code changes in results (default: False, notes/commits only)

    Returns:
        JSON with timeline of recent work grouped by day
    """
    if not repository:
        return json.dumps({"error": "Repository name is required"})

    logger.info(f"Recalling recent work for {repository}, last {days} days")

    try:
        collection = get_collection()

        # Calculate cutoff date
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_str = cutoff.isoformat()

        # Build type filter
        types_to_include = ["commit", "note"]
        if include_code:
            types_to_include.append("code")

        # Query recent commits and notes
        # ChromaDB doesn't support date comparison in where, so we fetch more and filter
        results = collection.get(
            where={
                "$and": [
                    {"repository": repository},
                    {"type": {"$in": types_to_include}},
                ]
            },
            include=["documents", "metadatas"],
        )

        # Filter by date and build timeline
        items = []
        for i, doc_id in enumerate(results.get("ids", [])):
            meta = results["metadatas"][i] if results.get("metadatas") else {}
            doc = results["documents"][i] if results.get("documents") else ""

            # Get timestamp
            created_at = meta.get("created_at", "")
            if not created_at:
                continue

            # Filter by cutoff date
            try:
                item_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                if item_date < cutoff:
                    continue
            except (ValueError, TypeError):
                continue

            items.append({
                "id": doc_id,
                "type": meta.get("type", ""),
                "created_at": created_at,
                "date": item_date.strftime("%Y-%m-%d"),
                "time": item_date.strftime("%H:%M"),
                "title": meta.get("title", ""),
                "initiative_id": meta.get("initiative_id", ""),
                "initiative_name": meta.get("initiative_name", ""),
                "files": json.loads(meta.get("files", "[]")) if meta.get("files") else [],
                "content": doc[:500] + "..." if len(doc) > 500 else doc,
            })

        # Sort by date descending
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        # Apply limit
        items = items[:limit]

        # Group by day
        by_day = defaultdict(list)
        for item in items:
            by_day[item["date"]].append(item)

        # Build timeline
        timeline = []
        for date in sorted(by_day.keys(), reverse=True):
            day_items = by_day[date]

            # Parse date for display
            try:
                parsed = datetime.strptime(date, "%Y-%m-%d")
                day_name = parsed.strftime("%A")  # e.g., "Monday"
                display_date = parsed.strftime("%b %d")  # e.g., "Jan 11"
            except ValueError:
                day_name = ""
                display_date = date

            timeline.append({
                "date": date,
                "day_name": day_name,
                "display_date": display_date,
                "items": day_items,
                "count": len(day_items),
            })

        # Gather initiative summary
        initiative_counts = defaultdict(int)
        for item in items:
            if item.get("initiative_name"):
                initiative_counts[item["initiative_name"]] += 1

        response = {
            "repository": repository,
            "period": f"Last {days} days",
            "total_items": len(items),
            "timeline": timeline,
        }

        if initiative_counts:
            response["initiatives_active"] = [
                {"name": name, "activity_count": count}
                for name, count in sorted(initiative_counts.items(), key=lambda x: -x[1])
            ]

        logger.info(f"Recalled {len(items)} items across {len(timeline)} days")
        return json.dumps(response, indent=2)

    except Exception as e:
        logger.error(f"Recall error: {e}")
        return json.dumps({"status": "error", "error": str(e)})


def summarize_initiative(
    initiative: str,
    repository: Optional[str] = None,
) -> str:
    """
    Generate a narrative summary of an initiative's progress.

    Gathers all commits and notes tagged with the initiative and synthesizes
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

        # Get all commits and notes for this initiative
        results = collection.get(
            where={
                "$and": [
                    {"initiative_id": initiative_id},
                    {"type": {"$in": ["commit", "note"]}},
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
        commit_count = 0
        note_count = 0

        for item in items:
            if item["type"] == "commit":
                commit_count += 1
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
        narrative = _build_narrative(init_meta, items, commit_count, note_count)

        response = {
            "initiative": {
                "id": initiative_id,
                "name": init_meta.get("name", ""),
                "goal": init_meta.get("goal", ""),
                "status": init_meta.get("status", "active"),
                "repository": repo,
            },
            "stats": {
                "commits": commit_count,
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

        logger.info(f"Summarized initiative: {commit_count} commits, {note_count} notes")
        return json.dumps(response, indent=2)

    except Exception as e:
        logger.error(f"Summarize initiative error: {e}")
        return json.dumps({"status": "error", "error": str(e)})


def _build_narrative(meta: dict, items: list, commit_count: int, note_count: int) -> str:
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
    if commit_count > 0 or note_count > 0:
        activity = []
        if commit_count > 0:
            activity.append(f"{commit_count} session commit{'s' if commit_count != 1 else ''}")
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
