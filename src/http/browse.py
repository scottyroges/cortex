"""
Browse Endpoints

HTTP endpoints for memory browsing and exploration.
"""

import json
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from logging_config import get_logger
from src.http.resources import get_collection, get_reranker, get_searcher
from src.storage.gc import (
    cleanup_orphaned_file_metadata,
    cleanup_orphaned_insights,
    cleanup_orphaned_dependencies,
    purge_by_filters,
)

logger = get_logger("http.browse")

router = APIRouter()


class UpdateDocumentRequest(BaseModel):
    """Request model for updating a document."""

    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    files: Optional[list[str]] = None


# Editable fields per document type
EDITABLE_FIELDS = {
    "note": {"title", "content", "tags"},
    "insight": {"title", "content", "tags", "files"},
    "session_summary": {"content", "files"},
}


@router.get("/stats")
def browse_stats() -> dict[str, Any]:
    """
    Get collection statistics.

    Returns counts by repository, type, and language.
    """
    logger.info("Browse stats requested")
    collection = get_collection()

    # Get all documents with metadata
    results = collection.get(include=["metadatas"])

    stats = {
        "total_documents": len(results["ids"]),
        "by_repository": {},
        "by_type": {},
        "by_language": {},
    }

    for meta in results["metadatas"]:
        # Count by repository
        repository = meta.get("repository", "unknown")
        stats["by_repository"][repository] = stats["by_repository"].get(repository, 0) + 1

        # Count by type
        doc_type = meta.get("type", "unknown")
        stats["by_type"][doc_type] = stats["by_type"].get(doc_type, 0) + 1

        # Count by language (for code)
        lang = meta.get("language")
        if lang:
            stats["by_language"][lang] = stats["by_language"].get(lang, 0) + 1

    logger.debug(f"Stats: {stats['total_documents']} total docs")
    return stats


@router.get("/sample")
def browse_sample(limit: int = Query(default=10, le=100)) -> list[dict[str, Any]]:
    """
    Get sample documents from the collection.

    Args:
        limit: Maximum number of documents to return (max 100)
    """
    logger.info(f"Browse sample requested: limit={limit}")
    collection = get_collection()

    results = collection.get(
        limit=limit,
        include=["documents", "metadatas"],
    )

    samples = []
    for doc_id, doc, meta in zip(
        results["ids"],
        results["documents"],
        results["metadatas"],
    ):
        samples.append({
            "id": doc_id,
            "content_preview": doc[:200] + "..." if len(doc) > 200 else doc,
            "metadata": meta,
        })

    return samples


@router.get("/list")
def browse_list(
    repository: Optional[str] = None,
    doc_type: Optional[str] = Query(default=None, alias="type"),
    limit: int = Query(default=50, le=500),
) -> dict[str, Any]:
    """
    List documents with optional filtering.

    Args:
        repository: Filter by repository name
        type: Filter by document type (note, session_summary, insight, initiative, file_metadata, etc.)
        limit: Maximum results
    """
    logger.info(f"Browse list requested: repository={repository}, type={doc_type}")
    collection = get_collection()

    # Build where filter
    where_filter = None
    if repository or doc_type:
        conditions = []
        if repository:
            conditions.append({"repository": repository})
        if doc_type:
            conditions.append({"type": doc_type})

        if len(conditions) == 1:
            where_filter = conditions[0]
        else:
            where_filter = {"$and": conditions}

    results = collection.get(
        where=where_filter,
        limit=limit,
        include=["metadatas"],
    )

    return {
        "documents": [
            {"id": doc_id, "metadata": meta}
            for doc_id, meta in zip(results["ids"], results["metadatas"])
        ]
    }


@router.get("/get")
def browse_get(id: str = Query(..., alias="id")) -> dict[str, Any]:
    """
    Get a specific document by ID.

    Args:
        id: Document ID (passed as query param to handle slashes in IDs)
    """
    doc_id = id
    logger.info(f"Browse get requested: doc_id={doc_id}")
    collection = get_collection()

    results = collection.get(
        ids=[doc_id],
        include=["documents", "metadatas", "embeddings"],
    )

    if not results["ids"]:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    return {
        "id": results["ids"][0],
        "content": results["documents"][0],
        "metadata": results["metadatas"][0],
        "has_embedding": results["embeddings"] is not None and len(results["embeddings"]) > 0,
    }


