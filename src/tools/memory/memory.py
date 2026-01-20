"""
Memory Tools

MCP tools for saving notes, insights, and session summaries.

Document types defined in src.documents:
- note: Decisions, documentation, learnings
- insight: Understanding anchored to specific files
- session_summary: End-of-session context capture
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional, TYPE_CHECKING

from src.configs import get_logger
from src.external.git import get_current_branch, get_head_commit
from src.tools.ingest.walker import compute_file_hash
from src.utils.secret_scrubber import scrub_secrets
from src.tools.initiatives.initiative_utils import find_initiative, resolve_initiative
from src.configs.services import CONFIG, get_collection, get_repo_path, get_searcher

if TYPE_CHECKING:
    from src.models import InsightDoc, NoteDoc, SessionSummaryDoc

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


def _resolve_repository(repository: Optional[str]) -> str:
    """
    Resolve repository name, auto-detecting if not provided.

    Resolution order:
    1. Explicit repository parameter
    2. Current working directory (if git repo)
    3. Repository from any focused initiative
    4. "global" fallback

    Args:
        repository: Explicit repository name, or None to auto-detect

    Returns:
        Repository name (falls back to "global" if detection fails)
    """
    if repository:
        return repository

    # Auto-detect from current working directory
    repo_path = get_repo_path()
    if repo_path:
        return repo_path.rstrip("/").split("/")[-1]

    # Try to get repository from any focused initiative
    try:
        collection = get_collection()
        # Find any focus document to get its repository
        focus_results = collection.get(
            where={"type": "focus"},
            include=["metadatas"],
            limit=1,
        )
        if focus_results["ids"] and focus_results["metadatas"]:
            focused_repo = focus_results["metadatas"][0].get("repository")
            if focused_repo:
                logger.debug(f"Auto-detected repository from focused initiative: {focused_repo}")
                return focused_repo
    except Exception as e:
        logger.debug(f"Failed to get repository from focused initiative: {e}")

    return "global"


def save_memory(
    content: str,
    kind: Literal["note", "insight"],
    title: Optional[str] = None,
    tags: Optional[list[str]] = None,
    repository: Optional[str] = None,
    initiative: Optional[str] = None,
    files: Optional[list[str]] = None,
) -> str:
    """
    Save understanding to Cortex memory.

    **When to use this tool:**
    - Discovered a pattern or gotcha? kind="insight", link to files
    - Making an architectural decision? kind="note"
    - Documenting a non-obvious behavior? kind="insight"
    - Recording a learning for future sessions? kind="note"

    Args:
        content: The content to save (note text or insight analysis)
        kind: Type of memory - "note" for decisions/docs, "insight" for file-linked analysis
        title: Optional title
        tags: Optional categorization tags
        repository: Repository identifier (defaults to "global")
        initiative: Initiative to tag (uses focused if not specified)
        files: File paths this insight is about (REQUIRED for kind="insight")

    Returns:
        JSON with saved memory ID and status
    """
    if kind == "note":
        return _save_note(content, title, tags, repository, initiative)
    elif kind == "insight":
        if not files:
            return json.dumps({
                "status": "error",
                "error": "files parameter is required when kind='insight'",
            })
        return _save_insight(content, files, title, tags, repository, initiative)
    else:
        return json.dumps({
            "status": "error",
            "error": f"Unknown kind: {kind}. Valid kinds: 'note', 'insight'",
        })


def _save_note(
    content: str,
    title: Optional[str] = None,
    tags: Optional[list[str]] = None,
    repository: Optional[str] = None,
    initiative: Optional[str] = None,
) -> str:
    """
    Save a note, documentation snippet, or decision to Cortex memory.

    Args:
        content: The note content
        title: Optional title for the note
        tags: Optional list of tags for categorization
        repository: Repository identifier
        initiative: Initiative ID/name to tag (uses focused initiative if not specified)

    Returns:
        JSON with note ID and save status
    """
    repo = _resolve_repository(repository)

    logger.info(f"Saving note: title='{title}', repository={repo}")

    try:
        collection = get_collection()
        note_id = f"note:{uuid.uuid4().hex[:8]}"
        repo_path = get_repo_path()
        branch = get_current_branch(repo_path) if repo_path else "unknown"
        timestamp = datetime.now(timezone.utc).isoformat()

        # Get initiative tagging
        initiative_id, initiative_name = resolve_initiative(
            collection, repo, initiative, _get_focused_initiative_info
        )

        # Build document text
        doc_text = ""
        if title:
            doc_text = f"{title}\n\n"
        doc_text += scrub_secrets(content)

        # Get current commit for staleness tracking
        current_commit = get_head_commit(repo_path) if repo_path else None

        metadata = {
            "type": "note",
            "title": title or "",
            "tags": json.dumps(tags) if tags else "[]",
            "repository": repo,
            "branch": branch,
            "created_at": timestamp,
            "updated_at": timestamp,
            # Staleness tracking
            "verified_at": timestamp,
            "status": "active",
        }

        # Add commit SHA if available (for staleness detection)
        if current_commit:
            metadata["created_commit"] = current_commit

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


def conclude_session(
    summary: str,
    changed_files: list[str],
    repository: Optional[str] = None,
    initiative: Optional[str] = None,
) -> str:
    """
    Save end-of-session summary to Cortex memory.

    **When to use this tool:**
    - Ending a coding session and want to preserve context
    - Capturing decisions, problems solved, and understanding
    - Recording what files changed and why

    Call this BEFORE ending the session to ensure context is captured.

    Args:
        summary: Detailed summary of what was done and why
        changed_files: List of file paths that were modified
        repository: Repository identifier
        initiative: Initiative to tag (uses focused if not specified)

    Returns:
        JSON with session summary status
    """
    repo = _resolve_repository(repository)

    logger.info(f"Saving session summary to Cortex: {len(changed_files)} files, repository={repo}")

    try:
        collection = get_collection()

        # Save the session summary
        doc_id = f"session_summary:{uuid.uuid4().hex[:8]}"

        repo_path = get_repo_path()
        branch = get_current_branch(repo_path) if repo_path else "unknown"
        timestamp = datetime.now(timezone.utc).isoformat()

        # Get initiative tagging
        initiative_id, initiative_name = resolve_initiative(
            collection, repo, initiative, _get_focused_initiative_info
        )

        # Get current git commit for staleness tracking
        current_commit = get_head_commit(repo_path) if repo_path else None

        # Build metadata
        metadata = {
            "type": "session_summary",
            "repository": repo,
            "branch": branch,
            "files": json.dumps(changed_files),
            "created_at": timestamp,
            "updated_at": timestamp,
            # Staleness tracking
            "status": "active",
        }

        # Add git commit SHA if available (for staleness detection)
        if current_commit:
            metadata["created_commit"] = current_commit

        # Add initiative tagging if available
        if initiative_id:
            metadata["initiative_id"] = initiative_id
            metadata["initiative_name"] = initiative_name or ""

            # Update initiative's updated_at timestamp
            _update_initiative_timestamp(collection, initiative_id, timestamp)

        collection.upsert(
            ids=[doc_id],
            documents=[f"Session Summary:\n\n{scrub_secrets(summary)}\n\nChanged files: {', '.join(changed_files)}"],
            metadatas=[metadata],
        )
        logger.debug(f"Saved session summary: {doc_id}")

        # Rebuild search index
        get_searcher().build_index()

        logger.info(f"Session summary complete: {doc_id}")

        # Build response
        response = {
            "status": "success",
            "session_id": doc_id,
            "summary_saved": True,
            "files_recorded": len(changed_files),
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
        logger.error(f"Session summary error: {e}")
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


def _save_insight(
    insight: str,
    files: list[str],
    title: Optional[str] = None,
    tags: Optional[list[str]] = None,
    repository: Optional[str] = None,
    initiative: Optional[str] = None,
) -> str:
    """Save an insight to Cortex memory (internal implementation)."""
    # Validate files is non-empty
    if not files:
        return json.dumps({
            "status": "error",
            "error": "files parameter is required and must be a non-empty list",
        })

    repo = _resolve_repository(repository)

    logger.info(f"Saving insight: title='{title}', files={len(files)}, repository={repo}")

    try:
        collection = get_collection()
        insight_id = f"insight:{uuid.uuid4().hex[:8]}"
        repo_path = get_repo_path()
        branch = get_current_branch(repo_path) if repo_path else "unknown"
        timestamp = datetime.now(timezone.utc).isoformat()

        # Get initiative tagging
        initiative_id, initiative_name = resolve_initiative(
            collection, repo, initiative, _get_focused_initiative_info
        )

        # Build document text
        doc_text = ""
        if title:
            doc_text = f"{title}\n\n"
        doc_text += scrub_secrets(insight)
        doc_text += f"\n\nLinked files: {', '.join(files)}"

        # Get current commit for staleness tracking
        current_commit = get_head_commit(repo_path) if repo_path else None

        # Compute file hashes for linked files (for staleness detection)
        file_hashes = {}
        if repo_path:
            for file_path in files:
                full_path = Path(file_path)
                if not full_path.is_absolute():
                    full_path = Path(repo_path) / file_path
                if full_path.exists():
                    try:
                        file_hashes[file_path] = compute_file_hash(full_path)
                    except (OSError, IOError) as e:
                        logger.warning(f"Could not hash file {file_path}: {e}")

        metadata = {
            "type": "insight",
            "title": title or "",
            "files": json.dumps(files),
            "tags": json.dumps(tags) if tags else "[]",
            "repository": repo,
            "branch": branch,
            "created_at": timestamp,
            "updated_at": timestamp,
            # Staleness tracking
            "verified_at": timestamp,
            "status": "active",
            "file_hashes": json.dumps(file_hashes),
        }

        # Add commit SHA if available (for staleness detection)
        if current_commit:
            metadata["created_commit"] = current_commit

        # Add initiative tagging if available
        if initiative_id:
            metadata["initiative_id"] = initiative_id
            metadata["initiative_name"] = initiative_name or ""

            # Update initiative's updated_at timestamp
            _update_initiative_timestamp(collection, initiative_id, timestamp)

        collection.upsert(
            ids=[insight_id],
            documents=[doc_text],
            metadatas=[metadata],
        )

        # Rebuild search index
        get_searcher().build_index()

        logger.info(f"Insight saved: {insight_id}")

        response = {
            "status": "saved",
            "insight_id": insight_id,
            "type": "insight",
            "title": title,
            "files": files,
            "tags": tags or [],
        }

        if initiative_id:
            response["initiative"] = {
                "id": initiative_id,
                "name": initiative_name,
            }
            response["initiative_name"] = initiative_name

        return json.dumps(response, indent=2)

    except Exception as e:
        logger.error(f"Insight save error: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e),
        })


def validate_insight(
    insight_id: str,
    validation_result: str,
    notes: Optional[str] = None,
    deprecate: bool = False,
    replacement_insight: Optional[str] = None,
    repository: Optional[str] = None,
) -> str:
    """
    Validate a stored insight and optionally update its status.

    Call this after re-reading linked files to verify whether a stale
    insight is still accurate.

    Args:
        insight_id: The insight ID to validate (e.g., "insight:abc123")
        validation_result: Assessment result - one of:
            - "still_valid": Insight is still accurate
            - "partially_valid": Some parts are still accurate
            - "no_longer_valid": Insight is outdated/wrong
        notes: Optional notes about the validation
        deprecate: If True and result is "no_longer_valid", mark as deprecated
        replacement_insight: If deprecating, new insight content to save as replacement
        repository: Repository identifier (optional)

    Returns:
        JSON with validation status and any actions taken
    """
    repo = _resolve_repository(repository)

    logger.info(f"Validating insight: {insight_id}, result={validation_result}")

    try:
        collection = get_collection()
        repo_path = get_repo_path()
        timestamp = datetime.now(timezone.utc).isoformat()

        # Fetch the insight
        result = collection.get(
            ids=[insight_id],
            include=["documents", "metadatas"],
        )

        if not result["ids"]:
            return json.dumps({
                "status": "error",
                "error": f"Insight not found: {insight_id}",
            })

        meta = result["metadatas"][0]
        doc = result["documents"][0]

        # Verify it's actually an insight
        if meta.get("type") != "insight":
            return json.dumps({
                "status": "error",
                "error": f"Document {insight_id} is not an insight (type={meta.get('type')})",
            })

        # Update timestamps
        meta["verified_at"] = timestamp
        meta["updated_at"] = timestamp
        meta["last_validation_result"] = validation_result
        # Backfill created_at if missing
        if not meta.get("created_at"):
            meta["created_at"] = timestamp
        if notes:
            meta["validation_notes"] = notes

        response = {
            "status": "validated",
            "insight_id": insight_id,
            "validation_result": validation_result,
            "verified_at": timestamp,
        }

        # Handle deprecation
        if validation_result == "no_longer_valid" and deprecate:
            meta["status"] = "deprecated"
            meta["deprecated_at"] = timestamp
            meta["deprecation_reason"] = notes or "Marked invalid during validation"
            response["deprecated"] = True
            logger.info(f"Deprecated insight: {insight_id}")

            # Create replacement if provided
            if replacement_insight:
                linked_files = json.loads(meta.get("files", "[]"))
                tags = json.loads(meta.get("tags", "[]"))

                new_result_json = _save_insight(
                    insight=replacement_insight,
                    files=linked_files,
                    title=meta.get("title", "") + " (Updated)" if meta.get("title") else None,
                    tags=tags,
                    repository=meta.get("repository", repo),
                )
                new_result = json.loads(new_result_json)

                if new_result.get("status") == "saved":
                    meta["superseded_by"] = new_result["insight_id"]
                    response["replacement_id"] = new_result["insight_id"]
                    logger.info(f"Created replacement insight: {new_result['insight_id']}")

        elif validation_result == "still_valid":
            # Refresh file hashes to current state
            linked_files = json.loads(meta.get("files", "[]"))

            if linked_files and repo_path:
                new_hashes = {}
                for file_path in linked_files:
                    full_path = Path(file_path)
                    if not full_path.is_absolute():
                        full_path = Path(repo_path) / file_path
                    if full_path.exists():
                        try:
                            new_hashes[file_path] = compute_file_hash(full_path)
                        except (OSError, IOError) as e:
                            logger.warning(f"Could not hash file {file_path}: {e}")

                meta["file_hashes"] = json.dumps(new_hashes)
                response["file_hashes_refreshed"] = True

            # Update commit reference
            current_commit = get_head_commit(repo_path) if repo_path else None
            if current_commit:
                meta["created_commit"] = current_commit

            logger.info(f"Validated insight as still valid: {insight_id}")

        # Save updated metadata
        collection.upsert(
            ids=[insight_id],
            documents=[doc],
            metadatas=[meta],
        )

        # Rebuild search index
        get_searcher().build_index()

        return json.dumps(response, indent=2)

    except Exception as e:
        logger.error(f"Validate insight error: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e),
        })


# --- Backward Compatibility Aliases (for tests and internal use) ---
# These aliases are NOT exported via __all__ but can be imported directly

def insight_to_cortex(
    insight: str,
    files: list[str],
    title: Optional[str] = None,
    tags: Optional[list[str]] = None,
    repository: Optional[str] = None,
    initiative: Optional[str] = None,
) -> str:
    """Backward-compatible alias for _save_insight."""
    return _save_insight(insight, files, title, tags, repository, initiative)


def save_note_to_cortex(
    content: str,
    title: Optional[str] = None,
    tags: Optional[list[str]] = None,
    repository: Optional[str] = None,
    initiative: Optional[str] = None,
) -> str:
    """Backward-compatible alias for _save_note."""
    return _save_note(content, title, tags, repository, initiative)


def session_summary_to_cortex(
    summary: str,
    changed_files: list[str],
    repository: Optional[str] = None,
    initiative: Optional[str] = None,
) -> str:
    """Backward-compatible alias for conclude_session."""
    return conclude_session(summary, changed_files, repository, initiative)
