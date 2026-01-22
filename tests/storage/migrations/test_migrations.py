"""Tests for migration system."""

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def temp_data_dir():
    """Create a temporary data directory for testing."""
    temp_dir = tempfile.mkdtemp()
    db_dir = Path(temp_dir) / "db"
    db_dir.mkdir(parents=True)

    # Create a fake database file
    (db_dir / "chroma.sqlite3").write_text("fake db content")

    yield temp_dir

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestSchemaVersioning:
    """Tests for schema version tracking."""

    def test_get_schema_version_no_file(self, temp_data_dir):
        """Test schema version returns 0 when file doesn't exist."""
        from src.storage.migrations.runner import get_current_schema_version

        with patch("src.storage.migrations.runner.DB_PATH", str(Path(temp_data_dir) / "db")):
            version = get_current_schema_version()
            assert version == 0

    def test_save_and_load_schema_version(self, temp_data_dir):
        """Test saving and loading schema version."""
        from src.storage.migrations.runner import (
            get_current_schema_version,
            save_schema_version,
        )

        db_path = str(Path(temp_data_dir) / "db")

        with patch("src.storage.migrations.runner.DB_PATH", db_path):
            save_schema_version(5)
            assert get_current_schema_version() == 5

            # Verify file contents
            version_file = Path(db_path) / "schema_version.json"
            assert version_file.exists()
            data = json.loads(version_file.read_text())
            assert data["version"] == 5
            assert "updated_at" in data

    def test_needs_migration_true(self, temp_data_dir):
        """Test needs_migration returns True when version is behind."""
        from src.storage.migrations.runner import needs_migration, SCHEMA_VERSION

        with patch("src.storage.migrations.runner.get_current_schema_version") as mock_version:
            mock_version.return_value = 0
            assert needs_migration() is True

            mock_version.return_value = SCHEMA_VERSION - 1
            assert needs_migration() is True

    def test_needs_migration_false(self, temp_data_dir):
        """Test needs_migration returns False when up to date."""
        from src.storage.migrations.runner import needs_migration, SCHEMA_VERSION

        with patch("src.storage.migrations.runner.get_current_schema_version") as mock_version:
            mock_version.return_value = SCHEMA_VERSION
            assert needs_migration() is False


class TestMigrationRunner:
    """Tests for migration execution."""

    def test_run_migrations_already_up_to_date(self, temp_data_dir):
        """Test run_migrations when already up to date."""
        from src.storage.migrations.runner import run_migrations, SCHEMA_VERSION

        with patch("src.storage.migrations.runner.get_current_schema_version") as mock_version:
            mock_version.return_value = SCHEMA_VERSION

            result = run_migrations()

            assert result["status"] == "up_to_date"
            assert result["migrations_run"] == 0

    def test_run_migrations_dry_run(self, temp_data_dir):
        """Test dry run mode doesn't modify anything."""
        from src.storage.migrations.runner import run_migrations

        db_path = str(Path(temp_data_dir) / "db")

        with patch("src.storage.migrations.runner.DB_PATH", db_path), \
             patch("src.storage.migrations.runner.get_current_schema_version") as mock_version:
            mock_version.return_value = 0

            result = run_migrations(dry_run=True)

            # Should report migrations would run
            assert len(result.get("results", [])) > 0
            for r in result.get("results", []):
                assert r["status"] == "dry_run"

            # Version file should not exist (dry run)
            version_file = Path(db_path) / "schema_version.json"
            assert not version_file.exists()

    def test_run_migrations_from_zero(self, temp_data_dir):
        """Test running migrations from version 0."""
        from unittest.mock import MagicMock
        from src.storage.migrations.runner import run_migrations, SCHEMA_VERSION

        db_path = str(Path(temp_data_dir) / "db")

        # Mock get_collection for migrations that need it
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": [], "documents": [], "metadatas": [], "embeddings": []}

        with patch("src.storage.migrations.runner.DB_PATH", db_path), \
             patch("src.configs.services.get_collection", return_value=mock_collection):
            result = run_migrations(from_version=0)

            assert result["status"] == "complete"
            assert result["current_version"] == SCHEMA_VERSION
            assert result["migrations_run"] >= 1


