"""
Codebase Walker

File system traversal with filtering for code files.
"""

import fnmatch
import hashlib
import os
from pathlib import Path
from typing import Generator, Optional

from src.config import BINARY_EXTENSIONS, MAX_FILE_SIZE, load_ignore_patterns


def walk_codebase(
    root_path: str,
    extensions: Optional[set[str]] = None,
    ignore_patterns: Optional[set[str]] = None,
    include_patterns: Optional[list[str]] = None,
    use_cortexignore: bool = True,
) -> Generator[Path, None, None]:
    """
    Walk codebase yielding files to process.

    Args:
        root_path: Root directory to walk
        extensions: Optional set of extensions to include (e.g., {'.py', '.js'})
        ignore_patterns: Additional patterns to ignore (merged with defaults + cortexignore)
        include_patterns: If provided, only files matching at least one pattern are yielded.
                          Patterns are relative to root_path (e.g., ["src/**", "tests/**"])
        use_cortexignore: If True, load patterns from global + project cortexignore files

    Yields:
        Path objects for each file to process
    """
    # Load ignore patterns (defaults + cortexignore files)
    ignore = load_ignore_patterns(root_path, use_cortexignore)
    if ignore_patterns:
        ignore = ignore | ignore_patterns

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

            # Check if file matches any ignore pattern
            rel_path = str(file_path.relative_to(root))
            if any(fnmatch.fnmatch(filename, p) or fnmatch.fnmatch(rel_path, p) for p in ignore):
                continue

            # Filter by include patterns if specified
            if include_patterns:
                if not any(fnmatch.fnmatch(rel_path, p) for p in include_patterns):
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
