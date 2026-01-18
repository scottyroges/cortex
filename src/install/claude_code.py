"""
Claude Code Integration

Handles installation and configuration of hooks for Claude Code.
Manages the ~/.claude/settings.json configuration file.
"""

import json
import shutil
from pathlib import Path
from typing import Optional

from logging_config import get_logger
from src.config import get_timeout

logger = get_logger("install.claude_code")

# Hook configuration for Claude Code (new matcher-based format)
# See: https://code.claude.com/docs/en/hooks


def get_hook_timeout() -> int:
    """Get hook timeout in milliseconds from config."""
    return int(get_timeout("hook_execution_ms", 15000))


def get_claude_settings_path() -> Path:
    """Get the path to Claude Code settings.json."""
    return Path.home() / ".claude" / "settings.json"


def get_cortex_hooks_dir() -> Path:
    """Get the Cortex hooks directory."""
    return Path.home() / ".cortex" / "hooks"


def get_hook_script_path() -> Path:
    """Get the path where the session end hook script should be installed."""
    return get_cortex_hooks_dir() / "claude_session_end.py"


def is_claude_cli_available() -> bool:
    """Check if the claude CLI is installed and available."""
    return shutil.which("claude") is not None


def load_claude_settings() -> dict:
    """
    Load existing Claude Code settings or return empty dict.

    Returns:
        Settings dictionary (may be empty if file doesn't exist)
    """
    settings_path = get_claude_settings_path()
    if not settings_path.exists():
        return {}

    try:
        return json.loads(settings_path.read_text())
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to read Claude settings: {e}")
        return {}


def save_claude_settings(settings: dict) -> bool:
    """
    Save settings to Claude Code settings.json.

    Args:
        settings: Settings dictionary to save

    Returns:
        True if successful, False otherwise
    """
    settings_path = get_claude_settings_path()

    try:
        # Ensure directory exists
        settings_path.parent.mkdir(parents=True, exist_ok=True)

        # Write with pretty formatting
        settings_path.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
        )
        return True
    except IOError as e:
        logger.error(f"Failed to write Claude settings: {e}")
        return False


def is_claude_code_hook_installed() -> bool:
    """
    Check if Cortex SessionEnd hook is installed in Claude Code.

    Detects both old format (deprecated) and new matcher-based format.

    Returns:
        True if at least SessionEnd hook is registered in settings.json
    """
    settings = load_claude_settings()
    hooks = settings.get("hooks", {})
    session_end_hooks = hooks.get("SessionEnd", [])

    hook_script = str(get_hook_script_path())

    for entry in session_end_hooks:
        # New format: {"matcher": {...}, "hooks": [...]}
        if "hooks" in entry:
            for hook in entry.get("hooks", []):
                command = hook.get("command", "")
                if hook_script in command:
                    return True
        # Old format (deprecated): {"command": "...", "args": [...]}
        elif "args" in entry:
            args = entry.get("args", [])
            if args and hook_script in args[0]:
                return True

    return False


def _is_old_format_hook(entry: dict, hook_script: str) -> bool:
    """Check if an entry is our hook in the old deprecated format."""
    if "args" in entry and "hooks" not in entry:
        args = entry.get("args", [])
        return bool(args and hook_script in args[0])
    return False


def _is_new_format_hook(entry: dict, hook_script: str) -> bool:
    """Check if an entry is our hook in the new matcher format."""
    if "hooks" in entry:
        for hook in entry.get("hooks", []):
            command = hook.get("command", "")
            if hook_script in command:
                return True
    return False


def install_claude_code_hook(
    source_script: Optional[Path] = None,
    force: bool = False,
) -> tuple[bool, str]:
    """
    Install Cortex SessionEnd hook for Claude Code.

    This function:
    1. Copies hook script to ~/.cortex/hooks/
    2. Registers hook in ~/.claude/settings.json

    Args:
        source_script: Path to the hook script source (uses bundled if None)
        force: Reinstall even if already present

    Returns:
        Tuple of (success, message)
    """
    # Check if already installed
    if not force and is_claude_code_hook_installed():
        return True, "Hook already installed"

    # Ensure hooks directory exists
    hooks_dir = get_cortex_hooks_dir()
    hooks_dir.mkdir(parents=True, exist_ok=True)

    # Copy SessionEnd hook script
    target_script = get_hook_script_path()

    if source_script and source_script.exists():
        # Copy from provided source
        try:
            shutil.copy2(source_script, target_script)
        except IOError as e:
            return False, f"Failed to copy hook script: {e}"
    elif not target_script.exists():
        # Create a placeholder that will be replaced by cortex update
        return False, "Hook script not found. Run 'cortex update' to install."

    # Make executable
    try:
        target_script.chmod(0o755)
    except IOError:
        pass  # Non-fatal on some systems

    # Register in Claude settings
    settings = load_claude_settings()

    # Initialize hooks structure if needed
    if "hooks" not in settings:
        settings["hooks"] = {}
    if "SessionEnd" not in settings["hooks"]:
        settings["hooks"]["SessionEnd"] = []

    hook_script_str = str(target_script)

    # Check for old format hooks and migrate them
    old_hooks_removed = _migrate_old_format_hooks(settings, hook_script_str)

    settings_changed = old_hooks_removed

    # Build SessionEnd hook config
    # See: https://code.claude.com/docs/en/hooks
    session_end_hook = {
        "hooks": [
            {
                "type": "command",
                "command": f"python3 {hook_script_str}",
                "timeout": get_hook_timeout(),
            }
        ],
    }

    # Check if SessionEnd is already registered
    session_end_registered = any(
        _is_new_format_hook(entry, hook_script_str)
        for entry in settings["hooks"]["SessionEnd"]
    )

    if not session_end_registered:
        settings["hooks"]["SessionEnd"].append(session_end_hook)
        settings_changed = True

    if settings_changed:
        if not save_claude_settings(settings):
            return False, "Failed to update Claude settings"

    msg = "Hook installed (SessionEnd)"
    if old_hooks_removed:
        msg += " - migrated from old format"
    return True, msg


