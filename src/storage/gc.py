"""
Garbage Collection

Cleanup of deleted/renamed file chunks from ChromaDB.
"""

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


def cleanup_state_entries(
    state: dict[str, Any],
    deleted_files: list[str],
) -> None:
    """
    Remove deleted files from state's file_hashes.

    Args:
        state: State dictionary with file_hashes key
        deleted_files: List of file paths to remove
    """
    file_hashes = state.get("file_hashes", {})
    for file_path in deleted_files:
        file_hashes.pop(file_path, None)


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
