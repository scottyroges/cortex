"""
Git Subprocess Utilities

Common patterns for executing git commands with consistent error handling.
"""

import os
import subprocess
from typing import Optional

from logging_config import get_logger
from src.config import get_timeout
from src.exceptions import GitCommandError

logger = get_logger("git.subprocess")


# Re-export for backwards compatibility
__all__ = ["GitCommandError", "run_git_command", "git_stdout", "git_stdout_or_none", "git_count_lines", "git_check"]

# Default timeout for git commands
GIT_TIMEOUT = int(get_timeout("git_command", 10))


def run_git_command(
    args: list[str],
    cwd: str,
    timeout: int | None = None,
) -> tuple[int, str, str]:
    """
    Low-level wrapper around subprocess.run for git commands.

    Args:
        args: Git command arguments (without 'git' prefix)
        cwd: Working directory
        timeout: Timeout in seconds (defaults to config value)

    Returns:
        Tuple of (returncode, stdout, stderr)

    Raises:
        GitCommandError: On FileNotFoundError or TimeoutExpired
    """
    if timeout is None:
        timeout = GIT_TIMEOUT
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        raise GitCommandError("git not found in PATH")
    except subprocess.TimeoutExpired:
        raise GitCommandError(f"git command timed out after {timeout}s: {args}")


def git_check(
    args: list[str],
    cwd: str,
    timeout: int | None = None,
) -> bool:
    """
    Execute git command and check if successful (returncode == 0).

    Used for: is_git_repo(), validation checks

    Args:
        args: Git command arguments (without 'git' prefix)
        cwd: Working directory
        timeout: Timeout in seconds

    Returns:
        True if returncode is 0, False otherwise
    """
    try:
        returncode, _, _ = run_git_command(args, cwd, timeout)
        return returncode == 0
    except GitCommandError:
        return False


def git_single_line(
    args: list[str],
    cwd: str,
    timeout: int = 5,
) -> Optional[str]:
    """
    Execute git command and extract single string value from stdout.

    Used for: get_head_commit(), get_current_branch(), repo root retrieval

    Args:
        args: Git command arguments (without 'git' prefix)
        cwd: Working directory
        timeout: Timeout in seconds

    Returns:
        Stripped stdout line or None if command fails
    """
    try:
        returncode, stdout, _ = run_git_command(args, cwd, timeout)
        if returncode == 0:
            return stdout.strip()
    except GitCommandError:
        pass
    return None


def git_count_lines(
    args: list[str],
    cwd: str,
    timeout: int = 5,
) -> int:
    """
    Execute git command and count non-empty lines in output.

    Used for: get_commits_since(), get_merge_commits_since(), count_tracked_files()

    Args:
        args: Git command arguments (without 'git' prefix)
        cwd: Working directory
        timeout: Timeout in seconds

    Returns:
        Number of non-empty lines, or 0 if command fails
    """
    try:
        returncode, stdout, _ = run_git_command(args, cwd, timeout)
        if returncode == 0:
            lines = stdout.strip().split("\n")
            return len([line for line in lines if line])
    except GitCommandError:
        pass
    return 0


def git_list_files(
    args: list[str],
    cwd: str,
    prefix_with_path: bool = True,
    timeout: int = 30,
) -> list[str]:
    """
    Execute git command and extract file paths from output.

    Used for: get_untracked_files(), listing tracked files

    Args:
        args: Git command arguments (without 'git' prefix)
        cwd: Working directory
        prefix_with_path: If True, join each file with cwd using os.path.join
        timeout: Timeout in seconds

    Returns:
        List of file paths (absolute if prefix_with_path=True)
    """
    try:
        returncode, stdout, _ = run_git_command(args, cwd, timeout)
        if returncode == 0:
            files = [f for f in stdout.strip().split("\n") if f]
            if prefix_with_path:
                return [os.path.join(cwd, f) for f in files]
            return files
    except GitCommandError:
        pass
    return []


def git_diff_name_status(
    cwd: str,
    since_commit: str,
    timeout: int = 30,
) -> tuple[int, str, str]:
    """
    Execute git diff --name-status with rename detection.

    Used for: get_git_changed_files()

    Args:
        cwd: Working directory
        since_commit: Commit to compare against
        timeout: Timeout in seconds

    Returns:
        Tuple of (returncode, stdout, stderr)
    """
    try:
        return run_git_command(
            ["diff", "--name-status", "-M", since_commit, "HEAD"],
            cwd,
            timeout,
        )
    except GitCommandError as e:
        logger.warning(f"git diff failed: {e}")
        return 1, "", str(e)
