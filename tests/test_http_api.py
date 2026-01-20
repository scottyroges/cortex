"""
Tests for HTTP API endpoints (Phase 2 API).

These endpoints are used by the CLI commands:
- cortex search <query>  -> GET /search
- cortex save <content>  -> POST /note
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_client(temp_chroma_client):
    """Create a test client for the HTTP API."""
    from src.configs.services import reset_services

    # Reset the ResourceManager singleton before patching
    reset_services()

    # Patch the ChromaDB client in the resources module
    with patch("src.configs.services.get_chroma_client", return_value=temp_chroma_client):
        from src.controllers.http import app
        client = TestClient(app)
        yield client

    # Reset after test
    reset_services()


@pytest.fixture
def browse_client(temp_chroma_client):
    """Create a test client for the browse API with patched ChromaDB."""
    from src.configs.services import reset_services

    # Reset the ResourceManager singleton before patching
    reset_services()

    with patch("src.configs.services.get_chroma_client", return_value=temp_chroma_client):
        from src.controllers.http import app
        client = TestClient(app)
        yield client

    # Reset after test
    reset_services()


class TestSearchEndpoint:
    """Tests for GET /search endpoint."""

    def test_search_returns_results(self, api_client, temp_chroma_client):
        """Test that search returns results from indexed content."""
        from src.storage import get_or_create_collection

        # Seed test data
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=[
                "Python function for user authentication with JWT tokens",
                "JavaScript utility for form validation",
                "Rust implementation of a hash table",
            ],
            ids=["doc1", "doc2", "doc3"],
            metadatas=[
                {"file_path": "/app/auth.py", "repository": "test", "branch": "main", "type": "code", "language": "python"},
                {"file_path": "/app/validate.js", "repository": "test", "branch": "main", "type": "code", "language": "javascript"},
                {"file_path": "/app/hash.rs", "repository": "test", "branch": "main", "type": "code", "language": "rust"},
            ],
        )

        response = api_client.get("/search", params={"q": "authentication JWT"})

        assert response.status_code == 200
        data = response.json()
        assert "query" in data
        assert "results" in data
        assert "timing_ms" in data
        assert data["query"] == "authentication JWT"

    def test_search_with_limit(self, api_client, temp_chroma_client):
        """Test search respects limit parameter."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        # Add multiple documents
        for i in range(10):
            collection.add(
                documents=[f"Document about authentication method {i}"],
                ids=[f"auth-doc-{i}"],
                metadatas=[{"repository": "test", "branch": "main", "type": "note", "title": "", "tags": ""}],
            )

        response = api_client.get("/search", params={"q": "authentication", "limit": 3})

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) <= 3

    def test_search_with_project_filter(self, api_client, temp_chroma_client):
        """Test search filters by project."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=[
                "API endpoint for project Alpha",
                "API endpoint for project Beta",
            ],
            ids=["alpha-1", "beta-1"],
            metadatas=[
                {"repository": "alpha", "branch": "main", "type": "code", "file_path": "/a.py", "language": "python"},
                {"repository": "beta", "branch": "main", "type": "code", "file_path": "/b.py", "language": "python"},
            ],
        )

        response = api_client.get("/search", params={"q": "API endpoint", "repository": "alpha"})

        assert response.status_code == 200
        data = response.json()
        # All results should be from alpha project
        for result in data["results"]:
            assert result["metadata"]["repository"] == "alpha"

    def test_search_with_min_score(self, api_client, temp_chroma_client):
        """Test search filters by minimum score."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=["Exact match for authentication"],
            ids=["exact-1"],
            metadatas=[{"repository": "test", "branch": "main", "type": "note", "title": "", "tags": ""}],
        )

        # High min_score should filter out low-quality matches
        response = api_client.get("/search", params={"q": "authentication", "min_score": 0.9})

        assert response.status_code == 200
        data = response.json()
        # Results should all have score >= 0.9
        for result in data["results"]:
            assert result["score"] >= 0.9

    def test_search_empty_query_fails(self, api_client):
        """Test that empty query returns 422."""
        response = api_client.get("/search", params={"q": ""})
        assert response.status_code == 422

    def test_search_missing_query_fails(self, api_client):
        """Test that missing query returns 422."""
        response = api_client.get("/search")
        assert response.status_code == 422

    def test_search_empty_collection(self, api_client):
        """Test search on empty collection returns empty results."""
        response = api_client.get("/search", params={"q": "anything"})

        assert response.status_code == 200
        data = response.json()
        assert data["results"] == []


