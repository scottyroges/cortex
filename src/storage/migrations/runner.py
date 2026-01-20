"""
Migration Runner

Handles schema versioning and migration execution.
"""

import json
import os
from datetime import datetime, timezone
from typing import Callable, Optional

from src.configs import get_logger
from src.configs.paths import DB_PATH
from src.storage.migrations.backup import backup_database, restore_database

logger = get_logger("migrations")

# Current schema version - increment when adding migrations
SCHEMA_VERSION = 2

# Schema version file name
SCHEMA_VERSION_FILE = "schema_version.json"


def get_schema_version_path() -> str:
    """Get path to schema version file."""
    return os.path.join(os.path.expanduser(DB_PATH), SCHEMA_VERSION_FILE)


def get_current_schema_version() -> int:
    """
    Get the current schema version from disk.

    Returns:
        Current schema version (0 if not set)
    """
    path = get_schema_version_path()
    if not os.path.exists(path):
        return 0

    try:
        with open(path, "r") as f:
            data = json.load(f)
            return data.get("version", 0)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to read schema version: {e}")
        return 0


def save_schema_version(version: int) -> None:
    """Save schema version to disk."""
    path = get_schema_version_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    data = {
        "version": version,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Atomic write
    temp_path = path + ".tmp"
    with open(temp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_path, path)


def needs_migration() -> bool:
    """Check if migrations are needed."""
    current = get_current_schema_version()
    return current < SCHEMA_VERSION


def get_migrations() -> list[tuple[int, str, Callable]]:
    """
    Get list of migrations to run.

    Returns:
        List of (version, description, migration_function) tuples
    """
    from src.storage.migrations import migrations as m

    return [
        (1, "Initial schema version tracking", m.migration_001_initial),
        (2, "Rename 'commit' to 'session_summary'", m.migration_002_commit_to_session_summary),
        # Future migrations added here:
        # (3, "Add insight staleness tracking", m.migration_003_insights),
    ]


def run_migrations(
    from_version: Optional[int] = None,
    dry_run: bool = False,
) -> dict:
    """
    Run pending migrations.

    Args:
        from_version: Override starting version (for testing)
        dry_run: If True, don't apply changes

    Returns:
        Dict with migration results
    """
    current = from_version if from_version is not None else get_current_schema_version()
    migrations = get_migrations()

    # Filter to pending migrations
    pending = [(v, desc, fn) for v, desc, fn in migrations if v > current]

    if not pending:
        return {
            "status": "up_to_date",
            "current_version": current,
            "target_version": SCHEMA_VERSION,
            "migrations_run": 0,
        }

    logger.info(f"Running {len(pending)} migrations (from v{current} to v{SCHEMA_VERSION})")

    results = []
    final_version = current
    backup_path = None
    rolled_back = False

    # Create backup before migrations (unless dry run)
    if not dry_run:
        try:
            backup_path = backup_database(label="pre-migration")
            logger.info(f"Created pre-migration backup: {backup_path}")
        except FileNotFoundError:
            # No database yet, nothing to backup
            logger.debug("No database to backup (first run)")
        except Exception as e:
            logger.warning(f"Failed to create backup: {e}")

    for version, description, migration_fn in pending:
        logger.info(f"Running migration {version}: {description}")

        if dry_run:
            results.append({"version": version, "description": description, "status": "dry_run"})
            continue

        try:
            migration_fn()
            save_schema_version(version)
            final_version = version
            results.append({"version": version, "description": description, "status": "success"})
            logger.info(f"Migration {version} complete")
        except Exception as e:
            logger.error(f"Migration {version} failed: {e}")
            results.append({"version": version, "description": description, "status": "failed", "error": str(e)})

            # Rollback to pre-migration state
            if backup_path:
                try:
                    logger.info("Rolling back to pre-migration state")
                    restore_database(backup_path)
                    final_version = current  # Reset to original version
                    rolled_back = True
                    results[-1]["status"] = "failed_rolled_back"
                    logger.info("Rollback complete")
                except Exception as restore_error:
                    logger.error(f"Rollback failed: {restore_error}")
                    results[-1]["rollback_error"] = str(restore_error)
            break

    status = "complete" if final_version == SCHEMA_VERSION else ("rolled_back" if rolled_back else "partial")
    return {
        "status": status,
        "current_version": final_version,
        "target_version": SCHEMA_VERSION,
        "migrations_run": len([r for r in results if r["status"] == "success"]),
        "results": results,
        "backup_path": backup_path,
        "rolled_back": rolled_back,
    }
