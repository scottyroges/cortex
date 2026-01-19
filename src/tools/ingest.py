"""
Ingest Tool

MCP tool for ingesting codebases into Cortex.

Supports both sync and async modes:
- Full reindex: Always async
- Delta reindex with ≥50 files: Async
- Delta reindex with <50 files: Sync
"""

import json
import time
from pathlib import Path
from typing import Literal, Optional

from logging_config import get_logger
from src.git import get_current_branch
from src.ingest import ingest_codebase as _ingest_codebase_engine
from src.ingest.engine import select_delta_strategy
from src.llm import get_provider
from src.tools.services import CONFIG, get_collection, get_searcher

logger = get_logger("tools.ingest")

# Threshold for async ingestion (files)
ASYNC_FILE_THRESHOLD = 50


def ingest_codebase(
    action: Literal["ingest", "status"] = "ingest",
    path: Optional[str] = None,
    repository: Optional[str] = None,
    force_full: bool = False,
    include_patterns: Optional[list[str]] = None,
    use_cortexignore: bool = True,
    task_id: Optional[str] = None,
) -> str:
    """
    Ingest a codebase or check ingestion status.

    **When to use this tool:**
    - First time indexing a codebase? action="ingest"
    - Updating index after code changes? action="ingest"
    - Checking async ingestion progress? action="status" with task_id

    Args:
        action: "ingest" to index code, "status" to check async task
        path: Codebase root path (required for action="ingest")
        repository: Repository identifier (defaults to directory name)
        force_full: Force full re-ingestion
        include_patterns: Glob patterns for selective ingestion
        use_cortexignore: Use .cortexignore files (default: True)
        task_id: Task ID for status check (required for action="status")

    Returns:
        JSON with ingestion stats or async task status
    """
    if action == "ingest":
        if not path:
            return json.dumps({"error": "path is required for action='ingest'"})
        return _ingest(path, repository, force_full, include_patterns, use_cortexignore)
    elif action == "status":
        if not task_id:
            return json.dumps({"error": "task_id is required for action='status'"})
        return _get_status(task_id)
    else:
        return json.dumps({"error": f"Unknown action: {action}. Valid actions: 'ingest', 'status'"})


def _ingest(
    path: str,
    repository: Optional[str] = None,
    force_full: bool = False,
    include_patterns: Optional[list[str]] = None,
    use_cortexignore: bool = True,
) -> str:
    """
    Ingest a codebase directory into Cortex memory.

    Uses metadata-first approach: extracts structured metadata
    (file_metadata, data_contract, entry_point, dependency) instead of raw
    code chunks. This helps AI agents find WHERE to look, not WHAT the code says.

    Supports Python, TypeScript, and Kotlin files. Unsupported languages are
    gracefully skipped. Includes secret scrubbing and delta sync (only processes
    changed files unless force_full=True).

    **Async behavior:**
    - Full reindex (force_full=True): Always async, returns task_id
    - Delta reindex with ≥50 changed files: Async, returns task_id
    - Delta reindex with <50 changed files: Sync, returns stats immediately

    Args:
        path: Absolute path to the codebase root directory
        repository: Optional repository identifier (defaults to directory name)
        force_full: Force full re-ingestion, ignoring delta sync
        include_patterns: If provided, only files matching at least one glob pattern are indexed.
                          Patterns are relative to path (e.g., ["src/**", "tests/**"])
        use_cortexignore: If True (default), load ignore patterns from global ~/.cortex/cortexignore
                          and project .cortexignore files

    Returns:
        JSON with ingestion statistics (sync) or task_id (async)
    """
    logger.info(
        f"Ingesting codebase: path={path}, repository={repository}, "
        f"force_full={force_full}, include_patterns={include_patterns}"
    )

    repo_id = repository or Path(path).name

    # Determine if we should run async
    should_async = force_full
    files_to_process = 0

    if not force_full:
        # Calculate delta to decide sync vs async
        try:
            collection = get_collection()
            branch = get_current_branch(path)

            strategy = select_delta_strategy(
                path,
                collection,
                repo_id,
                branch,
                force_full=False,
                include_patterns=include_patterns,
                use_cortexignore=use_cortexignore,
            )
            delta_result = strategy.get_files_to_process()
            files_to_process = len(delta_result.files_to_process)

            if files_to_process >= ASYNC_FILE_THRESHOLD:
                should_async = True
                logger.info(f"Delta has {files_to_process} files (≥{ASYNC_FILE_THRESHOLD}), using async mode")
        except Exception as e:
            logger.warning(f"Error calculating delta, defaulting to sync: {e}")

    if should_async:
        return _queue_async_ingestion(
            path=path,
            repository=repo_id,
            force_full=force_full,
            include_patterns=include_patterns,
            use_cortexignore=use_cortexignore,
            files_total=files_to_process,
        )
    else:
        return _run_sync_ingestion(
            path=path,
            repository=repo_id,
            force_full=force_full,
            include_patterns=include_patterns,
            use_cortexignore=use_cortexignore,
        )


