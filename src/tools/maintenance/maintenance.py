"""
Maintenance Tools

MCP tools for storage management - cleanup orphaned data and delete documents.
"""

import json
from typing import Literal, Optional

from src.configs import get_logger
from src.configs.services import get_collection, get_searcher
from src.storage import delete_document as delete_document_storage
from src.tools.maintenance.orchestrator import run_cleanup

logger = get_logger("tools.maintenance")


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
        searcher = get_searcher()

        # Use shared orchestrator
        result = run_cleanup(
            collection=collection,
            repo_path=path,
            repository=repository,
            dry_run=dry_run,
            rebuild_index_fn=searcher.build_index,
        )

        response = {
            "status": "success",
            "action": action,
            "repository": repository,
            "orphaned_file_metadata": result.file_metadata,
            "orphaned_insights": result.insights,
            "orphaned_dependencies": result.dependencies,
            "total_orphaned": result.total_orphaned,
            "total_deleted": result.total_deleted,
        }

        if action == "preview" and result.total_orphaned > 0:
            response["message"] = f"Found {result.total_orphaned} orphaned documents. Run with action='execute' to delete."

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

        # Call storage layer to delete
        result = delete_document_storage(collection, document_id)

        # Rebuild search index if deletion succeeded
        if result.get("status") == "deleted":
            get_searcher().build_index()

        return json.dumps(result)

    except Exception as e:
        logger.error(f"Delete document error: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e),
        })
