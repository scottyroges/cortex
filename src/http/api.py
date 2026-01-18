"""
Phase 2 API Endpoints

HTTP endpoints for web clipper, CLI search, and notes.
"""

import hashlib
import os
import time
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from logging_config import get_logger
from src.search import HybridSearcher, RerankerService
from src.security import scrub_secrets
from src.storage import get_chroma_client, get_or_create_collection

logger = get_logger("http.api")

router = APIRouter()

# Lazy-initialized resources
_client = None
_collection = None
_searcher = None
_reranker = None


def get_collection():
    """Get or create the ChromaDB collection."""
    global _client, _collection
    if _collection is None:
        _client = get_chroma_client()
        _collection = get_or_create_collection(_client)
    return _collection


def get_searcher():
    """Get or create the hybrid searcher."""
    global _searcher
    if _searcher is None:
        _searcher = HybridSearcher(get_collection())
    return _searcher


def get_reranker():
    """Get or create the reranker."""
    global _reranker
    if _reranker is None:
        _reranker = RerankerService()
    return _reranker


# --- Request/Response Models ---


class IngestRequest(BaseModel):
    """Request body for web content ingestion."""
    url: str
    content: str
    title: Optional[str] = None
    tags: Optional[list[str]] = None
    repository: str = "web"


class NoteRequest(BaseModel):
    """Request body for note creation."""
    content: str
    title: Optional[str] = None
    tags: Optional[list[str]] = None
    repository: str = "notes"


class CommitRequest(BaseModel):
    """Request body for session commit (from auto-capture hook)."""
    summary: str
    changed_files: list[str] = []
    repository: str = "global"
    initiative: Optional[str] = None


class SearchResponse(BaseModel):
    """Response for search endpoint."""
    query: str
    results: list[dict[str, Any]]
    timing_ms: float


# --- Endpoints ---


@router.post("/ingest")
def ingest_web(request: IngestRequest) -> dict[str, Any]:
    """
    Ingest web content (for web clipper).

    Args:
        url: Source URL
        content: Page content
        title: Optional title
        tags: Optional tags
        repository: Repository name (default: "web")
    """
    logger.info(f"Ingesting web content: url={request.url}")

    # Scrub secrets from content
    clean_content = scrub_secrets(request.content)

    # Generate document ID
    doc_id = f"web_{hashlib.md5(request.url.encode()).hexdigest()[:12]}_{uuid.uuid4().hex[:8]}"

    # Build metadata
    metadata = {
        "type": "web",
        "url": request.url,
        "repository": request.repository,
        "ingested_at": datetime.utcnow().isoformat(),
    }
    if request.title:
        metadata["title"] = request.title
    if request.tags:
        metadata["tags"] = ",".join(request.tags)

    # Add to collection
    collection = get_collection()
    collection.add(
        documents=[clean_content],
        ids=[doc_id],
        metadatas=[metadata],
    )

    logger.info(f"Ingested web content: id={doc_id}")
    return {
        "status": "success",
        "id": doc_id,
        "url": request.url,
        "content_length": len(clean_content),
    }


@router.get("/search")
def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=5, le=20),
    repository: Optional[str] = None,
    min_score: float = Query(default=0.3, ge=0.0, le=1.0),
) -> SearchResponse:
    """
    Search memory (for CLI).

    Args:
        q: Search query
        limit: Maximum results (default 5)
        repository: Optional repository filter
        min_score: Minimum rerank score (default 0.3)
    """
    logger.info(f"Search: query='{q}', limit={limit}, repository={repository}")
    start_time = time.time()

    # Build filter
    where_filter = {"repository": repository} if repository else None

    # Search
    searcher = get_searcher()
    results = searcher.search(q, top_k=50, where_filter=where_filter, rebuild_index=True)

    # Rerank
    reranker = get_reranker()
    results = reranker.rerank(q, results, top_k=limit)

    # Filter by min_score
    filtered = [r for r in results if r.get("rerank_score", 0) >= min_score]

    timing = round((time.time() - start_time) * 1000, 2)
    logger.debug(f"Search complete: {len(filtered)} results in {timing}ms")

    return SearchResponse(
        query=q,
        results=[
            {
                "content": r.get("text", ""),
                "metadata": r.get("meta", {}),
                "score": r.get("rerank_score"),
            }
            for r in filtered
        ],
        timing_ms=timing,
    )


@router.post("/note")
def save_note(request: NoteRequest) -> dict[str, Any]:
    """
    Save a note (for CLI).

    Args:
        content: Note content
        title: Optional title
        tags: Optional tags
        repository: Repository name (default: "notes")
    """
    logger.info(f"Saving note: title={request.title}")

    # Generate document ID
    doc_id = f"note_{uuid.uuid4().hex[:16]}"

    # Build content with optional title
    full_content = request.content
    if request.title:
        full_content = f"# {request.title}\n\n{request.content}"

    # Build metadata
    metadata = {
        "type": "note",
        "repository": request.repository,
        "created_at": datetime.utcnow().isoformat(),
    }
    if request.title:
        metadata["title"] = request.title
    if request.tags:
        metadata["tags"] = ",".join(request.tags)

    # Add to collection
    collection = get_collection()
    collection.add(
        documents=[full_content],
        ids=[doc_id],
        metadatas=[metadata],
    )

    logger.info(f"Saved note: id={doc_id}")
    return {
        "status": "success",
        "id": doc_id,
        "title": request.title,
        "content_length": len(full_content),
    }


