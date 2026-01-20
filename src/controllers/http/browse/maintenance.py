"""
Browse Maintenance Endpoints

HTTP endpoints for cleanup and purge operations.
"""

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.configs import get_logger
from src.configs.services import get_collection, get_searcher
from src.storage.gc import (
    cleanup_orphaned_file_metadata,
    cleanup_orphaned_insights,
    cleanup_orphaned_dependencies,
    purge_by_filters,
)

logger = get_logger("http.browse.maintenance")

router = APIRouter()


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
