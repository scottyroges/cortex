"""
File Chunk Deletion

Delete all chunks for specific file paths from ChromaDB.
Used during delta sync when files are renamed or deleted.
"""

import chromadb

from src.configs import get_logger

logger = get_logger("storage.gc.file_chunks")


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
