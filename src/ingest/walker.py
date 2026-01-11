"""
Codebase Walker

File system traversal with filtering for code files.
"""

import hashlib
import os
from pathlib import Path
from typing import Generator, Optional

from src.config import BINARY_EXTENSIONS, DEFAULT_IGNORE_PATTERNS, MAX_FILE_SIZE


def walk_codebase(
    root_path: str,
    extensions: Optional[set[str]] = None,
    ignore_patterns: Optional[set[str]] = None,
) -> Generator[Path, None, None]:
    """
    Walk codebase yielding files to process.

    Args:
        root_path: Root directory to walk
        extensions: Optional set of extensions to include (e.g., {'.py', '.js'})
        ignore_patterns: Patterns to ignore (directories/files)

    Yields:
        Path objects for each file to process
    """
    ignore = ignore_patterns or DEFAULT_IGNORE_PATTERNS
    root = Path(root_path)

    for dirpath, dirnames, filenames in os.walk(root):
        # Filter out ignored directories (in-place modification)
        dirnames[:] = [
            d
            for d in dirnames
            if d not in ignore and not d.startswith(".") and not d.endswith(".egg-info")
        ]

        for filename in filenames:
            file_path = Path(dirpath) / filename

            # Skip hidden files
            if filename.startswith("."):
                continue

            # Skip binary/large files
            if file_path.suffix.lower() in BINARY_EXTENSIONS:
                continue

            # Check file size
            try:
                if file_path.stat().st_size > MAX_FILE_SIZE:
                    continue
            except OSError:
                continue

            # Filter by extension if specified
            if extensions and file_path.suffix.lower() not in extensions:
                continue

            yield file_path


def compute_file_hash(file_path: Path) -> str:
    """
    Compute MD5 hash of a file for delta sync.

    Args:
        file_path: Path to the file

    Returns:
        MD5 hash as hex string
    """
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_changed_files(
    file_paths: list[Path],
    state: dict[str, str],
) -> list[Path]:
    """
    Return only files that have changed since last ingestion.

    Args:
        file_paths: List of file paths to check
        state: State dictionary with file path -> hash mappings

    Returns:
        List of paths that have changed
    """
    changed = []

    for file_path in file_paths:
        path_str = str(file_path)
        try:
            current_hash = compute_file_hash(file_path)
            if state.get(path_str) != current_hash:
                changed.append(file_path)
        except (OSError, IOError):
            # If we can't read the file, skip it
            continue

    return changed
