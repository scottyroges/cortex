"""
Storage Tools

MCP tools for storage management - cleanup orphaned data and delete documents.
"""

import json
from typing import Literal, Optional

from logging_config import get_logger
from src.storage.gc import (
    cleanup_orphaned_file_metadata,
    cleanup_orphaned_insights,
    cleanup_orphaned_dependencies,
)
from src.tools.services import get_collection, get_searcher

logger = get_logger("tools.storage")


def cleanup_storage(
    action: Literal["preview", "execute"] = "preview",
    repository: Optional[str] = None,
    path: Optional[str] = None,
) -> str:
    """
    Clean up orphaned data from Cortex memory.

    Removes:
    - file_metadata for files that no longer exist on disk
    - insights linked to files that no longer exist
    - dependency documents for files that no longer exist

    **When to use this tool:**
    - After deleting or moving files in your codebase
    - After major refactoring that renamed/relocated files
    - Periodic maintenance to reclaim storage

    Args:
        action: "preview" shows what would be deleted, "execute" performs deletion
        repository: Repository to clean up (required)
        path: Absolute path to repository root (required for file existence checks)

    Returns:
        JSON with cleanup results by type
    """
    if not repository:
        return json.dumps({
            "status": "error",
            "error": "repository parameter is required",
        })

    if not path:
        return json.dumps({
            "status": "error",
            "error": "path parameter is required (absolute path to repository root)",
        })

    logger.info(f"Cleanup storage: action={action}, repository={repository}")

    dry_run = action == "preview"

    try:
        collection = get_collection()

        # Run all cleanup operations
        file_metadata_result = cleanup_orphaned_file_metadata(
            collection, path, repository, dry_run=dry_run
        )
        insights_result = cleanup_orphaned_insights(
            collection, path, repository, dry_run=dry_run
        )
        dependencies_result = cleanup_orphaned_dependencies(
            collection, path, repository, dry_run=dry_run
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
            logger.info(f"Rebuilt search index after cleanup")

        response = {
            "status": "success",
            "action": action,
            "repository": repository,
            "orphaned_file_metadata": file_metadata_result,
            "orphaned_insights": insights_result,
            "orphaned_dependencies": dependencies_result,
            "total_orphaned": total_orphaned,
            "total_deleted": total_deleted,
        }

        if action == "preview" and total_orphaned > 0:
            response["message"] = f"Found {total_orphaned} orphaned documents. Run with action='execute' to delete."

        return json.dumps(response, indent=2)

    except Exception as e:
        logger.error(f"Cleanup storage error: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e),
        })


def delete_document(
    document_id: str,
) -> str:
    """
    Delete a single document from Cortex memory by ID.

    **When to use this tool:**
    - When a note, insight, or other document is stale or no longer applies
    - When you've determined a piece of stored knowledge is outdated
    - To remove incorrectly saved documents

    Args:
        document_id: The document ID to delete (e.g., "note:abc123", "insight:def456")

    Returns:
        JSON with deletion status
    """
    if not document_id:
        return json.dumps({
            "status": "error",
            "error": "document_id parameter is required",
        })

    logger.info(f"Delete document: {document_id}")

    try:
        collection = get_collection()

        # Verify document exists
        result = collection.get(ids=[document_id], include=["metadatas"])

        if not result["ids"]:
            return json.dumps({
                "status": "error",
                "error": f"Document not found: {document_id}",
            })

        # Get document info for response
        meta = result["metadatas"][0]
        doc_type = meta.get("type", "unknown")

        # Delete the document
        collection.delete(ids=[document_id])

        # Rebuild search index
        get_searcher().build_index()

        logger.info(f"Deleted document: {document_id} (type={doc_type})")

        return json.dumps({
            "status": "deleted",
            "document_id": document_id,
            "document_type": doc_type,
        })

    except Exception as e:
        logger.error(f"Delete document error: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e),
        })
