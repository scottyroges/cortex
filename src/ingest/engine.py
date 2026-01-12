"""
Ingestion Engine

Main ingestion logic for files and codebases.
"""

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import chromadb
from anthropic import Anthropic

from logging_config import get_logger
from src.git import get_current_branch, get_git_changed_files, get_head_commit, get_untracked_files, is_git_repo
from src.ingest.chunker import chunk_code_file, detect_language, extract_scope_from_chunk
from src.ingest.headers import generate_header_sync
from src.ingest.skeleton import generate_tree_structure, store_skeleton
from src.ingest.walker import compute_file_hash, get_changed_files, walk_codebase
from src.security import scrub_secrets
from src.state import load_state, migrate_state, save_state
from src.storage.gc import cleanup_state_entries, delete_file_chunks

logger = get_logger("ingest.engine")


def ingest_file(
    file_path: Path,
    collection: chromadb.Collection,
    project_id: str,
    branch: str,
    anthropic_client: Optional[Anthropic] = None,
    header_provider: str = "none",
    chunk_size: int = 1500,
    chunk_overlap: int = 200,
) -> list[str]:
    """
    Ingest a single file into the collection.

    Args:
        file_path: Path to the file
        collection: ChromaDB collection
        project_id: Project identifier
        branch: Git branch name
        anthropic_client: Anthropic client (for "anthropic" header provider)
        header_provider: One of "anthropic", "claude-cli", or "none"
        chunk_size: Maximum chunk size
        chunk_overlap: Overlap between chunks

    Returns:
        List of document IDs created
    """
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, IOError) as e:
        logger.debug(f"Skipped (read error): {file_path} - {e}")
        return []

    if not content.strip():
        logger.debug(f"Skipped (empty): {file_path}")
        return []

    # Detect language and scrub secrets
    language = detect_language(str(file_path), content)
    content = scrub_secrets(content)

    # Chunk the content
    chunks = chunk_code_file(content, language, chunk_size, chunk_overlap)

    if not chunks:
        logger.debug(f"Skipped (no chunks): {file_path}")
        return []

    doc_ids = []
    path_str = str(file_path)
    lang_str = language.value if language else "unknown"
    indexed_at = datetime.now(timezone.utc).isoformat()

    for i, chunk in enumerate(chunks):
        # Generate contextual header
        header = generate_header_sync(
            chunk,
            path_str,
            language,
            anthropic_client,
            header_provider=header_provider,
        )

        # Extract function/class scope from chunk
        scope_info = extract_scope_from_chunk(chunk, language)

        # Combine header with chunk
        full_text = f"{header}\n\n---\n\n{chunk}"

        # Create document ID
        doc_id = f"{project_id}:{path_str}:{i}"

        # Build metadata with scope info
        metadata = {
            "file_path": path_str,
            "project": project_id,
            "branch": branch,
            "chunk_index": i,
            "total_chunks": len(chunks),
            "language": lang_str,
            "type": "code",
            "indexed_at": indexed_at,
        }

        # Add scope fields if detected (ChromaDB doesn't allow None values)
        if scope_info["function_name"]:
            metadata["function_name"] = scope_info["function_name"]
        if scope_info["class_name"]:
            metadata["class_name"] = scope_info["class_name"]
        if scope_info["scope"]:
            metadata["scope"] = scope_info["scope"]

        # Upsert to collection
        collection.upsert(
            ids=[doc_id],
            documents=[full_text],
            metadatas=[metadata],
        )
        doc_ids.append(doc_id)

    logger.debug(f"File: {file_path.name} -> {len(chunks)} chunks ({lang_str})")
    return doc_ids


