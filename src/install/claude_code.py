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

logger = get_logger("install.claude_code")

# Hook configuration for Claude Code
CORTEX_HOOK_CONFIG = {
    "command": "python3",
    "timeout": 15000,  # 15 seconds for LLM summarization
}


def get_claude_settings_path() -> Path:
    """Get the path to Claude Code settings.json."""
    return Path.home() / ".claude" / "settings.json"


def get_cortex_hooks_dir() -> Path:
    """Get the Cortex hooks directory."""
    return Path.home() / ".cortex" / "hooks"


def get_hook_script_path() -> Path:
    """Get the path where the hook script should be installed."""
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
    Check if the Cortex hook is already installed in Claude Code.

    Returns:
        True if hook is registered in settings.json
    """
    settings = load_claude_settings()
    hooks = settings.get("hooks", {})
    session_end_hooks = hooks.get("SessionEnd", [])

    hook_script = str(get_hook_script_path())

    for hook in session_end_hooks:
        args = hook.get("args", [])
        if args and hook_script in args[0]:
            return True

    return False


def install_claude_code_hook(
    source_script: Optional[Path] = None,
    force: bool = False,
) -> tuple[bool, str]:
    """
    Install the Cortex SessionEnd hook for Claude Code.

    This function:
    1. Copies the hook script to ~/.cortex/hooks/
    2. Registers the hook in ~/.claude/settings.json

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

    # Copy hook script
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

    # Build our hook config
    cortex_hook = {
        **CORTEX_HOOK_CONFIG,
        "args": [str(target_script)],
    }

    # Check if we're already registered (by script path)
    hook_script_str = str(target_script)
    already_registered = any(
        hook.get("args", [None])[0] == hook_script_str
        for hook in settings["hooks"]["SessionEnd"]
    )

    if not already_registered:
        settings["hooks"]["SessionEnd"].append(cortex_hook)

        if not save_claude_settings(settings):
            return False, "Failed to update Claude settings"

    return True, f"Hook installed at {target_script}"


def uninstall_claude_code_hook() -> tuple[bool, str]:
    """
    Remove the Cortex hook from Claude Code.

    Returns:
        Tuple of (success, message)
    """
    # Remove from settings
    settings = load_claude_settings()
    hooks = settings.get("hooks", {})
    session_end_hooks = hooks.get("SessionEnd", [])

    hook_script_str = str(get_hook_script_path())

    # Filter out our hook
    new_hooks = [
        hook for hook in session_end_hooks
        if hook.get("args", [None])[0] != hook_script_str
    ]

    if len(new_hooks) != len(session_end_hooks):
        settings["hooks"]["SessionEnd"] = new_hooks
        if not save_claude_settings(settings):
            return False, "Failed to update Claude settings"

    # Optionally remove hook script
    hook_script = get_hook_script_path()
    if hook_script.exists():
        try:
            hook_script.unlink()
        except IOError as e:
            logger.warning(f"Failed to remove hook script: {e}")

    return True, "Hook uninstalled"


def get_claude_code_hook_status() -> dict:
    """
    Get detailed status of the Claude Code hook installation.

    Returns:
        Dictionary with status information
    """
    hook_script = get_hook_script_path()
    settings_path = get_claude_settings_path()

    return {
        "cli_available": is_claude_cli_available(),
        "hook_registered": is_claude_code_hook_installed(),
        "hook_script_exists": hook_script.exists(),
        "hook_script_path": str(hook_script),
        "settings_file_exists": settings_path.exists(),
        "settings_file_path": str(settings_path),
    }
