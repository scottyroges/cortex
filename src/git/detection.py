"""
Git Detection Utilities

Functions for detecting git repositories and retrieving git information.
"""

from typing import Optional

from src.git.subprocess_utils import git_check, git_count_lines, git_single_line


def is_git_repo(path: str) -> bool:
    """
    Check if the given path is inside a git repository.

    Args:
        path: Directory path to check

    Returns:
        True if path is in a git repository
    """
    return git_check(["rev-parse", "--git-dir"], path)


def get_head_commit(path: str) -> Optional[str]:
    """
    Get the current HEAD commit hash.

    Args:
        path: Repository path

    Returns:
        Commit hash or None if not a git repo
    """
    return git_single_line(["rev-parse", "HEAD"], path)


def get_git_info(path: str) -> tuple[Optional[str], bool, Optional[str]]:
    """
    Get git information for a path.

    Args:
        path: Directory path to check

    Returns:
        Tuple of (branch_name, is_git_repo, repo_root)
    """
    # Check if in a git repo
    if not git_check(["rev-parse", "--git-dir"], path):
        return None, False, None

    # Get current branch and repo root
    branch = git_single_line(["rev-parse", "--abbrev-ref", "HEAD"], path)
    repo_root = git_single_line(["rev-parse", "--show-toplevel"], path)

    return branch, True, repo_root


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


def get_commits_since(path: str, since_commit: str) -> int:
    """
    Count commits since a given commit (exclusive).

    Args:
        path: Repository path
        since_commit: Commit hash to start from (not included in count)

    Returns:
        Number of commits between since_commit and HEAD
    """
    return git_count_lines(
        ["log", "--oneline", f"{since_commit}..HEAD"],
        path,
        timeout=10,
    )


def get_merge_commits_since(path: str, since_commit: str) -> int:
    """
    Count merge commits since a given commit (exclusive).

    Args:
        path: Repository path
        since_commit: Commit hash to start from (not included in count)

    Returns:
        Number of merge commits between since_commit and HEAD
    """
    return git_count_lines(
        ["log", "--oneline", "--merges", f"{since_commit}..HEAD"],
        path,
        timeout=10,
    )


def count_tracked_files(path: str) -> int:
    """
    Count git-tracked files in the repository.

    Args:
        path: Repository path

    Returns:
        Number of tracked files
    """
    return git_count_lines(["ls-files"], path, timeout=30)
