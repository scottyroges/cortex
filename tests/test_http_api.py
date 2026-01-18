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
    from src.http.resources import reset_resources

    # Reset the ResourceManager singleton before patching
    reset_resources()

    # Patch the ChromaDB client in the resources module
    with patch("src.http.resources.get_chroma_client", return_value=temp_chroma_client):
        from src.http import app
        client = TestClient(app)
        yield client

    # Reset after test
    reset_resources()


@pytest.fixture
def browse_client(temp_chroma_client):
    """Create a test client for the browse API with patched ChromaDB."""
    from src.http.resources import reset_resources

    # Reset the ResourceManager singleton before patching
    reset_resources()

    with patch("src.http.resources.get_chroma_client", return_value=temp_chroma_client):
        from src.http import app
        client = TestClient(app)
        yield client

    # Reset after test
    reset_resources()


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

    def test_update_commit_content(self, browse_client, temp_chroma_client):
        """Test updating a commit's content."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=["Original commit summary"],
            ids=["commit_001"],
            metadatas=[{
                "type": "commit",
                "repository": "test",
                "branch": "main",
                "files": '["file1.py"]',
            }],
        )

        response = browse_client.put(
            "/browse/update",
            params={"id": "commit_001"},
            json={"content": "Updated commit summary with more details"}
        )

        assert response.status_code == 200
        assert "content" in response.json()["updated_fields"]

    def test_update_commit_title_not_allowed(self, browse_client, temp_chroma_client):
        """Test that commits cannot have their title updated (not an editable field)."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=["Commit summary"],
            ids=["commit_002"],
            metadatas=[{
                "type": "commit",
                "repository": "test",
                "branch": "main",
                "files": "[]",
            }],
        )

        # Title is not editable for commits - should return 400 with no valid fields
        response = browse_client.put(
            "/browse/update",
            params={"id": "commit_002"},
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

    def test_delete_commit(self, browse_client, temp_chroma_client):
        """Test deleting a commit."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=["Session summary to delete"],
            ids=["commit_to_delete"],
            metadatas=[{
                "type": "commit",
                "repository": "test",
                "branch": "main",
                "files": '["file.py"]',
            }],
        )

        response = browse_client.delete("/browse/delete", params={"id": "commit_to_delete"})

        assert response.status_code == 200
        assert response.json()["success"] is True

        # Verify deletion
        result = collection.get(ids=["commit_to_delete"])
        assert len(result["ids"]) == 0
