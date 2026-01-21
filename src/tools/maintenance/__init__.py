"""
Maintenance Tools

MCP tools for storage management - cleanup orphaned data and delete documents.
"""

from src.tools.maintenance.maintenance import (
    cleanup_storage,
    delete_document,
)
from src.tools.maintenance.orchestrator import (
    CleanupResult,
    run_cleanup,
)

__all__ = [
    # MCP tools
    "cleanup_storage",
    "delete_document",
    # Orchestration (shared logic for MCP and HTTP)
    "CleanupResult",
    "run_cleanup",
]