def _migrate_old_format_hooks(settings: dict, hook_script_str: str) -> bool:
    """
    Remove old format Cortex hooks and fix invalid matcher formats.

    Handles:
    1. Old format hooks with "args" field (deprecated)
    2. New format hooks with invalid "matcher": {} (SessionEnd doesn't use matchers)

    Args:
        settings: Claude settings dict (modified in place)
        hook_script_str: Path to our hook script

    Returns:
        True if any migrations were performed
    """
    session_end_hooks = settings.get("hooks", {}).get("SessionEnd", [])
    migrated = False

    # Remove old format entries (those with "args")
    original_count = len(session_end_hooks)
    new_hooks = [
        entry for entry in session_end_hooks
        if not _is_old_format_hook(entry, hook_script_str)
    ]

    if len(new_hooks) != original_count:
        settings["hooks"]["SessionEnd"] = new_hooks
        logger.info("Removed old format Cortex hooks")
        migrated = True
        session_end_hooks = new_hooks

    # Fix hooks with invalid matcher field (SessionEnd doesn't use matchers)
    for entry in session_end_hooks:
        if _is_new_format_hook(entry, hook_script_str):
            if "matcher" in entry:
                del entry["matcher"]
                logger.info("Removed invalid matcher field from SessionEnd hook")
                migrated = True

    return migrated


def uninstall_claude_code_hook() -> tuple[bool, str]:
    """
    Remove Cortex SessionEnd hook from Claude Code.

    Handles both old format and new matcher-based format.

    Returns:
        Tuple of (success, message)
    """
    # Remove from settings
    settings = load_claude_settings()
    hooks = settings.get("hooks", {})
    settings_changed = False

    # Remove SessionEnd hooks
    session_end_hooks = hooks.get("SessionEnd", [])
    hook_script_str = str(get_hook_script_path())

    new_session_end = [
        entry for entry in session_end_hooks
        if not _is_old_format_hook(entry, hook_script_str)
        and not _is_new_format_hook(entry, hook_script_str)
    ]

    if len(new_session_end) != len(session_end_hooks):
        settings["hooks"]["SessionEnd"] = new_session_end
        settings_changed = True

    if settings_changed:
        if not save_claude_settings(settings):
            return False, "Failed to update Claude settings"

    # Remove hook script
    hook_script = get_hook_script_path()
    if hook_script.exists():
        try:
            hook_script.unlink()
        except IOError as e:
            logger.warning(f"Failed to remove hook script {hook_script}: {e}")

    return True, "Hook uninstalled"


def get_claude_code_hook_status() -> dict:
    """
    Get detailed status of the Claude Code hook installation.

    Returns:
        Dictionary with status information
    """
    hook_script = get_hook_script_path()
    settings_path = get_claude_settings_path()
    hook_script_str = str(hook_script)

    # Detect format
    settings = load_claude_settings()
    session_end_hooks = settings.get("hooks", {}).get("SessionEnd", [])

    format_type = None
    for entry in session_end_hooks:
        if _is_new_format_hook(entry, hook_script_str):
            format_type = "new"
            break
        elif _is_old_format_hook(entry, hook_script_str):
            format_type = "old"
            break

    return {
        "cli_available": is_claude_cli_available(),
        "hook_registered": is_claude_code_hook_installed(),
        "hook_script_exists": hook_script.exists(),
        "hook_script_path": hook_script_str,
        "settings_file_exists": settings_path.exists(),
        "settings_file_path": str(settings_path),
        "hook_format": format_type,  # "new", "old", or None
        "needs_migration": format_type == "old",
    }
