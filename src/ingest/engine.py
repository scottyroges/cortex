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

from logging_config import get_logger
from src.git import get_current_branch, get_git_changed_files, get_head_commit, get_untracked_files, is_git_repo
from src.ingest.skeleton import generate_tree_structure, store_skeleton
from src.ingest.walker import compute_file_hash, get_changed_files, walk_codebase
from src.llm import LLMProvider
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


class MetadataFileProcessor:
    """Processes files using metadata-first approach.

    Instead of code chunking, extracts structured metadata:
    - file_metadata: File overview with description, exports, imports
    - data_contract: Interfaces, types, schemas, dataclasses
    - entry_point: Main functions, API routes, CLI commands
    - dependency: Import relationships (built after all files processed)

    Note: This processor also cleans up any old 'code' type chunks for files
    being processed, ensuring a clean transition from code chunking to metadata.
    """

    def __init__(
        self,
        collection: chromadb.Collection,
        repo_id: str,
        branch: str,
        llm_provider: Optional[LLMProvider] = None,
    ):
        self.collection = collection
        self.repo_id = repo_id
        self.branch = branch
        self.llm_provider = llm_provider

    def _cleanup_old_code_chunks(self, file_paths: list[Path]) -> int:
        """Delete old 'code' type chunks for files being processed."""
        if not file_paths:
            return 0

        path_strs = [str(p) for p in file_paths]
        deleted = delete_file_chunks(self.collection, path_strs, self.repo_id)
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old code chunks for {len(path_strs)} files")
        return deleted

    def process_files(
        self,
        files: list[Path],
        file_hashes: dict[str, str],
    ) -> tuple[int, int, int, list[dict]]:
        """
        Process files using metadata extraction.

        Returns:
            Tuple of (processed_count, skipped_count, docs_created, errors)
        """
        # Import here to avoid circular imports
        from src.ingest.metadata import ingest_file_metadata, build_dependencies, link_test_files

        # Clean up old code chunks before processing
        self._cleanup_old_code_chunks(files)

        processed = 0
        skipped = 0
        docs_created = 0
        errors = []
        results = []

        for file_path in files:
            try:
                result = ingest_file_metadata(
                    file_path=file_path,
                    collection=self.collection,
                    repo_id=self.repo_id,
                    branch=self.branch,
                    llm_provider=self.llm_provider,
                )

                if result.error:
                    skipped += 1
                    if "Unsupported" not in result.error and "Empty" not in result.error:
                        errors.append({"file": str(file_path), "error": result.error})
                else:
                    processed += 1
                    # Count documents created
                    if result.file_metadata_id:
                        docs_created += 1
                    docs_created += len(result.data_contract_ids)
                    if result.entry_point_id:
                        docs_created += 1

                    # Update hash if available
                    if result.metadata and result.metadata.file_hash:
                        file_hashes[str(file_path)] = result.metadata.file_hash

                results.append(result)

            except Exception as e:
                logger.warning(f"Error processing {file_path}: {e}")
                errors.append({"file": str(file_path), "error": str(e)})
                skipped += 1

        # Build dependency graph after all files processed
        if results:
            dep_count = build_dependencies(
                results, self.collection, self.repo_id, self.branch
            )
            docs_created += dep_count

            # Link test files to source files
            link_test_files(results, self.collection, self.repo_id)

        return processed, skipped, docs_created, errors


# =============================================================================
# Main Ingestion Function
# =============================================================================


def ingest_codebase(
    root_path: str,
    collection: chromadb.Collection,
    repo_id: Optional[str] = None,
    force_full: bool = False,
    state_file: Optional[str] = None,
    include_patterns: Optional[list[str]] = None,
    use_cortexignore: bool = True,
    llm_provider_instance: Optional[LLMProvider] = None,
) -> dict[str, Any]:
    """
    Ingest an entire codebase into the collection using metadata-first approach.

    Extracts structured metadata (file_metadata, data_contract, entry_point, dependency)
    instead of raw code chunks. This helps AI agents find WHERE to look, not WHAT the
    code says.

    Uses git-based delta sync when available:
    - Only processes files changed since last indexed commit
    - Garbage collects documents for deleted files
    - Handles file renames (deletes old path, indexes new path)

    Falls back to MD5 hash-based delta sync for non-git repos.

    Args:
        root_path: Root directory to ingest
        collection: ChromaDB collection to add documents to
        repo_id: Repository identifier (defaults to directory name)
        force_full: Force full re-ingestion (ignore delta sync)
        state_file: Path to state file for delta sync
        include_patterns: If provided, only files matching at least one glob pattern are indexed.
                          Patterns are relative to root_path (e.g., ["src/**", "tests/**"])
        use_cortexignore: If True, load patterns from global + project cortexignore files
        llm_provider_instance: LLMProvider instance for metadata descriptions

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
        "docs_created": 0,
        "chunks_deleted": 0,
        "delta_mode": delta_result.delta_mode,
        "errors": [],
    }

    # Garbage collection
    gc = GarbageCollector(collection, repo_id, state)
    stats["chunks_deleted"] += gc.cleanup_deleted(delta_result.deleted_files)
    stats["chunks_deleted"] += gc.cleanup_renamed(delta_result.renamed_files)

    # Process files using metadata-first approach
    file_hashes = state.get("file_hashes", {})

    processor = MetadataFileProcessor(
        collection, repo_id, branch, llm_provider_instance
    )

    processed, skipped, docs_created, errors = processor.process_files(
        delta_result.files_to_process, file_hashes
    )

    stats["files_processed"] = processed
    stats["files_skipped"] = skipped
    stats["docs_created"] = docs_created
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
        f"{stats['files_processed']} files, {stats['docs_created']} docs, "
        f"{stats['chunks_deleted']} deleted in {elapsed:.1f}s"
    )

    return stats
