"""
Tests for src/tools/memory module.

Covers:
- save_memory (notes and insights)
- conclude_session
- _build_base_context helper
- _resolve_repository
- Initiative tagging
"""

import json
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def temp_db_dir():
    """Create temporary database directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_services(temp_db_dir):
    """Set up mocked services for memory tools."""
    import chromadb
    client = chromadb.PersistentClient(path=temp_db_dir)
    collection = client.get_or_create_collection("cortex_memory")

    mock_searcher = MagicMock()
    mock_searcher.build_index = MagicMock()

    with patch("src.tools.memory.memory.get_collection", return_value=collection), \
         patch("src.tools.memory.memory.get_repo_path", return_value=None), \
         patch("src.tools.memory.memory.get_searcher", return_value=mock_searcher), \
         patch("src.tools.memory.memory.get_current_branch", return_value="main"), \
         patch("src.tools.memory.memory.get_head_commit", return_value="abc123"), \
         patch("src.tools.initiatives.initiatives.get_collection", return_value=collection), \
         patch("src.tools.initiatives.focus.get_collection", return_value=collection):
        yield collection


class TestSaveMemory:
    """Tests for the unified save_memory function."""

    def test_save_note_via_save_memory(self, mock_services):
        """Test saving a note through save_memory."""
        from src.tools.memory import save_memory

        result = json.loads(save_memory(
            content="This is a test note",
            kind="note",
            title="Test Note",
            repository="TestRepo"
        ))

        assert result["status"] == "saved"
        assert result["note_id"].startswith("note:")
        assert result["title"] == "Test Note"

    def test_save_insight_via_save_memory(self, mock_services):
        """Test saving an insight through save_memory."""
        from src.tools.memory import save_memory

        result = json.loads(save_memory(
            content="This module uses observer pattern",
            kind="insight",
            files=["src/events.py"],
            repository="TestRepo"
        ))

        assert result["status"] == "saved"
        assert result["insight_id"].startswith("insight:")
        assert result["type"] == "insight"
        assert "src/events.py" in result["files"]

    def test_save_insight_requires_files(self, mock_services):
        """Test that save_memory with kind='insight' requires files."""
        from src.tools.memory import save_memory

        result = json.loads(save_memory(
            content="Insight without files",
            kind="insight",
            repository="TestRepo"
        ))

        assert result["status"] == "error"
        assert "files" in result["error"].lower()

    def test_save_memory_invalid_kind(self, mock_services):
        """Test save_memory with invalid kind."""
        from src.tools.memory import save_memory

        result = json.loads(save_memory(
            content="Some content",
            kind="invalid",
            repository="TestRepo"
        ))

        assert result["status"] == "error"
        assert "Unknown kind" in result["error"]


class TestConcludeSession:
    """Tests for conclude_session function."""

    def test_basic_session_summary(self, mock_services):
        """Test creating a basic session summary."""
        from src.tools.memory import conclude_session

        result = json.loads(conclude_session(
            summary="Implemented feature X",
            changed_files=["src/feature.py", "tests/test_feature.py"],
            repository="TestRepo"
        ))

        assert result["status"] == "success"
        assert result["session_id"].startswith("session_summary:")
        assert result["summary_saved"] is True
        assert result["files_recorded"] == 2

    def test_session_summary_with_initiative(self, mock_services):
        """Test session summary auto-tags focused initiative."""
        collection = mock_services
        now = datetime.now(timezone.utc).isoformat()

        # Create and focus an initiative
        collection.add(
            ids=["initiative:test123"],
            documents=["Test Initiative"],
            metadatas=[{
                "type": "initiative",
                "repository": "TestRepo",
                "name": "Test Initiative",
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }],
        )
        collection.upsert(
            ids=["TestRepo:focus"],
            documents=["Current focus: Test Initiative"],
            metadatas=[{
                "type": "focus",
                "repository": "TestRepo",
                "initiative_id": "initiative:test123",
                "initiative_name": "Test Initiative",
            }],
        )

        from src.tools.memory import conclude_session

        result = json.loads(conclude_session(
            summary="Work on test initiative",
            changed_files=["src/code.py"],
            repository="TestRepo"
        ))

        assert result["status"] == "success"
        assert "initiative" in result
        assert result["initiative"]["id"] == "initiative:test123"

    def test_session_summary_detects_completion_signals(self, mock_services):
        """Test that completion signals are detected in summary."""
        collection = mock_services
        now = datetime.now(timezone.utc).isoformat()

        # Create and focus an initiative
        collection.add(
            ids=["initiative:comp123"],
            documents=["Completable Initiative"],
            metadatas=[{
                "type": "initiative",
                "repository": "TestRepo",
                "name": "Completable",
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }],
        )
        collection.upsert(
            ids=["TestRepo:focus"],
            documents=["Current focus: Completable"],
            metadatas=[{
                "type": "focus",
                "repository": "TestRepo",
                "initiative_id": "initiative:comp123",
                "initiative_name": "Completable",
            }],
        )

        from src.tools.memory import conclude_session

        result = json.loads(conclude_session(
            summary="Feature is complete and merged to main",
            changed_files=["src/feature.py"],
            repository="TestRepo"
        ))

        assert result["initiative"]["completion_signal_detected"] is True
        assert result["initiative"]["prompt"] == "mark_complete"


class TestResolveRepository:
    """Tests for repository resolution logic."""

    def test_explicit_repository(self, mock_services):
        """Test that explicit repository is used."""
        from src.tools.memory.memory import _resolve_repository

        with patch("src.tools.memory.memory.get_repo_path", return_value="/some/path"):
            result = _resolve_repository("ExplicitRepo")
            assert result == "ExplicitRepo"

    def test_repository_from_cwd(self, mock_services):
        """Test repository detection from current working directory."""
        from src.tools.memory.memory import _resolve_repository

        with patch("src.tools.memory.memory.get_repo_path", return_value="/path/to/MyRepo"):
            result = _resolve_repository(None)
            assert result == "MyRepo"

    def test_repository_from_focus(self, mock_services):
        """Test repository detection from focused initiative."""
        collection = mock_services

        # Create a focus document
        collection.upsert(
            ids=["FocusedRepo:focus"],
            documents=["Current focus"],
            metadatas=[{
                "type": "focus",
                "repository": "FocusedRepo",
                "initiative_id": "initiative:test",
                "initiative_name": "Test",
            }],
        )

        from src.tools.memory.memory import _resolve_repository

        with patch("src.tools.memory.memory.get_repo_path", return_value=None):
            result = _resolve_repository(None)
            assert result == "FocusedRepo"

    def test_repository_fallback_to_global(self, mock_services):
        """Test fallback to 'global' when no detection works."""
        from src.tools.memory.memory import _resolve_repository

        with patch("src.tools.memory.memory.get_repo_path", return_value=None), \
             patch("src.tools.memory.memory.get_any_focused_repository", return_value=None):
            result = _resolve_repository(None)
            assert result == "global"


class TestBuildBaseContext:
    """Tests for the _build_base_context helper."""

    def test_builds_complete_context(self, mock_services):
        """Test that _build_base_context returns all expected fields."""
        from src.tools.memory.memory import _build_base_context

        ctx = _build_base_context("TestRepo", None)

        assert "repo" in ctx
        assert "collection" in ctx
        assert "repo_path" in ctx
        assert "branch" in ctx
        assert "timestamp" in ctx
        assert "current_commit" in ctx
        assert "initiative_id" in ctx
        assert "initiative_name" in ctx

        assert ctx["repo"] == "TestRepo"
        # branch is "unknown" when repo_path is None (mocked)
        assert ctx["branch"] == "unknown"

    def test_resolves_initiative(self, mock_services):
        """Test that _build_base_context resolves initiative."""
        collection = mock_services
        now = datetime.now(timezone.utc).isoformat()

        # Create and focus an initiative
        collection.add(
            ids=["initiative:ctx123"],
            documents=["Context Test Initiative"],
            metadatas=[{
                "type": "initiative",
                "repository": "TestRepo",
                "name": "Context Test",
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }],
        )
        collection.upsert(
            ids=["TestRepo:focus"],
            documents=["Current focus: Context Test"],
            metadatas=[{
                "type": "focus",
                "repository": "TestRepo",
                "initiative_id": "initiative:ctx123",
                "initiative_name": "Context Test",
            }],
        )

        from src.tools.memory.memory import _build_base_context

        ctx = _build_base_context("TestRepo", None)

        assert ctx["initiative_id"] == "initiative:ctx123"
        assert ctx["initiative_name"] == "Context Test"


class TestComputeFileHashes:
    """Tests for _compute_file_hashes helper."""

    def test_computes_hashes_for_existing_files(self, temp_db_dir):
        """Test that file hashes are computed for files that exist."""
        import os
        from src.tools.memory.memory import _compute_file_hashes

        # Create a test file
        test_file = os.path.join(temp_db_dir, "test.py")
        with open(test_file, "w") as f:
            f.write("print('hello')")

        hashes = _compute_file_hashes(["test.py"], temp_db_dir)

        assert "test.py" in hashes
        assert len(hashes["test.py"]) > 0

    def test_skips_nonexistent_files(self, temp_db_dir):
        """Test that nonexistent files are skipped."""
        from src.tools.memory.memory import _compute_file_hashes

        hashes = _compute_file_hashes(["nonexistent.py"], temp_db_dir)

        assert "nonexistent.py" not in hashes

    def test_returns_empty_without_repo_path(self):
        """Test that empty dict is returned when repo_path is None."""
        from src.tools.memory.memory import _compute_file_hashes

        hashes = _compute_file_hashes(["file.py"], None)

        assert hashes == {}


class TestGetAnyFocusedRepository:
    """Tests for get_any_focused_repository in initiatives module."""

    def test_returns_repository_from_focus(self, mock_services):
        """Test that repository is returned from a focus document."""
        collection = mock_services

        collection.upsert(
            ids=["SomeRepo:focus"],
            documents=["Current focus"],
            metadatas=[{
                "type": "focus",
                "repository": "SomeRepo",
                "initiative_id": "initiative:test",
                "initiative_name": "Test",
            }],
        )

        from src.tools.initiatives import get_any_focused_repository

        result = get_any_focused_repository()
        assert result == "SomeRepo"

    def test_returns_none_when_no_focus(self, mock_services):
        """Test that None is returned when no focus exists."""
        from src.tools.initiatives import get_any_focused_repository

        result = get_any_focused_repository()
        assert result is None


class TestSecretScrubbing:
    """Tests for secret scrubbing in memory operations."""

    def test_secrets_scrubbed_from_notes(self, mock_services):
        """Test that secrets are scrubbed from note content."""
        collection = mock_services
        from src.tools.memory import save_memory

        save_memory(
            content="API key is AKIAIOSFODNN7EXAMPLE for AWS",
            kind="note",
            repository="TestRepo"
        )

        # Check stored document
        results = collection.get(
            where={"type": "note"},
            include=["documents"],
        )

        assert "AKIAIOSFODNN7EXAMPLE" not in results["documents"][0]

    def test_secrets_scrubbed_from_session_summary(self, mock_services):
        """Test that secrets are scrubbed from session summaries."""
        collection = mock_services
        from src.tools.memory import conclude_session

        conclude_session(
            summary="Used AWS key: AKIAIOSFODNN7EXAMPLE for S3 access",
            changed_files=["config.py"],
            repository="TestRepo"
        )

        results = collection.get(
            where={"type": "session_summary"},
            include=["documents"],
        )

        # Secret scrubber should have redacted the AWS key
        doc = results["documents"][0]
        assert "AKIAIOSFODNN7EXAMPLE" not in doc


class TestSearchIndexRebuild:
    """Tests for search index rebuild after save operations."""

    def test_index_rebuilt_after_save_note(self, mock_services):
        """Test that search index is rebuilt after saving a note."""
        from src.tools.memory import save_memory

        with patch("src.tools.memory.memory.get_searcher") as mock_get_searcher:
            mock_searcher = MagicMock()
            mock_get_searcher.return_value = mock_searcher

            save_memory(
                content="Test note",
                kind="note",
                repository="TestRepo"
            )

            mock_searcher.build_index.assert_called_once()

    def test_index_rebuilt_after_conclude_session(self, mock_services):
        """Test that search index is rebuilt after concluding session."""
        from src.tools.memory import conclude_session

        with patch("src.tools.memory.memory.get_searcher") as mock_get_searcher:
            mock_searcher = MagicMock()
            mock_get_searcher.return_value = mock_searcher

            conclude_session(
                summary="Test summary",
                changed_files=["test.py"],
                repository="TestRepo"
            )

            mock_searcher.build_index.assert_called_once()
