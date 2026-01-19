"""
Recall Tools

MCP tools for recalling recent work.
Addresses the core goal: "What did I work on yesterday/last week?"
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from logging_config import get_logger
from src.tools.services import get_collection

logger = get_logger("tools.recall")


def recall_recent_work(
    repository: str,
    days: int = 7,
    limit: int = 20,
    include_code: bool = False,
) -> str:
    """
    Recall recent session summaries and notes for a repository.

    Returns a timeline view of recent work, grouped by day, with initiative context.
    Answers "What did I work on this week?" without manual search queries.

    Args:
        repository: Repository identifier
        days: Number of days to look back (default: 7)
        limit: Maximum number of items to return (default: 20)
        include_code: Include code changes in results (default: False, notes/session_summaries only)

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
        types_to_include = ["session_summary", "note"]
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