@router.get("/search")
def browse_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=20, le=100),
    rerank: bool = Query(default=False),
) -> dict[str, Any]:
    """
    Search with detailed scores and timing.

    Args:
        q: Search query
        limit: Maximum results
        rerank: Whether to apply reranking
    """
    logger.info(f"Browse search: query='{q}', limit={limit}, rerank={rerank}")
    start_time = time.time()

    searcher = get_searcher()

    search_start = time.time()
    results = searcher.search(q, top_k=limit)
    search_time = time.time() - search_start

    response = {
        "query": q,
        "timing": {
            "search_ms": round(search_time * 1000, 2),
        },
        "results": [],
    }

    if rerank and results:
        rerank_start = time.time()
        reranker = get_reranker()
        results = reranker.rerank(q, results, top_k=limit)
        rerank_time = time.time() - rerank_start
        response["timing"]["rerank_ms"] = round(rerank_time * 1000, 2)

    for r in results:
        response["results"].append({
            "id": r.get("id"),
            "content_preview": r.get("text", "")[:200],
            "metadata": r.get("meta", {}),
            "scores": {
                "rrf": r.get("rrf_score"),
                "rerank": r.get("rerank_score"),
                "vector_distance": r.get("vector_distance"),
                "bm25": r.get("bm25_score"),
            },
        })

    response["timing"]["total_ms"] = round((time.time() - start_time) * 1000, 2)
    response["result_count"] = len(response["results"])

    logger.debug(f"Browse search complete: {len(response['results'])} results in {response['timing']['total_ms']}ms")
    return response


@router.put("/update")
def browse_update(
    id: str = Query(..., alias="id"),
    request: UpdateDocumentRequest = None,
) -> dict[str, Any]:
    """
    Update a document's editable fields.

    Args:
        id: Document ID
        request: Fields to update (title, content, tags, files)

    Only updates fields that are editable for the document's type.
    """
    doc_id = id
    logger.info(f"Browse update requested: doc_id={doc_id}")
    collection = get_collection()

    # Fetch existing document
    results = collection.get(
        ids=[doc_id],
        include=["documents", "metadatas", "embeddings"],
    )

    if not results["ids"]:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    current_content = results["documents"][0]
    current_metadata = results["metadatas"][0]
    current_embedding = (
        results["embeddings"][0]
        if results["embeddings"] is not None and len(results["embeddings"]) > 0
        else None
    )
    doc_type = current_metadata.get("type", "unknown")

    # Check if document type is editable
    if doc_type not in EDITABLE_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"Document type '{doc_type}' is not editable",
        )

    allowed_fields = EDITABLE_FIELDS[doc_type]
    updated_fields = []

    # Update content if provided and allowed
    new_content = current_content
    if request.content is not None and "content" in allowed_fields:
        new_content = request.content
        updated_fields.append("content")

    # Update metadata fields
    new_metadata = current_metadata.copy()

    if request.title is not None and "title" in allowed_fields:
        new_metadata["title"] = request.title
        updated_fields.append("title")

    if request.tags is not None and "tags" in allowed_fields:
        new_metadata["tags"] = json.dumps(request.tags)
        updated_fields.append("tags")

    if request.files is not None and "files" in allowed_fields:
        new_metadata["files"] = json.dumps(request.files)
        updated_fields.append("files")

    if not updated_fields:
        raise HTTPException(
            status_code=400,
            detail="No valid fields provided for update",
        )

    # Upsert the updated document
    if current_embedding is not None:
        collection.upsert(
            ids=[doc_id],
            documents=[new_content],
            metadatas=[new_metadata],
            embeddings=[current_embedding],
        )
    else:
        collection.upsert(
            ids=[doc_id],
            documents=[new_content],
            metadatas=[new_metadata],
        )

    # Rebuild search index
    get_searcher().build_index()

    logger.info(f"Document {doc_id} updated: {updated_fields}")
    return {
        "success": True,
        "id": doc_id,
        "updated_fields": updated_fields,
    }


@router.delete("/delete")
def browse_delete(id: str = Query(..., alias="id")) -> dict[str, Any]:
    """
    Delete a document by ID.

    Args:
        id: Document ID to delete
    """
    doc_id = id
    logger.info(f"Browse delete requested: doc_id={doc_id}")
    collection = get_collection()

    # Verify document exists
    results = collection.get(ids=[doc_id], include=[])

    if not results["ids"]:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    # Delete the document
    collection.delete(ids=[doc_id])

    # Rebuild search index
    get_searcher().build_index()

    logger.info(f"Document {doc_id} deleted")
    return {
        "success": True,
        "id": doc_id,
    }


