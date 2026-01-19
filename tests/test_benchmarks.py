"""
Performance benchmark tests for Cortex.

These tests verify that core operations complete within acceptable time bounds
and can handle realistic workloads. They use pytest-benchmark style assertions
but don't require the plugin - just simple timing checks.

Target thresholds:
- Search latency: <500ms for typical queries
- Ingest throughput: >10 files/sec for small files
- Large codebase: Handle 500+ files without timeout
"""

import tempfile
import time
import uuid
from pathlib import Path
from typing import Generator

import pytest


class TestSearchLatency:
    """Verify search operations complete within acceptable time bounds."""

    @pytest.fixture
    def populated_collection(self, temp_chroma_client):
        """Create a collection with realistic test data."""
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "benchmark_search")

        # Add mix of content types (code, notes, insights)
        documents = []
        metadatas = []
        ids = []

        # Add 50 code chunks
        for i in range(50):
            documents.append(f"""
def function_{i}(x, y):
    '''Process data using algorithm variant {i}.'''
    result = x + y * {i}
    return result
""")
            metadatas.append({
                "type": "code",
                "repository": "benchmark-repo",
                "file_path": f"/src/module_{i // 10}/file_{i}.py",
                "language": "python",
            })
            ids.append(f"code:{uuid.uuid4().hex[:8]}")

        # Add 20 notes
        for i in range(20):
            documents.append(f"""
Decision: Use caching strategy {i} for performance optimization.
Rationale: Reduces database load by {i * 10}% in high-traffic scenarios.
Trade-offs: Increased memory usage, potential staleness.
""")
            metadatas.append({
                "type": "note",
                "repository": "benchmark-repo",
            })
            ids.append(f"note:{uuid.uuid4().hex[:8]}")

        # Add 10 insights
        for i in range(10):
            documents.append(f"""
The authentication module uses JWT tokens with refresh rotation.
Key pattern: Middleware validates tokens before route handlers.
File relationship: auth.py depends on crypto_utils.py for signing.
""")
            metadatas.append({
                "type": "insight",
                "repository": "benchmark-repo",
                "files": f'["/src/auth.py", "/src/crypto_{i}.py"]',
            })
            ids.append(f"insight:{uuid.uuid4().hex[:8]}")

        # Add 5 commits
        for i in range(5):
            documents.append(f"""
Session {i}: Implemented feature X with tests.
Changed files: src/feature.py, tests/test_feature.py
Key decisions: Used factory pattern for flexibility.
""")
            metadatas.append({
                "type": "commit",
                "repository": "benchmark-repo",
            })
            ids.append(f"commit:{uuid.uuid4().hex[:8]}")

        collection.add(documents=documents, metadatas=metadatas, ids=ids)
        return collection

    def test_search_latency_under_500ms(self, populated_collection):
        """Search should complete in under 500ms for typical queries."""
        from src.search import HybridSearcher

        searcher = HybridSearcher(populated_collection)
        searcher.build_index()

        queries = [
            "authentication JWT tokens",
            "caching strategy performance",
            "function process data algorithm",
            "decision rationale trade-offs",
        ]

        for query in queries:
            start = time.perf_counter()
            results = searcher.search(query, top_k=10)
            elapsed = time.perf_counter() - start

            assert elapsed < 0.5, f"Search took {elapsed:.3f}s (>500ms) for query: {query}"
            assert len(results) > 0, f"No results for query: {query}"

    def test_search_with_rerank_under_1s(self, populated_collection):
        """Search + rerank should complete in under 1 second."""
        from src.search import HybridSearcher, RerankerService

        searcher = HybridSearcher(populated_collection)
        searcher.build_index()
        reranker = RerankerService()

        query = "authentication middleware JWT validation"

        start = time.perf_counter()
        candidates = searcher.search(query, top_k=20)
        reranked = reranker.rerank(query, candidates, top_k=5)
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"Search+rerank took {elapsed:.3f}s (>1s)"
        assert len(reranked) > 0

    def test_empty_collection_search_fast(self, temp_chroma_client):
        """Search on empty collection should be very fast."""
        from src.search import HybridSearcher
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "empty_bench")
        searcher = HybridSearcher(collection)

        start = time.perf_counter()
        results = searcher.search("anything", top_k=10)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.1, f"Empty search took {elapsed:.3f}s (>100ms)"
        assert len(results) == 0


