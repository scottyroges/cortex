"""
Orphaned Data Cleanup

Find and remove documents whose linked files no longer exist on disk:
- file_metadata for deleted files
- insights linked to deleted files
- dependencies for deleted files
"""

import json
import os
from typing import Any

import chromadb

from src.configs import get_logger

logger = get_logger("storage.gc.orphans")


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
