"""
Ingestion Engine

Main ingestion logic for files and codebases.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import chromadb

from src.configs import get_logger
from src.external.git import get_current_branch, get_git_changed_files, get_head_commit, get_untracked_files, is_git_repo
from src.tools.ingest.skeleton import generate_tree_structure, store_skeleton
from src.tools.ingest.walker import compute_file_hash, get_changed_files, walk_codebase
from src.external.llm import LLMProvider
from src.storage import delete_file_chunks

logger = get_logger("ingest.engine")


# =============================================================================
# DB State Helpers (replaces state file)
# =============================================================================


def get_indexed_commit_from_db(
    collection: chromadb.Collection,
    repo_id: str,
    branch: str,
) -> Optional[str]:
    """
    Get the indexed_commit from skeleton metadata.

    Args:
        collection: ChromaDB collection
        repo_id: Repository identifier
        branch: Git branch name

    Returns:
        Commit hash if found, None otherwise
    """
    skeleton_id = f"{repo_id}:skeleton:{branch}"
    try:
        result = collection.get(ids=[skeleton_id], include=["metadatas"])
        if result["metadatas"]:
            return result["metadatas"][0].get("indexed_commit")
    except Exception as e:
        logger.debug(f"Could not get indexed_commit from skeleton: {e}")
    return None


def get_file_hashes_from_db(
    collection: chromadb.Collection,
    repo_id: str,
) -> dict[str, str]:
    """
    Load file hashes from file_metadata documents in ChromaDB.

    Used for hash-based delta sync in non-git repos.

    Args:
        collection: ChromaDB collection
        repo_id: Repository identifier

    Returns:
        Dict mapping file_path -> file_hash
    """
    try:
        result = collection.get(
            where={
                "$and": [
                    {"type": "file_metadata"},
                    {"repository": repo_id},
                ]
            },
            include=["metadatas"],
        )
        return {
            meta["file_path"]: meta.get("file_hash", "")
            for meta in result.get("metadatas", [])
            if meta.get("file_path") and meta.get("file_hash")
        }
    except Exception as e:
        logger.warning(f"Could not load file hashes from DB: {e}")
        return {}


# Progress callback: (files_processed, files_total, docs_created) -> None
ProgressCallback = Callable[[int, int, int], None]

# Progress update interval (every N files)
PROGRESS_BATCH_SIZE = 10


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
    collection: chromadb.Collection,
    repo_id: str,
    branch: str,
    force_full: bool,
    include_patterns: Optional[list[str]],
    use_cortexignore: bool,
) -> DeltaSyncStrategy:
    """Select the appropriate delta sync strategy.

    Args:
        root_path: Root directory path
        collection: ChromaDB collection (for querying existing state)
        repo_id: Repository identifier
        branch: Git branch name
        force_full: Force full re-ingestion
        include_patterns: Glob patterns for selective ingestion
        use_cortexignore: Use cortexignore files

    Returns:
        Appropriate delta sync strategy
    """
    if force_full:
        return FullSyncStrategy(root_path, include_patterns, use_cortexignore)

    use_git = is_git_repo(root_path)
    current_commit = get_head_commit(root_path) if use_git else None

    if use_git and current_commit:
        # Get last indexed commit from skeleton metadata
        last_commit = get_indexed_commit_from_db(collection, repo_id, branch)
        if last_commit:
            return GitDeltaSyncStrategy(root_path, last_commit, include_patterns, use_cortexignore)

    # Fall back to hash-based delta for non-git or first-time indexing
    file_hashes = get_file_hashes_from_db(collection, repo_id)
    return HashDeltaSyncStrategy(
        root_path,
        file_hashes,
        include_patterns,
        use_cortexignore,
    )


# =============================================================================
# Garbage Collection
# =============================================================================


class GarbageCollector:
    """Handles cleanup of deleted and renamed file chunks."""

    def __init__(self, collection: chromadb.Collection, repo_id: str):
        self.collection = collection
        self.repo_id = repo_id

    def cleanup_deleted(self, deleted_files: list[str]) -> int:
        """Remove chunks for deleted files."""
        if not deleted_files:
            return 0

        chunks_deleted = delete_file_chunks(self.collection, deleted_files, self.repo_id)
        logger.info(f"Garbage collected: {len(deleted_files)} files, {chunks_deleted} chunks")
        return chunks_deleted

    def cleanup_renamed(self, renamed_files: list[tuple[str, str]]) -> int:
        """Remove chunks at old paths for renamed files."""
        if not renamed_files:
            return 0

        old_paths = [old for old, new in renamed_files]
        chunks_deleted = delete_file_chunks(self.collection, old_paths, self.repo_id)
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
        root_path: Path,
        llm_provider: Optional[LLMProvider] = None,
    ):
        self.collection = collection
        self.repo_id = repo_id
        self.branch = branch
        self.root_path = root_path
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
        progress_callback: Optional[ProgressCallback] = None,
    ) -> tuple[int, int, int, list[dict]]:
        """
        Process files using metadata extraction.

        Args:
            files: List of file paths to process
            file_hashes: Dict to store/update file hashes
            progress_callback: Optional callback for progress reporting

        Returns:
            Tuple of (processed_count, skipped_count, docs_created, errors)
        """
        # Import here to avoid circular imports
        from src.tools.ingest.metadata import ingest_file_metadata, build_dependencies, link_test_files

        # Clean up old code chunks before processing
        self._cleanup_old_code_chunks(files)

        processed = 0
        skipped = 0
        docs_created = 0
        errors = []
        results = []
        total_files = len(files)

        for i, file_path in enumerate(files):
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

            # Report progress every PROGRESS_BATCH_SIZE files or on last file
            if progress_callback and (
                (i + 1) % PROGRESS_BATCH_SIZE == 0 or i == total_files - 1
            ):
                progress_callback(i + 1, total_files, docs_created)

        # Build dependency graph after all files processed
        if results:
            dep_count = build_dependencies(
                results, self.collection, self.repo_id, self.branch, self.root_path
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
    include_patterns: Optional[list[str]] = None,
    use_cortexignore: bool = True,
    llm_provider_instance: Optional[LLMProvider] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> dict[str, Any]:
    """
    Ingest an entire codebase into the collection using metadata-first approach.

    Extracts structured metadata (file_metadata, data_contract, entry_point, dependency)
    instead of raw code chunks. This helps AI agents find WHERE to look, not WHAT the
    code says.

    Uses git-based delta sync when available:
    - Only processes files changed since last indexed commit (stored in skeleton metadata)
    - Garbage collects documents for deleted files
    - Handles file renames (deletes old path, indexes new path)

    Falls back to MD5 hash-based delta sync for non-git repos (queries file_metadata for hashes).

    Args:
        root_path: Root directory to ingest
        collection: ChromaDB collection to add documents to
        repo_id: Repository identifier (defaults to directory name)
        force_full: Force full re-ingestion (ignore delta sync)
        include_patterns: If provided, only files matching at least one glob pattern are indexed.
                          Patterns are relative to root_path (e.g., ["src/**", "tests/**"])
        use_cortexignore: If True, load patterns from global + project cortexignore files
        llm_provider_instance: LLMProvider instance for metadata descriptions
        progress_callback: Optional callback for progress reporting (processed, total, docs_created)

    Returns:
        Stats dictionary with ingestion results
    """
    start_time = time.time()
    root = Path(root_path)
    repo_id = repo_id or root.name
    branch = get_current_branch(root_path)

    logger.info(f"Starting ingestion: {root_path} (repository={repo_id}, branch={branch})")

    # Select and execute delta sync strategy (queries DB for state)
    strategy = select_delta_strategy(
        root_path, collection, repo_id, branch, force_full, include_patterns, use_cortexignore
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
    gc = GarbageCollector(collection, repo_id)
    stats["chunks_deleted"] += gc.cleanup_deleted(delta_result.deleted_files)
    stats["chunks_deleted"] += gc.cleanup_renamed(delta_result.renamed_files)

    # Process files using metadata-first approach
    # Note: file_hashes dict is only used during processing to track new hashes
    # Hashes are stored in file_metadata docs in ChromaDB
    file_hashes: dict[str, str] = {}

    processor = MetadataFileProcessor(
        collection, repo_id, branch, root, llm_provider_instance
    )

    processed, skipped, docs_created, errors = processor.process_files(
        delta_result.files_to_process, file_hashes, progress_callback
    )

    stats["files_processed"] = processed
    stats["files_skipped"] = skipped
    stats["docs_created"] = docs_created
    stats["errors"] = errors

    # Get current commit for skeleton metadata (used for git delta sync)
    current_commit = get_head_commit(root_path) if is_git_repo(root_path) else None

    # Generate and store skeleton with indexed_commit
    try:
        tree_output, tree_stats = generate_tree_structure(
            root_path,
            include_patterns=include_patterns,
            use_cortexignore=use_cortexignore,
        )
        store_skeleton(collection, tree_output, repo_id, branch, tree_stats, indexed_commit=current_commit)
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
