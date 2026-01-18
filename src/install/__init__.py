"""
Hook Installation Module

Handles automatic installation and maintenance of Claude Code hooks
and integration with other AI coding tools.
"""

from .hooks import (
    HookStatus,
    install_hooks,
    verify_hook_installation,
    get_hook_status,
    repair_hooks,
    copy_hook_scripts,
)
from .claude_code import (
    install_claude_code_hook,
    is_claude_code_hook_installed,
    get_claude_settings_path,
)

__all__ = [
    # Hook management
    "HookStatus",
    "install_hooks",
    "verify_hook_installation",
    "get_hook_status",
    "repair_hooks",
    "copy_hook_scripts",
    # Claude Code specific
    "install_claude_code_hook",
    "is_claude_code_hook_installed",
    "get_claude_settings_path",
]
