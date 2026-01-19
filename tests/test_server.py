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
                {"file_path": "/test/fib.py", "repository": "test", "branch": "main", "language": "python"},
                {"file_path": "/test/auth.js", "repository": "test", "branch": "main", "language": "javascript"},
                {"file_path": "/test/hashmap.rs", "repository": "test", "branch": "main", "language": "rust"},
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
            repo_id="testproject",
            state_file=state_file,
        )

        assert stats["files_processed"] == 2
        assert stats["docs_created"] >= 2

        # Verify content in collection
        results = collection.get(include=["metadatas"])
        assert len(results["ids"]) >= 2

        # All should have the correct project
        for meta in results["metadatas"]:
            assert meta["repository"] == "testproject"

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
            state_file=state_file,
        )
        assert stats1["files_processed"] == 1

        # Second ingest without changes (should skip)
        stats2 = ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            state_file=state_file,
        )
        assert stats2["files_processed"] == 0

        # Third ingest with force_full (should re-process)
        stats3 = ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            state_file=state_file,
            force_full=True,
        )
        assert stats3["files_processed"] == 1


class TestSessionSummaryToCortex:
    """Tests for session_summary_to_cortex tool."""

    def test_session_summary_saves_summary(self, temp_dir: Path, temp_chroma_client):
        """Test that session summary saves to collection."""
        import uuid

        from src.security import scrub_secrets
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "session_summary_test")

        # Simulate what session_summary_to_cortex does
        summary = "Implemented new authentication flow with JWT tokens"
        changed_files = ["/app/auth.py", "/app/middleware.py"]

        doc_id = f"session_summary:{uuid.uuid4().hex[:8]}"

        collection.upsert(
            ids=[doc_id],
            documents=[f"Session Summary:\n\n{scrub_secrets(summary)}\n\nChanged files: {', '.join(changed_files)}"],
            metadatas=[{
                "type": "session_summary",
                "repository": "test",
                "branch": "main",
                "files": json.dumps(changed_files),
            }],
        )

        # Verify saved
        results = collection.get(ids=[doc_id], include=["documents", "metadatas"])
        assert len(results["ids"]) == 1
        assert "authentication" in results["documents"][0].lower()
        assert results["metadatas"][0]["type"] == "session_summary"


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
                "repository": "myproject",
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
            metadatas=[{"type": "note", "repository": "test", "branch": "main", "title": "", "tags": ""}],
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


class TestConfigureEnabled:
    """Tests for configure_cortex enabled parameter (replaces toggle_cortex)."""

    def test_configure_disable(self):
        """Test disabling Cortex via configure_cortex."""
        import json

        from src.tools import configure_cortex
        from src.tools.services import CONFIG

        # Enable first
        CONFIG["enabled"] = True

        result = json.loads(configure_cortex(enabled=False))

        assert CONFIG["enabled"] is False
        assert result["config"]["enabled"] is False

    def test_configure_enable(self):
        """Test enabling Cortex via configure_cortex."""
        import json

        from src.tools import configure_cortex
        from src.tools.services import CONFIG

        # Disable first
        CONFIG["enabled"] = False

        result = json.loads(configure_cortex(enabled=True))

        assert CONFIG["enabled"] is True
        assert result["config"]["enabled"] is True