@router.delete("/delete-by-type")
def browse_delete_by_type(
    doc_type: str = Query(..., alias="type"),
    repository: Optional[str] = None,
) -> dict[str, Any]:
    """
    Delete all documents of a specific type.

    Args:
        type: Document type to delete (e.g., 'code', 'note')
        repository: Optional repository filter
    """
    logger.info(f"Browse delete by type requested: type={doc_type}, repository={repository}")
    collection = get_collection()

    # Build where filter
    where_filter: dict[str, Any] = {"type": doc_type}
    if repository:
        where_filter = {"$and": [{"type": doc_type}, {"repository": repository}]}

    # Get all matching documents
    results = collection.get(where=where_filter, include=[])

    if not results["ids"]:
        return {
            "success": True,
            "deleted_count": 0,
            "message": f"No documents found with type '{doc_type}'",
        }

    # Delete all matching documents
    collection.delete(ids=results["ids"])

    # Rebuild search index
    get_searcher().build_index()

    logger.info(f"Deleted {len(results['ids'])} documents of type '{doc_type}'")
    return {
        "success": True,
        "deleted_count": len(results["ids"]),
        "type": doc_type,
    }


class CleanupRequest(BaseModel):
    """Request model for cleanup operations."""

    repository: str
    path: Optional[str] = None
    dry_run: bool = True


class PurgeRequest(BaseModel):
    """Request model for purge operations."""

    repository: Optional[str] = None
    branch: Optional[str] = None
    doc_type: Optional[str] = None
    before_date: Optional[str] = None
    after_date: Optional[str] = None
    dry_run: bool = True


@router.post("/cleanup")
def browse_cleanup(request: CleanupRequest) -> dict[str, Any]:
    """
    Clean up orphaned data for a repository.

    Removes file_metadata, insights, and dependencies for files that no longer exist.

    Args:
        request: CleanupRequest with repository, path, and dry_run flag
    """
    logger.info(f"Browse cleanup requested: repository={request.repository}, dry_run={request.dry_run}")

    if not request.path:
        raise HTTPException(
            status_code=400,
            detail="path parameter is required (absolute path to repository root)",
        )

    collection = get_collection()

    # Run all cleanup operations
    file_metadata_result = cleanup_orphaned_file_metadata(
        collection, request.path, request.repository, dry_run=request.dry_run
    )
    insights_result = cleanup_orphaned_insights(
        collection, request.path, request.repository, dry_run=request.dry_run
    )
    dependencies_result = cleanup_orphaned_dependencies(
        collection, request.path, request.repository, dry_run=request.dry_run
    )

    # Calculate totals
    total_orphaned = (
        file_metadata_result.get("count", 0) +
        insights_result.get("count", 0) +
        dependencies_result.get("count", 0)
    )
    total_deleted = (
        file_metadata_result.get("deleted", 0) +
        insights_result.get("deleted", 0) +
        dependencies_result.get("deleted", 0)
    )

    # Rebuild search index if we deleted anything
    if total_deleted > 0:
        get_searcher().build_index()
        logger.info("Rebuilt search index after cleanup")

    logger.info(f"Cleanup complete: {total_orphaned} orphaned, {total_deleted} deleted")

    return {
        "success": True,
        "repository": request.repository,
        "dry_run": request.dry_run,
        "orphaned_file_metadata": file_metadata_result,
        "orphaned_insights": insights_result,
        "orphaned_dependencies": dependencies_result,
        "total_orphaned": total_orphaned,
        "total_deleted": total_deleted,
    }


@router.post("/purge")
def browse_purge(request: PurgeRequest) -> dict[str, Any]:
    """
    Purge documents matching the specified filters.

    Args:
        request: PurgeRequest with filters and dry_run flag
    """
    logger.info(
        f"Browse purge requested: repository={request.repository}, "
        f"branch={request.branch}, type={request.doc_type}, dry_run={request.dry_run}"
    )

    # Require at least one filter
    if not any([request.repository, request.branch, request.doc_type, request.before_date, request.after_date]):
        raise HTTPException(
            status_code=400,
            detail="At least one filter is required (repository, branch, doc_type, before_date, or after_date)",
        )

    collection = get_collection()

    result = purge_by_filters(
        collection,
        repository=request.repository,
        branch=request.branch,
        doc_type=request.doc_type,
        before_date=request.before_date,
        after_date=request.after_date,
        dry_run=request.dry_run,
    )

    # Rebuild search index if we deleted anything
    if result.get("deleted_count", 0) > 0:
        get_searcher().build_index()
        logger.info("Rebuilt search index after purge")

    logger.info(f"Purge complete: {result.get('matched_count', 0)} matched, {result.get('deleted_count', 0)} deleted")

    return {
        "success": True,
        "dry_run": request.dry_run,
        **result,
    }