class TestBackup:
    """Tests for backup functionality."""

    def test_backup_creates_copy(self, temp_data_dir):
        """Test backup creates a copy of the database."""
        from src.storage.migrations.backup import backup_database

        with patch("src.storage.migrations.backup.DB_PATH", str(Path(temp_data_dir) / "db")), \
             patch("src.storage.migrations.backup.get_data_path") as mock_data_path:
            mock_data_path.return_value = Path(temp_data_dir)

            backup_path = backup_database(label="test")

            assert os.path.exists(backup_path)
            assert "backup_test_" in backup_path
            # Verify content was copied
            assert (Path(backup_path) / "chroma.sqlite3").exists()
            assert (Path(backup_path) / "chroma.sqlite3").read_text() == "fake db content"

    def test_backup_without_label(self, temp_data_dir):
        """Test backup without a label uses timestamp only."""
        from src.storage.migrations.backup import backup_database

        with patch("src.storage.migrations.backup.DB_PATH", str(Path(temp_data_dir) / "db")), \
             patch("src.storage.migrations.backup.get_data_path") as mock_data_path:
            mock_data_path.return_value = Path(temp_data_dir)

            backup_path = backup_database()

            assert os.path.exists(backup_path)
            assert "backup_" in backup_path

    def test_list_backups(self, temp_data_dir):
        """Test listing backups."""
        from src.storage.migrations.backup import list_backups

        # Create fake backup directories
        backups_dir = Path(temp_data_dir) / "backups"
        backups_dir.mkdir()
        (backups_dir / "backup_test_20240101_120000").mkdir()
        (backups_dir / "backup_test_20240102_120000").mkdir()
        (backups_dir / "not_a_backup").mkdir()  # Should be ignored

        with patch("src.storage.migrations.backup.get_backup_dir") as mock_dir:
            mock_dir.return_value = backups_dir

            backups = list_backups()
            assert len(backups) == 2
            # Should be sorted by date descending
            assert "20240102" in backups[0]["name"]
            assert "20240101" in backups[1]["name"]

    def test_backup_cleanup_keeps_recent(self, temp_data_dir):
        """Test that backup cleanup keeps the N most recent backups."""
        from src.storage.migrations.backup import backup_database

        with patch("src.storage.migrations.backup.DB_PATH", str(Path(temp_data_dir) / "db")), \
             patch("src.storage.migrations.backup.get_data_path") as mock_data_path:
            mock_data_path.return_value = Path(temp_data_dir)

            # Create more than 5 backups
            for i in range(7):
                backup_database(label=f"test{i}")

            # Check that only 5 remain
            backups_dir = Path(temp_data_dir) / "backups"
            backups = list(backups_dir.iterdir())
            assert len(backups) == 5

    def test_backup_fails_if_no_db(self, temp_data_dir):
        """Test backup raises error if database doesn't exist."""
        from src.storage.migrations.backup import backup_database

        # Point to non-existent db
        with patch("src.storage.migrations.backup.DB_PATH", "/nonexistent/db"), \
             patch("src.storage.migrations.backup.get_data_path") as mock_data_path:
            mock_data_path.return_value = Path(temp_data_dir)

            with pytest.raises(FileNotFoundError):
                backup_database()


class TestVersionCheck:
    """Tests for version checking."""

    def test_get_current_version(self):
        """Test getting current version info."""
        from src.tools.orient.version import get_current_version

        with patch.dict(os.environ, {
            "CORTEX_GIT_COMMIT": "abc1234567890",
            "CORTEX_BUILD_TIME": "2024-01-01T00:00:00Z",
        }):
            version = get_current_version()

            assert version["git_commit"] == "abc1234567890"
            assert version["build_time"] == "2024-01-01T00:00:00Z"
            assert "version" in version

    def test_check_for_updates_no_local_head(self):
        """Test update check without local HEAD."""
        from src.tools.orient.version import check_for_updates, clear_version_cache

        clear_version_cache()
        result = check_for_updates(local_head=None)

        assert "update_available" in result
        assert "current_version" in result
        assert result["update_available"] is False

    def test_check_for_updates_same_commit(self):
        """Test update check when commits match."""
        from src.tools.orient.version import check_for_updates, clear_version_cache

        with patch.dict(os.environ, {"CORTEX_GIT_COMMIT": "abc1234"}):
            clear_version_cache()
            result = check_for_updates(local_head="abc1234567890")

            assert result["update_available"] is False

    def test_check_for_updates_different_commit(self):
        """Test update check when commits differ (local_head fallback)."""
        from src.tools.orient.version import check_for_updates, clear_version_cache

        with patch.dict(os.environ, {"CORTEX_GIT_COMMIT": "abc1234"}):
            # Mock GHCR check to return None so we fall back to local_head comparison
            with patch("src.tools.orient.version._check_ghcr_latest", return_value=None):
                clear_version_cache()
                result = check_for_updates(local_head="def5678901234")

                assert result["update_available"] is True
                assert result["check_method"] == "local_head"
                assert "message" in result

    def test_version_cache(self):
        """Test that version check results are cached."""
        from src.tools.orient.version import check_for_updates, clear_version_cache, _version_cache

        clear_version_cache()

        with patch.dict(os.environ, {"CORTEX_GIT_COMMIT": "abc1234"}):
            # First call
            result1 = check_for_updates(local_head="def5678")

            # Verify cache was populated
            assert len(_version_cache) > 0

            # Second call should use cache
            result2 = check_for_updates(local_head="def5678")

            assert result1 == result2