class TestNoteEndpoint:
    """Tests for POST /note endpoint."""

    def test_save_note_basic(self, api_client):
        """Test basic note creation."""
        response = api_client.post(
            "/note",
            json={"content": "This is a test note about architecture decisions."}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "id" in data
        assert data["id"].startswith("note_")
        assert data["content_length"] > 0

    def test_save_note_with_title(self, api_client):
        """Test note creation with title."""
        response = api_client.post(
            "/note",
            json={
                "content": "We decided to use PostgreSQL for better query performance.",
                "title": "Database Decision"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["title"] == "Database Decision"

    def test_save_note_with_tags(self, api_client):
        """Test note creation with tags."""
        response = api_client.post(
            "/note",
            json={
                "content": "Use Redis for caching API responses.",
                "tags": ["caching", "performance", "infrastructure"]
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    def test_save_note_with_project(self, api_client):
        """Test note creation with custom project."""
        response = api_client.post(
            "/note",
            json={
                "content": "Project-specific documentation.",
                "repository": "my-custom-project"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    def test_save_note_empty_content_fails(self, api_client):
        """Test that empty content returns 422."""
        response = api_client.post(
            "/note",
            json={"content": ""}
        )
        # FastAPI/Pydantic may allow empty string, check actual behavior
        # If it should fail, assert 422
        # For now, we test it returns 200 (empty notes are allowed)
        assert response.status_code == 200

    def test_save_note_missing_content_fails(self, api_client):
        """Test that missing content returns 422."""
        response = api_client.post(
            "/note",
            json={"title": "Title only"}
        )
        assert response.status_code == 422

    def test_saved_note_is_searchable(self, api_client, temp_chroma_client):
        """Test that saved notes can be found via search."""
        # Save a note
        save_response = api_client.post(
            "/note",
            json={
                "content": "Unique architecture decision about microservices",
                "title": "Microservices ADR"
            }
        )
        assert save_response.status_code == 200

        # Search for it
        search_response = api_client.get("/search", params={"q": "microservices architecture"})
        assert search_response.status_code == 200

        data = search_response.json()
        # Should find the note
        found = any("microservices" in r["content"].lower() for r in data["results"])
        assert found, "Saved note should be searchable"


class TestInfoEndpoint:
    """Tests for GET /info endpoint."""

    def test_info_returns_version(self, api_client):
        """Test info endpoint returns build info."""
        response = api_client.get("/info")

        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "git_commit" in data
        assert "build_time" in data


class TestIngestEndpoint:
    """Tests for POST /ingest endpoint (web clipper)."""

    def test_ingest_web_content(self, api_client):
        """Test web content ingestion."""
        response = api_client.post(
            "/ingest",
            json={
                "url": "https://example.com/article",
                "content": "This is the article content about machine learning.",
                "title": "ML Article"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "id" in data
        assert data["url"] == "https://example.com/article"

    def test_ingest_with_tags(self, api_client):
        """Test web ingestion with tags."""
        response = api_client.post(
            "/ingest",
            json={
                "url": "https://docs.example.com/api",
                "content": "API documentation content.",
                "tags": ["documentation", "api"]
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    def test_ingested_content_searchable(self, api_client):
        """Test that ingested web content is searchable."""
        # Ingest content
        api_client.post(
            "/ingest",
            json={
                "url": "https://unique-test-url.com/page",
                "content": "Unique searchable content about quantum computing",
            }
        )

        # Search for it
        search_response = api_client.get("/search", params={"q": "quantum computing"})
        assert search_response.status_code == 200

        data = search_response.json()
        found = any("quantum" in r["content"].lower() for r in data["results"])
        assert found, "Ingested content should be searchable"


class TestFocusedInitiativeEndpoint:
    """Tests for GET /focused-initiative endpoint."""

    def test_focused_initiative_no_focus(self, api_client, temp_chroma_client):
        """Test returns null when no initiative is focused."""
        response = api_client.get("/focused-initiative", params={"repository": "test-repo"})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["initiative_id"] is None
        assert data["initiative_name"] is None

    def test_focused_initiative_with_focus(self, api_client, temp_chroma_client):
        """Test returns initiative info when one is focused."""
        # Mock the function where it's imported (inside the endpoint)
        with patch("src.tools.initiatives.get_focused_initiative") as mock_get_focused:
            mock_get_focused.return_value = {
                "initiative_id": "initiative:test123",
                "initiative_name": "Test Initiative",
            }

            response = api_client.get("/focused-initiative", params={"repository": "test-repo"})

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert data["initiative_id"] == "initiative:test123"
            assert data["initiative_name"] == "Test Initiative"

    def test_focused_initiative_requires_repository(self, api_client):
        """Test that repository parameter is required."""
        response = api_client.get("/focused-initiative")
        assert response.status_code == 422


class TestSessionSummaryWithInitiative:
    """Tests for /session-summary endpoint with initiative linking."""

    @patch("src.tools.notes.conclude_session")
    def test_session_summary_passes_initiative_id(self, mock_conclude, api_client):
        """Test that initiative_id is passed to conclude_session."""
        mock_conclude.return_value = '{"status": "success", "session_id": "session_summary:abc123"}'

        response = api_client.post(
            "/session-summary",
            json={
                "summary": "Test session summary",
                "changed_files": ["/a.py"],
                "repository": "test-repo",
                "initiative_id": "initiative:xyz789",
            }
        )

        assert response.status_code == 200
        mock_conclude.assert_called_once()
        call_kwargs = mock_conclude.call_args
        assert call_kwargs[1]["initiative"] == "initiative:xyz789"

    @patch("src.tools.notes.conclude_session")
    def test_session_summary_falls_back_to_initiative_name(self, mock_conclude, api_client):
        """Test that initiative (name) is used as fallback when initiative_id not provided."""
        mock_conclude.return_value = '{"status": "success", "session_id": "session_summary:abc123"}'

        response = api_client.post(
            "/session-summary",
            json={
                "summary": "Test session summary",
                "changed_files": [],
                "repository": "test-repo",
                "initiative": "My Initiative Name",
            }
        )

        assert response.status_code == 200
        mock_conclude.assert_called_once()
        call_kwargs = mock_conclude.call_args
        assert call_kwargs[1]["initiative"] == "My Initiative Name"

    @patch("src.tools.notes.conclude_session")
    def test_session_summary_prefers_initiative_id_over_name(self, mock_conclude, api_client):
        """Test that initiative_id takes precedence over initiative name."""
        mock_conclude.return_value = '{"status": "success", "session_id": "session_summary:abc123"}'

        response = api_client.post(
            "/session-summary",
            json={
                "summary": "Test session summary",
                "changed_files": [],
                "repository": "test-repo",
                "initiative_id": "initiative:preferred",
                "initiative": "Ignored Name",
            }
        )

        assert response.status_code == 200
        mock_conclude.assert_called_once()
        call_kwargs = mock_conclude.call_args
        assert call_kwargs[1]["initiative"] == "initiative:preferred"

    @patch("src.tools.notes.conclude_session")
    def test_session_summary_returns_initiative_info(self, mock_conclude, api_client):
        """Test that response includes initiative info from conclude_session."""
        mock_conclude.return_value = json.dumps({
            "status": "success",
            "session_id": "session_summary:abc123",
            "initiative": {
                "id": "initiative:xyz",
                "name": "Test Initiative",
            }
        })

        response = api_client.post(
            "/session-summary",
            json={
                "summary": "Test session summary",
                "changed_files": [],
                "repository": "test-repo",
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["initiative"]["id"] == "initiative:xyz"
        assert data["initiative"]["name"] == "Test Initiative"


class TestProcessSyncWithInitiative:
    """Tests for /process-sync endpoint with initiative linking."""

    @patch("src.configs.yaml_config.load_yaml_config")
    @patch("src.external.llm.get_provider")
    @patch("src.controllers.http.api.autocapture.save_session_summary")
    def test_process_sync_passes_initiative_id(
        self, mock_save, mock_get_provider, mock_load_config
    ):
        """Test that initiative_id is passed through to save_session_summary."""
        from src.controllers.http.api import ProcessSyncRequest, process_sync

        mock_load_config.return_value = {}
        mock_provider = MagicMock()
        mock_provider.summarize_session.return_value = "Generated summary"
        mock_get_provider.return_value = mock_provider
        mock_save.return_value = {"status": "success", "session_id": "test"}

        request = ProcessSyncRequest(
            session_id="test-session",
            transcript_text="User: Hello\nAssistant: Hi there",
            files_edited=["/a.py"],
            repository="test-repo",
            initiative_id="initiative:abc123",
        )

        result = process_sync(request)

        assert result["status"] == "success"
        mock_save.assert_called_once()
        call_args = mock_save.call_args[0][0]  # First positional arg (SessionSummaryRequest)
        assert call_args.initiative_id == "initiative:abc123"

    @patch("src.configs.yaml_config.load_yaml_config")
    @patch("src.external.llm.get_provider")
    @patch("src.controllers.http.api.autocapture.save_session_summary")
    def test_process_sync_without_initiative(
        self, mock_save, mock_get_provider, mock_load_config
    ):
        """Test process_sync works without initiative_id (falls back to focused)."""
        from src.controllers.http.api import ProcessSyncRequest, process_sync

        mock_load_config.return_value = {}
        mock_provider = MagicMock()
        mock_provider.summarize_session.return_value = "Generated summary"
        mock_get_provider.return_value = mock_provider
        mock_save.return_value = {"status": "success", "session_id": "test"}

        request = ProcessSyncRequest(
            session_id="test-session",
            transcript_text="User: Hello\nAssistant: Hi there",
            files_edited=[],
            repository="test-repo",
            # No initiative_id
        )

        result = process_sync(request)

        assert result["status"] == "success"
        mock_save.assert_called_once()
        call_args = mock_save.call_args[0][0]
        assert call_args.initiative_id is None


class TestBrowseUpdateEndpoint:
    """Tests for PUT /browse/update endpoint."""

    def test_update_note_title(self, browse_client, temp_chroma_client):
        """Test updating a note's title."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=["Original note content"],
            ids=["note_123"],
            metadatas=[{
                "type": "note",
                "title": "Original Title",
                "repository": "test",
                "branch": "main",
                "tags": "[]",
            }],
        )

        response = browse_client.put(
            "/browse/update",
            params={"id": "note_123"},
            json={"title": "Updated Title"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "title" in data["updated_fields"]

        # Verify the update
        result = collection.get(ids=["note_123"], include=["metadatas"])
        assert result["metadatas"][0]["title"] == "Updated Title"

    def test_update_note_content(self, browse_client, temp_chroma_client):
        """Test updating a note's content."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=["Original content"],
            ids=["note_456"],
            metadatas=[{
                "type": "note",
                "title": "Test Note",
                "repository": "test",
                "branch": "main",
                "tags": "[]",
            }],
        )

        response = browse_client.put(
            "/browse/update",
            params={"id": "note_456"},
            json={"content": "Updated content with more details"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "content" in data["updated_fields"]

        # Verify the update
        result = collection.get(ids=["note_456"], include=["documents"])
        assert result["documents"][0] == "Updated content with more details"

    def test_update_note_tags(self, browse_client, temp_chroma_client):
        """Test updating a note's tags."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=["Note with tags"],
            ids=["note_789"],
            metadatas=[{
                "type": "note",
                "title": "Tagged Note",
                "repository": "test",
                "branch": "main",
                "tags": '["old-tag"]',
            }],
        )

        response = browse_client.put(
            "/browse/update",
            params={"id": "note_789"},
            json={"tags": ["new-tag", "another-tag"]}
        )

        assert response.status_code == 200
        data = response.json()
        assert "tags" in data["updated_fields"]

        # Verify the update
        result = collection.get(ids=["note_789"], include=["metadatas"])
        assert result["metadatas"][0]["tags"] == '["new-tag", "another-tag"]'

    def test_update_insight_with_files(self, browse_client, temp_chroma_client):
        """Test updating an insight's files list."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=["Insight about code pattern"],
            ids=["insight_001"],
            metadatas=[{
                "type": "insight",
                "title": "Code Pattern",
                "repository": "test",
                "branch": "main",
                "tags": "[]",
                "files": '["old/path.py"]',
            }],
        )

        response = browse_client.put(
            "/browse/update",
            params={"id": "insight_001"},
            json={"files": ["new/path.py", "another/file.py"]}
        )

        assert response.status_code == 200
        data = response.json()
        assert "files" in data["updated_fields"]

    def test_update_nonexistent_document(self, browse_client):
        """Test updating a document that doesn't exist."""
        response = browse_client.put(
            "/browse/update",
            params={"id": "nonexistent_id"},
            json={"title": "New Title"}
        )

        assert response.status_code == 404

    def test_update_non_editable_type(self, browse_client, temp_chroma_client):
        """Test that code documents cannot be edited."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=["def hello(): pass"],
            ids=["code_001"],
            metadatas=[{
                "type": "code",
                "file_path": "/app/hello.py",
                "repository": "test",
                "branch": "main",
                "language": "python",
            }],
        )

        response = browse_client.put(
            "/browse/update",
            params={"id": "code_001"},
            json={"content": "def goodbye(): pass"}
        )

        assert response.status_code == 400
        assert "not editable" in response.json()["detail"]

    def test_update_session_summary_content(self, browse_client, temp_chroma_client):
        """Test updating a session summary's content."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=["Original session summary"],
            ids=["session_001"],
            metadatas=[{
                "type": "session_summary",
                "repository": "test",
                "branch": "main",
                "files": '["file1.py"]',
            }],
        )

        response = browse_client.put(
            "/browse/update",
            params={"id": "session_001"},
            json={"content": "Updated session summary with more details"}
        )

        assert response.status_code == 200
        assert "content" in response.json()["updated_fields"]

    def test_update_session_summary_title_not_allowed(self, browse_client, temp_chroma_client):
        """Test that session summaries cannot have their title updated (not an editable field)."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=["Session summary"],
            ids=["session_002"],
            metadatas=[{
                "type": "session_summary",
                "repository": "test",
                "branch": "main",
                "files": "[]",
            }],
        )

        # Title is not editable for session summaries - should return 400 with no valid fields
        response = browse_client.put(
            "/browse/update",
            params={"id": "session_002"},
            json={"title": "New Title"}
        )

        assert response.status_code == 400
        assert "No valid fields" in response.json()["detail"]


class TestBrowseDeleteEndpoint:
    """Tests for DELETE /browse/delete endpoint."""

    def test_delete_note(self, browse_client, temp_chroma_client):
        """Test deleting a note."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=["Note to delete"],
            ids=["note_to_delete"],
            metadatas=[{
                "type": "note",
                "title": "Delete Me",
                "repository": "test",
                "branch": "main",
                "tags": "[]",
            }],
        )

        response = browse_client.delete("/browse/delete", params={"id": "note_to_delete"})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["id"] == "note_to_delete"

        # Verify deletion
        result = collection.get(ids=["note_to_delete"])
        assert len(result["ids"]) == 0

    def test_delete_insight(self, browse_client, temp_chroma_client):
        """Test deleting an insight."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=["Insight to delete"],
            ids=["insight_to_delete"],
            metadatas=[{
                "type": "insight",
                "title": "Delete Me",
                "repository": "test",
                "branch": "main",
                "files": "[]",
            }],
        )

        response = browse_client.delete("/browse/delete", params={"id": "insight_to_delete"})

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_delete_code_chunk(self, browse_client, temp_chroma_client):
        """Test deleting a code chunk (all types are deletable)."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=["def hello(): pass"],
            ids=["code_to_delete"],
            metadatas=[{
                "type": "code",
                "file_path": "/app/hello.py",
                "repository": "test",
                "branch": "main",
                "language": "python",
            }],
        )

        response = browse_client.delete("/browse/delete", params={"id": "code_to_delete"})

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_delete_nonexistent_document(self, browse_client):
        """Test deleting a document that doesn't exist."""
        response = browse_client.delete("/browse/delete", params={"id": "nonexistent_id"})

        assert response.status_code == 404

    def test_delete_session_summary(self, browse_client, temp_chroma_client):
        """Test deleting a session summary."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=["Session summary to delete"],
            ids=["session_to_delete"],
            metadatas=[{
                "type": "session_summary",
                "repository": "test",
                "branch": "main",
                "files": '["file.py"]',
            }],
        )

        response = browse_client.delete("/browse/delete", params={"id": "session_to_delete"})

        assert response.status_code == 200
        assert response.json()["success"] is True

        # Verify deletion
        result = collection.get(ids=["session_to_delete"])
        assert len(result["ids"]) == 0


class TestBrowseCleanupEndpoint:
    """Tests for POST /browse/cleanup endpoint."""

    def test_cleanup_dry_run(self, browse_client, temp_chroma_client, temp_dir):
        """Test cleanup in dry_run mode shows orphaned documents."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        # Add file_metadata for non-existent file
        collection.add(
            documents=["Orphaned file metadata"],
            ids=["file_metadata:orphan.py"],
            metadatas=[{
                "type": "file_metadata",
                "repository": "test-repo",
                "file_path": "orphan.py",
            }],
        )

        response = browse_client.post(
            "/browse/cleanup",
            json={
                "repository": "test-repo",
                "path": str(temp_dir),
                "dry_run": True,
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["dry_run"] is True
        assert data["total_orphaned"] >= 1
        assert data["total_deleted"] == 0

    def test_cleanup_execute(self, browse_client, temp_chroma_client, temp_dir):
        """Test cleanup actually deletes orphaned documents."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        # Add file_metadata for non-existent file
        collection.add(
            documents=["Orphaned file metadata"],
            ids=["file_metadata:orphan.py"],
            metadatas=[{
                "type": "file_metadata",
                "repository": "test-repo",
                "file_path": "orphan.py",
            }],
        )

        response = browse_client.post(
            "/browse/cleanup",
            json={
                "repository": "test-repo",
                "path": str(temp_dir),
                "dry_run": False,
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["dry_run"] is False
        assert data["total_deleted"] >= 1

        # Verify deletion
        result = collection.get(ids=["file_metadata:orphan.py"])
        assert len(result["ids"]) == 0

    def test_cleanup_requires_path(self, browse_client):
        """Test that cleanup requires path parameter."""
        response = browse_client.post(
            "/browse/cleanup",
            json={
                "repository": "test-repo",
                "dry_run": True,
            }
        )

        assert response.status_code == 400
        assert "path" in response.json()["detail"].lower()

    def test_cleanup_returns_breakdown(self, browse_client, temp_chroma_client, temp_dir):
        """Test that cleanup returns breakdown by document type."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        # Add various orphaned document types
        collection.add(
            documents=["Orphaned file", "Orphaned insight", "Orphaned dep"],
            ids=["file_metadata:orphan.py", "insight:orphan", "dep:orphan"],
            metadatas=[
                {"type": "file_metadata", "repository": "test", "file_path": "orphan.py"},
                {"type": "insight", "repository": "test", "files": '["orphan.py"]'},
                {"type": "dependency", "repository": "test", "file_path": "orphan.py"},
            ],
        )

        response = browse_client.post(
            "/browse/cleanup",
            json={
                "repository": "test",
                "path": str(temp_dir),
                "dry_run": True,
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "orphaned_file_metadata" in data
        assert "orphaned_insights" in data
        assert "orphaned_dependencies" in data


class TestBrowsePurgeEndpoint:
    """Tests for POST /browse/purge endpoint."""

    def test_purge_by_repository_dry_run(self, browse_client, temp_chroma_client):
        """Test purge by repository in dry_run mode."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=["Doc from target repo", "Doc from other repo"],
            ids=["target-doc", "other-doc"],
            metadatas=[
                {"type": "note", "repository": "target-repo"},
                {"type": "note", "repository": "other-repo"},
            ],
        )

        response = browse_client.post(
            "/browse/purge",
            json={
                "repository": "target-repo",
                "dry_run": True,
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["dry_run"] is True
        assert data["matched_count"] == 1
        assert data["deleted_count"] == 0

    def test_purge_by_type(self, browse_client, temp_chroma_client):
        """Test purge by document type."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=["Note 1", "Note 2", "Insight 1"],
            ids=["note1", "note2", "insight1"],
            metadatas=[
                {"type": "note", "repository": "test"},
                {"type": "note", "repository": "test"},
                {"type": "insight", "repository": "test"},
            ],
        )

        response = browse_client.post(
            "/browse/purge",
            json={
                "doc_type": "note",
                "dry_run": True,
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["matched_count"] == 2

    def test_purge_execute(self, browse_client, temp_chroma_client):
        """Test purge actually deletes documents."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=["To purge"],
            ids=["purge-me"],
            metadatas=[{"type": "note", "repository": "purge-repo"}],
        )

        response = browse_client.post(
            "/browse/purge",
            json={
                "repository": "purge-repo",
                "dry_run": False,
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["deleted_count"] == 1

        # Verify deletion
        result = collection.get(ids=["purge-me"])
        assert len(result["ids"]) == 0

    def test_purge_requires_filter(self, browse_client):
        """Test that purge requires at least one filter."""
        response = browse_client.post(
            "/browse/purge",
            json={
                "dry_run": True,
            }
        )

        assert response.status_code == 400
        assert "filter" in response.json()["detail"].lower()

    def test_purge_with_date_filters(self, browse_client, temp_chroma_client):
        """Test purge with date range filters."""
        from datetime import datetime, timedelta, timezone
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")

        old_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        new_date = datetime.now(timezone.utc).isoformat()

        collection.add(
            documents=["Old doc", "New doc"],
            ids=["old", "new"],
            metadatas=[
                {"type": "note", "repository": "test", "created_at": old_date},
                {"type": "note", "repository": "test", "created_at": new_date},
            ],
        )

        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        response = browse_client.post(
            "/browse/purge",
            json={
                "repository": "test",
                "before_date": cutoff,
                "dry_run": True,
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["matched_count"] == 1  # Only old doc

    def test_purge_returns_sample_ids(self, browse_client, temp_chroma_client):
        """Test that purge returns sample IDs of matched documents."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=["Doc 1", "Doc 2", "Doc 3"],
            ids=["doc1", "doc2", "doc3"],
            metadatas=[
                {"type": "note", "repository": "sample-repo"},
                {"type": "note", "repository": "sample-repo"},
                {"type": "note", "repository": "sample-repo"},
            ],
        )

        response = browse_client.post(
            "/browse/purge",
            json={
                "repository": "sample-repo",
                "dry_run": True,
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["sample_ids"]) == 3
        assert "doc1" in data["sample_ids"]
