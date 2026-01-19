"""
Tests for recall tools (recall_recent_work, summarize_initiative).
"""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.tools.recall import recall_recent_work
from src.tools.initiatives import summarize_initiative


@pytest.fixture
def temp_db_dir():
    """Create temporary database directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_collection(temp_db_dir):
    """Set up ChromaDB with test data."""
    import chromadb
    client = chromadb.PersistentClient(path=temp_db_dir)
    collection = client.get_or_create_collection("cortex_memory")

    # Patch get_collection in all modules that use it
    with patch("src.tools.recall.get_collection", return_value=collection), \
         patch("src.tools.initiatives.get_collection", return_value=collection):
        yield collection


class TestRecallRecentWork:
    """Tests for recall_recent_work tool."""

    def test_recall_empty_repository(self, mock_collection):
        """Test recall with no data returns empty timeline."""
        result = json.loads(recall_recent_work("TestRepo"))

        assert result["repository"] == "TestRepo"
        assert result["total_items"] == 0
        assert result["timeline"] == []

    def test_recall_requires_repository(self, mock_collection):
        """Test recall requires repository parameter."""
        result = json.loads(recall_recent_work(""))

        assert "error" in result
        assert "required" in result["error"].lower()

    def test_recall_returns_recent_session_summaries(self, mock_collection):
        """Test recall returns session summaries from the last N days."""
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)

        # Add a recent session summary
        mock_collection.add(
            ids=["session_summary:abc123"],
            documents=["Session summary: Added new feature"],
            metadatas=[{
                "type": "session_summary",
                "repository": "TestRepo",
                "created_at": yesterday.isoformat(),
                "files": '["src/feature.py"]',
            }],
        )

        result = json.loads(recall_recent_work("TestRepo", days=7))

        assert result["total_items"] == 1
        assert len(result["timeline"]) == 1
        assert result["timeline"][0]["count"] == 1

    def test_recall_excludes_old_items(self, mock_collection):
        """Test recall excludes items older than the specified days."""
        now = datetime.now(timezone.utc)
        old_date = now - timedelta(days=30)

        # Add an old session summary
        mock_collection.add(
            ids=["session_summary:old123"],
            documents=["Old session summary"],
            metadatas=[{
                "type": "session_summary",
                "repository": "TestRepo",
                "created_at": old_date.isoformat(),
            }],
        )

        result = json.loads(recall_recent_work("TestRepo", days=7))

        assert result["total_items"] == 0

    def test_recall_groups_by_day(self, mock_collection):
        """Test recall groups items by day."""
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        two_days_ago = now - timedelta(days=2)

        # Add items on different days
        mock_collection.add(
            ids=["session_summary:day1", "session_summary:day2", "note:day1"],
            documents=["Session 1", "Session 2", "Note 1"],
            metadatas=[
                {"type": "session_summary", "repository": "TestRepo", "created_at": yesterday.isoformat()},
                {"type": "session_summary", "repository": "TestRepo", "created_at": two_days_ago.isoformat()},
                {"type": "note", "repository": "TestRepo", "created_at": yesterday.isoformat()},
            ],
        )

        result = json.loads(recall_recent_work("TestRepo", days=7))

        assert result["total_items"] == 3
        assert len(result["timeline"]) == 2  # Two different days

    def test_recall_includes_initiative_context(self, mock_collection):
        """Test recall includes initiative information."""
        now = datetime.now(timezone.utc)

        mock_collection.add(
            ids=["session_summary:init1"],
            documents=["Working on auth"],
            metadatas=[{
                "type": "session_summary",
                "repository": "TestRepo",
                "created_at": now.isoformat(),
                "initiative_id": "initiative:abc",
                "initiative_name": "Auth Migration",
            }],
        )

        result = json.loads(recall_recent_work("TestRepo", days=7))

        assert result["total_items"] == 1
        assert "initiatives_active" in result
        assert result["initiatives_active"][0]["name"] == "Auth Migration"

    def test_recall_respects_limit(self, mock_collection):
        """Test recall respects the limit parameter."""
        now = datetime.now(timezone.utc)

        # Add many items
        for i in range(10):
            mock_collection.add(
                ids=[f"session_summary:item{i}"],
                documents=[f"Session {i}"],
                metadatas=[{
                    "type": "session_summary",
                    "repository": "TestRepo",
                    "created_at": (now - timedelta(hours=i)).isoformat(),
                }],
            )

        result = json.loads(recall_recent_work("TestRepo", days=7, limit=5))

        assert result["total_items"] == 5


class TestSummarizeInitiative:
    """Tests for summarize_initiative tool."""

    def test_summarize_requires_initiative(self, mock_collection):
        """Test summarize requires initiative parameter."""
        result = json.loads(summarize_initiative(""))

        assert "error" in result
        assert "required" in result["error"].lower()

    def test_summarize_not_found(self, mock_collection):
        """Test summarize returns error for non-existent initiative."""
        result = json.loads(summarize_initiative("NonExistent", repository="TestRepo"))

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_summarize_basic(self, mock_collection):
        """Test basic initiative summarization."""
        now = datetime.now(timezone.utc)

        # Create initiative
        mock_collection.add(
            ids=["initiative:abc123"],
            documents=["Auth Migration\n\nGoal: Migrate to JWT auth"],
            metadatas=[{
                "type": "initiative",
                "repository": "TestRepo",
                "name": "Auth Migration",
                "goal": "Migrate to JWT auth",
                "status": "active",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }],
        )

        result = json.loads(summarize_initiative("Auth Migration", repository="TestRepo"))

        assert result["initiative"]["name"] == "Auth Migration"
        assert result["initiative"]["goal"] == "Migrate to JWT auth"
        assert result["initiative"]["status"] == "active"

    def test_summarize_includes_session_summaries_and_notes(self, mock_collection):
        """Test summarize includes session summaries and notes."""
        now = datetime.now(timezone.utc)

        # Create initiative
        mock_collection.add(
            ids=["initiative:abc123"],
            documents=["Auth Migration"],
            metadatas=[{
                "type": "initiative",
                "repository": "TestRepo",
                "name": "Auth Migration",
                "status": "active",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }],
        )

        # Add session summaries and notes tagged with initiative
        mock_collection.add(
            ids=["session_summary:c1", "session_summary:c2", "note:n1"],
            documents=["Session 1", "Session 2", "Note about auth"],
            metadatas=[
                {"type": "session_summary", "initiative_id": "initiative:abc123", "created_at": now.isoformat()},
                {"type": "session_summary", "initiative_id": "initiative:abc123", "created_at": now.isoformat()},
                {"type": "note", "initiative_id": "initiative:abc123", "created_at": now.isoformat()},
            ],
        )

        result = json.loads(summarize_initiative("initiative:abc123"))

        assert result["stats"]["session_summaries"] == 2
        assert result["stats"]["notes"] == 1
        assert len(result["timeline"]) == 3

    def test_summarize_by_id(self, mock_collection):
        """Test summarize can find initiative by ID."""
        now = datetime.now(timezone.utc)

        mock_collection.add(
            ids=["initiative:xyz789"],
            documents=["Performance Work"],
            metadatas=[{
                "type": "initiative",
                "repository": "TestRepo",
                "name": "Performance",
                "status": "active",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }],
        )

        result = json.loads(summarize_initiative("initiative:xyz789"))

        assert result["initiative"]["id"] == "initiative:xyz789"
        assert result["initiative"]["name"] == "Performance"

    def test_summarize_completed_initiative(self, mock_collection):
        """Test summarize includes completion info for completed initiatives."""
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)

        mock_collection.add(
            ids=["initiative:done123"],
            documents=["Finished Work"],
            metadatas=[{
                "type": "initiative",
                "repository": "TestRepo",
                "name": "Finished Work",
                "status": "completed",
                "created_at": yesterday.isoformat(),
                "updated_at": now.isoformat(),
                "completed_at": now.isoformat(),
                "completion_summary": "Successfully completed the migration",
            }],
        )

        result = json.loads(summarize_initiative("Finished Work", repository="TestRepo"))

        assert result["initiative"]["status"] == "completed"
        assert result["initiative"]["completion_summary"] == "Successfully completed the migration"

    def test_summarize_generates_narrative(self, mock_collection):
        """Test summarize generates a narrative summary."""
        now = datetime.now(timezone.utc)

        mock_collection.add(
            ids=["initiative:narr123"],
            documents=["Feature X\n\nGoal: Build feature X"],
            metadatas=[{
                "type": "initiative",
                "repository": "TestRepo",
                "name": "Feature X",
                "goal": "Build feature X",
                "status": "active",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }],
        )

        result = json.loads(summarize_initiative("Feature X", repository="TestRepo"))

        assert "narrative" in result
        assert "Feature X" in result["narrative"]
        assert "Build feature X" in result["narrative"]
