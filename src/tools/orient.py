"""
Orient Tool

MCP tool for session initialization and staleness detection.
"""

import json
from typing import Optional

from logging_config import get_logger
from src.git import (
    count_tracked_files,
    get_commits_since,
    get_current_branch,
    get_merge_commits_since,
)
from src.state import load_state, migrate_state
from src.tools.services import get_collection

logger = get_logger("tools.orient")


def orient_session(
    project_path: str,
) -> str:
    """
    Entry point for starting a session. Returns everything Claude needs to orient.

    Detects stale index and prompts for reindexing after merges, branch switches,
    or significant code changes.

    Args:
        project_path: Absolute path to the project repository

    Returns:
        JSON with:
            repository: str - Repository name (derived from path)
            branch: str - Current git branch
            indexed: bool - Is this repo indexed?
            last_indexed: str - When was it last indexed?
            file_count: int - How many files indexed?
            needs_reindex: bool - Is the index stale?
            reindex_reason: str - Why reindex is needed (if applicable)
            skeleton: dict - File tree structure (if available)
            tech_stack: str - Technologies and patterns (if set)
            active_initiative: dict - Current workstream (if any)
    """
    logger.info(f"Orienting session for: {project_path}")

    try:
        collection = get_collection()

        # Derive repository name from path
        repo_name = project_path.rstrip("/").split("/")[-1]
        current_branch = get_current_branch(project_path)

        # Load ingestion state
        state = migrate_state(load_state())

        # Check if this specific repository is indexed
        indexed_repo = state.get("repository")
        indexed = bool(
            indexed_repo == repo_name
            and (state.get("indexed_commit") or state.get("file_hashes"))
        )

        last_indexed = state.get("indexed_at") if indexed else None
        indexed_branch = state.get("branch") if indexed else None
        indexed_file_count = len(state.get("file_hashes", {})) if indexed else 0

        # Staleness detection
        needs_reindex = False
        reindex_reasons = []

        if indexed and last_indexed:
            # Signal 1: Branch switch
            if indexed_branch and current_branch != indexed_branch:
                needs_reindex = True
                reindex_reasons.append(
                    f"Branch changed: {indexed_branch} -> {current_branch}"
                )

            # Signal 2: New commits since index
            commits_since = get_commits_since(project_path, last_indexed)
            if commits_since > 0:
                needs_reindex = True
                reindex_reasons.append(f"{commits_since} new commit(s) since last index")

                # Signal 3: Check for merges (additional info)
                merges = get_merge_commits_since(project_path, last_indexed)
                if merges > 0:
                    reindex_reasons.append(f"Including {merges} merge commit(s)")

            # Signal 4: File count diff (significant change threshold)
            current_file_count = count_tracked_files(project_path)
            file_diff = abs(current_file_count - indexed_file_count)
            if file_diff > 5:  # Threshold for significant change
                needs_reindex = True
                reindex_reasons.append(
                    f"File count changed: {indexed_file_count} -> {current_file_count}"
                )

        # Fetch skeleton
        skeleton_data = _fetch_skeleton(collection, repo_name, current_branch)

        # Fetch tech_stack
        tech_stack = _fetch_tech_stack(collection, repo_name)

        # Fetch focused initiative (new format with stale detection)
        focused_initiative = _fetch_focused_initiative(collection, repo_name)

        # Fetch all active initiatives
        active_initiatives = _fetch_active_initiatives(collection, repo_name)

        # Fetch recent work highlights
        recent_work = _fetch_recent_work(collection, repo_name)

        # Fallback to legacy initiative if no new-format initiatives
        legacy_initiative = None
        if not focused_initiative and not active_initiatives:
            legacy_initiative = _fetch_initiative(collection, repo_name)

        # Build response
        response = {
            "repository": repo_name,
            "branch": current_branch,
            "indexed": indexed,
            "last_indexed": last_indexed or "never",
            "file_count": indexed_file_count,
            "needs_reindex": needs_reindex,
        }

        if reindex_reasons:
            response["reindex_reason"] = "; ".join(reindex_reasons)

        if skeleton_data:
            response["skeleton"] = skeleton_data

        if tech_stack:
            response["tech_stack"] = tech_stack
        else:
            response["prompt_set_context"] = (
                "No repo context set. Use set_repo_context to describe "
                "this project's tech stack and patterns."
            )

        # Include recent work highlights
        if recent_work:
            response["recent_work"] = recent_work

        # Include initiative data
        if focused_initiative:
            response["focused_initiative"] = focused_initiative

        if active_initiatives:
            response["active_initiatives"] = active_initiatives

        # Legacy fallback
        if legacy_initiative:
            response["active_initiative"] = legacy_initiative

        logger.info(f"Orient complete: indexed={indexed}, needs_reindex={needs_reindex}")

        return json.dumps(response, indent=2)

    except Exception as e:
        logger.error(f"Orient session error: {e}")
        return json.dumps(
            {
                "error": str(e),
                "indexed": False,
                "needs_reindex": False,
            }
        )


