"""
Cortex Git Integration

Git detection, branch tracking, and delta sync utilities.
"""

from src.git.detection import (
    count_tracked_files,
    get_commits_since,
    get_current_branch,
    get_git_info,
    get_head_commit,
    get_merge_commits_since,
    is_git_repo,
)
from src.git.delta import get_git_changed_files, get_untracked_files

__all__ = [
    "is_git_repo",
    "get_head_commit",
    "get_git_info",
    "get_current_branch",
    "get_git_changed_files",
    "get_untracked_files",
    "get_commits_since",
    "get_merge_commits_since",
    "count_tracked_files",
]
