"""
Tests for staleness detection and validation.
"""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.tools.staleness import (
    check_insight_staleness,
    check_note_staleness,
    format_verification_warning,
)


class TestCheckInsightStaleness:
    """Tests for check_insight_staleness function."""

    def test_fresh_insight_no_changes(self):
        """Test insight with no file changes is fresh."""
        now = datetime.now(timezone.utc).isoformat()
        metadata = {
            "type": "insight",
            "created_at": now,
            "verified_at": now,
            "status": "active",
            "files": json.dumps(["src/test.py"]),
            "file_hashes": json.dumps({"src/test.py": "abc123"}),
        }

        result = check_insight_staleness(metadata, repo_path=None)

        assert result["level"] == "fresh"
        assert result["verification_required"] is False
        assert result["files_changed"] == []
        assert result["files_deleted"] == []

    def test_insight_with_changed_files(self, tmp_path):
        """Test insight detects file changes via hash comparison."""
        # Create a test file
        test_file = tmp_path / "src" / "test.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("print('hello')")

        now = datetime.now(timezone.utc).isoformat()
        metadata = {
            "type": "insight",
            "created_at": now,
            "verified_at": now,
            "status": "active",
            "files": json.dumps(["src/test.py"]),
            "file_hashes": json.dumps({"src/test.py": "different_hash"}),
        }

        result = check_insight_staleness(metadata, repo_path=str(tmp_path))

        assert result["level"] == "likely_stale"
        assert result["verification_required"] is True
        assert "src/test.py" in result["files_changed"]

    def test_insight_with_deleted_files(self, tmp_path):
        """Test insight detects deleted files."""
        now = datetime.now(timezone.utc).isoformat()
        metadata = {
            "type": "insight",
            "created_at": now,
            "verified_at": now,
            "status": "active",
            "files": json.dumps(["src/deleted.py"]),
            "file_hashes": json.dumps({"src/deleted.py": "abc123"}),
        }

        result = check_insight_staleness(metadata, repo_path=str(tmp_path))

        assert result["level"] == "files_deleted"
        assert result["verification_required"] is True
        assert "src/deleted.py" in result["files_deleted"]

    def test_insight_time_based_staleness(self):
        """Test insight becomes possibly stale after threshold."""
        old_time = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        metadata = {
            "type": "insight",
            "created_at": old_time,
            "verified_at": old_time,
            "status": "active",
            "files": json.dumps([]),
            "file_hashes": json.dumps({}),
        }

        result = check_insight_staleness(metadata, repo_path=None)

        assert result["level"] == "possibly_stale"
        assert result["days_since_verified"] >= 45

    def test_insight_very_stale_requires_verification(self):
        """Test very old insight requires verification."""
        old_time = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        metadata = {
            "type": "insight",
            "created_at": old_time,
            "verified_at": old_time,
            "status": "active",
            "files": json.dumps([]),
            "file_hashes": json.dumps({}),
        }

        result = check_insight_staleness(metadata, repo_path=None)

        assert result["level"] == "possibly_stale"
        assert result["verification_required"] is True

    def test_deprecated_insight_returns_deprecated(self):
        """Test deprecated insight returns deprecated level."""
        now = datetime.now(timezone.utc).isoformat()
        metadata = {
            "type": "insight",
            "created_at": now,
            "verified_at": now,
            "status": "deprecated",
            "files": json.dumps([]),
            "file_hashes": json.dumps({}),
        }

        result = check_insight_staleness(metadata, repo_path=None)

        assert result["level"] == "deprecated"


class TestCheckNoteStaleness:
    """Tests for check_note_staleness function."""

    def test_fresh_note(self):
        """Test recent note is fresh."""
        now = datetime.now(timezone.utc).isoformat()
        metadata = {
            "type": "note",
            "created_at": now,
            "verified_at": now,
            "status": "active",
        }

        result = check_note_staleness(metadata)

        assert result["level"] == "fresh"
        assert result["verification_required"] is False

    def test_old_note_staleness(self):
        """Test old note becomes possibly stale."""
        old_time = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        metadata = {
            "type": "note",
            "created_at": old_time,
            "verified_at": old_time,
            "status": "active",
        }

        result = check_note_staleness(metadata)

        assert result["level"] == "possibly_stale"
        assert result["verification_required"] is True

    def test_deprecated_note(self):
        """Test deprecated note returns deprecated level."""
        now = datetime.now(timezone.utc).isoformat()
        metadata = {
            "type": "note",
            "created_at": now,
            "verified_at": now,
            "status": "deprecated",
        }

        result = check_note_staleness(metadata)

        assert result["level"] == "deprecated"


