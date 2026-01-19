"""
Ingestion Engine

Main ingestion logic for files and codebases.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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


# =============================================================================
# Delta Sync Strategy Pattern
# =============================================================================


@dataclass
class DeltaSyncResult:
    """Result from a delta sync strategy."""

    files_to_process: list[Path]
    deleted_files: list[str] = field(default_factory=list)
    renamed_files: list[tuple[str, str]] = field(default_factory=list)
    delta_mode: str = "full"
    files_scanned: int = 0


class DeltaSyncStrategy(ABC):
    """Abstract base for delta sync strategies."""

    @abstractmethod
    def get_files_to_process(self) -> DeltaSyncResult:
        """Determine which files need processing."""
        pass


class FullSyncStrategy(DeltaSyncStrategy):
    """Process all files (full re-ingestion)."""

    def __init__(
        self,
        root_path: str,
        include_patterns: Optional[list[str]],
        use_cortexignore: bool,
    ):
        self.root_path = root_path
        self.include_patterns = include_patterns
        self.use_cortexignore = use_cortexignore

    def get_files_to_process(self) -> DeltaSyncResult:
        all_files = list(walk_codebase(
            self.root_path,
            include_patterns=self.include_patterns,
            use_cortexignore=self.use_cortexignore,
        ))
        logger.info(f"Full ingestion: {len(all_files)} files")
        return DeltaSyncResult(
            files_to_process=all_files,
            delta_mode="full",
            files_scanned=len(all_files),
        )


class GitDeltaSyncStrategy(DeltaSyncStrategy):
    """Git-based delta sync using commit comparison."""

    def __init__(
        self,
        root_path: str,
        last_commit: str,
        include_patterns: Optional[list[str]],
        use_cortexignore: bool,
    ):
        self.root_path = root_path
        self.last_commit = last_commit
        self.include_patterns = include_patterns
        self.use_cortexignore = use_cortexignore

    def get_files_to_process(self) -> DeltaSyncResult:
        modified, deleted_files, renamed_files = get_git_changed_files(
            self.root_path, self.last_commit
        )

        # Also check for untracked files
        untracked = get_untracked_files(self.root_path)

        # Combine modified and untracked, filter through walk_codebase patterns
        all_changed = set(modified + untracked)
        all_valid_files = set(str(f) for f in walk_codebase(
            self.root_path,
            include_patterns=self.include_patterns,
            use_cortexignore=self.use_cortexignore,
        ))

        # Only process files that pass our filters
        files_to_process = [
            Path(f) for f in all_changed
            if f in all_valid_files and Path(f).exists()
        ]

        logger.info(
            f"Git delta sync: {len(files_to_process)} modified, "
            f"{len(deleted_files)} deleted, {len(renamed_files)} renamed"
        )

        return DeltaSyncResult(
            files_to_process=files_to_process,
            deleted_files=deleted_files,
            renamed_files=renamed_files,
            delta_mode="git",
            files_scanned=len(files_to_process),
        )


class HashDeltaSyncStrategy(DeltaSyncStrategy):
    """MD5 hash-based delta sync for non-git repos."""

    def __init__(
        self,
        root_path: str,
        file_hashes: dict[str, str],
        include_patterns: Optional[list[str]],
        use_cortexignore: bool,
    ):
        self.root_path = root_path
        self.file_hashes = file_hashes
        self.include_patterns = include_patterns
        self.use_cortexignore = use_cortexignore

    def get_files_to_process(self) -> DeltaSyncResult:
        all_files = list(walk_codebase(
            self.root_path,
            include_patterns=self.include_patterns,
            use_cortexignore=self.use_cortexignore,
        ))

        # Filter to changed files using MD5 hashes
        files_to_process = get_changed_files(all_files, self.file_hashes)

        skipped_unchanged = len(all_files) - len(files_to_process)
        if skipped_unchanged > 0:
            logger.debug(f"Skipped (unchanged by hash): {skipped_unchanged} files")

        return DeltaSyncResult(
            files_to_process=files_to_process,
            delta_mode="hash",
            files_scanned=len(all_files),
        )


def select_delta_strategy(
    root_path: str,
    state: dict,
    force_full: bool,
    include_patterns: Optional[list[str]],
    use_cortexignore: bool,
) -> DeltaSyncStrategy:
    """Select the appropriate delta sync strategy."""
    if force_full:
        return FullSyncStrategy(root_path, include_patterns, use_cortexignore)

    use_git = is_git_repo(root_path)
    last_commit = state.get("indexed_commit") if use_git else None
    current_commit = get_head_commit(root_path) if use_git else None

    if use_git and last_commit and current_commit:
        return GitDeltaSyncStrategy(root_path, last_commit, include_patterns, use_cortexignore)

    return HashDeltaSyncStrategy(
        root_path,
        state.get("file_hashes", {}),
        include_patterns,
        use_cortexignore,
    )


# =============================================================================
# Garbage Collection
# =============================================================================


class GarbageCollector:
    """Handles cleanup of deleted and renamed file chunks."""

    def __init__(self, collection: chromadb.Collection, repo_id: str, state: dict):
        self.collection = collection
        self.repo_id = repo_id
        self.state = state

    def cleanup_deleted(self, deleted_files: list[str]) -> int:
        """Remove chunks for deleted files."""
        if not deleted_files:
            return 0

        chunks_deleted = delete_file_chunks(self.collection, deleted_files, self.repo_id)
        cleanup_state_entries(self.state, deleted_files)
        logger.info(f"Garbage collected: {len(deleted_files)} files, {chunks_deleted} chunks")
        return chunks_deleted

    def cleanup_renamed(self, renamed_files: list[tuple[str, str]]) -> int:
        """Remove chunks at old paths for renamed files."""
        if not renamed_files:
            return 0

        old_paths = [old for old, new in renamed_files]
        chunks_deleted = delete_file_chunks(self.collection, old_paths, self.repo_id)
        cleanup_state_entries(self.state, old_paths)
        logger.info(f"Cleaned up {len(renamed_files)} renamed files")
        return chunks_deleted


# =============================================================================
# File Processing
# =============================================================================


def ingest_file(
    file_path: Path,
    collection: chromadb.Collection,
    repo_id: str,
    branch: str,
    anthropic_client: Optional[Anthropic] = None,
    llm_provider: str = "none",
    chunk_size: int = 1500,
    chunk_overlap: int = 200,
) -> list[str]:
    """
    Ingest a single file into the collection.

    Args:
        file_path: Path to the file
        collection: ChromaDB collection
        repo_id: Repository identifier
        branch: Git branch name
        anthropic_client: Anthropic client (for "anthropic" LLM provider)
        llm_provider: One of "anthropic", "claude-cli", or "none"
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
            llm_provider=llm_provider,
        )

        # Extract function/class scope from chunk
        scope_info = extract_scope_from_chunk(chunk, language)

        # Combine header with chunk
        full_text = f"{header}\n\n---\n\n{chunk}"

        # Create document ID
        doc_id = f"{repo_id}:{path_str}:{i}"

        # Build metadata with scope info
        metadata = {
            "file_path": path_str,
            "repository": repo_id,
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


class FileProcessor:
    """Processes files for ingestion."""

    def __init__(
        self,
        collection: chromadb.Collection,
        repo_id: str,
        branch: str,
        anthropic_client: Optional[Anthropic],
        llm_provider: str,
    ):
        self.collection = collection
        self.repo_id = repo_id
        self.branch = branch
        self.anthropic_client = anthropic_client
        self.llm_provider = llm_provider

    def process_files(
        self,
        files: list[Path],
        file_hashes: dict[str, str],
    ) -> tuple[int, int, int, list[dict]]:
        """
        Process a list of files.

        Returns:
            Tuple of (processed_count, skipped_count, chunks_created, errors)
        """
        processed = 0
        skipped = 0
        chunks_created = 0
        errors = []

        for file_path in files:
            try:
                doc_ids = ingest_file(
                    file_path=file_path,
                    collection=self.collection,
                    repo_id=self.repo_id,
                    branch=self.branch,
                    anthropic_client=self.anthropic_client,
                    llm_provider=self.llm_provider,
                )

                if doc_ids:
                    processed += 1
                    chunks_created += len(doc_ids)
                    file_hashes[str(file_path)] = compute_file_hash(file_path)
                else:
                    skipped += 1

            except Exception as e:
                logger.warning(f"Error processing {file_path}: {e}")
                errors.append({"file": str(file_path), "error": str(e)})
                skipped += 1

        return processed, skipped, chunks_created, errors


# =============================================================================
# Main Ingestion Function
# =============================================================================


def ingest_codebase(
    root_path: str,
    collection: chromadb.Collection,
    repo_id: Optional[str] = None,
    anthropic_client: Optional[Anthropic] = None,
    force_full: bool = False,
    llm_provider: str = "none",
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
        repo_id: Repository identifier (defaults to directory name)
        anthropic_client: Anthropic client (for "anthropic" LLM provider)
        force_full: Force full re-ingestion (ignore delta sync)
        llm_provider: One of "anthropic", "claude-cli", or "none"
        state_file: Path to state file for delta sync
        include_patterns: If provided, only files matching at least one glob pattern are indexed.
                          Patterns are relative to root_path (e.g., ["src/**", "tests/**"])
        use_cortexignore: If True, load patterns from global + project cortexignore files

    Returns:
        Stats dictionary with ingestion results
    """
    start_time = time.time()
    root = Path(root_path)
    repo_id = repo_id or root.name
    branch = get_current_branch(root_path)

    logger.info(f"Starting ingestion: {root_path} (repository={repo_id}, branch={branch})")

    # Load and migrate state for delta sync
    raw_state = {} if force_full else load_state(state_file)
    state = migrate_state(raw_state)

    # Select and execute delta sync strategy
    strategy = select_delta_strategy(
        root_path, state, force_full, include_patterns, use_cortexignore
    )
    delta_result = strategy.get_files_to_process()

    # Initialize stats
    stats: dict[str, Any] = {
        "repository": repo_id,
        "branch": branch,
        "files_scanned": delta_result.files_scanned,
        "files_processed": 0,
        "files_skipped": 0,
        "files_deleted": len(delta_result.deleted_files),
        "chunks_created": 0,
        "chunks_deleted": 0,
        "delta_mode": delta_result.delta_mode,
        "errors": [],
    }

    # Garbage collection
    gc = GarbageCollector(collection, repo_id, state)
    stats["chunks_deleted"] += gc.cleanup_deleted(delta_result.deleted_files)
    stats["chunks_deleted"] += gc.cleanup_renamed(delta_result.renamed_files)

    # Process files
    file_hashes = state.get("file_hashes", {})
    processor = FileProcessor(
        collection, repo_id, branch, anthropic_client, llm_provider
    )
    processed, skipped, chunks, errors = processor.process_files(
        delta_result.files_to_process, file_hashes
    )

    stats["files_processed"] = processed
    stats["files_skipped"] = skipped
    stats["chunks_created"] = chunks
    stats["errors"] = errors

    # Update state
    current_commit = get_head_commit(root_path) if is_git_repo(root_path) else None
    state["file_hashes"] = file_hashes
    state["indexed_commit"] = current_commit
    state["indexed_at"] = datetime.now(timezone.utc).isoformat()
    state["repository"] = repo_id
    state["branch"] = branch
    save_state(state, state_file)

    # Generate and store skeleton
    try:
        tree_output, tree_stats = generate_tree_structure(
            root_path,
            include_patterns=include_patterns,
            use_cortexignore=use_cortexignore,
        )
        store_skeleton(collection, tree_output, repo_id, branch, tree_stats)
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
    repo_id: str,
    anthropic_client: Optional[Anthropic] = None,
    llm_provider: str = "none",
) -> dict[str, Any]:
    """
    Ingest specific files into the collection.

    Used by smart_commit to re-index only changed files.

    Args:
        file_paths: List of file paths to ingest
        collection: ChromaDB collection
        repo_id: Repository identifier
        anthropic_client: Anthropic client
        llm_provider: LLM provider setting

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
                repo_id=repo_id,
                branch=branch,
                anthropic_client=anthropic_client,
                llm_provider=llm_provider,
            )

            stats["files_processed"] += 1
            stats["chunks_added"] += len(doc_ids)

        except Exception as e:
            stats["errors"].append({"file": path_str, "error": str(e)})

    return stats