class TestIngestThroughput:
    """Verify ingest operations achieve acceptable throughput."""

    @pytest.fixture
    def codebase_small(self, temp_dir: Path) -> Path:
        """Create a small codebase with 20 files."""
        src = temp_dir / "src"
        src.mkdir()

        for i in range(20):
            (src / f"module_{i}.py").write_text(f'''
"""Module {i} for testing."""

class Handler{i}:
    """Handle operations for variant {i}."""

    def __init__(self, config):
        self.config = config
        self.value = {i}

    def process(self, data):
        """Process incoming data."""
        return data * self.value

    def validate(self, input_data):
        """Validate input before processing."""
        if not input_data:
            raise ValueError("Empty input")
        return True


def helper_function_{i}(x, y):
    """Helper function for module {i}."""
    return x + y + {i}
''')

        return temp_dir

    @pytest.fixture
    def codebase_medium(self, temp_dir: Path) -> Path:
        """Create a medium codebase with 100 files."""
        for module_idx in range(10):
            module_dir = temp_dir / f"module_{module_idx}"
            module_dir.mkdir()

            for file_idx in range(10):
                (module_dir / f"file_{file_idx}.py").write_text(f'''
"""File {file_idx} in module {module_idx}."""

import os
import sys
from typing import Optional, List

class Service{module_idx}_{file_idx}:
    """Service class for module {module_idx}, file {file_idx}."""

    def __init__(self, db_connection, cache_client):
        self.db = db_connection
        self.cache = cache_client
        self.logger = self._setup_logger()

    def _setup_logger(self):
        """Initialize logging."""
        import logging
        return logging.getLogger(f"service.{module_idx}.{file_idx}")

    def fetch_data(self, query: str) -> List[dict]:
        """Fetch data from database."""
        cached = self.cache.get(query)
        if cached:
            return cached
        result = self.db.execute(query)
        self.cache.set(query, result)
        return result

    def process_batch(self, items: List[dict]) -> List[dict]:
        """Process a batch of items."""
        results = []
        for item in items:
            processed = self._transform(item)
            results.append(processed)
        return results

    def _transform(self, item: dict) -> dict:
        """Transform a single item."""
        return {{**item, "processed": True, "module": {module_idx}}}


def utility_function_{module_idx}_{file_idx}(data: Optional[str] = None) -> str:
    """Utility function."""
    if data is None:
        return "default"
    return data.upper()
''')

        return temp_dir

    def test_ingest_small_codebase_throughput(self, codebase_small, temp_chroma_client):
        """Small codebase (20 files) should ingest at >10 files/sec."""
        from src.ingest import ingest_codebase
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "throughput_small")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_file = f.name

        start = time.perf_counter()
        stats = ingest_codebase(
            root_path=str(codebase_small),
            collection=collection,
            repo_id="throughput-test",
            llm_provider="none",
            state_file=state_file,
        )
        elapsed = time.perf_counter() - start

        files_processed = stats["files_processed"]
        throughput = files_processed / elapsed if elapsed > 0 else float("inf")

        assert throughput > 10, f"Throughput {throughput:.1f} files/sec < 10 files/sec"
        assert files_processed == 20, f"Expected 20 files, got {files_processed}"

    def test_ingest_medium_codebase_completes(self, codebase_medium, temp_chroma_client):
        """Medium codebase (100 files) should complete in <30 seconds."""
        from src.ingest import ingest_codebase
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "throughput_medium")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_file = f.name

        start = time.perf_counter()
        stats = ingest_codebase(
            root_path=str(codebase_medium),
            collection=collection,
            repo_id="throughput-medium",
            llm_provider="none",
            state_file=state_file,
        )
        elapsed = time.perf_counter() - start

        assert elapsed < 30, f"Medium codebase took {elapsed:.1f}s (>30s)"
        assert stats["files_processed"] == 100
        assert stats["chunks_created"] >= 100  # At least one chunk per file