def ingest_codebase(
    root_path: str,
    collection: chromadb.Collection,
    project_id: Optional[str] = None,
    anthropic_client: Optional[Anthropic] = None,
    force_full: bool = False,
    header_provider: str = "none",
    state_file: Optional[str] = None,
    include_patterns: Optional[list[str]] = None,
    use_cortexignore: bool = True,
) -> dict[str, Any]:
    """
    Ingest an entire codebase into the collection.

    Uses git-based delta sync when available:
    - Only processes files changed since last indexed commit
    - Garbage collects chunks for deleted files
    - Handles file renames (deletes old path, indexes new path)

    Falls back to MD5 hash-based delta sync for non-git repos.

    Args:
        root_path: Root directory to ingest
        collection: ChromaDB collection to add documents to
        project_id: Project identifier (defaults to directory name)
        anthropic_client: Anthropic client (for "anthropic" header provider)
        force_full: Force full re-ingestion (ignore delta sync)
        header_provider: One of "anthropic", "claude-cli", or "none"
        state_file: Path to state file for delta sync
        include_patterns: If provided, only files matching at least one glob pattern are indexed.
                          Patterns are relative to root_path (e.g., ["src/**", "tests/**"])
        use_cortexignore: If True, load patterns from global + project cortexignore files

    Returns:
        Stats dictionary with ingestion results
    """
    start_time = time.time()
    root = Path(root_path)
    project_id = project_id or root.name
    branch = get_current_branch(root_path)

    logger.info(f"Starting ingestion: {root_path} (project={project_id}, branch={branch})")

    stats = {
        "project": project_id,
        "branch": branch,
        "files_scanned": 0,
        "files_processed": 0,
        "files_skipped": 0,
        "files_deleted": 0,
        "chunks_created": 0,
        "chunks_deleted": 0,
        "delta_mode": "full",
        "errors": [],
    }

    # Load and migrate state for delta sync
    raw_state = {} if force_full else load_state(state_file)
    state = migrate_state(raw_state)

    # Determine delta sync strategy
    use_git = is_git_repo(root_path) and not force_full
    last_commit = state.get("indexed_commit") if use_git else None
    current_commit = get_head_commit(root_path) if use_git else None

    files_to_process: list[Path] = []
    deleted_files: list[str] = []
    renamed_files: list[tuple[str, str]] = []

    if force_full:
        # Full re-ingestion requested
        stats["delta_mode"] = "full"
        all_files = list(walk_codebase(
            root_path,
            include_patterns=include_patterns,
            use_cortexignore=use_cortexignore,
        ))
        files_to_process = all_files
        stats["files_scanned"] = len(all_files)
        logger.info(f"Full ingestion: {len(all_files)} files")

    elif use_git and last_commit and current_commit:
        # Git-based delta sync (fast path)
        stats["delta_mode"] = "git"
        modified, deleted_files, renamed_files = get_git_changed_files(
            root_path, last_commit
        )

        # Also check for untracked files
        untracked = get_untracked_files(root_path)

        # Combine modified and untracked, filter through walk_codebase patterns
        all_changed = set(modified + untracked)
        all_valid_files = set(str(f) for f in walk_codebase(
            root_path,
            include_patterns=include_patterns,
            use_cortexignore=use_cortexignore,
        ))

        # Only process files that pass our filters (not binary, not ignored, etc.)
        files_to_process = [
            Path(f) for f in all_changed
            if f in all_valid_files and Path(f).exists()
        ]

        stats["files_scanned"] = len(files_to_process)
        logger.info(
            f"Git delta sync: {len(files_to_process)} modified, "
            f"{len(deleted_files)} deleted, {len(renamed_files)} renamed"
        )

    else:
        # Hash-based fallback (first index or non-git repo)
        stats["delta_mode"] = "hash" if not force_full else "full"
        all_files = list(walk_codebase(
            root_path,
            include_patterns=include_patterns,
            use_cortexignore=use_cortexignore,
        ))
        stats["files_scanned"] = len(all_files)

        # Filter to changed files using MD5 hashes
        file_hashes = state.get("file_hashes", {})
        files_to_process = get_changed_files(all_files, file_hashes)

        skipped_unchanged = len(all_files) - len(files_to_process)
        if skipped_unchanged > 0:
            logger.debug(f"Skipped (unchanged by hash): {skipped_unchanged} files")

    # --- Garbage Collection ---
    # Handle deleted files: remove their chunks from ChromaDB
    if deleted_files:
        chunks_deleted = delete_file_chunks(collection, deleted_files, project_id)
        stats["files_deleted"] = len(deleted_files)
        stats["chunks_deleted"] = chunks_deleted
        cleanup_state_entries(state, deleted_files)
        logger.info(f"Garbage collected: {len(deleted_files)} files, {chunks_deleted} chunks")

    # Handle renamed files: delete chunks at old paths
    if renamed_files:
        old_paths = [old for old, new in renamed_files]
        chunks_deleted = delete_file_chunks(collection, old_paths, project_id)
        stats["chunks_deleted"] += chunks_deleted
        cleanup_state_entries(state, old_paths)
        logger.info(f"Cleaned up {len(renamed_files)} renamed files")

    # --- Process Files ---
    file_hashes = state.get("file_hashes", {})

    for file_path in files_to_process:
        try:
            doc_ids = ingest_file(
                file_path=file_path,
                collection=collection,
                project_id=project_id,
                branch=branch,
                anthropic_client=anthropic_client,
                header_provider=header_provider,
            )

            if doc_ids:
                stats["files_processed"] += 1
                stats["chunks_created"] += len(doc_ids)

                # Update state with new hash (for fallback mode and integrity)
                file_hashes[str(file_path)] = compute_file_hash(file_path)
            else:
                stats["files_skipped"] += 1

        except Exception as e:
            logger.warning(f"Error processing {file_path}: {e}")
            stats["errors"].append({"file": str(file_path), "error": str(e)})
            stats["files_skipped"] += 1

    # Update state with current commit and timestamp
    state["file_hashes"] = file_hashes
    state["indexed_commit"] = current_commit
    state["indexed_at"] = datetime.now(timezone.utc).isoformat()
    state["project"] = project_id
    state["branch"] = branch

    # Save updated state
    save_state(state, state_file)

    # Generate and store skeleton
    try:
        tree_output, tree_stats = generate_tree_structure(
            root_path,
            include_patterns=include_patterns,
            use_cortexignore=use_cortexignore,
        )
        store_skeleton(collection, tree_output, project_id, branch, tree_stats)
        stats["skeleton"] = tree_stats
        logger.info(f"Skeleton indexed: {tree_stats['total_files']} files, {tree_stats['total_dirs']} dirs")
    except Exception as e:
        logger.warning(f"Skeleton generation failed: {e}")
        stats["skeleton"] = {"error": str(e)}

    elapsed = time.time() - start_time
    logger.info(
        f"Ingestion complete ({stats['delta_mode']}): "
        f"{stats['files_processed']} files, {stats['chunks_created']} chunks, "
        f"{stats['chunks_deleted']} deleted in {elapsed:.1f}s"
    )

    return stats