def _queue_async_ingestion(
    path: str,
    repository: str,
    force_full: bool,
    include_patterns: Optional[list[str]],
    use_cortexignore: bool,
    files_total: int,
) -> str:
    """Queue an async ingestion task."""
    from src.ingest.async_processor import get_worker, create_task

    worker = get_worker()

    # Check for existing active task
    existing = worker._store.get_active_task_for_repo(repository)
    if existing:
        return json.dumps({
            "status": "already_running",
            "task_id": existing.task_id,
            "message": f"Ingestion already in progress for {repository}",
            "progress": {
                "files_processed": existing.files_processed,
                "files_total": existing.files_total,
                "percent": round(existing.files_processed / existing.files_total * 100, 1)
                if existing.files_total > 0
                else 0,
            },
        })

    # Create and queue task
    task = create_task(
        path=path,
        repository=repository,
        force_full=force_full,
        include_patterns=include_patterns,
        use_cortexignore=use_cortexignore,
        files_total=files_total,
    )

    try:
        task_id = worker.queue_task(task)
        mode = "full reindex" if force_full else f"delta ({files_total} files)"
        return json.dumps({
            "status": "queued",
            "task_id": task_id,
            "message": f"Ingestion queued for {repository} ({mode}). Use get_ingest_status(task_id) to check progress.",
            "async": True,
            "path": path,
        })
    except ValueError as e:
        return json.dumps({
            "status": "error",
            "error": str(e),
        })


def _run_sync_ingestion(
    path: str,
    repository: str,
    force_full: bool,
    include_patterns: Optional[list[str]],
    use_cortexignore: bool,
) -> str:
    """Run synchronous ingestion (existing behavior for small deltas)."""
    start_time = time.time()

    try:
        collection = get_collection()

        # Get LLM provider instance for metadata descriptions
        llm_provider_instance = None
        if CONFIG["llm_provider"] != "none":
            try:
                llm_provider_instance = get_provider()
            except Exception as e:
                logger.warning(f"Could not get LLM provider for metadata descriptions: {e}")

        stats = _ingest_codebase_engine(
            root_path=path,
            collection=collection,
            repo_id=repository,
            force_full=force_full,
            include_patterns=include_patterns,
            use_cortexignore=use_cortexignore,
            llm_provider_instance=llm_provider_instance,
        )

        # Rebuild search index after ingestion
        get_searcher().build_index()

        total_time = time.time() - start_time
        logger.info(
            f"Sync ingestion complete: {stats.get('files_processed', 0)} files, "
            f"{stats.get('docs_created', 0)} docs in {total_time:.1f}s"
        )

        return json.dumps({
            "status": "success",
            "async": False,
            "path": path,
            "stats": stats,
        }, indent=2)

    except Exception as e:
        logger.error(f"Ingestion error: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e),
            "path": path,
        })


def _get_status(task_id: str) -> str:
    """Get the status of an async ingestion task (internal implementation)."""
    from src.ingest.async_processor import get_worker

    worker = get_worker()
    status = worker.get_status(task_id)

    if status is None:
        return json.dumps({
            "status": "not_found",
            "task_id": task_id,
            "error": "Task not found or expired",
        })

    return json.dumps(status, indent=2)


# --- Backward Compatibility Aliases (for tests and internal use) ---
# These aliases are NOT exported via __all__ but can be imported directly

def ingest_code_into_cortex(
    path: str,
    repository: Optional[str] = None,
    force_full: bool = False,
    include_patterns: Optional[list[str]] = None,
    use_cortexignore: bool = True,
) -> str:
    """Backward-compatible alias for _ingest."""
    return _ingest(path, repository, force_full, include_patterns, use_cortexignore)


def get_ingest_status(task_id: str) -> str:
    """Backward-compatible alias for _get_status."""
    return _get_status(task_id)
