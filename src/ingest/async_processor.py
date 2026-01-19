"""
Async Ingestion Processor

Background worker for async ingestion tasks. Full reindexing and large delta
reindexing run asynchronously to avoid blocking MCP tool calls.

Follows the QueueProcessor pattern from src/autocapture/queue_processor.py:
- Threading-based daemon
- File-based persistence for task state
- Event-based wake-up for immediate processing
- Atomic file operations
"""

import json
import os
import tempfile
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from logging_config import get_logger
from src.config import get_data_path

logger = get_logger("ingest.async")

TASK_FILE = get_data_path() / "ingest_tasks.json"
PROCESSING_INTERVAL = 5  # seconds between queue checks
PROGRESS_BATCH_SIZE = 10  # Update progress every N files
MAX_TASK_AGE_HOURS = 24  # Cleanup completed tasks after this


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class IngestionTask:
    """Represents an async ingestion task."""

    task_id: str
    repository: str
    path: str
    status: str  # pending, in_progress, completed, failed
    force_full: bool
    include_patterns: Optional[list[str]]
    use_cortexignore: bool

    # Progress tracking
    files_total: int = 0
    files_processed: int = 0
    files_skipped: int = 0
    docs_created: int = 0

    # Timing
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    # Results
    result: Optional[dict] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "IngestionTask":
        """Create from dictionary."""
        return cls(**data)


# =============================================================================
# Task Store (Thread-Safe Persistence)
# =============================================================================


