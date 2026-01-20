"""
Cortex Storage Layer

ChromaDB client management and garbage collection.
"""

from src.storage.chromadb import (
    get_chroma_client,
    get_collection_stats,
    get_or_create_collection,
)
from src.storage.gc import (
    cleanup_deprecated_insights,
    cleanup_orphaned_dependencies,
    cleanup_orphaned_file_metadata,
    cleanup_orphaned_insights,
    delete_document,
    delete_file_chunks,
    purge_by_filters,
)

__all__ = [
    # Client management
    "get_chroma_client",
    "get_or_create_collection",
    "get_collection_stats",
    # Garbage collection
    "delete_file_chunks",
    "cleanup_orphaned_file_metadata",
    "cleanup_orphaned_insights",
    "cleanup_orphaned_dependencies",
    "cleanup_deprecated_insights",
    "purge_by_filters",
    "delete_document",
]
