"""
Cortex MCP Tools

All MCP tool implementations organized by function.

Consolidated tool set (12 tools):
1. orient_session - Session entry point
2. search_cortex - Search memory
3. recall_recent_work - Timeline view of recent work
4. get_skeleton - File tree structure
5. manage_initiative - CRUD for initiatives
6. save_memory - Save notes and insights
7. conclude_session - End-of-session summary
8. ingest_codebase - Code ingestion
9. validate_insight - Validate stale insights
10. configure_cortex - Configuration and status
11. cleanup_storage - Clean up orphaned data
12. delete_document - Delete a single document
"""

from src.tools.configure.admin import configure_cortex, get_skeleton
from src.tools.ingest.ingest import ingest_codebase
from src.tools.initiatives.initiatives import manage_initiative
from src.tools.notes.notes import save_memory, conclude_session, validate_insight
from src.tools.orient.orient import orient_session
from src.tools.orient.recall import recall_recent_work
from src.tools.search.search import search_cortex
from src.tools.storage_tools.storage_tools import cleanup_storage, delete_document

__all__ = [
    # Session
    "orient_session",
    # Search
    "search_cortex",
    # Recall
    "recall_recent_work",
    # Navigation
    "get_skeleton",
    # Initiatives
    "manage_initiative",
    # Memory
    "save_memory",
    "conclude_session",
    "validate_insight",
    # Ingest
    "ingest_codebase",
    # Admin
    "configure_cortex",
    # Storage
    "cleanup_storage",
    "delete_document",
]
