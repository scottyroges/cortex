"""
Tests for insight_to_cortex tool.
"""

import json
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.tools.memory.memory import insight_to_cortex


@pytest.fixture
def temp_db_dir():
    """Create temporary database directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_services(temp_db_dir):
    """Set up mocked services for insight_to_cortex."""
    import chromadb
    client = chromadb.PersistentClient(path=temp_db_dir)
    collection = client.get_or_create_collection("cortex_memory")

    mock_searcher = MagicMock()
    mock_searcher.build_index = MagicMock()

    with patch("src.tools.memory.memory.get_collection", return_value=collection), \
         patch("src.tools.memory.memory.get_repo_path", return_value=None), \
         patch("src.tools.memory.memory.get_searcher", return_value=mock_searcher), \
         patch("src.tools.memory.memory.get_current_branch", return_value="main"), \
         patch("src.tools.initiatives.initiatives.get_collection", return_value=collection):
        yield collection


class TestInsightToCortex:
    """Tests for insight_to_cortex tool."""

    def test_basic_insight_creation(self, mock_services):
        """Test creating insight linked to files."""
        result = json.loads(insight_to_cortex(
            insight="This module uses observer pattern for event handling",
            files=["src/events.py", "src/handlers.py"],
            repository="TestRepo"
        ))

        assert result["status"] == "saved"
        assert result["type"] == "insight"
        assert len(result["files"]) == 2
        assert "src/events.py" in result["files"]
        assert "insight_id" in result
        assert result["insight_id"].startswith("insight:")

    def test_insight_requires_files(self, mock_services):
        """Test that empty files list is rejected."""
        result = json.loads(insight_to_cortex(
            insight="Some insight without files",
            files=[],
            repository="TestRepo"
        ))

        assert result["status"] == "error"
        assert "files" in result["error"].lower()

    def test_insight_auto_tags_focused_initiative(self, mock_services):
        """Test insight inherits focused initiative."""
        collection = mock_services

        # Create and focus an initiative
        now = datetime.now(timezone.utc).isoformat()
        collection.add(
            ids=["initiative:feat123"],
            documents=["Feature X\n\nGoal: Build feature X"],
            metadatas=[{
                "type": "initiative",
                "repository": "TestRepo",
                "name": "Feature X",
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }],
        )
        # Set focus
        collection.upsert(
            ids=["TestRepo:focus"],
            documents=["Current focus: Feature X"],
            metadatas=[{
                "type": "focus",
                "repository": "TestRepo",
                "initiative_id": "initiative:feat123",
                "initiative_name": "Feature X",
            }],
        )

        result = json.loads(insight_to_cortex(
            insight="Key pattern discovered in the codebase",
            files=["src/feature.py"],
            repository="TestRepo"
        ))

        assert result["status"] == "saved"
        assert result["initiative_name"] == "Feature X"
        assert result["initiative"]["id"] == "initiative:feat123"

    def test_insight_explicit_initiative(self, mock_services):
        """Test insight with explicit initiative override."""
        collection = mock_services
        now = datetime.now(timezone.utc).isoformat()

        # Create two initiatives
        collection.add(
            ids=["initiative:featA", "initiative:featB"],
            documents=["Feature A", "Feature B"],
            metadatas=[
                {"type": "initiative", "repository": "TestRepo", "name": "Feature A", "status": "active", "created_at": now, "updated_at": now},
                {"type": "initiative", "repository": "TestRepo", "name": "Feature B", "status": "active", "created_at": now, "updated_at": now},
            ],
        )
        # Focus on B
        collection.upsert(
            ids=["TestRepo:focus"],
            documents=["Current focus: Feature B"],
            metadatas=[{
                "type": "focus",
                "repository": "TestRepo",
                "initiative_id": "initiative:featB",
                "initiative_name": "Feature B",
            }],
        )

        # But explicitly tag with A
        result = json.loads(insight_to_cortex(
            insight="Analysis result for Feature A",
            files=["src/code.py"],
            repository="TestRepo",
            initiative="Feature A"
        ))

        assert result["status"] == "saved"
        assert result["initiative_name"] == "Feature A"

    def test_insight_with_title_and_tags(self, mock_services):
        """Test insight with optional title and tags."""
        result = json.loads(insight_to_cortex(
            insight="Complex analysis of authentication flow",
            files=["src/auth.py"],
            repository="TestRepo",
            title="Auth Pattern Discovery",
            tags=["auth", "security", "pattern"]
        ))

        assert result["status"] == "saved"
        assert result["title"] == "Auth Pattern Discovery"
        assert "auth" in result["tags"]
        assert "security" in result["tags"]
        assert len(result["tags"]) == 3

    def test_insight_stored_in_collection(self, mock_services):
        """Test that insight is actually stored in ChromaDB."""
        collection = mock_services

        insight_to_cortex(
            insight="Uses two-phase commit pattern for transactions",
            files=["src/transactions.py", "src/db.py"],
            repository="TestRepo",
            title="Transaction Pattern"
        )

        # Query the collection directly
        results = collection.get(
            where={"type": "insight"},
            include=["documents", "metadatas"],
        )

        assert len(results["ids"]) == 1
        assert "two-phase commit" in results["documents"][0]
        assert "Transaction Pattern" in results["documents"][0]

        meta = results["metadatas"][0]
        assert meta["type"] == "insight"
        assert meta["repository"] == "TestRepo"
        assert "src/transactions.py" in meta["files"]

    def test_insight_file_paths_preserved(self, mock_services):
        """Test that file paths are stored exactly as provided."""
        result = json.loads(insight_to_cortex(
            insight="Pattern found in relative paths",
            files=["./src/relative.py", "../other/file.py", "/absolute/path.py"],
            repository="TestRepo"
        ))

        assert result["status"] == "saved"
        assert result["files"] == ["./src/relative.py", "../other/file.py", "/absolute/path.py"]

    def test_insight_secrets_scrubbed(self, mock_services):
        """Test that secrets are scrubbed from insight content."""
        collection = mock_services

        insight_to_cortex(
            insight="API key is AKIAIOSFODNN7EXAMPLE for testing AWS access",
            files=["src/config.py"],
            repository="TestRepo"
        )

        # Check stored document
        results = collection.get(
            where={"type": "insight"},
            include=["documents"],
        )

        # The AWS key pattern should be scrubbed
        assert "AKIAIOSFODNN7EXAMPLE" not in results["documents"][0]

    def test_insight_linked_files_in_document(self, mock_services):
        """Test that linked files appear in the document text."""
        collection = mock_services

        insight_to_cortex(
            insight="Core pipeline implementation",
            files=["src/pipeline/input.py", "src/pipeline/output.py"],
            repository="TestRepo"
        )

        results = collection.get(
            where={"type": "insight"},
            include=["documents"],
        )

        doc = results["documents"][0]
        assert "Linked files:" in doc
        assert "src/pipeline/input.py" in doc
        assert "src/pipeline/output.py" in doc

    def test_insight_updates_initiative_timestamp(self, mock_services):
        """Test that saving insight updates initiative's updated_at."""
        collection = mock_services
        old_time = "2026-01-01T00:00:00+00:00"

        # Create initiative with old timestamp
        collection.add(
            ids=["initiative:upd123"],
            documents=["Update Test"],
            metadatas=[{
                "type": "initiative",
                "repository": "TestRepo",
                "name": "Update Test",
                "status": "active",
                "created_at": old_time,
                "updated_at": old_time,
            }],
        )
        # Focus on it
        collection.upsert(
            ids=["TestRepo:focus"],
            documents=["Current focus: Update Test"],
            metadatas=[{
                "type": "focus",
                "repository": "TestRepo",
                "initiative_id": "initiative:upd123",
                "initiative_name": "Update Test",
            }],
        )

        # Save insight
        insight_to_cortex(
            insight="New analysis",
            files=["src/new.py"],
            repository="TestRepo"
        )

        # Check initiative timestamp was updated
        results = collection.get(
            ids=["initiative:upd123"],
            include=["metadatas"],
        )

        updated_at = results["metadatas"][0]["updated_at"]
        assert updated_at != old_time  # Should be updated to current time

    def test_insight_without_repository_defaults_to_global(self, mock_services):
        """Test insight without repository defaults to 'global'."""
        collection = mock_services

        insight_to_cortex(
            insight="Global insight",
            files=["some/file.py"],
        )

        results = collection.get(
            where={"type": "insight"},
            include=["metadatas"],
        )

        assert results["metadatas"][0]["repository"] == "global"

    def test_insight_without_repository_uses_focused_initiative_repo(self, mock_services):
        """Test insight without repository uses focused initiative's repository."""
        collection = mock_services

        # Create a focus document for a repository
        collection.upsert(
            ids=["FocusedRepo:focus"],
            documents=["Current focus: Test Initiative"],
            metadatas=[{
                "type": "focus",
                "repository": "FocusedRepo",
                "initiative_id": "initiative:test123",
                "initiative_name": "Test Initiative",
            }],
        )

        insight_to_cortex(
            insight="Insight should use focused repo",
            files=["some/file.py"],
            # No repository specified
        )

        results = collection.get(
            where={"type": "insight"},
            include=["metadatas"],
        )

        # Should use repository from focused initiative, not "global"
        assert results["metadatas"][0]["repository"] == "FocusedRepo"
