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
from src.tools.initiatives import get_any_focused_repository, get_focused_initiative
from src.tools.initiatives.utils import find_initiative, resolve_initiative
from src.configs.services import CONFIG, get_collection, get_repo_path, get_searcher

if TYPE_CHECKING:
    from src.models import InsightDoc, NoteDoc, SessionSummaryDoc

logger = get_logger("tools.memory")


def _get_focused_initiative_info(repository: str) -> tuple[Optional[str], Optional[str]]:
    """Get focused initiative (id, name) tuple for resolve_initiative callback."""
    try:
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
    focused_repo = get_any_focused_repository()
    if focused_repo:
        return focused_repo

    return "global"


def _build_base_context(
    repository: Optional[str],
    initiative: Optional[str],
) -> dict:
    """
    Build common context for save operations.

    Returns dict with:
        - repo: resolved repository name
        - collection: ChromaDB collection
        - repo_path: path to repo (or None)
        - branch: current git branch
        - timestamp: ISO timestamp
        - current_commit: HEAD commit SHA (or None)
        - initiative_id: resolved initiative ID (or None)
        - initiative_name: resolved initiative name (or None)
    """
    repo = _resolve_repository(repository)
    collection = get_collection()
    repo_path = get_repo_path()
    branch = get_current_branch(repo_path) if repo_path else "unknown"
    timestamp = datetime.now(timezone.utc).isoformat()
    current_commit = get_head_commit(repo_path) if repo_path else None

    initiative_id, initiative_name = resolve_initiative(
        collection, repo, initiative, _get_focused_initiative_info
    )

    return {
        "repo": repo,
        "collection": collection,
        "repo_path": repo_path,
        "branch": branch,
        "timestamp": timestamp,
        "current_commit": current_commit,
        "initiative_id": initiative_id,
        "initiative_name": initiative_name,
    }


def _add_common_metadata(
    metadata: dict,
    ctx: dict,
) -> None:
    """Add common fields to metadata dict from context."""
    if ctx["current_commit"]:
        metadata["created_commit"] = ctx["current_commit"]
    if ctx["initiative_id"]:
        metadata["initiative_id"] = ctx["initiative_id"]
        metadata["initiative_name"] = ctx["initiative_name"] or ""


