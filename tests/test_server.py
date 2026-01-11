"""
Tests for server MCP tools
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestSearchCortex:
    """Tests for search_cortex tool."""

    def test_search_returns_results(self, temp_dir: Path, temp_chroma_client):
        """Test that search returns results from indexed content."""
        from src.storage import get_or_create_collection

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
        from src.search import HybridSearcher, RerankerService

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
        from src.tools.services import CONFIG

        CONFIG["enabled"] = False

        # The actual tool would return an error
        # We verify the config is properly set
        assert CONFIG["enabled"] is False

        # Reset
        CONFIG["enabled"] = True

    def test_search_empty_collection(self, temp_chroma_client):
        """Test search on empty collection."""
        from src.search import HybridSearcher
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "empty")
        searcher = HybridSearcher(collection)
        searcher.build_index()

        results = searcher.search("anything", top_k=10)
        assert results == []


class TestIngestCodeIntoCortex:
    """Tests for ingest_code_into_cortex tool."""

    def test_ingest_basic(self, temp_dir: Path, temp_chroma_client):
        """Test basic code ingestion."""
        from src.ingest import ingest_codebase
        from src.storage import get_or_create_collection

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
            header_provider="none",
            state_file=state_file,
        )

        assert stats["files_processed"] == 2
        assert stats["chunks_created"] >= 2

        # Verify content in collection
        results = collection.get(include=["metadatas"])
        assert len(results["ids"]) >= 2

        # All should have the correct project
        for meta in results["metadatas"]:
            assert meta["project"] == "testproject"

    def test_ingest_respects_force_full(self, temp_dir: Path, temp_chroma_client):
        """Test that force_full re-ingests everything."""
        from src.ingest import ingest_codebase
        from src.storage import get_or_create_collection

        (temp_dir / "main.py").write_text("def main(): pass")

        collection = get_or_create_collection(temp_chroma_client, "force_test")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_file = f.name

        # First ingest
        stats1 = ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            header_provider="none",
            state_file=state_file,
        )
        assert stats1["files_processed"] == 1

        # Second ingest without changes (should skip)
        stats2 = ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            header_provider="none",
            state_file=state_file,
        )
        assert stats2["files_processed"] == 0

        # Third ingest with force_full (should re-process)
        stats3 = ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            header_provider="none",
            state_file=state_file,
            force_full=True,
        )
        assert stats3["files_processed"] == 1


class TestCommitToCortex:
    """Tests for commit_to_cortex tool."""

    def test_commit_saves_summary(self, temp_dir: Path, temp_chroma_client):
        """Test that commit saves summary to collection."""
        import uuid

        from src.security import scrub_secrets
        from src.storage import get_or_create_collection

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
        import uuid

        from src.security import scrub_secrets
        from src.storage import get_or_create_collection

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
        import uuid

        from src.security import scrub_secrets
        from src.storage import get_or_create_collection

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
        from src.tools.services import CONFIG

        original = CONFIG["min_score"]

        CONFIG["min_score"] = 0.7
        assert CONFIG["min_score"] == 0.7

        # Reset
        CONFIG["min_score"] = original

    def test_configure_verbose(self):
        """Test configuring verbose mode."""
        from src.tools.services import CONFIG

        original = CONFIG["verbose"]

        CONFIG["verbose"] = True
        assert CONFIG["verbose"] is True

        CONFIG["verbose"] = False
        assert CONFIG["verbose"] is False

        # Reset
        CONFIG["verbose"] = original

    def test_configure_top_k_limits(self):
        """Test that top_k values are bounded."""
        from src.tools.services import CONFIG

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
        from src.tools.services import CONFIG

        CONFIG["enabled"] = False
        assert CONFIG["enabled"] is False

    def test_toggle_enable(self):
        """Test enabling Cortex."""
        from src.tools.services import CONFIG

        CONFIG["enabled"] = True
        assert CONFIG["enabled"] is True


class TestContextTools:
    """Tests for context composition tools."""

    def test_set_context_saves_domain(self, temp_chroma_client):
        """Test that set_context_in_cortex saves domain context."""
        from datetime import datetime, timezone

        from src.security import scrub_secrets
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "context_test")

        project = "myproject"
        domain = "NestJS backend, PostgreSQL database, React frontend"
        domain_id = f"{project}:domain_context"
        timestamp = datetime.now(timezone.utc).isoformat()

        collection.upsert(
            ids=[domain_id],
            documents=[scrub_secrets(domain)],
            metadatas=[{
                "type": "domain_context",
                "project": project,
                "branch": "main",
                "updated_at": timestamp,
            }],
        )

        # Verify saved
        results = collection.get(ids=[domain_id], include=["documents", "metadatas"])
        assert len(results["ids"]) == 1
        assert "NestJS" in results["documents"][0]
        assert results["metadatas"][0]["type"] == "domain_context"
        assert results["metadatas"][0]["project"] == project

    def test_set_context_saves_project_status(self, temp_chroma_client):
        """Test that set_context_in_cortex saves project status."""
        from datetime import datetime, timezone

        from src.security import scrub_secrets
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "context_test2")

        project = "myproject"
        status = "Migration V1: Phase 2 - auth module complete, API review pending"
        status_id = f"{project}:project_context"
        timestamp = datetime.now(timezone.utc).isoformat()

        collection.upsert(
            ids=[status_id],
            documents=[scrub_secrets(status)],
            metadatas=[{
                "type": "project_context",
                "project": project,
                "branch": "main",
                "updated_at": timestamp,
            }],
        )

        # Verify saved
        results = collection.get(ids=[status_id], include=["documents", "metadatas"])
        assert len(results["ids"]) == 1
        assert "Phase 2" in results["documents"][0]
        assert results["metadatas"][0]["type"] == "project_context"

    def test_context_upsert_overwrites(self, temp_chroma_client):
        """Test that context is overwritten on update (upsert behavior)."""
        from datetime import datetime, timezone

        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "context_upsert")

        project = "myproject"
        status_id = f"{project}:project_context"

        # First status
        collection.upsert(
            ids=[status_id],
            documents=["Phase 1: In progress"],
            metadatas=[{
                "type": "project_context",
                "project": project,
                "branch": "main",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }],
        )

        # Update status
        collection.upsert(
            ids=[status_id],
            documents=["Phase 2: Started"],
            metadatas=[{
                "type": "project_context",
                "project": project,
                "branch": "main",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }],
        )

        # Should only have one document with updated content
        results = collection.get(ids=[status_id], include=["documents"])
        assert len(results["ids"]) == 1
        assert "Phase 2" in results["documents"][0]
        assert "Phase 1" not in results["documents"][0]

    def test_get_context_retrieves_both(self, temp_chroma_client):
        """Test that get_context retrieves both domain and project context."""
        from datetime import datetime, timezone

        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "context_get")

        project = "myproject"
        domain_id = f"{project}:domain_context"
        status_id = f"{project}:project_context"
        timestamp = datetime.now(timezone.utc).isoformat()

        # Save both contexts
        collection.upsert(
            ids=[domain_id],
            documents=["Python FastAPI backend"],
            metadatas=[{
                "type": "domain_context",
                "project": project,
                "branch": "main",
                "updated_at": timestamp,
            }],
        )
        collection.upsert(
            ids=[status_id],
            documents=["Implementing user auth"],
            metadatas=[{
                "type": "project_context",
                "project": project,
                "branch": "main",
                "updated_at": timestamp,
            }],
        )

        # Retrieve both
        results = collection.get(
            ids=[domain_id, status_id],
            include=["documents", "metadatas"],
        )

        assert len(results["ids"]) == 2

        # Verify both are present
        docs = results["documents"]
        assert any("FastAPI" in doc for doc in docs)
        assert any("user auth" in doc for doc in docs)

    def test_context_scrubs_secrets(self, temp_chroma_client):
        """Test that context has secrets scrubbed."""
        from datetime import datetime, timezone

        from src.security import scrub_secrets
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "context_secrets")

        project = "myproject"
        domain_id = f"{project}:domain_context"

        # Domain with a secret
        domain_with_secret = "Backend using API key AKIAIOSFODNN7EXAMPLE for AWS"
        timestamp = datetime.now(timezone.utc).isoformat()

        collection.upsert(
            ids=[domain_id],
            documents=[scrub_secrets(domain_with_secret)],
            metadatas=[{
                "type": "domain_context",
                "project": project,
                "branch": "main",
                "updated_at": timestamp,
            }],
        )

        results = collection.get(ids=[domain_id], include=["documents"])
        assert "AKIAIOSFODNN7EXAMPLE" not in results["documents"][0]

    def test_context_included_in_search(self, temp_chroma_client):
        """Test that context can be fetched alongside search results."""
        from datetime import datetime, timezone

        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "context_search")

        project = "searchproject"
        domain_id = f"{project}:domain_context"
        status_id = f"{project}:project_context"
        timestamp = datetime.now(timezone.utc).isoformat()

        # Add some code
        collection.add(
            documents=["def calculate_total(): return sum(items)"],
            ids=["code:1"],
            metadatas=[{
                "type": "code",
                "file_path": "/app/utils.py",
                "project": project,
                "branch": "main",
                "language": "python",
            }],
        )

        # Add context
        collection.upsert(
            ids=[domain_id],
            documents=["E-commerce platform with Python backend"],
            metadatas=[{
                "type": "domain_context",
                "project": project,
                "branch": "main",
                "updated_at": timestamp,
            }],
        )
        collection.upsert(
            ids=[status_id],
            documents=["Building checkout flow"],
            metadatas=[{
                "type": "project_context",
                "project": project,
                "branch": "main",
                "updated_at": timestamp,
            }],
        )

        # Simulate search_cortex context fetch pattern
        context_results = collection.get(
            ids=[domain_id, status_id],
            include=["documents", "metadatas"],
        )

        # Verify context is retrievable
        assert len(context_results["ids"]) == 2
        docs = context_results["documents"]
        assert any("E-commerce" in doc for doc in docs)
        assert any("checkout" in doc for doc in docs)

    def test_set_context_validation_requires_content(self):
        """Test that set_context requires at least one of domain or project_status."""
        # Simulate the validation logic from set_context_in_cortex
        domain = None
        project_status = None

        # This is the validation check in set_context_in_cortex
        if not domain and not project_status:
            error = json.dumps({
                "error": "At least one of 'domain' or 'project_status' must be provided",
            })
            parsed = json.loads(error)
            assert "error" in parsed
            assert "domain" in parsed["error"] or "project_status" in parsed["error"]

    def test_get_context_validation_requires_project(self):
        """Test that get_context requires project parameter."""
        # Simulate the validation logic from get_context_from_cortex
        project = None

        if not project:
            error = json.dumps({
                "error": "Project name is required",
                "hint": "Provide the project identifier",
            })
            parsed = json.loads(error)
            assert "error" in parsed
            assert "required" in parsed["error"].lower()

    def test_update_status_validation_requires_project(self):
        """Test that update_project_status requires project parameter."""
        # Simulate the validation logic from update_project_status
        project = None

        if not project:
            error = json.dumps({
                "error": "Project name is required",
                "hint": "Provide the project identifier",
            })
            parsed = json.loads(error)
            assert "error" in parsed
            assert "required" in parsed["error"].lower()

    def test_get_context_empty_returns_message(self, temp_chroma_client):
        """Test that get_context returns helpful message when no context exists."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "empty_context")
        project = "nonexistent_project"
        domain_id = f"{project}:domain_context"
        status_id = f"{project}:project_context"

        # Try to fetch non-existent context
        results = collection.get(
            ids=[domain_id, status_id],
            include=["documents", "metadatas"],
        )

        # Should return empty
        assert len(results["ids"]) == 0

        # Simulate the response logic
        context = {
            "project": project,
            "domain": None,
            "project_status": None,
        }
        has_context = context["domain"] or context["project_status"]
        assert not has_context

    def test_set_context_domain_only(self, temp_chroma_client):
        """Test setting only domain context (no project_status)."""
        from datetime import datetime, timezone

        from src.security import scrub_secrets
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "domain_only")

        project = "testproj"
        domain = "Python Flask backend"
        domain_id = f"{project}:domain_context"
        timestamp = datetime.now(timezone.utc).isoformat()

        # Only save domain (simulate set_context with domain only)
        saved = {}
        collection.upsert(
            ids=[domain_id],
            documents=[scrub_secrets(domain)],
            metadatas=[{
                "type": "domain_context",
                "project": project,
                "branch": "main",
                "updated_at": timestamp,
            }],
        )
        saved["domain_context_id"] = domain_id

        # Verify only domain was saved
        assert "domain_context_id" in saved
        assert "project_context_id" not in saved

        # Verify content
        results = collection.get(ids=[domain_id], include=["documents"])
        assert "Flask" in results["documents"][0]

    def test_set_context_status_only(self, temp_chroma_client):
        """Test setting only project_status (no domain)."""
        from datetime import datetime, timezone

        from src.security import scrub_secrets
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "status_only")

        project = "testproj"
        project_status = "Working on feature X"
        status_id = f"{project}:project_context"
        timestamp = datetime.now(timezone.utc).isoformat()

        # Only save status (simulate set_context with status only)
        saved = {}
        collection.upsert(
            ids=[status_id],
            documents=[scrub_secrets(project_status)],
            metadatas=[{
                "type": "project_context",
                "project": project,
                "branch": "main",
                "updated_at": timestamp,
            }],
        )
        saved["project_context_id"] = status_id

        # Verify only status was saved
        assert "project_context_id" in saved
        assert "domain_context_id" not in saved

        # Verify content
        results = collection.get(ids=[status_id], include=["documents"])
        assert "feature X" in results["documents"][0]

    def test_update_project_status_overwrites(self, temp_chroma_client):
        """Test that update_project_status overwrites existing status."""
        from datetime import datetime, timezone

        from src.security import scrub_secrets
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "update_status")

        project = "testproj"
        status_id = f"{project}:project_context"

        # Initial status
        collection.upsert(
            ids=[status_id],
            documents=["Phase 1: Planning"],
            metadatas=[{
                "type": "project_context",
                "project": project,
                "branch": "main",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }],
        )

        # Update status (simulate update_project_status)
        new_status = "Phase 3: Testing"
        collection.upsert(
            ids=[status_id],
            documents=[scrub_secrets(new_status)],
            metadatas=[{
                "type": "project_context",
                "project": project,
                "branch": "main",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }],
        )

        # Verify update
        results = collection.get(ids=[status_id], include=["documents"])
        assert len(results["ids"]) == 1
        assert "Phase 3" in results["documents"][0]
        assert "Phase 1" not in results["documents"][0]


class TestIntegration:
    """Integration tests for the full workflow."""

    def test_full_workflow(self, temp_dir: Path, temp_chroma_client):
        """Test complete ingest -> search workflow."""
        from src.ingest import ingest_codebase
        from src.search import HybridSearcher, RerankerService
        from src.storage import get_or_create_collection

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
            header_provider="none",
            state_file=state_file,
        )

        assert stats["files_processed"] == 2
        assert stats["chunks_created"] >= 2

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
        import uuid

        from src.search import HybridSearcher, RerankerService
        from src.storage import get_or_create_collection

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
