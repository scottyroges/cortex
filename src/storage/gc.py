"""
Garbage Collection

Cleanup of deleted/renamed file chunks from ChromaDB.
"""

from typing import Any

import chromadb

from logging_config import get_logger

logger = get_logger("storage.gc")


def delete_file_chunks(
    collection: chromadb.Collection,
    file_paths: list[str],
    project_id: str,
) -> int:
    """
    Delete all chunks for the given file paths from ChromaDB.

    Args:
        collection: ChromaDB collection
        file_paths: List of file paths to delete chunks for
        project_id: Project identifier

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
                        {"project": project_id},
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
