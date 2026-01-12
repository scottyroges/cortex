"""
Notes Tools

MCP tools for saving notes and session commits.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from logging_config import get_logger
from src.git import get_current_branch
from src.ingest import ingest_files
from src.security import scrub_secrets
from src.tools.services import CONFIG, get_anthropic, get_collection, get_repo_path, get_searcher

logger = get_logger("tools.notes")


def _get_focused_initiative_info(repository: str) -> tuple[Optional[str], Optional[str]]:
    """Get focused initiative ID and name for a repository."""
    try:
        from src.tools.initiatives import get_focused_initiative
        focus = get_focused_initiative(repository)
        if focus:
            return focus.get("initiative_id"), focus.get("initiative_name")
    except Exception as e:
        logger.warning(f"Failed to get focused initiative: {e}")
    return None, None


def save_note_to_cortex(
    content: str,
    title: Optional[str] = None,
    tags: Optional[list[str]] = None,
    project: Optional[str] = None,
    repository: Optional[str] = None,
    initiative: Optional[str] = None,
) -> str:
    """
    Save a note, documentation snippet, or decision to Cortex memory.

    Args:
        content: The note content
        title: Optional title for the note
        tags: Optional list of tags for categorization
        project: Associated project identifier (deprecated, use repository)
        repository: Repository identifier
        initiative: Initiative ID/name to tag (uses focused initiative if not specified)

    Returns:
        JSON with note ID and save status
    """
    # Handle project/repository naming transition
    repo = repository or project or "global"

    logger.info(f"Saving note: title='{title}', repository={repo}")

    try:
        collection = get_collection()
        note_id = f"note:{uuid.uuid4().hex[:8]}"
        repo_path = get_repo_path()
        branch = get_current_branch(repo_path) if repo_path else "unknown"
        timestamp = datetime.now(timezone.utc).isoformat()

        # Get initiative tagging
        initiative_id = None
        initiative_name = None

        if initiative:
            # Explicit initiative specified
            if initiative.startswith("initiative:"):
                initiative_id = initiative
                # Look up the name
                from src.tools.initiatives import _find_initiative
                init_data = _find_initiative(collection, repo, initiative)
                if init_data:
                    initiative_name = init_data["metadata"].get("name", "")
            else:
                # Assume it's a name, look up the ID
                from src.tools.initiatives import _find_initiative
                init_data = _find_initiative(collection, repo, initiative)
                if init_data:
                    initiative_id = init_data["id"]
                    initiative_name = init_data["metadata"].get("name", "")
        else:
            # Use focused initiative
            initiative_id, initiative_name = _get_focused_initiative_info(repo)

        # Build document text
        doc_text = ""
        if title:
            doc_text = f"{title}\n\n"
        doc_text += scrub_secrets(content)

        metadata = {
            "type": "note",
            "title": title or "",
            "tags": json.dumps(tags) if tags else "[]",
            "repository": repo,
            "project": repo,  # Keep for backwards compatibility
            "branch": branch,
            "created_at": timestamp,
        }

        # Add initiative tagging if available
        if initiative_id:
            metadata["initiative_id"] = initiative_id
            metadata["initiative_name"] = initiative_name or ""

        collection.upsert(
            ids=[note_id],
            documents=[doc_text],
            metadatas=[metadata],
        )

        # Rebuild search index
        get_searcher().build_index()

        logger.info(f"Note saved: {note_id}")

        response = {
            "status": "saved",
            "note_id": note_id,
            "title": title,
        }

        if initiative_id:
            response["initiative"] = {
                "id": initiative_id,
                "name": initiative_name,
            }

        return json.dumps(response, indent=2)

    except Exception as e:
        logger.error(f"Note save error: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e),
        })


def commit_to_cortex(
    summary: str,
    changed_files: list[str],
    project: Optional[str] = None,
    repository: Optional[str] = None,
    initiative: Optional[str] = None,
) -> str:
    """
    Save a session summary and re-index changed files.

    Use this at the end of a coding session to capture decisions
    and ensure changed code is indexed.

    Args:
        summary: Summary of the session/changes made
        changed_files: List of file paths that were modified
        project: Project identifier (deprecated, use repository)
        repository: Repository identifier
        initiative: Initiative ID/name to tag (uses focused initiative if not specified)

    Returns:
        JSON with commit status, re-indexing stats, and initiative info
    """
    # Handle project/repository naming transition
    repo = repository or project or "global"

    logger.info(f"Committing to Cortex: {len(changed_files)} files, repository={repo}")

    try:
        collection = get_collection()
        anthropic = get_anthropic() if CONFIG["header_provider"] == "anthropic" else None

        # Save the summary as a note
        note_id = f"commit:{uuid.uuid4().hex[:8]}"

        repo_path = get_repo_path()
        branch = get_current_branch(repo_path) if repo_path else "unknown"
        timestamp = datetime.now(timezone.utc).isoformat()

        # Get initiative tagging
        initiative_id = None
        initiative_name = None

        if initiative:
            # Explicit initiative specified
            if initiative.startswith("initiative:"):
                initiative_id = initiative
                from src.tools.initiatives import _find_initiative
                init_data = _find_initiative(collection, repo, initiative)
                if init_data:
                    initiative_name = init_data["metadata"].get("name", "")
            else:
                # Assume it's a name, look up the ID
                from src.tools.initiatives import _find_initiative
                init_data = _find_initiative(collection, repo, initiative)
                if init_data:
                    initiative_id = init_data["id"]
                    initiative_name = init_data["metadata"].get("name", "")
        else:
            # Use focused initiative
            initiative_id, initiative_name = _get_focused_initiative_info(repo)

        # Build metadata
        metadata = {
            "type": "commit",
            "repository": repo,
            "project": repo,  # Keep for backwards compatibility
            "branch": branch,
            "files": json.dumps(changed_files),
            "created_at": timestamp,
        }

        # Add initiative tagging if available
        if initiative_id:
            metadata["initiative_id"] = initiative_id
            metadata["initiative_name"] = initiative_name or ""

            # Update initiative's updated_at timestamp
            _update_initiative_timestamp(collection, initiative_id, timestamp)

        collection.upsert(
            ids=[note_id],
            documents=[f"Session Summary:\n\n{scrub_secrets(summary)}\n\nChanged files: {', '.join(changed_files)}"],
            metadatas=[metadata],
        )
        logger.debug(f"Saved commit summary: {note_id}")

        # Re-index the changed files
        reindex_stats = ingest_files(
            file_paths=changed_files,
            collection=collection,
            project_id=repo,
            anthropic_client=anthropic,
            header_provider=CONFIG["header_provider"],
        )
        logger.debug(f"Re-indexed files: {reindex_stats}")

        # Rebuild search index
        get_searcher().build_index()

        logger.info(f"Commit complete: {note_id}")

        # Build response
        response = {
            "status": "success",
            "commit_id": note_id,
            "summary_saved": True,
            "reindex_stats": reindex_stats,
        }

        # Add initiative info
        if initiative_id:
            # Check for completion signals
            from src.tools.initiatives import detect_completion_signals
            completion_detected = detect_completion_signals(summary)

            response["initiative"] = {
                "id": initiative_id,
                "name": initiative_name,
                "completion_signal_detected": completion_detected,
            }

            if completion_detected:
                response["initiative"]["prompt"] = "mark_complete"

        return json.dumps(response, indent=2)

    except Exception as e:
        logger.error(f"Commit error: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e),
        })


def _update_initiative_timestamp(collection, initiative_id: str, timestamp: str) -> None:
    """Update an initiative's updated_at timestamp."""
    try:
        result = collection.get(
            ids=[initiative_id],
            include=["documents", "metadatas"],
        )
        if result["ids"]:
            meta = result["metadatas"][0]
            meta["updated_at"] = timestamp
            collection.upsert(
                ids=[initiative_id],
                documents=[result["documents"][0]],
                metadatas=[meta],
            )
    except Exception as e:
        logger.warning(f"Failed to update initiative timestamp: {e}")
