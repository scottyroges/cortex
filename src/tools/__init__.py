"""
Cortex MCP Tools

All MCP tool implementations organized by function.
"""

from src.tools.admin import configure_cortex, get_cortex_version, get_skeleton
from src.tools.context import (
    get_context_from_cortex,
    set_initiative,
    set_repo_context,
)
from src.tools.ingest import ingest_code_into_cortex
from src.tools.initiatives import (
    complete_initiative,
    create_initiative,
    focus_initiative,
    list_initiatives,
)
from src.tools.notes import commit_to_cortex, save_note_to_cortex
from src.tools.orient import orient_session
from src.tools.search import search_cortex

__all__ = [
    # Session
    "orient_session",
    # Search
    "search_cortex",
    # Ingest
    "ingest_code_into_cortex",
    # Notes
    "save_note_to_cortex",
    "commit_to_cortex",
    # Context
    "set_repo_context",
    "set_initiative",  # Legacy - use create_initiative instead
    "get_context_from_cortex",
    # Initiatives
    "create_initiative",
    "list_initiatives",
    "focus_initiative",
    "complete_initiative",
    # Admin
    "configure_cortex",
    "get_cortex_version",
    "get_skeleton",
]
