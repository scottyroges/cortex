"""
Purge Operations

Selective deletion of documents by filters, deprecated insight cleanup,
and single document deletion.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import chromadb

from src.configs import get_logger

logger = get_logger("storage.gc.purge")

# Default max age for deprecated insights before cleanup
DEPRECATED_MAX_AGE_DAYS = 180


def cleanup_deprecated_insights(
    collection: chromadb.Collection,
    max_age_days: int = DEPRECATED_MAX_AGE_DAYS,
    repository: str | None = None,
) -> int:
    """
    Remove deprecated insights older than max_age_days.

    Deprecated insights are kept for a period to allow recovery,
    but eventually cleaned up to save storage space.

    Args:
        collection: ChromaDB collection
        max_age_days: Maximum age in days for deprecated insights
        repository: Optional repository filter

    Returns:
        Number of insights deleted
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()

    try:
        # Build filter for deprecated insights older than cutoff
        where_filter: dict[str, Any] = {
            "$and": [
                {"type": "insight"},
                {"status": "deprecated"},
            ]
        }

        if repository:
            where_filter["$and"].append({"repository": repository})

        # Query for deprecated insights
        results = collection.get(
            where=where_filter,
            include=["metadatas"],
        )

        if not results["ids"]:
            logger.debug("No deprecated insights found")
            return 0

        # Filter by deprecated_at timestamp
        ids_to_delete = []
        for i, doc_id in enumerate(results["ids"]):
            meta = results["metadatas"][i]
            deprecated_at = meta.get("deprecated_at", "")

            if deprecated_at and deprecated_at < cutoff:
                ids_to_delete.append(doc_id)

        if ids_to_delete:
            collection.delete(ids=ids_to_delete)
            logger.info(f"Cleaned up {len(ids_to_delete)} deprecated insights older than {max_age_days} days")
            return len(ids_to_delete)

        return 0

    except Exception as e:
        logger.error(f"Failed to cleanup deprecated insights: {e}")
        return 0


def purge_by_filters(
    collection: chromadb.Collection,
    repository: str | None = None,
    branch: str | None = None,
    doc_type: str | None = None,
    before_date: str | None = None,
    after_date: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """
    Delete documents matching the provided filters.

    Args:
        collection: ChromaDB collection
        repository: Filter by repository name
        branch: Filter by branch
        doc_type: Filter by document type
        before_date: Delete documents created before this date (ISO 8601)
        after_date: Delete documents created after this date (ISO 8601)
        dry_run: If True, only report what would be deleted

    Returns:
        Dict with matched_count, deleted_count, sample_ids, and filters_applied
    """
    try:
        # Build where filter
        conditions = []

        if repository:
            conditions.append({"repository": repository})
        if branch:
            conditions.append({"branch": branch})
        if doc_type:
            conditions.append({"type": doc_type})

        where_filter = None
        if len(conditions) == 1:
            where_filter = conditions[0]
        elif len(conditions) > 1:
            where_filter = {"$and": conditions}

        # Query matching documents
        results = collection.get(
            where=where_filter,
            include=["metadatas"],
        )

        if not results["ids"]:
            return {
                "matched_count": 0,
                "deleted_count": 0,
                "sample_ids": [],
                "filters_applied": {
                    "repository": repository,
                    "branch": branch,
                    "doc_type": doc_type,
                    "before_date": before_date,
                    "after_date": after_date,
                },
            }

        # Apply date filters (post-query since ChromaDB string comparison is limited)
        ids_to_delete = []
        for i, doc_id in enumerate(results["ids"]):
            meta = results["metadatas"][i]
            created_at = meta.get("created_at", "")

            # Check date filters
            if before_date and created_at and created_at >= before_date:
                continue
            if after_date and created_at and created_at <= after_date:
                continue

            ids_to_delete.append(doc_id)

        deleted_count = 0
        if ids_to_delete and not dry_run:
            collection.delete(ids=ids_to_delete)
            deleted_count = len(ids_to_delete)
            logger.info(f"Purged {deleted_count} documents matching filters")

        return {
            "matched_count": len(ids_to_delete),
            "deleted_count": deleted_count,
            "sample_ids": ids_to_delete[:10],  # Limit sample size
            "filters_applied": {
                "repository": repository,
                "branch": branch,
                "doc_type": doc_type,
                "before_date": before_date,
                "after_date": after_date,
            },
        }

    except Exception as e:
        logger.error(f"Failed to purge documents: {e}")
        return {
            "matched_count": 0,
            "deleted_count": 0,
            "sample_ids": [],
            "error": str(e),
        }


def delete_document(
    collection: chromadb.Collection,
    document_id: str,
) -> dict[str, Any]:
    """
    Delete a single document from ChromaDB by ID.

    Args:
        collection: ChromaDB collection
        document_id: The document ID to delete (e.g., "note:abc123", "insight:def456")

    Returns:
        Dict with status, document_id, and document_type (or error)
    """
    if not document_id:
        return {
            "status": "error",
            "error": "document_id parameter is required",
        }

    try:
        # Verify document exists
        result = collection.get(ids=[document_id], include=["metadatas"])

        if not result["ids"]:
            return {
                "status": "error",
                "error": f"Document not found: {document_id}",
            }

        # Get document info for response
        meta = result["metadatas"][0]
        doc_type = meta.get("type", "unknown")

        # Delete the document
        collection.delete(ids=[document_id])

        logger.info(f"Deleted document: {document_id} (type={doc_type})")

        return {
            "status": "deleted",
            "document_id": document_id,
            "document_type": doc_type,
        }

    except Exception as e:
        logger.error(f"Delete document error: {e}")
        return {
            "status": "error",
            "error": str(e),
        }
