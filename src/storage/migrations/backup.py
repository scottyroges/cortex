"""
Database Backup and Restore

Handles backup before migrations and restore on failure.
"""

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.configs import get_logger
from src.configs.paths import DB_PATH, get_data_path

logger = get_logger("migrations.backup")


def get_backup_dir() -> Path:
    """Get the backup directory path."""
    return Path(get_data_path()) / "backups"


def backup_database(label: Optional[str] = None) -> str:
    """
    Create a backup of the database directory.

    Args:
        label: Optional label for the backup (default: timestamp only)

    Returns:
        Path to the backup directory
    """
    db_path = Path(os.path.expanduser(DB_PATH))

    if not db_path.exists():
        raise FileNotFoundError(f"Database directory not found: {db_path}")

    backup_dir = get_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Clean old backups first (keep 4, so after new backup we have 5)
    _cleanup_old_backups(backup_dir, keep=4)

    # Generate backup name
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{label}_{timestamp}" if label else f"backup_{timestamp}"
    backup_path = backup_dir / backup_name

    logger.info(f"Creating backup: {backup_path}")
    shutil.copytree(db_path, backup_path)

    return str(backup_path)


def restore_database(backup_path: str) -> None:
    """
    Restore database from a backup.

    Args:
        backup_path: Path to the backup directory
    """
    db_path = Path(os.path.expanduser(DB_PATH))
    backup = Path(backup_path)

    if not backup.exists():
        raise FileNotFoundError(f"Backup not found: {backup_path}")

    logger.info(f"Restoring from backup: {backup_path}")

    # Remove current db
    if db_path.exists():
        shutil.rmtree(db_path)

    # Restore from backup
    shutil.copytree(backup, db_path)
    logger.info("Database restored successfully")


def list_backups() -> list[dict]:
    """List available backups with metadata."""
    backup_dir = get_backup_dir()
    if not backup_dir.exists():
        return []

    backups = []
    for entry in sorted(backup_dir.iterdir(), reverse=True):
        if entry.is_dir() and entry.name.startswith("backup_"):
            stat = entry.stat()
            # Calculate size
            size_bytes = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
            backups.append({
                "path": str(entry),
                "name": entry.name,
                "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "size_mb": round(size_bytes / 1024 / 1024, 2),
            })

    return backups


def _cleanup_old_backups(backup_dir: Path, keep: int = 5) -> None:
    """Remove old backups, keeping the most recent N."""
    backups = sorted(
        [d for d in backup_dir.iterdir() if d.is_dir() and d.name.startswith("backup_")],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )

    for old_backup in backups[keep:]:
        logger.debug(f"Removing old backup: {old_backup}")
        shutil.rmtree(old_backup)
