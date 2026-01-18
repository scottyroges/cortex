"""
Hook Installation Management

Unified interface for installing and managing Cortex hooks across
different AI coding tools.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .claude_code import (
    install_claude_code_hook,
    is_claude_code_hook_installed,
    get_claude_code_hook_status,
    uninstall_claude_code_hook,
    get_hook_script_path,
)

from logging_config import get_logger

logger = get_logger("install.hooks")


@dataclass
class HookStatus:
    """Status of hook installations."""

    claude_code_installed: bool = False
    claude_code_available: bool = False  # Is Claude CLI present?
    hook_script_exists: bool = False
    errors: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    @property
    def any_installed(self) -> bool:
        """Check if any hook is installed."""
        return self.claude_code_installed

    @property
    def summary(self) -> str:
        """Human-readable status summary."""
        parts = []
        if self.claude_code_installed:
            parts.append("Claude Code: installed (SessionEnd)")
        elif self.claude_code_available:
            parts.append("Claude Code: available but not installed")
        else:
            parts.append("Claude Code: not available")

        if self.errors:
            parts.append(f"Errors: {', '.join(self.errors)}")

        return "; ".join(parts) if parts else "No hooks configured"


def verify_hook_installation() -> HookStatus:
    """
    Verify the status of all hook installations.

    Returns:
        HookStatus with current installation state
    """
    status = HookStatus()

    # Check Claude Code
    try:
        cc_status = get_claude_code_hook_status()
        status.claude_code_available = cc_status["cli_available"]
        status.claude_code_installed = cc_status["hook_registered"]
        status.hook_script_exists = cc_status["hook_script_exists"]
        status.details["claude_code"] = cc_status
    except Exception as e:
        status.errors.append(f"Claude Code check failed: {e}")
        logger.warning(f"Failed to check Claude Code hook status: {e}")

    return status


def get_hook_status() -> HookStatus:
    """Alias for verify_hook_installation."""
    return verify_hook_installation()


def install_hooks(
    claude_code: bool = True,
    source_dir: Optional[Path] = None,
    force: bool = False,
) -> tuple[bool, list[str]]:
    """
    Install hooks for configured tools.

    Args:
        claude_code: Install Claude Code hook
        source_dir: Directory containing hook scripts (for updates)
        force: Reinstall even if already present

    Returns:
        Tuple of (overall_success, list of messages)
    """
    messages = []
    overall_success = True

    if claude_code:
        # Determine source script path
        source_script = None
        if source_dir:
            source_script = source_dir / "hooks" / "claude_session_end.py"
            if not source_script.exists():
                source_script = None

        success, msg = install_claude_code_hook(
            source_script=source_script,
            force=force,
        )
        messages.append(f"Claude Code: {msg}")
        if not success:
            overall_success = False
            logger.warning(f"Claude Code hook installation failed: {msg}")
        else:
            logger.info(f"Claude Code hook: {msg}")

    return overall_success, messages


def repair_hooks() -> tuple[bool, list[str]]:
    """
    Repair hook installations by reinstalling.

    Returns:
        Tuple of (success, list of messages)
    """
    return install_hooks(force=True)


def uninstall_hooks(claude_code: bool = True) -> tuple[bool, list[str]]:
    """
    Uninstall hooks from configured tools.

    Args:
        claude_code: Uninstall Claude Code hook

    Returns:
        Tuple of (overall_success, list of messages)
    """
    messages = []
    overall_success = True

    if claude_code:
        success, msg = uninstall_claude_code_hook()
        messages.append(f"Claude Code: {msg}")
        if not success:
            overall_success = False

    return overall_success, messages


def copy_hook_scripts(
    source_dir: Path,
    target_dir: Optional[Path] = None,
) -> tuple[bool, str]:
    """
    Copy hook scripts from source to installation directory.

    Used during cortex update to refresh hook scripts.

    Args:
        source_dir: Directory containing hooks/ subdirectory
        target_dir: Target directory (defaults to ~/.cortex/hooks)

    Returns:
        Tuple of (success, message)
    """
    import shutil

    if target_dir is None:
        target_dir = Path.home() / ".cortex" / "hooks"

    source_hooks = source_dir / "hooks"
    if not source_hooks.exists():
        return False, f"Source hooks directory not found: {source_hooks}"

    try:
        target_dir.mkdir(parents=True, exist_ok=True)

        # Copy each hook script
        copied = []
        for script in source_hooks.glob("*.py"):
            target = target_dir / script.name
            shutil.copy2(script, target)
            target.chmod(0o755)
            copied.append(script.name)

        if copied:
            return True, f"Copied hooks: {', '.join(copied)}"
        return True, "No hook scripts found to copy"

    except IOError as e:
        return False, f"Failed to copy hooks: {e}"
