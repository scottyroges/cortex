"""
Browse Read Endpoints

HTTP endpoints for reading/querying stored documents.
"""

import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from src.configs import get_logger
from src.configs.services import get_collection, get_reranker, get_searcher

logger = get_logger("http.browse.read")

router = APIRouter()


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
