"""
Garbage Collection

Cleanup operations for ChromaDB storage:
- File chunk deletion (when files are removed/renamed)
- Orphaned data cleanup (file_metadata, insights, dependencies)
- Selective purge by filters
- Document deletion
"""

from src.storage.gc.file_chunks import delete_file_chunks
from src.storage.gc.orphans import (
    cleanup_orphaned_dependencies,
    cleanup_orphaned_file_metadata,
    cleanup_orphaned_insights,
)
from src.storage.gc.purge import (
    cleanup_deprecated_insights,
    delete_document,
    purge_by_filters,
)

__all__ = [
    # File-level cleanup
    "delete_file_chunks",
    # Orphan cleanup
    "cleanup_orphaned_file_metadata",
    "cleanup_orphaned_insights",
    "cleanup_orphaned_dependencies",
    # Purge operations
    "purge_by_filters",
    "cleanup_deprecated_insights",
    "delete_document",
]
