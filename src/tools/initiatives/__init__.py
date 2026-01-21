"""
Initiative Management Tools

MCP tools for managing multi-session initiatives.
"""

from src.tools.initiatives.focus import (
    get_any_focused_repository,
    get_focus,
    get_focus_id,
    get_focused_initiative,
    get_focused_initiative_info,
    set_focus,
    clear_focus,
)
from src.tools.initiatives.initiatives import (
    complete_initiative,
    create_initiative,
    focus_initiative,
    list_initiatives,
    manage_initiative,
    summarize_initiative,
)
from src.tools.initiatives.utils import (
    COMPLETION_SIGNALS,
    STALE_THRESHOLD_DAYS,
    calculate_duration,
    calculate_duration_from_now,
    check_initiative_staleness,
    detect_completion_signals,
    find_initiative,
    resolve_initiative,
    resolve_initiative_id,
)

__all__ = [
    # Constants
    "COMPLETION_SIGNALS",
    "STALE_THRESHOLD_DAYS",
    # Main tool
    "manage_initiative",
    # Individual action functions
    "create_initiative",
    "list_initiatives",
    "focus_initiative",
    "complete_initiative",
    "summarize_initiative",
    # Focus management
    "get_any_focused_repository",
    "get_focus",
    "get_focus_id",
    "get_focused_initiative",
    "get_focused_initiative_info",
    "set_focus",
    "clear_focus",
    # Utilities
    "find_initiative",
    "resolve_initiative",
    "resolve_initiative_id",
    "calculate_duration",
    "calculate_duration_from_now",
    "detect_completion_signals",
    "check_initiative_staleness",
]