def ingest_files(
    file_paths: list[str],
    collection: chromadb.Collection,
    project_id: str,
    anthropic_client: Optional[Anthropic] = None,
    header_provider: str = "none",
) -> dict[str, Any]:
    """
    Ingest specific files into the collection.

    Used by smart_commit to re-index only changed files.

    Args:
        file_paths: List of file paths to ingest
        collection: ChromaDB collection
        project_id: Project identifier
        anthropic_client: Anthropic client
        header_provider: Header provider setting

    Returns:
        Stats dictionary
    """
    # Get branch from first file's directory
    if file_paths:
        first_path = Path(file_paths[0])
        branch = get_current_branch(str(first_path.parent))
    else:
        branch = "unknown"

    stats = {
        "files_processed": 0,
        "chunks_added": 0,
        "errors": [],
    }

    for path_str in file_paths:
        file_path = Path(path_str)

        if not file_path.exists():
            stats["errors"].append({"file": path_str, "error": "File not found"})
            continue

        try:
            doc_ids = ingest_file(
                file_path=file_path,
                collection=collection,
                project_id=project_id,
                branch=branch,
                anthropic_client=anthropic_client,
                header_provider=header_provider,
            )

            stats["files_processed"] += 1
            stats["chunks_added"] += len(doc_ids)

        except Exception as e:
            stats["errors"].append({"file": path_str, "error": str(e)})

    return stats