def _fetch_skeleton(
    collection, repo_name: str, branch: str
) -> Optional[dict]:
    """Fetch skeleton data from collection."""
    try:
        # Try current branch first
        skeleton_id = f"{repo_name}:skeleton:{branch}"
        result = collection.get(
            ids=[skeleton_id],
            include=["documents", "metadatas"],
        )

        if not result["documents"]:
            # Fallback: any skeleton for this repository
            fallback = collection.get(
                where={"$and": [{"type": "skeleton"}, {"repository": repo_name}]},
                include=["documents", "metadatas"],
            )
            if fallback["documents"]:
                result = {
                    "documents": [fallback["documents"][0]],
                    "metadatas": [fallback["metadatas"][0]],
                }

        if result["documents"]:
            meta = result["metadatas"][0]
            return {
                "tree": result["documents"][0],
                "total_files": meta.get("total_files", 0),
                "total_dirs": meta.get("total_dirs", 0),
                "branch": meta.get("branch", "unknown"),
            }
    except Exception as e:
        logger.warning(f"Failed to fetch skeleton: {e}")

    return None


def _fetch_tech_stack(collection, repo_name: str) -> Optional[str]:
    """Fetch tech stack context from collection."""
    try:
        tech_stack_id = f"{repo_name}:tech_stack"
        result = collection.get(
            ids=[tech_stack_id],
            include=["documents"],
        )
        if result["documents"]:
            return result["documents"][0]
    except Exception as e:
        logger.warning(f"Failed to fetch tech stack: {e}")

    return None


def _fetch_initiative(collection, repo_name: str) -> Optional[dict]:
    """Fetch active initiative from collection (legacy format)."""
    try:
        initiative_id = f"{repo_name}:initiative"
        result = collection.get(
            ids=[initiative_id],
            include=["documents", "metadatas"],
        )
        if result["documents"]:
            meta = result["metadatas"][0]
            return {
                "name": meta.get("initiative_name", ""),
                "status": meta.get("initiative_status", ""),
            }
    except Exception as e:
        logger.warning(f"Failed to fetch initiative: {e}")

    return None


def _fetch_focused_initiative(collection, repo_name: str) -> Optional[dict]:
    """Fetch focused initiative with stale detection."""
    try:
        from src.tools.initiatives import check_initiative_staleness, STALE_THRESHOLD_DAYS

        # Get focus document
        focus_id = f"{repo_name}:focus"
        focus_result = collection.get(
            ids=[focus_id],
            include=["metadatas"],
        )

        if not focus_result["ids"]:
            return None

        focus_meta = focus_result["metadatas"][0]
        initiative_id = focus_meta.get("initiative_id", "")

        if not initiative_id:
            return None

        # Get initiative details
        init_result = collection.get(
            ids=[initiative_id],
            include=["documents", "metadatas"],
        )

        if not init_result["ids"]:
            return None

        init_meta = init_result["metadatas"][0]
        updated_at = init_meta.get("updated_at", "")

        # Check staleness
        is_stale, days_inactive = check_initiative_staleness(updated_at, STALE_THRESHOLD_DAYS)

        return {
            "id": initiative_id,
            "name": init_meta.get("name", ""),
            "goal": init_meta.get("goal", ""),
            "status": init_meta.get("status", "active"),
            "updated_at": updated_at,
            "days_inactive": days_inactive,
            "stale": is_stale,
            "prompt": "still_working_or_complete" if is_stale else None,
        }

    except Exception as e:
        logger.warning(f"Failed to fetch focused initiative: {e}")

    return None


def _fetch_recent_work(collection, repo_name: str, days: int = 7, limit: int = 5) -> list:
    """Fetch brief highlights of recent work (commits/notes)."""
    try:
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Query recent commits and notes
        results = collection.get(
            where={
                "$and": [
                    {"repository": repo_name},
                    {"type": {"$in": ["commit", "note"]}},
                ]
            },
            include=["documents", "metadatas"],
        )

        # Filter by date and extract highlights
        items = []
        for i, doc_id in enumerate(results.get("ids", [])):
            meta = results["metadatas"][i] if results.get("metadatas") else {}
            doc = results["documents"][i] if results.get("documents") else ""

            created_at = meta.get("created_at", "")
            if not created_at:
                continue

            try:
                item_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                if item_date < cutoff:
                    continue
            except (ValueError, TypeError):
                continue

            # Extract highlight: use title if available, otherwise first line of content
            title = meta.get("title", "")
            if not title and doc:
                # For commits, try to extract a meaningful summary
                first_line = doc.split("\n")[0].strip()
                # Skip "Session Summary:" prefix if present
                if first_line.lower().startswith("session summary"):
                    lines = [l.strip() for l in doc.split("\n") if l.strip()]
                    title = lines[1] if len(lines) > 1 else first_line
                else:
                    title = first_line[:100]

            if title:
                items.append({
                    "created_at": created_at,
                    "highlight": title,
                })

        # Sort by date descending and limit
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        items = items[:limit]

        # Return just the highlights
        return [item["highlight"] for item in items]

    except Exception as e:
        logger.warning(f"Failed to fetch recent work: {e}")

    return []


def _fetch_active_initiatives(collection, repo_name: str) -> list:
    """Fetch all active (non-completed) initiatives for a repository."""
    try:
        result = collection.get(
            where={
                "$and": [
                    {"type": "initiative"},
                    {"repository": repo_name},
                    {"status": "active"},
                ]
            },
            include=["metadatas"],
        )

        initiatives = []
        for i, doc_id in enumerate(result.get("ids", [])):
            meta = result["metadatas"][i] if result.get("metadatas") else {}
            initiatives.append({
                "id": doc_id,
                "name": meta.get("name", ""),
                "goal": meta.get("goal", ""),
            })

        return initiatives

    except Exception as e:
        logger.warning(f"Failed to fetch active initiatives: {e}")

    return []