class IngestionTaskStore:
    """
    Thread-safe persistence for ingestion tasks.

    Stores tasks in ~/.cortex/ingest_tasks.json with atomic writes.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._file_path = TASK_FILE

    def _load(self) -> dict:
        """Load state from disk."""
        if not self._file_path.exists():
            return {"tasks": {}, "active_task_by_repo": {}}

        try:
            return json.loads(self._file_path.read_text())
        except Exception as e:
            logger.warning(f"Failed to load task state: {e}")
            return {"tasks": {}, "active_task_by_repo": {}}

    def _save(self, state: dict) -> None:
        """Atomic save using temp file + os.replace()."""
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(dir=str(self._file_path.parent))
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_path, str(self._file_path))
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def get_task(self, task_id: str) -> Optional[IngestionTask]:
        """Get task by ID."""
        with self._lock:
            state = self._load()
            task_data = state.get("tasks", {}).get(task_id)
            if task_data:
                return IngestionTask.from_dict(task_data)
            return None

    def get_all_tasks(self, repository: Optional[str] = None) -> list[IngestionTask]:
        """Get all tasks, optionally filtered by repository."""
        with self._lock:
            state = self._load()
            tasks = []
            for task_data in state.get("tasks", {}).values():
                task = IngestionTask.from_dict(task_data)
                if repository is None or task.repository == repository:
                    tasks.append(task)
            return tasks

    def create_task(self, task: IngestionTask) -> None:
        """Create new task, checking for repo conflicts."""
        with self._lock:
            state = self._load()

            # Check for existing active task
            active_id = state.get("active_task_by_repo", {}).get(task.repository)
            if active_id:
                existing = state.get("tasks", {}).get(active_id)
                if existing and existing.get("status") in ("pending", "in_progress"):
                    raise ValueError(
                        f"Ingestion already in progress for {task.repository}: {active_id}"
                    )

            # Add task
            state.setdefault("tasks", {})[task.task_id] = task.to_dict()
            state.setdefault("active_task_by_repo", {})[task.repository] = task.task_id

            self._save(state)
            logger.info(f"Created task {task.task_id} for {task.repository}")

    def update_status(self, task_id: str, status: str) -> None:
        """Update task status."""
        with self._lock:
            state = self._load()
            if task_id in state.get("tasks", {}):
                state["tasks"][task_id]["status"] = status
                if status == "in_progress":
                    state["tasks"][task_id]["started_at"] = datetime.now(timezone.utc).isoformat()
                self._save(state)

    def update_progress(
        self,
        task_id: str,
        files_processed: int,
        files_total: int,
        docs_created: int,
    ) -> None:
        """Update task progress."""
        with self._lock:
            state = self._load()
            if task_id in state.get("tasks", {}):
                state["tasks"][task_id]["files_processed"] = files_processed
                state["tasks"][task_id]["files_total"] = files_total
                state["tasks"][task_id]["docs_created"] = docs_created
                self._save(state)

    def complete_task(self, task_id: str, result: dict) -> None:
        """Mark task as completed with results."""
        with self._lock:
            state = self._load()
            if task_id in state.get("tasks", {}):
                state["tasks"][task_id]["status"] = "completed"
                state["tasks"][task_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
                state["tasks"][task_id]["result"] = result

                # Clear active task for repo
                repo = state["tasks"][task_id].get("repository")
                if repo and state.get("active_task_by_repo", {}).get(repo) == task_id:
                    del state["active_task_by_repo"][repo]

                self._save(state)
                logger.info(f"Task {task_id} completed")

    def fail_task(self, task_id: str, error: str) -> None:
        """Mark task as failed with error."""
        with self._lock:
            state = self._load()
            if task_id in state.get("tasks", {}):
                state["tasks"][task_id]["status"] = "failed"
                state["tasks"][task_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
                state["tasks"][task_id]["error"] = error

                # Clear active task for repo
                repo = state["tasks"][task_id].get("repository")
                if repo and state.get("active_task_by_repo", {}).get(repo) == task_id:
                    del state["active_task_by_repo"][repo]

                self._save(state)
                logger.error(f"Task {task_id} failed: {error}")

    def get_active_task_for_repo(self, repository: str) -> Optional[IngestionTask]:
        """Check if there's an active task for this repo."""
        with self._lock:
            state = self._load()
            active_id = state.get("active_task_by_repo", {}).get(repository)
            if active_id:
                task_data = state.get("tasks", {}).get(active_id)
                if task_data and task_data.get("status") in ("pending", "in_progress"):
                    return IngestionTask.from_dict(task_data)
            return None

    def get_pending_tasks(self) -> list[IngestionTask]:
        """Get all pending tasks."""
        with self._lock:
            state = self._load()
            pending = []
            for task_data in state.get("tasks", {}).values():
                if task_data.get("status") == "pending":
                    pending.append(IngestionTask.from_dict(task_data))
            return pending

    def cleanup_old_tasks(self, max_age_hours: int = MAX_TASK_AGE_HOURS) -> int:
        """Remove completed/failed tasks older than max_age_hours."""
        from datetime import timedelta

        with self._lock:
            state = self._load()
            cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
            removed = 0

            tasks_to_remove = []
            for task_id, task_data in state.get("tasks", {}).items():
                if task_data.get("status") in ("completed", "failed"):
                    completed_at = task_data.get("completed_at")
                    if completed_at:
                        try:
                            completed_time = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                            if completed_time < cutoff:
                                tasks_to_remove.append(task_id)
                        except (ValueError, TypeError):
                            pass

            for task_id in tasks_to_remove:
                del state["tasks"][task_id]
                removed += 1

            if removed > 0:
                self._save(state)
                logger.info(f"Cleaned up {removed} old tasks")

            return removed


# =============================================================================
# Worker (Background Thread)
# =============================================================================


ProgressCallback = Callable[[int, int, int], None]  # (processed, total, docs_created)


