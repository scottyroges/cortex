"""
Project Skeleton Generation

Generate, store, and retrieve tree structure for file-path grounding.
"""

import fnmatch
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import chromadb

from src.configs import get_logger
from src.configs.ignore_patterns import load_ignore_patterns
from src.configs.services import get_collection, get_repo_path
from src.external.git import get_current_branch

logger = get_logger("ingest.skeleton")


def generate_tree_structure(
    root_path: str,
    max_depth: int = 10,
    ignore_patterns: Optional[set[str]] = None,
    include_patterns: Optional[list[str]] = None,
    use_cortexignore: bool = True,
) -> tuple[str, dict]:
    """
    Generate tree output for a project directory.

    Tries system `tree` command first, falls back to Python implementation.
    Uses Python fallback when include_patterns is specified for accurate filtering.

    Args:
        root_path: Root directory path
        max_depth: Maximum depth to traverse
        ignore_patterns: Additional patterns to ignore (merged with cortexignore)
        include_patterns: If provided, only paths matching patterns are shown
        use_cortexignore: If True, load patterns from global + project cortexignore files

    Returns:
        Tuple of (tree_text, stats_dict)
    """
    root = Path(root_path)

    # Load ignore patterns (defaults + cortexignore files)
    ignore = load_ignore_patterns(root_path, use_cortexignore)
    if ignore_patterns:
        ignore = ignore | ignore_patterns

    # Use Python fallback when include_patterns is specified for accurate filtering
    if include_patterns:
        tree_output = _generate_tree_fallback(root, max_depth, ignore, include_patterns)
    else:
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
    include_patterns: Optional[list[str]] = None,
) -> str:
    """Pure-Python tree generation fallback."""

    def matches_include(rel_path: str, is_dir: bool) -> bool:
        """Check if path matches any include pattern."""
        if not include_patterns:
            return True
        for pattern in include_patterns:
            # For directories, check if pattern starts with this directory
            if is_dir:
                # Directory matches if any pattern starts with it or matches it
                if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(rel_path + "/", pattern):
                    return True
                # Also match if any pattern could be under this directory
                if pattern.startswith(rel_path + "/") or fnmatch.fnmatch(pattern, rel_path + "/*"):
                    return True
                # Check if pattern could match something under this directory
                pattern_parts = pattern.split("/")
                rel_parts = rel_path.split("/")
                if len(pattern_parts) > len(rel_parts):
                    if all(fnmatch.fnmatch(rp, pp) for rp, pp in zip(rel_parts, pattern_parts[:len(rel_parts)])):
                        return True
            else:
                if fnmatch.fnmatch(rel_path, pattern):
                    return True
        return False

    def traverse(path: Path, prefix: str = "", depth: int = 0, rel_prefix: str = "") -> list[str]:
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

            # Filter by include patterns if specified
            if include_patterns:
                filtered_items = []
                for item in items:
                    rel_path = f"{rel_prefix}/{item.name}" if rel_prefix else item.name
                    if matches_include(rel_path, item.is_dir()):
                        filtered_items.append(item)
                items = filtered_items

            for i, item in enumerate(items):
                is_last = i == len(items) - 1
                current_prefix = "└── " if is_last else "├── "
                lines.append(f"{prefix}{current_prefix}{item.name}")

                if item.is_dir():
                    next_prefix = prefix + ("    " if is_last else "│   ")
                    next_rel = f"{rel_prefix}/{item.name}" if rel_prefix else item.name
                    lines.extend(traverse(item, next_prefix, depth + 1, next_rel))
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
    repo_id: str,
    branch: str,
    stats: dict,
    indexed_commit: Optional[str] = None,
) -> str:
    """
    Store skeleton in collection with type='skeleton' metadata.

    Args:
        collection: ChromaDB collection
        tree_output: The tree structure text
        repo_id: Repository identifier
        branch: Git branch name
        stats: Tree statistics
        indexed_commit: Git commit hash at time of indexing (for delta sync)

    Returns:
        Document ID
    """
    doc_id = f"{repo_id}:skeleton:{branch}"

    now = datetime.now(timezone.utc).isoformat()
    meta = {
        "type": "skeleton",
        "repository": repo_id,
        "branch": branch,
        "created_at": now,
        "updated_at": now,
        "total_files": stats.get("total_files", 0),
        "total_dirs": stats.get("total_dirs", 0),
    }
    if indexed_commit:
        meta["indexed_commit"] = indexed_commit

    collection.upsert(
        ids=[doc_id],
        documents=[tree_output],
        metadatas=[meta],
    )

    logger.debug(f"Skeleton stored: {doc_id} ({stats['total_files']} files, {stats['total_dirs']} dirs)")
    return doc_id


def get_skeleton(
    repository: Optional[str] = None,
) -> str:
    """
    Get the file tree structure for a repository.

    Returns the stored skeleton (tree output) for file-path grounding.
    The skeleton is auto-generated during ingest_code_into_cortex.

    Args:
        repository: Repository name (required)

    Returns:
        JSON with tree structure and metadata
    """
    if not repository:
        return json.dumps({
            "error": "Repository name is required",
            "hint": "Provide the repository name used during ingestion",
        })

    logger.info(f"Getting skeleton for repository: {repository}")

    try:
        collection = get_collection()
        repo_path = get_repo_path()
        branch = get_current_branch(repo_path) if repo_path else "unknown"

        # Try current branch first, then fall back to any branch
        doc_id = f"{repository}:skeleton:{branch}"
        result = collection.get(ids=[doc_id], include=["documents", "metadatas"])

        if not result["documents"]:
            # Try to find skeleton for any branch
            all_results = collection.get(
                where={"$and": [{"type": "skeleton"}, {"repository": repository}]},
                include=["documents", "metadatas"],
            )
            if all_results["documents"]:
                result = {
                    "documents": [all_results["documents"][0]],
                    "metadatas": [all_results["metadatas"][0]],
                }

        if not result["documents"]:
            return json.dumps({
                "error": f"No skeleton found for repository '{repository}'",
                "hint": "Run ingest_code_into_cortex first to generate the skeleton",
            })

        metadata = result["metadatas"][0]
        tree = result["documents"][0]

        logger.info(f"Skeleton found: {metadata.get('total_files', 0)} files, {metadata.get('total_dirs', 0)} dirs")

        return json.dumps({
            "repository": repository,
            "branch": metadata.get("branch", "unknown"),
            "generated_at": metadata.get("generated_at", "unknown"),
            "total_files": metadata.get("total_files", 0),
            "total_dirs": metadata.get("total_dirs", 0),
            "tree": tree,
        }, indent=2)

    except Exception as e:
        logger.error(f"Get skeleton error: {e}")
        return json.dumps({"error": str(e)})
