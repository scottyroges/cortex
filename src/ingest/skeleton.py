"""
Project Skeleton Generation

Generate and store tree structure for file-path grounding.
"""

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import chromadb

from logging_config import get_logger
from src.config import DEFAULT_IGNORE_PATTERNS

logger = get_logger("ingest.skeleton")


def generate_tree_structure(
    root_path: str,
    max_depth: int = 10,
    ignore_patterns: Optional[set[str]] = None,
) -> tuple[str, dict]:
    """
    Generate tree output for a project directory.

    Tries system `tree` command first, falls back to Python implementation.

    Args:
        root_path: Root directory path
        max_depth: Maximum depth to traverse
        ignore_patterns: Patterns to ignore (uses DEFAULT_IGNORE_PATTERNS if None)

    Returns:
        Tuple of (tree_text, stats_dict)
    """
    root = Path(root_path)
    ignore = ignore_patterns or DEFAULT_IGNORE_PATTERNS

    # Try system 'tree' command first
    try:
        ignore_pattern = "|".join(ignore)
        result = subprocess.run(
            ["tree", "-L", str(max_depth), "-a", "-I", ignore_pattern, "--noreport"],
            cwd=root_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            tree_output = result.stdout.strip()
        else:
            tree_output = _generate_tree_fallback(root, max_depth, ignore)
    except FileNotFoundError:
        # 'tree' command not installed
        tree_output = _generate_tree_fallback(root, max_depth, ignore)
    except subprocess.TimeoutExpired:
        tree_output = _generate_tree_fallback(root, max_depth, ignore)

    # Calculate stats
    stats = _analyze_tree(tree_output)

    return tree_output, stats


def _generate_tree_fallback(
    root: Path,
    max_depth: int,
    ignore: set[str],
) -> str:
    """Pure-Python tree generation fallback."""

    def traverse(path: Path, prefix: str = "", depth: int = 0) -> list[str]:
        if depth > max_depth:
            return []

        lines = []
        try:
            items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            # Filter ignored items
            items = [
                i
                for i in items
                if i.name not in ignore
                and not i.name.startswith(".")
                and not i.name.endswith(".egg-info")
            ]

            for i, item in enumerate(items):
                is_last = i == len(items) - 1
                current_prefix = "└── " if is_last else "├── "
                lines.append(f"{prefix}{current_prefix}{item.name}")

                if item.is_dir():
                    next_prefix = prefix + ("    " if is_last else "│   ")
                    lines.extend(traverse(item, next_prefix, depth + 1))
        except PermissionError:
            pass

        return lines

    tree_lines = [root.name]
    tree_lines.extend(traverse(root))
    return "\n".join(tree_lines)


def _analyze_tree(tree_output: str) -> dict:
    """Extract stats from tree output."""
    lines = tree_output.split("\n")
    file_count = 0
    dir_count = 0

    for line in lines[1:]:  # Skip root
        # Count entries (lines with tree connectors)
        if "├── " in line or "└── " in line:
            # Directories typically don't have extensions or end with /
            name = line.split("── ")[-1] if "── " in line else ""
            if "." in name and not name.endswith("/"):
                file_count += 1
            else:
                dir_count += 1

    return {
        "total_lines": len(lines),
        "total_files": file_count,
        "total_dirs": dir_count,
    }


def store_skeleton(
    collection: chromadb.Collection,
    tree_output: str,
    project_id: str,
    branch: str,
    stats: dict,
) -> str:
    """
    Store skeleton in collection with type='skeleton' metadata.

    Args:
        collection: ChromaDB collection
        tree_output: The tree structure text
        project_id: Project identifier
        branch: Git branch name
        stats: Tree statistics

    Returns:
        Document ID
    """
    doc_id = f"{project_id}:skeleton:{branch}"

    collection.upsert(
        ids=[doc_id],
        documents=[tree_output],
        metadatas=[
            {
                "type": "skeleton",
                "project": project_id,
                "branch": branch,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_files": stats.get("total_files", 0),
                "total_dirs": stats.get("total_dirs", 0),
            }
        ],
    )

    logger.debug(f"Skeleton stored: {doc_id} ({stats['total_files']} files, {stats['total_dirs']} dirs)")
    return doc_id