def _compute_file_hashes(files: list[str], repo_path: Optional[str]) -> dict[str, str]:
    """Compute content hashes for a list of files (for staleness detection)."""
    file_hashes = {}
    if not repo_path:
        return file_hashes

    for file_path in files:
        full_path = Path(file_path)
        if not full_path.is_absolute():
            full_path = Path(repo_path) / file_path
        if full_path.exists():
            try:
                file_hashes[file_path] = compute_file_hash(full_path)
            except (OSError, IOError) as e:
                logger.warning(f"Could not hash file {file_path}: {e}")

    return file_hashes


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
    ctx = _build_base_context(repository, initiative)
    logger.info(f"Saving note: title='{title}', repository={ctx['repo']}")

    try:
        note_id = f"note:{uuid.uuid4().hex[:8]}"

        # Build document text
        doc_text = f"{title}\n\n" if title else ""
        doc_text += scrub_secrets(content)

        metadata = {
            "type": "note",
            "title": title or "",
            "tags": json.dumps(tags) if tags else "[]",
            "repository": ctx["repo"],
            "branch": ctx["branch"],
            "created_at": ctx["timestamp"],
            "updated_at": ctx["timestamp"],
            "verified_at": ctx["timestamp"],
            "status": "active",
        }
        _add_common_metadata(metadata, ctx)

        ctx["collection"].upsert(
            ids=[note_id],
            documents=[doc_text],
            metadatas=[metadata],
        )
        get_searcher().build_index()

        logger.info(f"Note saved: {note_id}")

        response = {
            "status": "saved",
            "note_id": note_id,
            "title": title,
        }
        if ctx["initiative_id"]:
            response["initiative"] = {
                "id": ctx["initiative_id"],
                "name": ctx["initiative_name"],
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
    ctx = _build_base_context(repository, initiative)
    logger.info(f"Saving session summary to Cortex: {len(changed_files)} files, repository={ctx['repo']}")

    try:
        doc_id = f"session_summary:{uuid.uuid4().hex[:8]}"

        metadata = {
            "type": "session_summary",
            "repository": ctx["repo"],
            "branch": ctx["branch"],
            "files": json.dumps(changed_files),
            "created_at": ctx["timestamp"],
            "updated_at": ctx["timestamp"],
            "status": "active",
        }
        _add_common_metadata(metadata, ctx)

        # Update initiative's updated_at timestamp if tagged
        if ctx["initiative_id"]:
            _update_initiative_timestamp(ctx["collection"], ctx["initiative_id"], ctx["timestamp"])

        ctx["collection"].upsert(
            ids=[doc_id],
            documents=[f"Session Summary:\n\n{scrub_secrets(summary)}\n\nChanged files: {', '.join(changed_files)}"],
            metadatas=[metadata],
        )
        logger.debug(f"Saved session summary: {doc_id}")
        get_searcher().build_index()

        logger.info(f"Session summary complete: {doc_id}")

        response = {
            "status": "success",
            "session_id": doc_id,
            "summary_saved": True,
            "files_recorded": len(changed_files),
        }

        if ctx["initiative_id"]:
            from src.tools.initiatives import detect_completion_signals
            completion_detected = detect_completion_signals(summary)

            response["initiative"] = {
                "id": ctx["initiative_id"],
                "name": ctx["initiative_name"],
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
    # Validate files (kept here for backward-compat aliases like insight_to_cortex)
    if not files:
        return json.dumps({
            "status": "error",
            "error": "files parameter is required and must be a non-empty list",
        })

    ctx = _build_base_context(repository, initiative)
    logger.info(f"Saving insight: title='{title}', files={len(files)}, repository={ctx['repo']}")

    try:
        insight_id = f"insight:{uuid.uuid4().hex[:8]}"

        # Build document text
        doc_text = f"{title}\n\n" if title else ""
        doc_text += scrub_secrets(insight)
        doc_text += f"\n\nLinked files: {', '.join(files)}"

        # Compute file hashes for linked files (for staleness detection)
        file_hashes = _compute_file_hashes(files, ctx["repo_path"])

        metadata = {
            "type": "insight",
            "title": title or "",
            "files": json.dumps(files),
            "tags": json.dumps(tags) if tags else "[]",
            "repository": ctx["repo"],
            "branch": ctx["branch"],
            "created_at": ctx["timestamp"],
            "updated_at": ctx["timestamp"],
            "verified_at": ctx["timestamp"],
            "status": "active",
            "file_hashes": json.dumps(file_hashes),
        }
        _add_common_metadata(metadata, ctx)

        # Update initiative's updated_at timestamp if tagged
        if ctx["initiative_id"]:
            _update_initiative_timestamp(ctx["collection"], ctx["initiative_id"], ctx["timestamp"])

        ctx["collection"].upsert(
            ids=[insight_id],
            documents=[doc_text],
            metadatas=[metadata],
        )
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
        if ctx["initiative_id"]:
            response["initiative"] = {
                "id": ctx["initiative_id"],
                "name": ctx["initiative_name"],
            }
            response["initiative_name"] = ctx["initiative_name"]

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
                new_hashes = _compute_file_hashes(linked_files, repo_path)
                if new_hashes:
                    meta["file_hashes"] = json.dumps(new_hashes)
                    response["file_hashes_refreshed"] = True

            # Update commit reference for validation tracking
            current_commit = get_head_commit(repo_path) if repo_path else None
            if current_commit:
                meta["validated_commit"] = current_commit

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


# --- Backward Compatibility Aliases ---
# Exported via __init__.py for tests and internal use.
# Prefer save_memory() and conclude_session() for new code.

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
