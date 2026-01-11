"""
Git Detection Utilities

Functions for detecting git repositories and retrieving git information.
"""

import subprocess
from typing import Optional


def is_git_repo(path: str) -> bool:
    """
    Check if the given path is inside a git repository.

    Args:
        path: Directory path to check

    Returns:
        True if path is in a git repository
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def get_head_commit(path: str) -> Optional[str]:
    """
    Get the current HEAD commit hash.

    Args:
        path: Repository path

    Returns:
        Commit hash or None if not a git repo
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def get_git_info(path: str) -> tuple[Optional[str], bool, Optional[str]]:
    """
    Get git information for a path.

    Args:
        path: Directory path to check

    Returns:
        Tuple of (branch_name, is_git_repo, repo_root)
    """
    try:
        # Check if in a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None, False, None

        # Get current branch
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )

        # Get repo root
        root_result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )

        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
        repo_root = root_result.stdout.strip() if root_result.returncode == 0 else None

        return branch, True, repo_root
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None, False, None


def get_current_branch(path: str) -> str:
    """
    Get current git branch, or 'unknown' if not a git repo.

    Args:
        path: Repository path

    Returns:
        Branch name or 'unknown'
    """
    branch, is_git, _ = get_git_info(path)
    return branch if branch else "unknown"


def get_commits_since(path: str, since_timestamp: str) -> int:
    """
    Count commits since a given timestamp.

    Args:
        path: Repository path
        since_timestamp: ISO format timestamp

    Returns:
        Number of commits since timestamp
    """
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"--since={since_timestamp}"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            return len([line for line in lines if line])
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return 0


def get_merge_commits_since(path: str, since_timestamp: str) -> int:
    """
    Count merge commits since a given timestamp.

    Args:
        path: Repository path
        since_timestamp: ISO format timestamp

    Returns:
        Number of merge commits since timestamp
    """
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--merges", f"--since={since_timestamp}"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            return len([line for line in lines if line])
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return 0


def count_tracked_files(path: str) -> int:
    """
    Count git-tracked files in the repository.

    Args:
        path: Repository path

    Returns:
        Number of tracked files
    """
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            return len([line for line in lines if line])
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return 0