class IngestionWorker:
    """
    Background worker for async ingestion tasks.

    Runs in a daemon thread, periodically checking for pending tasks
    and processing them asynchronously.
    """

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._process_event = threading.Event()
        self._store = IngestionTaskStore()

    def start(self) -> None:
        """Start the background worker thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Ingestion worker started")

    def stop(self) -> None:
        """Stop the background worker thread."""
        self._running = False
        self._process_event.set()  # Wake up the thread
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Ingestion worker stopped")

    def queue_task(self, task: IngestionTask) -> str:
        """
        Queue a new ingestion task.

        Returns task_id. Wakes up worker for immediate processing.
        Raises ValueError if task already exists for this repo.
        """
        self._store.create_task(task)
        self._process_event.set()  # Wake up worker
        return task.task_id

    def get_status(self, task_id: str) -> Optional[dict]:
        """Get task status for polling."""
        task = self._store.get_task(task_id)
        if task is None:
            return None

        response = {
            "task_id": task.task_id,
            "repository": task.repository,
            "path": task.path,
            "status": task.status,
            "force_full": task.force_full,
            "progress": {
                "files_processed": task.files_processed,
                "files_total": task.files_total,
                "files_skipped": task.files_skipped,
                "docs_created": task.docs_created,
                "percent": round(task.files_processed / task.files_total * 100, 1)
                if task.files_total > 0
                else 0,
            },
            "timing": {
                "created_at": task.created_at,
                "started_at": task.started_at,
                "completed_at": task.completed_at,
            },
        }

        if task.status == "completed" and task.result:
            response["result"] = task.result

        if task.status == "failed" and task.error:
            response["error"] = task.error

        return response

    def _run_loop(self) -> None:
        """Main processing loop."""
        while self._running:
            try:
                # Cleanup old tasks periodically
                self._store.cleanup_old_tasks()

                # Process pending tasks
                self._process_pending_tasks()
            except Exception as e:
                logger.error(f"Worker error: {e}")

            # Wait for next interval or trigger
            self._process_event.wait(timeout=PROCESSING_INTERVAL)
            self._process_event.clear()

    def _process_pending_tasks(self) -> None:
        """Process all pending tasks."""
        pending = self._store.get_pending_tasks()

        for task in pending:
            if not self._running:
                break

            try:
                self._execute_ingestion(task)
            except Exception as e:
                logger.error(f"Error executing task {task.task_id}: {e}")
                self._store.fail_task(task.task_id, str(e))

    def _execute_ingestion(self, task: IngestionTask) -> None:
        """Execute a single ingestion task with progress callbacks."""
        from src.ingest.engine import ingest_codebase
        from src.llm import get_provider
        from src.tools.services import CONFIG, get_collection, get_searcher

        logger.info(f"Starting task {task.task_id} for {task.repository}")
        self._store.update_status(task.task_id, "in_progress")

        # Progress callback
        def on_progress(files_processed: int, files_total: int, docs_created: int):
            self._store.update_progress(
                task.task_id, files_processed, files_total, docs_created
            )

        try:
            collection = get_collection()

            # Get LLM provider if available
            llm_provider_instance = None
            if CONFIG["llm_provider"] != "none":
                try:
                    llm_provider_instance = get_provider()
                except Exception as e:
                    logger.warning(f"Could not get LLM provider: {e}")

            # Execute ingestion with progress tracking
            stats = ingest_codebase(
                root_path=task.path,
                collection=collection,
                repo_id=task.repository,
                force_full=task.force_full,
                include_patterns=task.include_patterns,
                use_cortexignore=task.use_cortexignore,
                llm_provider_instance=llm_provider_instance,
                progress_callback=on_progress,
            )

            # Rebuild search index
            get_searcher().build_index()

            self._store.complete_task(task.task_id, stats)
            logger.info(f"Task {task.task_id} completed: {stats.get('files_processed', 0)} files")

        except Exception as e:
            logger.error(f"Task {task.task_id} failed: {e}")
            self._store.fail_task(task.task_id, str(e))


# =============================================================================
# Global Instance
# =============================================================================


_worker: Optional[IngestionWorker] = None


def get_worker() -> IngestionWorker:
    """Get the global worker instance."""
    global _worker
    if _worker is None:
        _worker = IngestionWorker()
    return _worker


def start_worker() -> None:
    """Start the global worker."""
    get_worker().start()


def stop_worker() -> None:
    """Stop the global worker."""
    if _worker:
        _worker.stop()


def create_task(
    path: str,
    repository: str,
    force_full: bool = False,
    include_patterns: Optional[list[str]] = None,
    use_cortexignore: bool = True,
    files_total: int = 0,
) -> IngestionTask:
    """Create a new ingestion task."""
    return IngestionTask(
        task_id=f"ingest:{uuid.uuid4().hex[:12]}",
        repository=repository,
        path=path,
        status="pending",
        force_full=force_full,
        include_patterns=include_patterns,
        use_cortexignore=use_cortexignore,
        files_total=files_total,
    )
