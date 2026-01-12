"""
Tests for Initiative Management functionality.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.storage import get_or_create_collection
from src.tools.services import reset_services, set_collection


class TestCreateInitiative:
    """Tests for create_initiative tool."""

    def test_create_initiative_basic(self, temp_chroma_client):
        """Test creating a basic initiative."""
        from src.tools.initiatives import create_initiative

        reset_services()
        collection = get_or_create_collection(temp_chroma_client, "test_create_init")
        set_collection(collection)

        result = json.loads(create_initiative(
            repository="TestRepo",
            name="Auth Migration",
        ))

        assert result["status"] == "created"
        assert result["name"] == "Auth Migration"
        assert result["repository"] == "TestRepo"
        assert result["initiative_id"].startswith("initiative:")
        assert result["focused"] is True

    def test_create_initiative_with_goal(self, temp_chroma_client):
        """Test creating an initiative with a goal."""
        from src.tools.initiatives import create_initiative

        reset_services()
        collection = get_or_create_collection(temp_chroma_client, "test_create_goal")
        set_collection(collection)

        result = json.loads(create_initiative(
            repository="TestRepo",
            name="Performance Optimization",
            goal="Reduce page load time by 50%",
        ))

        assert result["status"] == "created"
        assert result["goal"] == "Reduce page load time by 50%"

    def test_create_initiative_without_auto_focus(self, temp_chroma_client):
        """Test creating an initiative without auto-focus."""
        from src.tools.initiatives import create_initiative

        reset_services()
        collection = get_or_create_collection(temp_chroma_client, "test_no_focus")
        set_collection(collection)

        result = json.loads(create_initiative(
            repository="TestRepo",
            name="Background Task",
            auto_focus=False,
        ))

        assert result["status"] == "created"
        assert "focused" not in result

    def test_create_initiative_validation(self):
        """Test validation errors."""
        from src.tools.initiatives import create_initiative

        result = json.loads(create_initiative(repository="", name="Test"))
        assert "error" in result

        result = json.loads(create_initiative(repository="Repo", name=""))
        assert "error" in result


class TestListInitiatives:
    """Tests for list_initiatives tool."""

    def test_list_initiatives_empty(self, temp_chroma_client):
        """Test listing when no initiatives exist."""
        from src.tools.initiatives import list_initiatives

        reset_services()
        collection = get_or_create_collection(temp_chroma_client, "test_list_empty")
        set_collection(collection)

        result = json.loads(list_initiatives(repository="TestRepo"))

        assert result["repository"] == "TestRepo"
        assert result["total"] == 0
        assert result["initiatives"] == []

    def test_list_initiatives_with_filter(self, temp_chroma_client):
        """Test listing with status filter."""
        from src.tools.initiatives import create_initiative, complete_initiative, list_initiatives

        reset_services()
        collection = get_or_create_collection(temp_chroma_client, "test_list_filter")
        set_collection(collection)

        # Create initiatives
        create_initiative(repository="TestRepo", name="Active One")
        create_initiative(repository="TestRepo", name="Active Two")
        create_initiative(repository="TestRepo", name="To Complete")
        complete_initiative(initiative="To Complete", summary="Done", repository="TestRepo")

        # List all
        result = json.loads(list_initiatives(repository="TestRepo", status="all"))
        assert result["total"] == 3

        # List active only
        result = json.loads(list_initiatives(repository="TestRepo", status="active"))
        assert result["total"] == 2

        # List completed only
        result = json.loads(list_initiatives(repository="TestRepo", status="completed"))
        assert result["total"] == 1


class TestFocusInitiative:
    """Tests for focus_initiative tool."""

    def test_focus_initiative_by_name(self, temp_chroma_client):
        """Test focusing an initiative by name."""
        from src.tools.initiatives import create_initiative, focus_initiative

        reset_services()
        collection = get_or_create_collection(temp_chroma_client, "test_focus_name")
        set_collection(collection)

        # Create two initiatives
        create_initiative(repository="TestRepo", name="First", auto_focus=True)
        create_initiative(repository="TestRepo", name="Second", auto_focus=False)

        # Focus the second one
        result = json.loads(focus_initiative(repository="TestRepo", initiative="Second"))

        assert result["status"] == "focused"
        assert result["name"] == "Second"

    def test_focus_initiative_by_id(self, temp_chroma_client):
        """Test focusing an initiative by ID."""
        from src.tools.initiatives import create_initiative, focus_initiative

        reset_services()
        collection = get_or_create_collection(temp_chroma_client, "test_focus_id")
        set_collection(collection)

        result = json.loads(create_initiative(repository="TestRepo", name="Test"))
        init_id = result["initiative_id"]

        focus_result = json.loads(focus_initiative(repository="TestRepo", initiative=init_id))

        assert focus_result["status"] == "focused"
        assert focus_result["initiative_id"] == init_id

    def test_focus_completed_initiative_fails(self, temp_chroma_client):
        """Test that focusing a completed initiative fails."""
        from src.tools.initiatives import create_initiative, complete_initiative, focus_initiative

        reset_services()
        collection = get_or_create_collection(temp_chroma_client, "test_focus_completed")
        set_collection(collection)

        create_initiative(repository="TestRepo", name="Done Task")
        complete_initiative(initiative="Done Task", summary="Finished", repository="TestRepo")

        result = json.loads(focus_initiative(repository="TestRepo", initiative="Done Task"))
        assert "error" in result


class TestCompleteInitiative:
    """Tests for complete_initiative tool."""

    def test_complete_initiative_basic(self, temp_chroma_client):
        """Test completing an initiative."""
        from src.tools.initiatives import create_initiative, complete_initiative

        reset_services()
        collection = get_or_create_collection(temp_chroma_client, "test_complete_basic")
        set_collection(collection)

        create_initiative(repository="TestRepo", name="Feature X")

        result = json.loads(complete_initiative(
            initiative="Feature X",
            summary="Implemented all requirements",
            repository="TestRepo",
        ))

        assert result["status"] == "completed"
        assert result["summary"] == "Implemented all requirements"
        assert "archive" in result

    def test_complete_initiative_clears_focus(self, temp_chroma_client):
        """Test that completing a focused initiative clears focus."""
        from src.tools.initiatives import create_initiative, complete_initiative, list_initiatives

        reset_services()
        collection = get_or_create_collection(temp_chroma_client, "test_complete_focus")
        set_collection(collection)

        create_initiative(repository="TestRepo", name="Focused Task", auto_focus=True)
        complete_initiative(initiative="Focused Task", summary="Done", repository="TestRepo")

        result = json.loads(list_initiatives(repository="TestRepo"))
        assert result["focused"] is None

    def test_complete_initiative_validation(self):
        """Test validation errors."""
        from src.tools.initiatives import complete_initiative

        result = json.loads(complete_initiative(initiative="", summary="Done"))
        assert "error" in result

        result = json.loads(complete_initiative(initiative="Test", summary=""))
        assert "error" in result


class TestCompletionSignals:
    """Tests for completion signal detection."""

    def test_detect_completion_keywords(self):
        """Test detection of completion keywords."""
        from src.tools.initiatives import detect_completion_signals

        assert detect_completion_signals("This feature is complete") is True
        assert detect_completion_signals("Task done") is True
        assert detect_completion_signals("Work finished") is True
        assert detect_completion_signals("Shipped the feature") is True
        assert detect_completion_signals("PR merged") is True

        assert detect_completion_signals("Work in progress") is False
        assert detect_completion_signals("Starting implementation") is False

    def test_completion_signal_word_boundary(self):
        """Test that signals match word boundaries."""
        from src.tools.initiatives import detect_completion_signals

        assert detect_completion_signals("complete") is True
        assert detect_completion_signals("completed") is True
        # Should not match partial words
        assert detect_completion_signals("completion") is False
        assert detect_completion_signals("incompleteness") is False


class TestStalenessDetection:
    """Tests for initiative staleness detection."""

    def test_check_staleness_recent(self):
        """Test that recent initiatives are not stale."""
        from src.tools.initiatives import check_initiative_staleness

        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=2)

        is_stale, days = check_initiative_staleness(recent.isoformat())

        assert is_stale is False
        assert days == 2

    def test_check_staleness_old(self):
        """Test that old initiatives are stale."""
        from src.tools.initiatives import check_initiative_staleness

        now = datetime.now(timezone.utc)
        old = now - timedelta(days=10)

        is_stale, days = check_initiative_staleness(old.isoformat())

        assert is_stale is True
        assert days == 10

    def test_check_staleness_custom_threshold(self):
        """Test custom staleness threshold."""
        from src.tools.initiatives import check_initiative_staleness

        now = datetime.now(timezone.utc)
        week_old = now - timedelta(days=7)

        # Default threshold (5 days) - should be stale
        is_stale, _ = check_initiative_staleness(week_old.isoformat())
        assert is_stale is True

        # Higher threshold (10 days) - should not be stale
        is_stale, _ = check_initiative_staleness(week_old.isoformat(), threshold_days=10)
        assert is_stale is False


class TestInitiativeTagging:
    """Tests for tagging commits/notes with initiatives."""

    def test_commit_tagged_with_focused_initiative(self, temp_chroma_client):
        """Test that commits are tagged with focused initiative."""
        from src.tools.initiatives import create_initiative
        from src.tools.notes import commit_to_cortex

        reset_services()
        collection = get_or_create_collection(temp_chroma_client, "test_commit_tag")
        set_collection(collection)

        with patch("src.git.get_current_branch", return_value="main"):
            with patch("src.tools.services.get_repo_path", return_value=None):

                # Create and focus initiative
                create_result = json.loads(create_initiative(
                    repository="TestRepo",
                    name="Test Initiative",
                ))
                init_id = create_result["initiative_id"]

                # Create a commit
                result = json.loads(commit_to_cortex(
                    summary="Test commit",
                    changed_files=[],
                    repository="TestRepo",
                ))

                assert result["status"] == "success"
                assert result["initiative"]["id"] == init_id
                assert result["initiative"]["name"] == "Test Initiative"

    def test_note_tagged_with_focused_initiative(self, temp_chroma_client):
        """Test that notes are tagged with focused initiative."""
        from src.tools.initiatives import create_initiative
        from src.tools.notes import save_note_to_cortex

        reset_services()
        collection = get_or_create_collection(temp_chroma_client, "test_note_tag")
        set_collection(collection)

        with patch("src.git.get_current_branch", return_value="main"):
            with patch("src.tools.services.get_repo_path", return_value=None):

                # Create and focus initiative
                create_result = json.loads(create_initiative(
                    repository="TestRepo",
                    name="Note Initiative",
                ))
                init_id = create_result["initiative_id"]

                # Save a note
                result = json.loads(save_note_to_cortex(
                    content="Test note content",
                    repository="TestRepo",
                ))

                assert result["status"] == "saved"
                assert result["initiative"]["id"] == init_id

    def test_commit_completion_signal_detected(self, temp_chroma_client):
        """Test that completion signals are detected in commits."""
        from src.tools.initiatives import create_initiative
        from src.tools.notes import commit_to_cortex

        reset_services()
        collection = get_or_create_collection(temp_chroma_client, "test_commit_signal")
        set_collection(collection)

        with patch("src.git.get_current_branch", return_value="main"):
            with patch("src.tools.services.get_repo_path", return_value=None):

                create_initiative(repository="TestRepo", name="Feature")

                result = json.loads(commit_to_cortex(
                    summary="Feature implementation complete. All tests passing.",
                    changed_files=[],
                    repository="TestRepo",
                ))

                assert result["initiative"]["completion_signal_detected"] is True
                assert result["initiative"]["prompt"] == "mark_complete"


class TestOrientWithInitiatives:
    """Tests for orient_session with initiative support."""

    def test_orient_returns_focused_initiative(self, temp_chroma_client, temp_git_repo):
        """Test that orient returns focused initiative info."""
        from src.tools.initiatives import create_initiative
        from src.tools.orient import orient_session

        reset_services()
        collection = get_or_create_collection(temp_chroma_client, "test_orient_focus")
        set_collection(collection)

        # Create and focus an initiative
        create_initiative(repository=temp_git_repo.name, name="Current Work")

        result = json.loads(orient_session(str(temp_git_repo)))

        assert "focused_initiative" in result
        assert result["focused_initiative"]["name"] == "Current Work"

    def test_orient_detects_stale_initiative(self, temp_chroma_client, temp_git_repo):
        """Test that orient detects stale initiatives."""
        from src.tools.initiatives import create_initiative
        from src.tools.orient import orient_session
        from src.tools.services import get_collection

        reset_services()
        collection = get_or_create_collection(temp_chroma_client, "test_orient_stale")
        set_collection(collection)

        # Create initiative
        create_result = json.loads(create_initiative(
            repository=temp_git_repo.name,
            name="Old Work",
        ))

        # Manually set old timestamp to simulate staleness
        coll = get_collection()
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()

        init_id = create_result["initiative_id"]
        init_result = coll.get(ids=[init_id], include=["documents", "metadatas"])
        meta = init_result["metadatas"][0]
        meta["updated_at"] = old_date
        coll.upsert(
            ids=[init_id],
            documents=[init_result["documents"][0]],
            metadatas=[meta],
        )

        result = json.loads(orient_session(str(temp_git_repo)))

        assert result["focused_initiative"]["stale"] is True
        assert result["focused_initiative"]["days_inactive"] >= 10


class TestInitiativeBoost:
    """Tests for initiative boost logic."""

    def test_apply_initiative_boost_multiplies_score(self):
        """Test that boost multiplies score by factor."""
        from src.tools.search import _apply_initiative_boost

        results = [
            {"text": "doc1", "rerank_score": 0.8, "meta": {"initiative_id": "initiative:abc123"}},
            {"text": "doc2", "rerank_score": 0.7, "meta": {"initiative_id": "initiative:other"}},
            {"text": "doc3", "rerank_score": 0.6, "meta": {}},
        ]

        boosted = _apply_initiative_boost(results, "initiative:abc123", boost_factor=1.3)

        # First result should have boosted score
        assert boosted[0]["boosted_score"] == pytest.approx(0.8 * 1.3, rel=1e-3)
        assert boosted[0]["initiative_boost"] == 1.3

        # Other results should not have initiative_boost
        assert "initiative_boost" not in boosted[1]
        assert "initiative_boost" not in boosted[2]

    def test_apply_initiative_boost_reorders_results(self):
        """Test that boost can reorder results."""
        from src.tools.search import _apply_initiative_boost

        # Lower scored result from focused initiative
        results = [
            {"text": "doc1", "rerank_score": 0.9, "meta": {"initiative_id": "initiative:other"}},
            {"text": "doc2", "rerank_score": 0.75, "meta": {"initiative_id": "initiative:focused"}},
        ]

        boosted = _apply_initiative_boost(results, "initiative:focused", boost_factor=1.3)

        # Boosted result (0.75 * 1.3 = 0.975) should now be first
        assert boosted[0]["meta"]["initiative_id"] == "initiative:focused"
        assert boosted[0]["boosted_score"] == pytest.approx(0.975, rel=1e-3)

    def test_apply_initiative_boost_uses_existing_boosted_score(self):
        """Test that boost applies to existing boosted_score if present."""
        from src.tools.search import _apply_initiative_boost

        results = [
            {"text": "doc1", "rerank_score": 0.8, "boosted_score": 0.85, "meta": {"initiative_id": "initiative:abc"}},
        ]

        boosted = _apply_initiative_boost(results, "initiative:abc", boost_factor=1.3)

        # Should multiply the existing boosted_score, not rerank_score
        assert boosted[0]["boosted_score"] == pytest.approx(0.85 * 1.3, rel=1e-3)


class TestSearchWithInitiatives:
    """Tests for search with initiative filtering and boosting."""

    def test_search_filters_by_initiative(self, temp_chroma_client):
        """Test that search can filter by initiative."""
        from src.tools.initiatives import create_initiative
        from src.tools.notes import save_note_to_cortex
        from src.tools.search import search_cortex

        reset_services()
        collection = get_or_create_collection(temp_chroma_client, "test_search_init")
        set_collection(collection)

        with patch("src.git.get_current_branch", return_value="main"):
            with patch("src.tools.services.get_repo_path", return_value=None):

                # Create two initiatives with notes
                create_initiative(repository="TestRepo", name="Initiative A")
                save_note_to_cortex(
                    content="Note for initiative A about authentication",
                    repository="TestRepo",
                )

                create_initiative(repository="TestRepo", name="Initiative B")
                save_note_to_cortex(
                    content="Note for initiative B about authentication",
                    repository="TestRepo",
                )

                # Search with initiative filter
                result = json.loads(search_cortex(
                    query="authentication",
                    repository="TestRepo",
                    initiative="Initiative A",
                ))

                # Should only find note from Initiative A
                for r in result["results"]:
                    if r.get("initiative_name"):
                        assert r["initiative_name"] == "Initiative A"
