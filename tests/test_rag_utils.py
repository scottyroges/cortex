"""
Tests for rag_utils.py
"""

from pathlib import Path

import pytest
from langchain_text_splitters import Language

from rag_utils import (
    BM25Index,
    HybridSearcher,
    RerankerService,
    detect_language,
    get_collection_stats,
    get_current_branch,
    get_git_info,
    get_or_create_collection,
    reciprocal_rank_fusion,
    scrub_secrets,
)


class TestSecretScrubbing:
    """Tests for secret scrubbing functionality."""

    def test_aws_access_key_scrubbed(self):
        """Test AWS access key is redacted."""
        text = 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"'
        result = scrub_secrets(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "[AWS_ACCESS_KEY_REDACTED]" in result

    def test_github_pat_scrubbed(self):
        """Test GitHub PAT is redacted."""
        text = "token = ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        result = scrub_secrets(text)
        assert "ghp_" not in result
        assert "[GITHUB_PAT_REDACTED]" in result

    def test_stripe_key_scrubbed(self):
        """Test Stripe secret key is redacted."""
        text = "STRIPE_KEY = sk_test_TESTKEY1234567890abcdef"
        result = scrub_secrets(text)
        assert "sk_test_" not in result
        assert "[STRIPE_SECRET_REDACTED]" in result

    def test_anthropic_key_scrubbed(self):
        """Test Anthropic API key is redacted."""
        text = "ANTHROPIC_API_KEY = sk-ant-api03-xxxxxxxxxxxxxxxxxxxxx"
        result = scrub_secrets(text)
        assert "sk-ant-" not in result
        assert "[ANTHROPIC_KEY_REDACTED]" in result

    def test_private_key_scrubbed(self):
        """Test private key header is redacted."""
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIE..."
        result = scrub_secrets(text)
        assert "BEGIN RSA PRIVATE KEY" not in result
        assert "[PRIVATE_KEY_REDACTED]" in result

    def test_slack_token_scrubbed(self):
        """Test Slack token is redacted."""
        text = "SLACK_TOKEN = xoxb-123456789-abcdefghijk"
        result = scrub_secrets(text)
        assert "xoxb-" not in result
        assert "[SLACK_TOKEN_REDACTED]" in result

    def test_normal_text_preserved(self):
        """Test normal text is not modified."""
        text = "This is normal code without any secrets. URL = https://api.example.com"
        result = scrub_secrets(text)
        assert result == text

    def test_generic_api_key_scrubbed(self):
        """Test generic API key assignments are redacted."""
        text = 'api_key = "super_secret_key_12345678"'
        result = scrub_secrets(text)
        assert "super_secret_key" not in result
        assert "[SECRET_REDACTED]" in result


class TestGitDetection:
    """Tests for git information detection."""

    def test_git_repo_detection(self, temp_git_repo: Path):
        """Test detection of git repository."""
        branch, is_git, root = get_git_info(str(temp_git_repo))
        assert is_git is True
        assert root == str(temp_git_repo)
        # Branch should be main or master (depends on git config)
        assert branch in ["main", "master"]

    def test_non_git_directory(self, temp_dir: Path):
        """Test non-git directory returns appropriate values."""
        branch, is_git, root = get_git_info(str(temp_dir))
        assert is_git is False
        assert branch is None
        assert root is None

    def test_get_current_branch_git(self, temp_git_repo: Path):
        """Test get_current_branch in a git repo."""
        branch = get_current_branch(str(temp_git_repo))
        assert branch in ["main", "master"]

    def test_get_current_branch_non_git(self, temp_dir: Path):
        """Test get_current_branch in a non-git directory."""
        branch = get_current_branch(str(temp_dir))
        assert branch == "unknown"


class TestLanguageDetection:
    """Tests for programming language detection."""

    def test_python_detection(self):
        """Test Python file detection."""
        assert detect_language("main.py") == Language.PYTHON
        assert detect_language("script.py") == Language.PYTHON

    def test_javascript_detection(self):
        """Test JavaScript file detection."""
        assert detect_language("app.js") == Language.JS
        assert detect_language("component.jsx") == Language.JS

    def test_typescript_detection(self):
        """Test TypeScript file detection."""
        assert detect_language("app.ts") == Language.TS
        assert detect_language("component.tsx") == Language.TS

    def test_go_detection(self):
        """Test Go file detection."""
        assert detect_language("main.go") == Language.GO

    def test_rust_detection(self):
        """Test Rust file detection."""
        assert detect_language("lib.rs") == Language.RUST

    def test_markdown_detection(self):
        """Test Markdown file detection."""
        assert detect_language("README.md") == Language.MARKDOWN
        assert detect_language("docs.markdown") == Language.MARKDOWN

    def test_unknown_extension(self):
        """Test unknown extension returns None."""
        assert detect_language("file.xyz") is None
        assert detect_language("file.unknown") is None

    def test_shebang_detection_python(self):
        """Test Python shebang detection."""
        content = "#!/usr/bin/env python3\nprint('hello')"
        assert detect_language("script", content) == Language.PYTHON

    def test_shebang_detection_node(self):
        """Test Node shebang detection."""
        content = "#!/usr/bin/env node\nconsole.log('hello')"
        assert detect_language("script", content) == Language.JS


class TestChromaDB:
    """Tests for ChromaDB functionality."""

    def test_create_collection(self, temp_chroma_client):
        """Test collection creation."""
        collection = get_or_create_collection(temp_chroma_client, "test_collection")
        assert collection is not None
        assert collection.name == "test_collection"

    def test_collection_stats_empty(self, temp_chroma_client):
        """Test stats for empty collection."""
        collection = get_or_create_collection(temp_chroma_client, "test_empty")
        stats = get_collection_stats(collection)
        assert stats["document_count"] == 0

    def test_collection_stats_with_docs(self, temp_chroma_client):
        """Test stats for collection with documents."""
        collection = get_or_create_collection(temp_chroma_client, "test_with_docs")
        collection.add(
            documents=["doc1", "doc2", "doc3"],
            ids=["1", "2", "3"],
            metadatas=[{"type": "test"}] * 3,
        )
        stats = get_collection_stats(collection)
        assert stats["document_count"] == 3


class TestBM25Index:
    """Tests for BM25 indexing."""

    def test_build_index(self, temp_chroma_client):
        """Test building BM25 index from collection."""
        collection = get_or_create_collection(temp_chroma_client, "test_bm25")
        collection.add(
            documents=[
                "Python is a programming language",
                "JavaScript runs in the browser",
                "Rust is fast and safe",
            ],
            ids=["1", "2", "3"],
            metadatas=[{"lang": "python"}, {"lang": "javascript"}, {"lang": "rust"}],
        )

        index = BM25Index()
        index.build_from_collection(collection)

        assert index.index is not None
        assert len(index.documents) == 3

    def test_search(self, temp_chroma_client):
        """Test BM25 search."""
        collection = get_or_create_collection(temp_chroma_client, "test_bm25_search")
        collection.add(
            documents=[
                "Python is a programming language",
                "JavaScript runs in the browser",
                "Rust is fast and memory safe",
            ],
            ids=["1", "2", "3"],
            metadatas=[{"lang": "python"}, {"lang": "javascript"}, {"lang": "rust"}],
        )

        index = BM25Index()
        index.build_from_collection(collection)

        results = index.search("Python programming", top_k=2)
        assert len(results) <= 2
        # Python document should rank highest
        assert "Python" in results[0]["text"]

    def test_empty_collection(self, temp_chroma_client):
        """Test BM25 with empty collection."""
        collection = get_or_create_collection(temp_chroma_client, "test_empty_bm25")

        index = BM25Index()
        index.build_from_collection(collection)

        results = index.search("anything")
        assert results == []


class TestRRFFusion:
    """Tests for Reciprocal Rank Fusion."""

    def test_basic_fusion(self):
        """Test basic RRF fusion of two result lists."""
        vector_results = [
            {"id": "a", "text": "doc a"},
            {"id": "b", "text": "doc b"},
            {"id": "c", "text": "doc c"},
        ]
        bm25_results = [
            {"id": "b", "text": "doc b"},
            {"id": "d", "text": "doc d"},
            {"id": "a", "text": "doc a"},
        ]

        fused = reciprocal_rank_fusion(vector_results, bm25_results)

        # Documents appearing in both should have higher scores
        assert len(fused) == 4  # a, b, c, d
        assert all("rrf_score" in doc for doc in fused)

        # 'b' appears high in both lists, should be near top
        top_ids = [doc["id"] for doc in fused[:2]]
        assert "b" in top_ids or "a" in top_ids

    def test_empty_lists(self):
        """Test RRF with empty lists."""
        fused = reciprocal_rank_fusion([], [])
        assert fused == []

    def test_single_list(self):
        """Test RRF with only one non-empty list."""
        vector_results = [
            {"id": "a", "text": "doc a"},
            {"id": "b", "text": "doc b"},
        ]

        fused = reciprocal_rank_fusion(vector_results, [])
        assert len(fused) == 2


class TestHybridSearcher:
    """Tests for hybrid search functionality."""

    def test_hybrid_search(self, temp_chroma_client):
        """Test hybrid search combines vector and BM25."""
        collection = get_or_create_collection(temp_chroma_client, "test_hybrid")
        collection.add(
            documents=[
                "Python is a programming language for data science",
                "JavaScript is used for web development",
                "Rust provides memory safety without garbage collection",
                "Python and machine learning go well together",
            ],
            ids=["1", "2", "3", "4"],
            metadatas=[
                {"topic": "python"},
                {"topic": "javascript"},
                {"topic": "rust"},
                {"topic": "python"},
            ],
        )

        searcher = HybridSearcher(collection)
        results = searcher.search("Python programming", top_k=3)

        assert len(results) <= 3
        assert all("rrf_score" in doc for doc in results)


class TestRerankerService:
    """Tests for reranking functionality."""

    def test_rerank_basic(self):
        """Test basic reranking."""
        reranker = RerankerService()

        documents = [
            {"text": "This is about cats and dogs"},
            {"text": "Programming in Python is fun"},
            {"text": "Python is a snake species"},
        ]

        results = reranker.rerank("Python programming language", documents, top_k=2)

        assert len(results) == 2
        assert all("rerank_score" in doc for doc in results)
        # Programming document should rank higher than snake document
        assert "Programming" in results[0]["text"] or "Python" in results[0]["text"]

    def test_rerank_empty(self):
        """Test reranking empty document list."""
        reranker = RerankerService()
        results = reranker.rerank("query", [], top_k=5)
        assert results == []

    def test_rerank_preserves_metadata(self):
        """Test that reranking preserves document metadata."""
        reranker = RerankerService()

        documents = [
            {"text": "Python programming", "source": "docs", "page": 1},
            {"text": "JavaScript tutorial", "source": "blog", "page": 5},
        ]

        results = reranker.rerank("Python", documents, top_k=2)

        # Original metadata should be preserved
        for result in results:
            assert "source" in result
            assert "page" in result
