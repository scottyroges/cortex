"""
Garbage Collection

Cleanup of deleted/renamed file chunks from ChromaDB.
Includes orphaned data detection and selective purge by filters.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import chromadb

from logging_config import get_logger

logger = get_logger("storage.gc")

# Default max age for deprecated insights before cleanup
DEPRECATED_MAX_AGE_DAYS = 180


def delete_file_chunks(
    collection: chromadb.Collection,
    file_paths: list[str],
    repo_id: str,
) -> int:
    """
    Delete all chunks for the given file paths from ChromaDB.

    Args:
        collection: ChromaDB collection
        file_paths: List of file paths to delete chunks for
        repo_id: Repository identifier

    Returns:
        Number of chunks deleted
    """
    if not file_paths:
        return 0

    deleted_count = 0
    for file_path in file_paths:
        try:
            # Query for all chunks with this file path
            results = collection.get(
                where={
                    "$and": [
                        {"file_path": file_path},
                        {"repository": repo_id},
                    ]
                },
                include=[],  # We only need IDs
            )

            if results["ids"]:
                collection.delete(ids=results["ids"])
                deleted_count += len(results["ids"])
                logger.debug(f"Deleted {len(results['ids'])} chunks for: {file_path}")

        except Exception as e:
            logger.warning(f"Failed to delete chunks for {file_path}: {e}")

    return deleted_count


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


def cleanup_orphaned_file_metadata(
    collection: chromadb.Collection,
    repo_path: str,
    repository: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    """
    Find and optionally remove file_metadata for files that don't exist on disk.

    Args:
        collection: ChromaDB collection
        repo_path: Absolute path to repository root
        repository: Repository identifier
        dry_run: If True, only report what would be deleted

    Returns:
        Dict with count, deleted, and orphaned_files list
    """
    try:
        results = collection.get(
            where={
                "$and": [
                    {"type": "file_metadata"},
                    {"repository": repository},
                ]
            },
            include=["metadatas"],
        )

        if not results["ids"]:
            return {"count": 0, "deleted": 0, "orphaned_files": []}

        orphaned_ids = []
        orphaned_files = []

        for i, doc_id in enumerate(results["ids"]):
            meta = results["metadatas"][i]
            file_path = meta.get("file_path", "")

            if file_path:
                full_path = os.path.join(repo_path, file_path)
                if not os.path.exists(full_path):
                    orphaned_ids.append(doc_id)
                    orphaned_files.append(file_path)

        deleted = 0
        if orphaned_ids and not dry_run:
            collection.delete(ids=orphaned_ids)
            deleted = len(orphaned_ids)
            logger.info(f"Deleted {deleted} orphaned file_metadata documents")

        return {
            "count": len(orphaned_ids),
            "deleted": deleted,
            "orphaned_files": orphaned_files[:20],  # Limit sample size
        }

    except Exception as e:
        logger.error(f"Failed to cleanup orphaned file_metadata: {e}")
        return {"count": 0, "deleted": 0, "orphaned_files": [], "error": str(e)}


def cleanup_orphaned_insights(
    collection: chromadb.Collection,
    repo_path: str,
    repository: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    """
    Find and optionally remove insights linked to files that don't exist.

    Args:
        collection: ChromaDB collection
        repo_path: Absolute path to repository root
        repository: Repository identifier
        dry_run: If True, only report what would be deleted

    Returns:
        Dict with count, deleted, and orphaned_ids list
    """
    try:
        results = collection.get(
            where={
                "$and": [
                    {"type": "insight"},
                    {"repository": repository},
                ]
            },
            include=["metadatas"],
        )

        if not results["ids"]:
            return {"count": 0, "deleted": 0, "orphaned_ids": []}

        orphaned_ids = []

        for i, doc_id in enumerate(results["ids"]):
            meta = results["metadatas"][i]
            files_json = meta.get("files", "[]")

            try:
                files = json.loads(files_json) if isinstance(files_json, str) else files_json
            except json.JSONDecodeError:
                files = []

            if not files:
                continue

            # Check if ALL linked files are missing
            all_missing = True
            for file_path in files:
                full_path = os.path.join(repo_path, file_path)
                if os.path.exists(full_path):
                    all_missing = False
                    break

            if all_missing:
                orphaned_ids.append(doc_id)

        deleted = 0
        if orphaned_ids and not dry_run:
            collection.delete(ids=orphaned_ids)
            deleted = len(orphaned_ids)
            logger.info(f"Deleted {deleted} orphaned insight documents")

        return {
            "count": len(orphaned_ids),
            "deleted": deleted,
            "orphaned_ids": orphaned_ids[:20],  # Limit sample size
        }

    except Exception as e:
        logger.error(f"Failed to cleanup orphaned insights: {e}")
        return {"count": 0, "deleted": 0, "orphaned_ids": [], "error": str(e)}


def cleanup_orphaned_dependencies(
    collection: chromadb.Collection,
    repo_path: str,
    repository: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    """
    Find and optionally remove dependency documents for files that don't exist.

    Args:
        collection: ChromaDB collection
        repo_path: Absolute path to repository root
        repository: Repository identifier
        dry_run: If True, only report what would be deleted

    Returns:
        Dict with count and deleted
    """
    try:
        results = collection.get(
            where={
                "$and": [
                    {"type": "dependency"},
                    {"repository": repository},
                ]
            },
            include=["metadatas"],
        )

        if not results["ids"]:
            return {"count": 0, "deleted": 0}

        orphaned_ids = []

        for i, doc_id in enumerate(results["ids"]):
            meta = results["metadatas"][i]
            file_path = meta.get("file_path", "")

            if file_path:
                full_path = os.path.join(repo_path, file_path)
                if not os.path.exists(full_path):
                    orphaned_ids.append(doc_id)

        deleted = 0
        if orphaned_ids and not dry_run:
            collection.delete(ids=orphaned_ids)
            deleted = len(orphaned_ids)
            logger.info(f"Deleted {deleted} orphaned dependency documents")

        return {
            "count": len(orphaned_ids),
            "deleted": deleted,
        }

    except Exception as e:
        logger.error(f"Failed to cleanup orphaned dependencies: {e}")
        return {"count": 0, "deleted": 0, "error": str(e)}


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
