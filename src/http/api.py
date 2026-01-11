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
    project: str = "web"


class NoteRequest(BaseModel):
    """Request body for note creation."""
    content: str
    title: Optional[str] = None
    tags: Optional[list[str]] = None
    project: str = "notes"


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
        project: Project name (default: "web")
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
        "project": request.project,
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
    project: Optional[str] = None,
    min_score: float = Query(default=0.3, ge=0.0, le=1.0),
) -> SearchResponse:
    """
    Search memory (for CLI).

    Args:
        q: Search query
        limit: Maximum results (default 5)
        project: Optional project filter
        min_score: Minimum rerank score (default 0.3)
    """
    logger.info(f"Search: query='{q}', limit={limit}, project={project}")
    start_time = time.time()

    # Build filter
    where_filter = {"project": project} if project else None

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
        project: Project name (default: "notes")
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
        "project": request.project,
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