class TestFormatVerificationWarning:
    """Tests for format_verification_warning function."""

    def test_no_warning_for_fresh(self):
        """Test no warning for fresh content."""
        staleness = {
            "level": "fresh",
            "verification_required": False,
        }
        metadata = {"type": "insight"}

        result = format_verification_warning(staleness, metadata)

        assert result == ""

    def test_warning_for_files_deleted(self):
        """Test warning message for deleted files."""
        staleness = {
            "level": "files_deleted",
            "verification_required": True,
            "files_deleted": ["src/auth.py", "src/users.py"],
        }
        metadata = {"type": "insight"}

        result = format_verification_warning(staleness, metadata)

        assert "VERIFICATION REQUIRED" in result
        assert "FILES DELETED" in result
        assert "src/auth.py" in result

    def test_warning_for_files_changed(self):
        """Test warning message for changed files."""
        staleness = {
            "level": "likely_stale",
            "verification_required": True,
            "files_changed": ["src/config.py"],
        }
        metadata = {"type": "insight"}

        result = format_verification_warning(staleness, metadata)

        assert "VERIFICATION REQUIRED" in result
        assert "FILES CHANGED" in result
        assert "src/config.py" in result
        assert "MUST re-read" in result

    def test_warning_for_possibly_stale(self):
        """Test warning message for time-based staleness."""
        staleness = {
            "level": "possibly_stale",
            "verification_required": True,
            "days_since_verified": 95,
        }
        metadata = {"type": "note"}

        result = format_verification_warning(staleness, metadata)

        assert "POSSIBLY OUTDATED" in result
        assert "95 days old" in result

    def test_warning_for_deprecated_with_replacement(self):
        """Test warning message for deprecated content."""
        staleness = {
            "level": "deprecated",
            "verification_required": False,
        }
        metadata = {
            "type": "insight",
            "superseded_by": "insight:abc123",
        }

        result = format_verification_warning(staleness, metadata)

        assert "DEPRECATED" in result
        assert "insight:abc123" in result


class TestValidateInsight:
    """Tests for validate_insight function."""

    @pytest.fixture
    def temp_db_dir(self):
        """Create temporary database directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def mock_services(self, temp_db_dir):
        """Set up mocked services for validate_insight."""
        import chromadb
        client = chromadb.PersistentClient(path=temp_db_dir)
        collection = client.get_or_create_collection("cortex_memory")

        mock_searcher = MagicMock()
        mock_searcher.build_index = MagicMock()

        with patch("src.tools.notes.get_collection", return_value=collection), \
             patch("src.tools.notes.get_repo_path", return_value=None), \
             patch("src.tools.notes.get_searcher", return_value=mock_searcher), \
             patch("src.tools.notes.get_current_branch", return_value="main"), \
             patch("src.tools.notes.get_head_commit", return_value="abc123"), \
             patch("src.tools.initiatives.get_collection", return_value=collection):
            yield collection

    def test_validate_insight_still_valid(self, mock_services):
        """Test validating insight as still valid updates verified_at."""
        from src.tools.notes import insight_to_cortex, validate_insight

        collection = mock_services

        # Create an insight first
        create_result = json.loads(insight_to_cortex(
            insight="Test insight",
            files=["src/test.py"],
            repository="TestRepo"
        ))

        insight_id = create_result["insight_id"]

        # Validate it as still valid
        validate_result = json.loads(validate_insight(
            insight_id=insight_id,
            validation_result="still_valid",
            notes="Checked and confirmed accurate",
        ))

        assert validate_result["status"] == "validated"
        assert validate_result["validation_result"] == "still_valid"
        assert "verified_at" in validate_result

    def test_validate_insight_no_longer_valid_deprecate(self, mock_services):
        """Test deprecating an invalid insight."""
        from src.tools.notes import insight_to_cortex, validate_insight

        collection = mock_services

        # Create an insight
        create_result = json.loads(insight_to_cortex(
            insight="Outdated insight",
            files=["src/old.py"],
            repository="TestRepo"
        ))

        insight_id = create_result["insight_id"]

        # Validate as no longer valid and deprecate
        validate_result = json.loads(validate_insight(
            insight_id=insight_id,
            validation_result="no_longer_valid",
            notes="Code has completely changed",
            deprecate=True,
        ))

        assert validate_result["status"] == "validated"
        assert validate_result["deprecated"] is True

        # Check metadata was updated
        results = collection.get(ids=[insight_id], include=["metadatas"])
        assert results["metadatas"][0]["status"] == "deprecated"

    def test_validate_insight_with_replacement(self, mock_services):
        """Test deprecating insight and creating replacement."""
        from src.tools.notes import insight_to_cortex, validate_insight

        collection = mock_services

        # Create original insight
        create_result = json.loads(insight_to_cortex(
            insight="Old understanding",
            files=["src/code.py"],
            repository="TestRepo",
            title="Original Insight"
        ))

        original_id = create_result["insight_id"]

        # Validate as invalid with replacement
        validate_result = json.loads(validate_insight(
            insight_id=original_id,
            validation_result="no_longer_valid",
            notes="Architecture changed",
            deprecate=True,
            replacement_insight="New understanding after refactor",
        ))

        assert validate_result["status"] == "validated"
        assert "replacement_id" in validate_result

        # Check original points to replacement
        original = collection.get(ids=[original_id], include=["metadatas"])
        assert original["metadatas"][0]["superseded_by"] == validate_result["replacement_id"]

    def test_validate_nonexistent_insight(self, mock_services):
        """Test validating insight that doesn't exist."""
        from src.tools.notes import validate_insight

        result = json.loads(validate_insight(
            insight_id="insight:nonexistent",
            validation_result="still_valid",
        ))

        assert result["status"] == "error"
        assert "not found" in result["error"].lower()

    def test_validate_wrong_type(self, mock_services):
        """Test validating a document that isn't an insight."""
        from src.tools.notes import save_note_to_cortex, validate_insight

        # Create a note (not an insight)
        note_result = json.loads(save_note_to_cortex(
            content="This is a note",
            repository="TestRepo"
        ))

        note_id = note_result["note_id"]

        # Try to validate it as an insight
        result = json.loads(validate_insight(
            insight_id=note_id,
            validation_result="still_valid",
        ))

        assert result["status"] == "error"
        assert "not an insight" in result["error"].lower()