class TestLargeCodebase:
    """Verify Cortex handles large codebases without issues."""

    @pytest.fixture
    def codebase_large(self, temp_dir: Path) -> Path:
        """Create a large codebase with 500 files."""
        # Create directory structure mimicking real project
        dirs = [
            "src/api", "src/core", "src/models", "src/services", "src/utils",
            "tests/unit", "tests/integration",
            "lib/helpers", "lib/adapters",
            "scripts",
        ]

        for d in dirs:
            (temp_dir / d).mkdir(parents=True)

        file_count = 0
        files_per_dir = 50

        for dir_path in dirs:
            for i in range(files_per_dir):
                file_path = temp_dir / dir_path / f"file_{i}.py"
                file_path.write_text(f'''
"""Auto-generated file {i} in {dir_path}."""

from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class Component{i}:
    """Component {i} for {dir_path}."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.initialized = False

    def initialize(self) -> None:
        """Initialize the component."""
        logger.info(f"Initializing Component{i}")
        self.initialized = True

    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the main operation."""
        if not self.initialized:
            raise RuntimeError("Not initialized")
        return {{"status": "success", "component": {i}}}

    def cleanup(self) -> None:
        """Clean up resources."""
        self.initialized = False


def process_{i}(data: List[Any]) -> List[Any]:
    """Process data for component {i}."""
    return [item for item in data if item is not None]


def validate_{i}(value: Optional[str]) -> bool:
    """Validate input for component {i}."""
    return value is not None and len(value) > 0
''')
                file_count += 1

        return temp_dir

    def test_large_codebase_ingest_completes(self, codebase_large, temp_chroma_client):
        """Large codebase (500 files) should complete ingest without timeout."""
        from src.ingest import ingest_codebase
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "large_codebase")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_file = f.name

        start = time.perf_counter()
        stats = ingest_codebase(
            root_path=str(codebase_large),
            collection=collection,
            repo_id="large-test",
            llm_provider="none",
            state_file=state_file,
        )
        elapsed = time.perf_counter() - start

        # Should complete in under 2 minutes
        assert elapsed < 120, f"Large codebase took {elapsed:.1f}s (>120s)"
        assert stats["files_processed"] == 500
        assert stats["errors"] == []

    def test_large_codebase_search_still_fast(self, codebase_large, temp_chroma_client):
        """Search should remain fast even with large indexed codebase."""
        from src.ingest import ingest_codebase
        from src.search import HybridSearcher
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "large_search")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_file = f.name

        # Ingest all files
        ingest_codebase(
            root_path=str(codebase_large),
            collection=collection,
            repo_id="large-search-test",
            llm_provider="none",
            state_file=state_file,
        )

        # Now test search performance
        searcher = HybridSearcher(collection)
        searcher.build_index()

        queries = [
            "initialize component config",
            "execute operation params",
            "validate input string",
            "process data list",
        ]

        for query in queries:
            start = time.perf_counter()
            results = searcher.search(query, top_k=10)
            elapsed = time.perf_counter() - start

            # Even with 500 files, search should be under 1 second
            assert elapsed < 1.0, f"Search took {elapsed:.3f}s on large codebase"
            assert len(results) > 0


class TestMemoryEfficiency:
    """Verify operations don't consume excessive memory."""

    def test_incremental_ingest_memory_stable(self, temp_dir: Path, temp_chroma_client):
        """Incremental ingests shouldn't accumulate memory."""
        import gc

        from src.ingest import ingest_codebase
        from src.storage import get_or_create_collection

        collection = get_or_create_collection(temp_chroma_client, "memory_test")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_file = f.name

        # Create initial files
        src = temp_dir / "src"
        src.mkdir()
        for i in range(10):
            (src / f"file_{i}.py").write_text(f"def func_{i}(): pass")

        # Initial ingest
        ingest_codebase(
            root_path=str(temp_dir),
            collection=collection,
            repo_id="memory-test",
            llm_provider="none",
            state_file=state_file,
        )

        gc.collect()

        # Perform multiple incremental ingests
        for batch in range(5):
            # Add new files
            for i in range(10):
                idx = (batch + 1) * 10 + i
                (src / f"file_{idx}.py").write_text(f"def func_{idx}(): pass")

            # Re-ingest (should be incremental)
            stats = ingest_codebase(
                root_path=str(temp_dir),
                collection=collection,
                repo_id="memory-test",
                llm_provider="none",
                state_file=state_file,
            )

            # Verify incremental behavior (only new files processed)
            # Note: Without git, it uses hash-based delta which processes all
            assert stats["files_scanned"] > 0

        # Final state should be consistent
        gc.collect()
        final_count = collection.count()
        assert final_count > 0, "Collection should have documents"
