"""
Admin API Endpoints

HTTP endpoints for migrations, backups, and ingestion status.
"""

from typing import Any, Optional

from fastapi import APIRouter, Query

from src.configs import get_logger

logger = get_logger("http.api.admin")

router = APIRouter()


# --- Migration/Admin Endpoints ---


@router.get("/migrations/status")
def migrations_status() -> dict[str, Any]:
    """
    Get current migration status.

    Returns schema version info and whether migrations are needed.
    """
    from src.storage.migrations import (
        SCHEMA_VERSION,
        get_current_schema_version,
        needs_migration,
    )

    return {
        "current_version": get_current_schema_version(),
        "target_version": SCHEMA_VERSION,
        "needs_migration": needs_migration(),
    }


@router.post("/admin/backup")
def create_backup(label: Optional[str] = None) -> dict[str, Any]:
    """
    Create a database backup.

    Args:
        label: Optional label for the backup
    """
    from src.storage.migrations import backup_database

    try:
        backup_path = backup_database(label=label or "manual")
        return {
            "status": "success",
            "backup_path": backup_path,
        }
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        return {
            "status": "error",
            "error": str(e),
        }


@router.get("/admin/backups")
def get_backups() -> dict[str, Any]:
    """List available backups."""
    from src.storage.migrations import list_backups

    return {
        "backups": list_backups(),
    }


# --- Ingestion Status Endpoints ---


@router.get("/ingest-status")
def list_ingest_tasks(repository: Optional[str] = None) -> dict[str, Any]:
    """
    List all ingestion tasks, optionally filtered by repository.

    Returns summary of active and recent tasks.

    Args:
        repository: Optional filter by repository name
    """
    from src.tools.ingest.async_processor import get_worker

    worker = get_worker()
    tasks = worker._store.get_all_tasks(repository=repository)

    return {
        "tasks": [
            {
                "task_id": t.task_id,
                "repository": t.repository,
                "status": t.status,
                "force_full": t.force_full,
                "progress": {
                    "files_processed": t.files_processed,
                    "files_total": t.files_total,
                    "percent": round(t.files_processed / t.files_total * 100, 1)
                    if t.files_total > 0
                    else 0,
                },
                "created_at": t.created_at,
                "completed_at": t.completed_at,
            }
            for t in tasks
        ]
    }


@router.get("/ingest-status/{task_id}")
def get_ingest_task_status(task_id: str) -> dict[str, Any]:
    """
    Get detailed status of a specific ingestion task.

    Returns full progress information and results if completed.

    Args:
        task_id: Task ID from ingest_code_into_cortex
    """
    from src.tools.ingest.async_processor import get_worker

    worker = get_worker()
    status = worker.get_status(task_id)

    if status is None:
        return {
            "status": "not_found",
            "task_id": task_id,
            "error": "Task not found or expired",
        }

    return status