@router.get("/info")
def info() -> dict[str, str]:
    """
    Build and runtime information.

    Returns git commit, build time, and startup time for verifying
    the daemon is running the expected code version.
    """
    from src.http import get_startup_time

    return {
        "git_commit": os.environ.get("CORTEX_GIT_COMMIT", "unknown"),
        "build_time": os.environ.get("CORTEX_BUILD_TIME", "unknown"),
        "startup_time": get_startup_time(),
        "version": "1.0.0",
    }


# --- Migration/Admin Endpoints ---


@router.get("/migrations/status")
def migrations_status() -> dict[str, Any]:
    """
    Get current migration status.

    Returns schema version info and whether migrations are needed.
    """
    from src.migrations import (
        SCHEMA_VERSION,
        get_current_schema_version,
        needs_migration,
    )

    return {
        "current_version": get_current_schema_version(),
        "target_version": SCHEMA_VERSION,
        "needs_migration": needs_migration(),
    }


@router.post("/admin/backup")
def create_backup(label: Optional[str] = None) -> dict[str, Any]:
    """
    Create a database backup.

    Args:
        label: Optional label for the backup
    """
    from src.migrations import backup_database

    try:
        backup_path = backup_database(label=label or "manual")
        return {
            "status": "success",
            "backup_path": backup_path,
        }
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        return {
            "status": "error",
            "error": str(e),
        }


@router.get("/admin/backups")
def get_backups() -> dict[str, Any]:
    """List available backups."""
    from src.migrations import list_backups

    return {
        "backups": list_backups(),
    }


# --- Auto-Capture Endpoints ---


@router.post("/commit")
def commit_session(request: CommitRequest) -> dict[str, Any]:
    """
    Commit a session summary to Cortex memory.

    Used by the auto-capture hook to save session summaries.
    This is a simplified version of commit_to_cortex MCP tool.

    Args:
        summary: Session summary text
        changed_files: List of files edited in the session
        repository: Repository name (default: "global")
        initiative: Optional initiative to tag
    """
    from datetime import timezone

    logger.info(f"Commit session: repository={request.repository}, files={len(request.changed_files)}")

    # Scrub secrets from summary
    clean_summary = scrub_secrets(request.summary)

    # Generate document ID
    doc_id = f"commit:{uuid.uuid4().hex[:8]}"

    # Build document content
    content = f"Session Summary:\n\n{clean_summary}"
    if request.changed_files:
        content += f"\n\nChanged files: {', '.join(request.changed_files)}"

    # Build metadata
    metadata = {
        "type": "commit",
        "repository": request.repository,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "active",
        "source": "auto-capture",
    }

    if request.changed_files:
        import json
        metadata["files"] = json.dumps(request.changed_files)

    if request.initiative:
        metadata["initiative_name"] = request.initiative

    # Add to collection
    collection = get_collection()
    collection.add(
        documents=[content],
        ids=[doc_id],
        metadatas=[metadata],
    )

    # Rebuild search index
    try:
        searcher = get_searcher()
        searcher.build_index()
    except Exception as e:
        logger.warning(f"Failed to rebuild search index: {e}")

    logger.info(f"Committed session: id={doc_id}")

    return {
        "status": "success",
        "commit_id": doc_id,
        "summary_length": len(clean_summary),
        "files_count": len(request.changed_files),
    }


@router.get("/autocapture/status")
def autocapture_status() -> dict[str, Any]:
    """
    Get auto-capture system status.

    Returns configuration, hook status, and recent captures.
    """
    from pathlib import Path

    cortex_data = Path.home() / ".cortex"

    # Check hook installation
    hook_script = cortex_data / "hooks" / "claude_session_end.py"
    hook_log = cortex_data / "hook.log"
    captured_sessions = cortex_data / "captured_sessions.json"

    # Count recent captures
    recent_captures = 0
    if captured_sessions.exists():
        try:
            import json
            data = json.loads(captured_sessions.read_text())
            recent_captures = len(data.get("captured", []))
        except Exception:
            pass

    # Get last log entries
    last_logs = []
    if hook_log.exists():
        try:
            lines = hook_log.read_text().strip().split("\n")
            last_logs = lines[-5:]  # Last 5 log entries
        except Exception:
            pass

    return {
        "hook_script_installed": hook_script.exists(),
        "hook_script_path": str(hook_script),
        "captured_sessions_count": recent_captures,
        "last_hook_logs": last_logs,
    }
