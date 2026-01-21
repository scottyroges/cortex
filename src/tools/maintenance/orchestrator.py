"""
Cleanup Orchestration

Shared logic for orphan cleanup operations - coordinates cleanup across
file_metadata, insights, and dependencies. Used by both MCP tools
and HTTP endpoints.
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional

import chromadb

from src.configs import get_logger
from src.storage import (
    cleanup_orphaned_dependencies,
    cleanup_orphaned_file_metadata,
    cleanup_orphaned_insights,
)

logger = get_logger("maintenance.orchestrator")


@dataclass
class CleanupResult:
    """Result of cleanup orchestration."""

    file_metadata: dict[str, Any]
    """Result from cleanup_orphaned_file_metadata()."""

    insights: dict[str, Any]
    """Result from cleanup_orphaned_insights()."""

    dependencies: dict[str, Any]
    """Result from cleanup_orphaned_dependencies()."""

    total_orphaned: int
    """Total count of orphaned documents found."""

    total_deleted: int
    """Total count of documents deleted (0 if dry_run)."""

    index_rebuilt: bool
    """Whether the search index was rebuilt."""


def run_cleanup(
    collection: chromadb.Collection,
    repo_path: str,
    repository: str,
    dry_run: bool = True,
    rebuild_index_fn: Optional[Callable[[], None]] = None,
) -> CleanupResult:
    """
    Run all orphan cleanup operations and optionally rebuild search index.

    This is the shared implementation used by both:
    - cleanup_storage MCP tool
    - /cleanup HTTP endpoint

    Args:
        collection: ChromaDB collection
        repo_path: Absolute path to repository root
        repository: Repository identifier
        dry_run: If True, only report what would be deleted
        rebuild_index_fn: Optional function to rebuild search index
                         (called if deletions occurred)

    Returns:
        CleanupResult with results from each cleanup operation
    """
    logger.info(f"Running cleanup: repository={repository}, dry_run={dry_run}")

    # Run all cleanup operations
    file_metadata_result = cleanup_orphaned_file_metadata(
        collection, repo_path, repository, dry_run=dry_run
    )
    insights_result = cleanup_orphaned_insights(
        collection, repo_path, repository, dry_run=dry_run
    )
    dependencies_result = cleanup_orphaned_dependencies(
        collection, repo_path, repository, dry_run=dry_run
    )

    # Calculate totals
    total_orphaned = (
        file_metadata_result.get("count", 0)
        + insights_result.get("count", 0)
        + dependencies_result.get("count", 0)
    )
    total_deleted = (
        file_metadata_result.get("deleted", 0)
        + insights_result.get("deleted", 0)
        + dependencies_result.get("deleted", 0)
    )

    # Rebuild search index if we deleted anything
    index_rebuilt = False
    if total_deleted > 0 and rebuild_index_fn is not None:
        rebuild_index_fn()
        index_rebuilt = True
        logger.info("Rebuilt search index after cleanup")

    return CleanupResult(
        file_metadata=file_metadata_result,
        insights=insights_result,
        dependencies=dependencies_result,
        total_orphaned=total_orphaned,
        total_deleted=total_deleted,
        index_rebuilt=index_rebuilt,
    )
