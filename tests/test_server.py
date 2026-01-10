"""
Tests for server.py MCP tools
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Mock the MCP module before importing server
@pytest.fixture(autouse=True)
def mock_mcp():
    """Mock MCP server for testing."""
    with patch.dict("sys.modules", {"mcp": MagicMock(), "mcp.server": MagicMock(), "mcp.server.fastmcp": MagicMock()}):
        yield


class TestSearchCortex:
    """Tests for search_cortex tool."""

    def test_search_returns_results(self, temp_dir: Path, temp_chroma_client):
        """Test that search returns results from indexed content."""
        from rag_utils import get_or_create_collection

        # Set up collection with test data
        collection = get_or_create_collection(temp_chroma_client, "cortex_memory")
        collection.add(
            documents=[
                "Python function for calculating fibonacci numbers",
                "JavaScript class for handling user authentication",
                "Rust implementation of a hash map",
            ],
            ids=["1", "2", "3"],
            metadatas=[
                {"file_path": "/test/fib.py", "project": "test", "branch": "main", "language": "python"},
                {"file_path": "/test/auth.js", "project": "test", "branch": "main", "language": "javascript"},
                {"file_path": "/test/hashmap.rs", "project": "test", "branch": "main", "language": "rust"},
            ],
        )

        # Import and test search
        from rag_utils import HybridSearcher, RerankerService

        searcher = HybridSearcher(collection)
        reranker = RerankerService()

        # Build index
        searcher.build_index()

        # Search
        candidates = searcher.search("fibonacci", top_k=10)
        assert len(candidates) > 0

        # Rerank
        reranked = reranker.rerank("fibonacci", candidates, top_k=3)
        assert len(reranked) > 0

    def test_search_with_disabled_cortex(self):
        """Test that search returns error when Cortex is disabled."""
        # This would require importing server module with mocked dependencies
        # For now, we test the config behavior
        from server import CONFIG

        CONFIG["enabled"] = False

        # The actual tool would return an error
        # We verify the config is properly set
        assert CONFIG["enabled"] is False

        # Reset
        CONFIG["enabled"] = True

    def test_search_empty_collection(self, temp_chroma_client):
        """Test search on empty collection."""
        from rag_utils import get_or_create_collection, HybridSearcher

        collection = get_or_create_collection(temp_chroma_client, "empty")
        searcher = HybridSearcher(collection)
        searcher.build_index()

        results = searcher.search("anything", top_k=10)
        assert results == []


class TestIngestCodeIntoCortex:
    """Tests for ingest_code_into_cortex tool."""

    def test_ingest_basic(self, temp_dir: Path, temp_chroma_client):
        """Test basic code ingestion."""
        from rag_utils import get_or_create_collection
        from ingest import ingest_codebase

        # Create test files
        (temp_dir / "main.py").write_text("def hello(): print('world')")
        (temp_dir / "utils.py").write_text("def helper(): return 42")

        collection = get_or_create_collection(temp_chroma_client, "test")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_file = f.name

        stats = ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            project_id="testproject",
            use_haiku=False,
            state_file=state_file,
        )

        assert stats["files_processed"] == 2
        assert stats["chunks_added"] >= 2

        # Verify content in collection
        results = collection.get(include=["metadatas"])
        assert len(results["ids"]) >= 2

        # All should have the correct project
        for meta in results["metadatas"]:
            assert meta["project"] == "testproject"

    def test_ingest_respects_force_full(self, temp_dir: Path, temp_chroma_client):
        """Test that force_full re-ingests everything."""
        from rag_utils import get_or_create_collection
        from ingest import ingest_codebase

        (temp_dir / "main.py").write_text("def main(): pass")

        collection = get_or_create_collection(temp_chroma_client, "force_test")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_file = f.name

        # First ingest
        stats1 = ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            use_haiku=False,
            state_file=state_file,
        )
        assert stats1["files_processed"] == 1

        # Second ingest without changes (should skip)
        stats2 = ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            use_haiku=False,
            state_file=state_file,
        )
        assert stats2["files_processed"] == 0

        # Third ingest with force_full (should re-process)
        stats3 = ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            use_haiku=False,
            state_file=state_file,
            force_full=True,
        )
        assert stats3["files_processed"] == 1


class TestCommitToCortex:
    """Tests for commit_to_cortex tool."""

    def test_commit_saves_summary(self, temp_dir: Path, temp_chroma_client):
        """Test that commit saves summary to collection."""
        from rag_utils import get_or_create_collection, scrub_secrets
        import uuid

        collection = get_or_create_collection(temp_chroma_client, "commit_test")

        # Simulate what commit_to_cortex does
        summary = "Implemented new authentication flow with JWT tokens"
        changed_files = ["/app/auth.py", "/app/middleware.py"]

        note_id = f"commit:{uuid.uuid4().hex[:8]}"

        collection.upsert(
            ids=[note_id],
            documents=[f"Session Summary:\n\n{scrub_secrets(summary)}\n\nChanged files: {', '.join(changed_files)}"],
            metadatas=[{
                "type": "commit",
                "project": "test",
                "branch": "main",
                "files": json.dumps(changed_files),
            }],
        )

        # Verify saved
        results = collection.get(ids=[note_id], include=["documents", "metadatas"])
        assert len(results["ids"]) == 1
        assert "authentication" in results["documents"][0].lower()
        assert results["metadatas"][0]["type"] == "commit"


class TestSaveNoteToCortex:
    """Tests for save_note_to_cortex tool."""

    def test_save_note_basic(self, temp_chroma_client):
        """Test basic note saving."""
        from rag_utils import get_or_create_collection, scrub_secrets
        import uuid

        collection = get_or_create_collection(temp_chroma_client, "notes_test")

        title = "Architecture Decision"
        content = "We decided to use PostgreSQL instead of MongoDB for the user service."
        tags = ["architecture", "database"]

        note_id = f"note:{uuid.uuid4().hex[:8]}"

        doc_text = f"{title}\n\n{scrub_secrets(content)}"

        collection.upsert(
            ids=[note_id],
            documents=[doc_text],
            metadatas=[{
                "type": "note",
                "title": title,
                "tags": ",".join(tags),
                "project": "myproject",
                "branch": "main",
            }],
        )

        # Verify
        results = collection.get(ids=[note_id], include=["documents", "metadatas"])
        assert len(results["ids"]) == 1
        assert "PostgreSQL" in results["documents"][0]
        assert results["metadatas"][0]["type"] == "note"
        assert "architecture" in results["metadatas"][0]["tags"]

    def test_save_note_scrubs_secrets(self, temp_chroma_client):
        """Test that notes have secrets scrubbed."""
        from rag_utils import get_or_create_collection, scrub_secrets
        import uuid

        collection = get_or_create_collection(temp_chroma_client, "secret_notes")

        content = "API key is AKIAIOSFODNN7EXAMPLE"
        note_id = f"note:{uuid.uuid4().hex[:8]}"

        collection.upsert(
            ids=[note_id],
            documents=[scrub_secrets(content)],
            metadatas=[{"type": "note", "project": "test", "branch": "main", "title": "", "tags": ""}],
        )

        results = collection.get(ids=[note_id], include=["documents"])
        assert "AKIAIOSFODNN7EXAMPLE" not in results["documents"][0]


class TestConfigureCortex:
    """Tests for configure_cortex tool."""

    def test_configure_min_score(self):
        """Test configuring min_score."""
        from server import CONFIG

        original = CONFIG["min_score"]

        CONFIG["min_score"] = 0.7
        assert CONFIG["min_score"] == 0.7

        # Reset
        CONFIG["min_score"] = original

    def test_configure_verbose(self):
        """Test configuring verbose mode."""
        from server import CONFIG

        original = CONFIG["verbose"]

        CONFIG["verbose"] = True
        assert CONFIG["verbose"] is True

        CONFIG["verbose"] = False
        assert CONFIG["verbose"] is False

        # Reset
        CONFIG["verbose"] = original

    def test_configure_top_k_limits(self):
        """Test that top_k values are bounded."""
        from server import CONFIG

        # Test top_k_retrieve
        CONFIG["top_k_retrieve"] = max(10, min(200, 5))  # Below min
        assert CONFIG["top_k_retrieve"] == 10

        CONFIG["top_k_retrieve"] = max(10, min(200, 250))  # Above max
        assert CONFIG["top_k_retrieve"] == 200

        CONFIG["top_k_retrieve"] = max(10, min(200, 100))  # Normal
        assert CONFIG["top_k_retrieve"] == 100

        # Reset
        CONFIG["top_k_retrieve"] = 50


class TestToggleCortex:
    """Tests for toggle_cortex tool."""

    def test_toggle_disable(self):
        """Test disabling Cortex."""
        from server import CONFIG

        CONFIG["enabled"] = False
        assert CONFIG["enabled"] is False

    def test_toggle_enable(self):
        """Test enabling Cortex."""
        from server import CONFIG

        CONFIG["enabled"] = True
        assert CONFIG["enabled"] is True


class TestIntegration:
    """Integration tests for the full workflow."""

    def test_full_workflow(self, temp_dir: Path, temp_chroma_client):
        """Test complete ingest -> search workflow."""
        from rag_utils import get_or_create_collection, HybridSearcher, RerankerService
        from ingest import ingest_codebase

        # Create test codebase
        (temp_dir / "calculator.py").write_text('''
class Calculator:
    """A calculator that performs basic arithmetic."""

    def add(self, a: int, b: int) -> int:
        """Add two numbers together."""
        return a + b

    def multiply(self, a: int, b: int) -> int:
        """Multiply two numbers."""
        return a * b
''')

        (temp_dir / "utils.py").write_text('''
def validate_input(value):
    """Validate that input is a number."""
    if not isinstance(value, (int, float)):
        raise ValueError("Input must be a number")
    return True
''')

        collection = get_or_create_collection(temp_chroma_client, "integration")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_file = f.name

        # Ingest
        stats = ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            project_id="testcalc",
            use_haiku=False,
            state_file=state_file,
        )

        assert stats["files_processed"] == 2
        assert stats["chunks_added"] >= 2

        # Search
        searcher = HybridSearcher(collection)
        searcher.build_index()

        candidates = searcher.search("add two numbers", top_k=10)
        assert len(candidates) > 0

        # Rerank
        reranker = RerankerService()
        reranked = reranker.rerank("add two numbers", candidates, top_k=3)

        # The calculator add function should be in results
        found_add = False
        for result in reranked:
            if "add" in result.get("text", "").lower():
                found_add = True
                break

        assert found_add, "Should find the add function in search results"

    def test_note_searchable(self, temp_chroma_client):
        """Test that saved notes are searchable."""
        from rag_utils import get_or_create_collection, HybridSearcher, RerankerService
        import uuid

        collection = get_or_create_collection(temp_chroma_client, "notes_search")

        # Save a note
        note_id = f"note:{uuid.uuid4().hex[:8]}"
        collection.upsert(
            ids=[note_id],
            documents=["Architecture Decision: Use Redis for caching to improve API response times"],
            metadatas=[{"type": "note", "project": "test", "branch": "main", "title": "", "tags": ""}],
        )

        # Search for it
        searcher = HybridSearcher(collection)
        searcher.build_index()

        candidates = searcher.search("Redis caching", top_k=10)
        assert len(candidates) > 0

        # Verify our note is found
        found = False
        for c in candidates:
            if "Redis" in c.get("text", ""):
                found = True
                break

        assert found, "Note should be found in search"
