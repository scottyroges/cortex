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
from src.tools.services import CONFIG, get_anthropic, get_collection, get_searcher

logger = get_logger("tools.notes")


def save_note_to_cortex(
    content: str,
    title: Optional[str] = None,
    tags: Optional[list[str]] = None,
    project: Optional[str] = None,
) -> str:
    """
    Save a note, documentation snippet, or decision to Cortex memory.

    Args:
        content: The note content
        title: Optional title for the note
        tags: Optional list of tags for categorization
        project: Associated project identifier

    Returns:
        JSON with note ID and save status
    """
    logger.info(f"Saving note: title='{title}', project={project}")

    try:
        collection = get_collection()
        note_id = f"note:{uuid.uuid4().hex[:8]}"
        branch = get_current_branch("/projects")
        timestamp = datetime.now(timezone.utc).isoformat()

        # Build document text
        doc_text = ""
        if title:
            doc_text = f"{title}\n\n"
        doc_text += scrub_secrets(content)

        collection.upsert(
            ids=[note_id],
            documents=[doc_text],
            metadatas=[{
                "type": "note",
                "title": title or "",
                "tags": json.dumps(tags) if tags else "[]",
                "project": project or "global",
                "branch": branch,
                "created_at": timestamp,
            }],
        )

        # Rebuild search index
        get_searcher().build_index()

        logger.info(f"Note saved: {note_id}")

        return json.dumps({
            "status": "saved",
            "note_id": note_id,
            "title": title,
        }, indent=2)

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
) -> str:
    """
    Save a session summary and re-index changed files.

    Use this at the end of a coding session to capture decisions
    and ensure changed code is indexed.

    Args:
        summary: Summary of the session/changes made
        changed_files: List of file paths that were modified
        project: Project identifier for the files

    Returns:
        JSON with commit status and re-indexing stats
    """
    logger.info(f"Committing to Cortex: {len(changed_files)} files, project={project}")

    try:
        collection = get_collection()
        anthropic = get_anthropic() if CONFIG["header_provider"] == "anthropic" else None

        # Save the summary as a note
        note_id = f"commit:{uuid.uuid4().hex[:8]}"

        branch = get_current_branch("/projects")
        project_id = project or "global"
        timestamp = datetime.now(timezone.utc).isoformat()

        collection.upsert(
            ids=[note_id],
            documents=[f"Session Summary:\n\n{scrub_secrets(summary)}\n\nChanged files: {', '.join(changed_files)}"],
            metadatas=[{
                "type": "commit",
                "project": project_id,
                "branch": branch,
                "files": json.dumps(changed_files),
                "created_at": timestamp,
            }],
        )
        logger.debug(f"Saved commit summary: {note_id}")

        # Re-index the changed files
        reindex_stats = ingest_files(
            file_paths=changed_files,
            collection=collection,
            project_id=project_id,
            anthropic_client=anthropic,
            header_provider=CONFIG["header_provider"],
        )
        logger.debug(f"Re-indexed files: {reindex_stats}")

        # Rebuild search index
        get_searcher().build_index()

        logger.info(f"Commit complete: {note_id}")

        return json.dumps({
            "status": "success",
            "commit_id": note_id,
            "summary_saved": True,
            "reindex_stats": reindex_stats,
        }, indent=2)

    except Exception as e:
        logger.error(f"Commit error: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e),
        })