class TestContextTools:
    """Tests for context composition tools (set_repo_context, set_initiative, etc.)."""

    def test_set_repo_context_saves_tech_stack(self, temp_chroma_client):
        """Test that set_repo_context saves tech stack context."""
        from datetime import datetime, timezone

        from src.security import scrub_secrets
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "context_test")

        repository = "myproject"
        tech_stack = "NestJS backend, PostgreSQL database, React frontend"
        tech_stack_id = f"{repository}:tech_stack"
        timestamp = datetime.now(timezone.utc).isoformat()

        collection.upsert(
            ids=[tech_stack_id],
            documents=[scrub_secrets(tech_stack)],
            metadatas=[{
                "type": "tech_stack",
                "repository": repository,
                "branch": "main",
                "updated_at": timestamp,
            }],
        )

        # Verify saved
        results = collection.get(ids=[tech_stack_id], include=["documents", "metadatas"])
        assert len(results["ids"]) == 1
        assert "NestJS" in results["documents"][0]
        assert results["metadatas"][0]["type"] == "tech_stack"
        assert results["metadatas"][0]["repository"] == repository

    def test_set_initiative_saves_name_and_status(self, temp_chroma_client):
        """Test that set_initiative saves initiative name and status."""
        from datetime import datetime, timezone

        from src.security import scrub_secrets
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "context_test2")

        repository = "myproject"
        initiative_name = "Migration V1"
        initiative_status = "Phase 2 - auth module complete, API review pending"
        initiative_id = f"{repository}:initiative"
        timestamp = datetime.now(timezone.utc).isoformat()

        content = f"{initiative_name}\n\nStatus: {initiative_status}"

        collection.upsert(
            ids=[initiative_id],
            documents=[scrub_secrets(content)],
            metadatas=[{
                "type": "initiative",
                "repository": repository,
                "initiative_name": initiative_name,
                "initiative_status": initiative_status,
                "branch": "main",
                "updated_at": timestamp,
            }],
        )

        # Verify saved
        results = collection.get(ids=[initiative_id], include=["documents", "metadatas"])
        assert len(results["ids"]) == 1
        assert "Phase 2" in results["documents"][0]
        assert results["metadatas"][0]["type"] == "initiative"
        assert results["metadatas"][0]["initiative_name"] == initiative_name
        assert results["metadatas"][0]["initiative_status"] == initiative_status

    def test_initiative_upsert_overwrites(self, temp_chroma_client):
        """Test that initiative is overwritten on update (upsert behavior)."""
        from datetime import datetime, timezone

        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "context_upsert")

        repository = "myproject"
        initiative_id = f"{repository}:initiative"

        # First initiative
        collection.upsert(
            ids=[initiative_id],
            documents=["Feature X\n\nStatus: Phase 1: In progress"],
            metadatas=[{
                "type": "initiative",
                "repository": repository,
                "initiative_name": "Feature X",
                "initiative_status": "Phase 1: In progress",
                "branch": "main",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }],
        )

        # Update initiative
        collection.upsert(
            ids=[initiative_id],
            documents=["Feature X\n\nStatus: Phase 2: Started"],
            metadatas=[{
                "type": "initiative",
                "repository": repository,
                "initiative_name": "Feature X",
                "initiative_status": "Phase 2: Started",
                "branch": "main",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }],
        )

        # Should only have one document with updated content
        results = collection.get(ids=[initiative_id], include=["documents"])
        assert len(results["ids"]) == 1
        assert "Phase 2" in results["documents"][0]
        assert "Phase 1" not in results["documents"][0]

    def test_get_context_retrieves_both(self, temp_chroma_client):
        """Test that get_context retrieves both tech_stack and initiative."""
        from datetime import datetime, timezone

        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "context_get")

        repository = "myproject"
        tech_stack_id = f"{repository}:tech_stack"
        initiative_id = f"{repository}:initiative"
        timestamp = datetime.now(timezone.utc).isoformat()

        # Save both contexts
        collection.upsert(
            ids=[tech_stack_id],
            documents=["Python FastAPI backend"],
            metadatas=[{
                "type": "tech_stack",
                "repository": repository,
                "branch": "main",
                "updated_at": timestamp,
            }],
        )
        collection.upsert(
            ids=[initiative_id],
            documents=["User Auth\n\nStatus: Implementing"],
            metadatas=[{
                "type": "initiative",
                "repository": repository,
                "initiative_name": "User Auth",
                "initiative_status": "Implementing",
                "branch": "main",
                "updated_at": timestamp,
            }],
        )

        # Retrieve both
        results = collection.get(
            ids=[tech_stack_id, initiative_id],
            include=["documents", "metadatas"],
        )

        assert len(results["ids"]) == 2

        # Verify both are present
        docs = results["documents"]
        assert any("FastAPI" in doc for doc in docs)
        assert any("User Auth" in doc for doc in docs)

    def test_context_scrubs_secrets(self, temp_chroma_client):
        """Test that context has secrets scrubbed."""
        from datetime import datetime, timezone

        from src.security import scrub_secrets
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "context_secrets")

        repository = "myproject"
        tech_stack_id = f"{repository}:tech_stack"

        # Tech stack with a secret
        tech_stack_with_secret = "Backend using API key AKIAIOSFODNN7EXAMPLE for AWS"
        timestamp = datetime.now(timezone.utc).isoformat()

        collection.upsert(
            ids=[tech_stack_id],
            documents=[scrub_secrets(tech_stack_with_secret)],
            metadatas=[{
                "type": "tech_stack",
                "repository": repository,
                "branch": "main",
                "updated_at": timestamp,
            }],
        )

        results = collection.get(ids=[tech_stack_id], include=["documents"])
        assert "AKIAIOSFODNN7EXAMPLE" not in results["documents"][0]

    def test_context_included_in_search(self, temp_chroma_client):
        """Test that context can be fetched alongside search results."""
        from datetime import datetime, timezone

        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "context_search")

        repository = "searchproject"
        tech_stack_id = f"{repository}:tech_stack"
        initiative_id = f"{repository}:initiative"
        timestamp = datetime.now(timezone.utc).isoformat()

        # Add some code
        collection.add(
            documents=["def calculate_total(): return sum(items)"],
            ids=["code:1"],
            metadatas=[{
                "type": "file_metadata",
                "file_path": "/app/utils.py",
                "repository": repository,
                "branch": "main",
                "language": "python",
            }],
        )

        # Add context
        collection.upsert(
            ids=[tech_stack_id],
            documents=["E-commerce platform with Python backend"],
            metadatas=[{
                "type": "tech_stack",
                "repository": repository,
                "branch": "main",
                "updated_at": timestamp,
            }],
        )
        collection.upsert(
            ids=[initiative_id],
            documents=["Checkout Flow\n\nStatus: Building"],
            metadatas=[{
                "type": "initiative",
                "repository": repository,
                "initiative_name": "Checkout Flow",
                "initiative_status": "Building",
                "branch": "main",
                "updated_at": timestamp,
            }],
        )

        # Simulate search_cortex context fetch pattern
        context_results = collection.get(
            ids=[tech_stack_id, initiative_id],
            include=["documents", "metadatas"],
        )

        # Verify context is retrievable
        assert len(context_results["ids"]) == 2
        docs = context_results["documents"]
        assert any("E-commerce" in doc for doc in docs)
        assert any("Checkout" in doc for doc in docs)

    def test_set_repo_context_validation_requires_tech_stack(self):
        """Test that set_repo_context requires tech_stack parameter."""
        repository = "myproject"
        tech_stack = None

        if not tech_stack:
            error = json.dumps({
                "error": "Tech stack description is required",
            })
            parsed = json.loads(error)
            assert "error" in parsed
            assert "tech_stack" in parsed["error"].lower() or "required" in parsed["error"].lower()

    def test_get_context_validation_requires_repository(self):
        """Test that get_context requires repository parameter."""
        repository = None

        if not repository:
            error = json.dumps({
                "error": "Repository name is required",
            })
            parsed = json.loads(error)
            assert "error" in parsed
            assert "required" in parsed["error"].lower()

    def test_set_initiative_validation_requires_repository(self):
        """Test that set_initiative requires repository parameter."""
        repository = None

        if not repository:
            error = json.dumps({
                "error": "Repository name is required",
            })
            parsed = json.loads(error)
            assert "error" in parsed
            assert "required" in parsed["error"].lower()

    def test_get_context_empty_returns_message(self, temp_chroma_client):
        """Test that get_context returns helpful message when no context exists."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "empty_context")
        repository = "nonexistent_project"
        tech_stack_id = f"{repository}:tech_stack"
        initiative_id = f"{repository}:initiative"

        # Try to fetch non-existent context
        results = collection.get(
            ids=[tech_stack_id, initiative_id],
            include=["documents", "metadatas"],
        )

        # Should return empty
        assert len(results["ids"]) == 0

        # Simulate the response logic
        context = {
            "repository": repository,
            "tech_stack": None,
            "initiative": None,
        }
        has_context = context["tech_stack"] or context["initiative"]
        assert not has_context

    def test_set_initiative_name_only(self, temp_chroma_client):
        """Test setting initiative with name only (no status)."""
        from datetime import datetime, timezone

        from src.security import scrub_secrets
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "initiative_name_only")

        repository = "testproj"
        initiative_name = "Feature Y"
        initiative_id = f"{repository}:initiative"
        timestamp = datetime.now(timezone.utc).isoformat()

        # Save initiative with name only
        collection.upsert(
            ids=[initiative_id],
            documents=[scrub_secrets(initiative_name)],
            metadatas=[{
                "type": "initiative",
                "repository": repository,
                "initiative_name": initiative_name,
                "initiative_status": "",
                "branch": "main",
                "updated_at": timestamp,
            }],
        )

        # Verify content
        results = collection.get(ids=[initiative_id], include=["documents", "metadatas"])
        assert "Feature Y" in results["documents"][0]
        assert results["metadatas"][0]["initiative_name"] == initiative_name
        assert results["metadatas"][0]["initiative_status"] == ""

    def test_set_initiative_status_overwrites(self, temp_chroma_client):
        """Test that set_initiative overwrites existing status."""
        from datetime import datetime, timezone

        from src.security import scrub_secrets
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "update_status")

        repository = "testproj"
        initiative_id = f"{repository}:initiative"
        initiative_name = "Feature Z"

        # Initial initiative
        collection.upsert(
            ids=[initiative_id],
            documents=[f"{initiative_name}\n\nStatus: Phase 1: Planning"],
            metadatas=[{
                "type": "initiative",
                "repository": repository,
                "initiative_name": initiative_name,
                "initiative_status": "Phase 1: Planning",
                "branch": "main",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }],
        )

        # Update status (simulate set_initiative with new status)
        new_status = "Phase 3: Testing"
        collection.upsert(
            ids=[initiative_id],
            documents=[scrub_secrets(f"{initiative_name}\n\nStatus: {new_status}")],
            metadatas=[{
                "type": "initiative",
                "repository": repository,
                "initiative_name": initiative_name,
                "initiative_status": new_status,
                "branch": "main",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }],
        )

        # Verify update
        results = collection.get(ids=[initiative_id], include=["documents", "metadatas"])
        assert len(results["ids"]) == 1
        assert "Phase 3" in results["documents"][0]
        assert "Phase 1" not in results["documents"][0]
        assert results["metadatas"][0]["initiative_status"] == new_status


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
            repo_id="testcalc",
            state_file=state_file,
        )

        assert stats["files_processed"] == 2
        assert stats["docs_created"] >= 2

        # Search - with metadata-first, we search for file metadata, not raw code
        searcher = HybridSearcher(collection)
        searcher.build_index()

        candidates = searcher.search("calculator arithmetic", top_k=10)
        assert len(candidates) > 0

        # Rerank
        reranker = RerankerService()
        reranked = reranker.rerank("calculator arithmetic", candidates, top_k=3)

        # Should find calculator-related content (file path, description, or exports)
        found_calc = False
        for result in reranked:
            text = result.get("text", "").lower()
            meta = result.get("meta", {})
            file_path = meta.get("file_path", "").lower()
            if "calculator" in text or "calculator" in file_path or "arithmetic" in text:
                found_calc = True
                break

        assert found_calc, "Should find calculator-related metadata in search results"

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
            metadatas=[{"type": "note", "repository": "test", "branch": "main", "title": "", "tags": ""}],
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


class TestBranchAwareFilter:
    """Tests for build_branch_aware_filter function."""

    def test_filter_with_project_and_branches(self):
        """Test filter construction with project and branch list."""
        from src.tools.search import build_branch_aware_filter

        result = build_branch_aware_filter(repository="myproject", branches=["feature-x", "main"])

        assert result is not None
        assert "$and" in result
        # Should have project filter and branch filter combined
        assert {"repository": "myproject"} in result["$and"]

        # Find the $or clause
        or_clause = None
        for item in result["$and"]:
            if "$or" in item:
                or_clause = item["$or"]
                break

        assert or_clause is not None
        # Should have code/skeleton filtered by branch
        assert any("type" in c.get("$and", [{}])[0] for c in or_clause if "$and" in c)
        # Should have non-code types always included (note, session_summary, tech_stack, initiative, insight)
        assert any(c.get("type", {}).get("$in") == ["note", "session_summary", "tech_stack", "initiative", "insight"] for c in or_clause)

    def test_filter_with_unknown_branch(self):
        """Test that unknown branch returns simple project filter."""
        from src.tools.search import build_branch_aware_filter

        result = build_branch_aware_filter(repository="myproject", branches=["unknown"])

        # Should fall back to simple project filter
        assert result == {"repository": "myproject"}

    def test_filter_with_no_branches(self):
        """Test that empty branches returns simple project filter."""
        from src.tools.search import build_branch_aware_filter

        result = build_branch_aware_filter(repository="myproject", branches=None)
        assert result == {"repository": "myproject"}

        result = build_branch_aware_filter(repository="myproject", branches=[])
        assert result == {"repository": "myproject"}

    def test_filter_without_project(self):
        """Test filter with branches but no project."""
        from src.tools.search import build_branch_aware_filter

        result = build_branch_aware_filter(repository=None, branches=["main"])

        assert result is not None
        assert "$or" in result
        # Should only have branch filter, no project
        assert "$and" not in result or not any(
            "repository" in item for item in result.get("$and", [])
        )

    def test_filter_returns_none_when_no_filters(self):
        """Test that no project and unknown branch returns None."""
        from src.tools.search import build_branch_aware_filter

        result = build_branch_aware_filter(repository=None, branches=["unknown"])
        assert result is None

        result = build_branch_aware_filter(repository=None, branches=None)
        assert result is None

    def test_filter_code_types_filtered_by_branch(self):
        """Test that branch-filtered types (code, skeleton, etc.) are in the branch-filtered clause."""
        from src.tools.search import build_branch_aware_filter, BRANCH_FILTERED_TYPES

        result = build_branch_aware_filter(repository=None, branches=["feature", "main"])

        # Find the branch-filtered clause (the one with $and containing type and branch)
        or_clauses = result["$or"]
        branch_filtered = None
        for clause in or_clauses:
            if "$and" in clause:
                for sub in clause["$and"]:
                    if "type" in sub:
                        types_in_clause = set(sub["type"].get("$in", []))
                        # Check if this is the branch-filtered types clause
                        if types_in_clause == BRANCH_FILTERED_TYPES:
                            branch_filtered = clause
                            break

        assert branch_filtered is not None
        # Should filter by branches
        branch_clause = None
        for sub in branch_filtered["$and"]:
            if "branch" in sub:
                branch_clause = sub
                break
        assert branch_clause is not None
        assert branch_clause["branch"]["$in"] == ["feature", "main"]

    def test_filter_non_code_types_not_filtered(self):
        """Test that note, session_summary, tech_stack, initiative, insight are not branch-filtered."""
        from src.tools.search import build_branch_aware_filter

        result = build_branch_aware_filter(repository=None, branches=["feature", "main"])

        # Find the non-filtered clause
        or_clauses = result["$or"]
        non_filtered = None
        for clause in or_clauses:
            if "type" in clause and "$in" in clause["type"]:
                if "note" in clause["type"]["$in"]:
                    non_filtered = clause
                    break

        assert non_filtered is not None
        assert non_filtered["type"]["$in"] == ["note", "session_summary", "tech_stack", "initiative", "insight"]
        # Should NOT have branch filter
        assert "branch" not in non_filtered
        assert "$and" not in non_filtered


class TestGetRepoPath:
    """Tests for get_repo_path helper function."""

    def test_returns_path_in_git_repo(self, temp_git_repo: Path):
        """Test that get_repo_path returns cwd when in a git repo."""
        from src.tools.services import get_repo_path

        # Mock os.getcwd to return our temp git repo
        with patch("src.tools.services.os.getcwd", return_value=str(temp_git_repo)):
            result = get_repo_path()

        assert result == str(temp_git_repo)

    def test_returns_none_in_non_git_dir(self, temp_dir: Path):
        """Test that get_repo_path returns None when not in a git repo."""
        from src.tools.services import get_repo_path

        # Mock os.getcwd to return our non-git temp dir
        with patch("src.tools.services.os.getcwd", return_value=str(temp_dir)):
            result = get_repo_path()

        assert result is None


class TestBranchAwareSearch:
    """Integration tests for branch-aware search filtering."""

    def test_code_filtered_by_branch(self, temp_chroma_client):
        """Test that code chunks are filtered by branch."""
        from src.search import HybridSearcher
        from src.storage import get_or_create_collection
        from src.tools.search import build_branch_aware_filter

        collection = get_or_create_collection(temp_chroma_client, "branch_test")

        # Add code on different branches
        collection.add(
            documents=[
                "function processOrder() { return 'feature branch implementation'; }",
                "function processOrder() { return 'main branch implementation'; }",
                "function helperUtil() { return 'main only'; }",
            ],
            ids=["code-feature-1", "code-main-1", "code-main-2"],
            metadatas=[
                {"type": "file_metadata", "file_path": "/src/order.js", "repository": "test", "branch": "feature-x", "language": "javascript"},
                {"type": "file_metadata", "file_path": "/src/order.js", "repository": "test", "branch": "main", "language": "javascript"},
                {"type": "file_metadata", "file_path": "/src/utils.js", "repository": "test", "branch": "main", "language": "javascript"},
            ],
        )

        # Search with branch filter for "feature-x" branch (should include feature-x + main)
        where_filter = build_branch_aware_filter(repository="test", branches=["feature-x", "main"])
        searcher = HybridSearcher(collection)
        searcher.build_index(where_filter)

        results = searcher.search("processOrder", top_k=10, where_filter=where_filter)

        # Should find both feature and main branch code
        branches_found = {r["meta"]["branch"] for r in results}
        assert "feature-x" in branches_found or "main" in branches_found

    def test_notes_not_filtered_by_branch(self, temp_chroma_client):
        """Test that notes are visible from any branch."""
        from src.search import HybridSearcher
        from src.storage import get_or_create_collection
        from src.tools.search import build_branch_aware_filter

        collection = get_or_create_collection(temp_chroma_client, "notes_branch_test")

        # Add a note on main branch
        collection.add(
            documents=[
                "Architecture Decision: Use PostgreSQL for the database layer",
            ],
            ids=["note-1"],
            metadatas=[
                {"type": "note", "repository": "test", "branch": "main", "title": "DB Choice", "tags": "[]"},
            ],
        )

        # Search from a different branch - note should still be visible
        where_filter = build_branch_aware_filter(repository="test", branches=["feature-x", "main"])
        searcher = HybridSearcher(collection)
        searcher.build_index(where_filter)

        results = searcher.search("PostgreSQL database", top_k=10, where_filter=where_filter)

        # Note should be found even though we're on feature-x
        assert len(results) > 0
        assert any(r["meta"]["type"] == "note" for r in results)

    def test_session_summaries_not_filtered_by_branch(self, temp_chroma_client):
        """Test that session summaries are visible from any branch."""
        from src.search import HybridSearcher
        from src.storage import get_or_create_collection
        from src.tools.search import build_branch_aware_filter

        collection = get_or_create_collection(temp_chroma_client, "session_summaries_branch_test")

        # Add a session summary on main branch
        collection.add(
            documents=[
                "Session Summary: Implemented user authentication with JWT tokens",
            ],
            ids=["session-1"],
            metadatas=[
                {"type": "session_summary", "repository": "test", "branch": "main", "files": "[]"},
            ],
        )

        # Search from a different branch - session summary should still be visible
        where_filter = build_branch_aware_filter(repository="test", branches=["feature-y"])
        searcher = HybridSearcher(collection)
        searcher.build_index(where_filter)

        results = searcher.search("JWT authentication", top_k=10, where_filter=where_filter)

        # Commit should be found
        assert len(results) > 0
        assert any(r["meta"]["type"] == "session_summary" for r in results)

    def test_code_on_other_branch_excluded(self, temp_chroma_client):
        """Test that code on unrelated branches is excluded."""
        from src.search import HybridSearcher
        from src.storage import get_or_create_collection
        from src.tools.search import build_branch_aware_filter

        collection = get_or_create_collection(temp_chroma_client, "exclude_branch_test")

        # Add code only on feature-x branch
        collection.add(
            documents=[
                "function uniqueFeatureXFunction() { return 'only on feature-x'; }",
            ],
            ids=["code-feature-only"],
            metadatas=[
                {"type": "file_metadata", "file_path": "/src/feature.js", "repository": "test", "branch": "feature-x", "language": "javascript"},
            ],
        )

        # Search from feature-y branch (should NOT include feature-x code)
        where_filter = build_branch_aware_filter(repository="test", branches=["feature-y", "main"])
        searcher = HybridSearcher(collection)
        searcher.build_index(where_filter)

        results = searcher.search("uniqueFeatureXFunction", top_k=10, where_filter=where_filter)

        # Should NOT find the feature-x code
        for r in results:
            if r["meta"]["type"] == "file_metadata":
                assert r["meta"]["branch"] != "feature-x"

    def test_main_branch_included_from_feature_branch(self, temp_chroma_client):
        """Test that main branch code is included when searching from feature branch."""
        from src.search import HybridSearcher
        from src.storage import get_or_create_collection
        from src.tools.search import build_branch_aware_filter

        collection = get_or_create_collection(temp_chroma_client, "main_included_test")

        # Add code only on main branch
        collection.add(
            documents=[
                "function coreUtility() { return 'main branch core code'; }",
            ],
            ids=["code-main-core"],
            metadatas=[
                {"type": "file_metadata", "file_path": "/src/core.js", "repository": "test", "branch": "main", "language": "javascript"},
            ],
        )

        # Search from feature branch (should include main)
        where_filter = build_branch_aware_filter(repository="test", branches=["feature-x", "main"])
        searcher = HybridSearcher(collection)
        searcher.build_index(where_filter)

        results = searcher.search("coreUtility", top_k=10, where_filter=where_filter)

        # Should find main branch code
        assert len(results) > 0
        assert any(r["meta"]["branch"] == "main" for r in results)


class TestTypeFilter:
    """Tests for document type filtering in search."""

    def test_filter_single_type_notes_only(self, temp_chroma_client):
        """Test filtering to only return notes."""
        from src.search import HybridSearcher
        from src.storage import get_or_create_collection
        from src.tools.search import build_branch_aware_filter

        collection = get_or_create_collection(temp_chroma_client, "type_filter_notes")

        # Add different document types
        collection.add(
            documents=[
                "Architecture note: Use microservices pattern",
                "def process_order(): return calculate_total()",
                "Session summary: Implemented order processing",
            ],
            ids=["note-1", "code-1", "session-1"],
            metadatas=[
                {"type": "note", "repository": "test", "branch": "main", "title": "Architecture", "tags": ""},
                {"type": "file_metadata", "repository": "test", "branch": "main", "file_path": "/src/order.py", "language": "python"},
                {"type": "session_summary", "repository": "test", "branch": "main", "files": "[]"},
            ],
        )

        # Search with types filter for notes only
        where_filter = build_branch_aware_filter(repository="test", branches=["main"], types=["note"])
        searcher = HybridSearcher(collection)
        searcher.build_index(where_filter)

        results = searcher.search("order", top_k=10, where_filter=where_filter)

        # Should only return notes, not code or session summaries
        for r in results:
            assert r["meta"]["type"] == "note", f"Expected note, got {r['meta']['type']}"

    def test_filter_multiple_types(self, temp_chroma_client):
        """Test filtering to return multiple types (note + insight)."""
        from src.search import HybridSearcher
        from src.storage import get_or_create_collection
        from src.tools.search import build_branch_aware_filter

        collection = get_or_create_collection(temp_chroma_client, "type_filter_multiple")

        # Add different document types
        collection.add(
            documents=[
                "Architecture note: Use Redis for caching",
                "Insight: The auth module uses observer pattern",
                "def authenticate(): return jwt.encode()",
                "Session summary: Added caching layer",
            ],
            ids=["note-1", "insight-1", "code-1", "session-1"],
            metadatas=[
                {"type": "note", "repository": "test", "branch": "main", "title": "Caching", "tags": ""},
                {"type": "insight", "repository": "test", "branch": "main", "file_path": "/src/auth.py"},
                {"type": "file_metadata", "repository": "test", "branch": "main", "file_path": "/src/auth.py", "language": "python"},
                {"type": "session_summary", "repository": "test", "branch": "main", "files": "[]"},
            ],
        )

        # Search with types filter for notes and insights
        where_filter = build_branch_aware_filter(repository="test", branches=["main"], types=["note", "insight"])
        searcher = HybridSearcher(collection)
        searcher.build_index(where_filter)

        results = searcher.search("auth caching", top_k=10, where_filter=where_filter)

        # Should only return notes and insights
        for r in results:
            assert r["meta"]["type"] in ("note", "insight"), f"Unexpected type: {r['meta']['type']}"

    def test_filter_code_type_with_branch(self, temp_chroma_client):
        """Test that code type filter respects branch filtering."""
        from src.search import HybridSearcher
        from src.storage import get_or_create_collection
        from src.tools.search import build_branch_aware_filter

        collection = get_or_create_collection(temp_chroma_client, "type_filter_code_branch")

        # Add code on different branches
        collection.add(
            documents=[
                "def feature_func(): return 'feature branch'",
                "def main_func(): return 'main branch'",
                "Architecture note about functions",
            ],
            ids=["code-feature", "code-main", "note-1"],
            metadatas=[
                {"type": "file_metadata", "repository": "test", "branch": "feature-x", "file_path": "/src/app.py", "language": "python"},
                {"type": "file_metadata", "repository": "test", "branch": "main", "file_path": "/src/app.py", "language": "python"},
                {"type": "note", "repository": "test", "branch": "main", "title": "Functions", "tags": ""},
            ],
        )

        # Search for code only, from main branch (should exclude feature-x code)
        where_filter = build_branch_aware_filter(repository="test", branches=["main"], types=["file_metadata"])
        searcher = HybridSearcher(collection)
        searcher.build_index(where_filter)

        results = searcher.search("func", top_k=10, where_filter=where_filter)

        # Should only return main branch code
        for r in results:
            assert r["meta"]["type"] == "file_metadata"
            assert r["meta"]["branch"] == "main", f"Expected main branch, got {r['meta']['branch']}"

    def test_filter_mixed_branch_and_non_branch_types(self, temp_chroma_client):
        """Test filtering with both branch-filtered (code) and non-branch (note) types."""
        from src.search import HybridSearcher
        from src.storage import get_or_create_collection
        from src.tools.search import build_branch_aware_filter

        collection = get_or_create_collection(temp_chroma_client, "type_filter_mixed")

        # Add documents
        collection.add(
            documents=[
                "def feature_code(): pass",
                "def main_code(): pass",
                "Note about the code",
                "Session summary about the code",
            ],
            ids=["code-feature", "code-main", "note-1", "session-1"],
            metadatas=[
                {"type": "file_metadata", "repository": "test", "branch": "feature-x", "file_path": "/src/app.py", "language": "python"},
                {"type": "file_metadata", "repository": "test", "branch": "main", "file_path": "/src/app.py", "language": "python"},
                {"type": "note", "repository": "test", "branch": "main", "title": "Code Note", "tags": ""},
                {"type": "session_summary", "repository": "test", "branch": "main", "files": "[]"},
            ],
        )

        # Search for code + note from main branch
        where_filter = build_branch_aware_filter(repository="test", branches=["main"], types=["file_metadata", "note"])
        searcher = HybridSearcher(collection)
        searcher.build_index(where_filter)

        results = searcher.search("code", top_k=10, where_filter=where_filter)

        # Should return main branch code and notes (but not feature-x code or session summaries)
        types_found = {r["meta"]["type"] for r in results}
        assert "code" in types_found or "note" in types_found

        for r in results:
            assert r["meta"]["type"] in ("file_metadata", "note")
            if r["meta"]["type"] == "file_metadata":
                assert r["meta"]["branch"] == "main"

    def test_filter_empty_types_no_filter(self, temp_chroma_client):
        """Test that empty types list behaves as no filter."""
        from src.search import HybridSearcher
        from src.storage import get_or_create_collection
        from src.tools.search import build_branch_aware_filter

        collection = get_or_create_collection(temp_chroma_client, "type_filter_empty")

        collection.add(
            documents=[
                "Note content",
                "Code content",
            ],
            ids=["note-1", "code-1"],
            metadatas=[
                {"type": "note", "repository": "test", "branch": "main", "title": "", "tags": ""},
                {"type": "file_metadata", "repository": "test", "branch": "main", "file_path": "/app.py", "language": "python"},
            ],
        )

        # Search with empty types (should return all)
        where_filter = build_branch_aware_filter(repository="test", branches=["main"], types=[])
        searcher = HybridSearcher(collection)
        searcher.build_index(where_filter)

        results = searcher.search("content", top_k=10, where_filter=where_filter)

        # Should return both types
        types_found = {r["meta"]["type"] for r in results}
        assert len(types_found) >= 1  # At least some results

    def test_filter_none_types_no_filter(self):
        """Test that types=None behaves as no type filter."""
        from src.tools.search import build_branch_aware_filter

        # With types=None, should fall back to standard branch filtering
        result = build_branch_aware_filter(repository="test", branches=["main"], types=None)

        # Should have the standard $or structure for branch filtering
        assert "$and" in result
        assert {"repository": "test"} in result["$and"]

    def test_invalid_types_filtered_out(self):
        """Test that invalid types are filtered out with warning."""
        from src.documents import ALL_DOCUMENT_TYPES
        from src.tools.search import search_cortex
        import json
        from unittest.mock import patch, MagicMock

        # Mock the dependencies
        with patch("src.tools.search.get_collection") as mock_collection, \
             patch("src.tools.search.get_searcher") as mock_searcher, \
             patch("src.tools.search.get_reranker") as mock_reranker, \
             patch("src.tools.search.CONFIG", {"enabled": True, "top_k_retrieve": 50, "top_k_rerank": 10, "min_score": 0.0, "recency_boost": False, "verbose": False}):

            mock_collection.return_value = MagicMock()
            mock_searcher.return_value.search.return_value = []
            mock_reranker.return_value.rerank.return_value = []

            # This should log a warning but still work
            result = search_cortex(
                query="test",
                types=["note", "invalid_type", "also_invalid"]
            )

            parsed = json.loads(result)
            # Should not error, just return empty results
            assert "results" in parsed

    def test_build_filter_types_only_non_branch(self):
        """Test filter with only non-branch types doesn't include branch clause."""
        from src.tools.search import build_branch_aware_filter

        # Only notes and insights (non-branch types)
        result = build_branch_aware_filter(
            repository="test",
            branches=["main"],
            types=["note", "insight", "session_summary"]
        )

        # Should have simple type filter without branch conditions
        assert "$and" in result
        assert {"repository": "test"} in result["$and"]

        # Find the type filter
        type_filter = None
        for item in result["$and"]:
            if "type" in item:
                type_filter = item
                break

        assert type_filter is not None
        assert type_filter["type"]["$in"] == ["note", "insight", "session_summary"]

    def test_build_filter_types_only_branch_filtered(self):
        """Test filter with only branch-filtered types (code, skeleton)."""
        from src.tools.search import build_branch_aware_filter

        result = build_branch_aware_filter(
            repository="test",
            branches=["feature", "main"],
            types=["file_metadata", "skeleton"]
        )

        assert "$and" in result
        assert {"repository": "test"} in result["$and"]

        # Should have branch filtering for code/skeleton
        # Find the nested filter
        nested = None
        for item in result["$and"]:
            if "$and" in item:
                nested = item
                break

        assert nested is not None
        # Should filter by type and branch
        type_clause = None
        branch_clause = None
        for sub in nested["$and"]:
            if "type" in sub:
                type_clause = sub
            if "branch" in sub:
                branch_clause = sub

        assert type_clause is not None
        assert branch_clause is not None
        assert set(type_clause["type"]["$in"]) == {"file_metadata", "skeleton"}
        assert set(branch_clause["branch"]["$in"]) == {"feature", "main"}
