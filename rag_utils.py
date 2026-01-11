"""
Cortex RAG Utilities

Core utilities for the Cortex MCP server including:
- Secret scrubbing
- Git branch detection
- Language detection for AST chunking
- ChromaDB initialization
- BM25 keyword indexing
- Hybrid search with RRF fusion
- FlashRank reranking
"""

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import chromadb
from chromadb.config import Settings
from flashrank import Ranker, RerankRequest
from langchain_text_splitters import Language
from rank_bm25 import BM25Okapi

from logging_config import get_logger

logger = get_logger("rag")

# --- Secret Scrubbing ---

SECRET_PATTERNS: list[tuple[str, str]] = [
    # AWS
    (r"AKIA[0-9A-Z]{16}", "[AWS_ACCESS_KEY_REDACTED]"),
    (r"(?i)aws[_-]?secret[_-]?access[_-]?key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?", "[AWS_SECRET_REDACTED]"),
    # GitHub
    (r"ghp_[a-zA-Z0-9]{36}", "[GITHUB_PAT_REDACTED]"),
    (r"gho_[a-zA-Z0-9]{36}", "[GITHUB_OAUTH_REDACTED]"),
    (r"ghu_[a-zA-Z0-9]{36}", "[GITHUB_USER_REDACTED]"),
    (r"ghs_[a-zA-Z0-9]{36}", "[GITHUB_SERVER_REDACTED]"),
    (r"ghr_[a-zA-Z0-9]{36}", "[GITHUB_REFRESH_REDACTED]"),
    # Stripe
    (r"sk_(live|test)_[0-9a-zA-Z]{24,}", "[STRIPE_SECRET_REDACTED]"),
    (r"pk_(live|test)_[0-9a-zA-Z]{24,}", "[STRIPE_PUBLIC_REDACTED]"),
    # Slack
    (r"xox[bapors]-[0-9a-zA-Z\-]{10,}", "[SLACK_TOKEN_REDACTED]"),
    # Private keys
    (r"-----BEGIN (RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY-----", "[PRIVATE_KEY_REDACTED]"),
    # Anthropic
    (r"sk-ant-[a-zA-Z0-9\-]{20,}", "[ANTHROPIC_KEY_REDACTED]"),
    # OpenAI
    (r"sk-[a-zA-Z0-9]{48}", "[OPENAI_KEY_REDACTED]"),
    # Generic API keys/secrets in assignments
    (
        r'(?i)["\']?(?:api[_-]?key|secret|password|token|auth)["\']?\s*[:=]\s*["\'][^"\']{8,}["\']',
        "[SECRET_REDACTED]",
    ),
]


def scrub_secrets(text: str) -> str:
    """Remove sensitive data from text before embedding."""
    for pattern, replacement in SECRET_PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


# --- Git Detection ---


def get_git_info(path: str) -> tuple[Optional[str], bool, Optional[str]]:
    """
    Get git information for a path.

    Returns:
        (branch_name, is_git_repo, repo_root)
    """
    try:
        # Check if in a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None, False, None

        # Get current branch
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )

        # Get repo root
        root_result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )

        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
        repo_root = root_result.stdout.strip() if root_result.returncode == 0 else None

        return branch, True, repo_root
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None, False, None


def get_current_branch(path: str) -> str:
    """Get current git branch, or 'unknown' if not a git repo."""
    branch, is_git, _ = get_git_info(path)
    return branch if branch else "unknown"


# --- Language Detection ---

EXTENSION_TO_LANGUAGE: dict[str, Language] = {
    ".py": Language.PYTHON,
    ".js": Language.JS,
    ".jsx": Language.JS,
    ".ts": Language.TS,
    ".tsx": Language.TS,
    ".java": Language.JAVA,
    ".go": Language.GO,
    ".rs": Language.RUST,
    ".rb": Language.RUBY,
    ".php": Language.PHP,
    ".cpp": Language.CPP,
    ".cc": Language.CPP,
    ".cxx": Language.CPP,
    ".c": Language.C,
    ".h": Language.C,
    ".hpp": Language.CPP,
    ".cs": Language.CSHARP,
    ".swift": Language.SWIFT,
    ".kt": Language.KOTLIN,
    ".kts": Language.KOTLIN,
    ".scala": Language.SCALA,
    ".md": Language.MARKDOWN,
    ".markdown": Language.MARKDOWN,
    ".html": Language.HTML,
    ".htm": Language.HTML,
    ".sol": Language.SOL,
    ".lua": Language.LUA,
    ".hs": Language.HASKELL,
    ".ex": Language.ELIXIR,
    ".exs": Language.ELIXIR,
}


def detect_language(file_path: str, content: Optional[str] = None) -> Optional[Language]:
    """
    Detect programming language from file extension or shebang.

    Args:
        file_path: Path to the file
        content: Optional file content for shebang detection
    """
    # Check extension first
    ext = Path(file_path).suffix.lower()
    lang = EXTENSION_TO_LANGUAGE.get(ext)

    # If no match and content provided, check shebang
    if not lang and content and content.startswith("#!"):
        first_line = content.split("\n")[0].lower()
        if "python" in first_line:
            return Language.PYTHON
        if "node" in first_line or "deno" in first_line:
            return Language.JS
        if "ruby" in first_line:
            return Language.RUBY
        if "bash" in first_line or "sh" in first_line:
            return None  # Shell scripts don't have good AST support

    return lang


# --- ChromaDB Initialization ---


def get_default_db_path() -> str:
    """Get the default database path, expanding ~ to home directory."""
    env_path = os.environ.get("CORTEX_DB_PATH")
    if env_path:
        return os.path.expanduser(env_path)
    # Default: ~/.cortex/db (or /app/cortex_db in Docker)
    if os.path.exists("/app") and os.access("/app", os.W_OK):
        return "/app/cortex_db"
    return os.path.expanduser("~/.cortex/db")


DB_PATH = get_default_db_path()


def get_chroma_client(persist_dir: Optional[str] = None) -> chromadb.PersistentClient:
    """Initialize persistent ChromaDB client."""
    path = persist_dir or DB_PATH
    path = os.path.expanduser(path)
    # Ensure directory exists
    os.makedirs(path, exist_ok=True)
    return chromadb.PersistentClient(
        path=path,
        settings=Settings(anonymized_telemetry=False),
    )


def get_or_create_collection(
    client: chromadb.PersistentClient,
    name: str = "cortex_memory",
) -> chromadb.Collection:
    """Get or create the main collection with cosine similarity."""
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


# --- BM25 Index ---


class BM25Index:
    """BM25 keyword index for hybrid search."""

    def __init__(self):
        self.index: Optional[BM25Okapi] = None
        self.documents: list[dict[str, Any]] = []
        self.doc_ids: list[str] = []

    def build_from_collection(
        self,
        collection: chromadb.Collection,
        where_filter: Optional[dict] = None,
    ) -> None:
        """Build BM25 index from ChromaDB collection documents."""
        start_time = time.time()
        results = collection.get(
            where=where_filter,
            include=["documents", "metadatas"],
        )

        if not results["documents"]:
            self.index = None
            self.documents = []
            self.doc_ids = []
            logger.debug("BM25 index: empty collection")
            return

        self.doc_ids = results["ids"]
        self.documents = [
            {"id": doc_id, "text": doc, "meta": meta}
            for doc_id, doc, meta in zip(
                results["ids"],
                results["documents"],
                results["metadatas"],
            )
        ]

        # Tokenize for BM25
        tokenized = [doc.lower().split() for doc in results["documents"]]
        self.index = BM25Okapi(tokenized)
        elapsed = time.time() - start_time
        logger.debug(f"BM25 index built: {len(self.documents)} docs in {elapsed*1000:.1f}ms")

    def search(self, query: str, top_k: int = 50) -> list[dict[str, Any]]:
        """Search using BM25 and return scored documents."""
        if not self.index or not self.documents:
            return []

        tokens = query.lower().split()
        scores = self.index.get_scores(tokens)

        # Pair documents with scores and sort
        scored_docs = [
            {**doc, "bm25_score": float(score)}
            for doc, score in zip(self.documents, scores)
        ]
        scored_docs.sort(key=lambda x: x["bm25_score"], reverse=True)

        return scored_docs[:top_k]


# --- Hybrid Search with RRF ---


def reciprocal_rank_fusion(
    vector_results: list[dict[str, Any]],
    bm25_results: list[dict[str, Any]],
    k: int = 60,
) -> list[dict[str, Any]]:
    """
    Combine vector and BM25 results using Reciprocal Rank Fusion.

    RRF score = sum(1 / (k + rank)) for each result list
    """
    # Map document IDs to their RRF scores
    rrf_scores: dict[str, float] = {}
    doc_map: dict[str, dict[str, Any]] = {}

    # Process vector results
    for rank, doc in enumerate(vector_results, start=1):
        doc_id = doc.get("id", doc.get("doc_id", str(rank)))
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + 1 / (k + rank)
        doc_map[doc_id] = doc

    # Process BM25 results
    for rank, doc in enumerate(bm25_results, start=1):
        doc_id = doc.get("id", doc.get("doc_id", str(rank)))
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + 1 / (k + rank)
        if doc_id not in doc_map:
            doc_map[doc_id] = doc

    # Sort by RRF score and return
    sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)

    return [
        {**doc_map[doc_id], "rrf_score": rrf_scores[doc_id]}
        for doc_id in sorted_ids
        if doc_id in doc_map
    ]


class HybridSearcher:
    """Combines vector search with BM25 using RRF fusion."""

    def __init__(self, collection: chromadb.Collection):
        self.collection = collection
        self.bm25_index = BM25Index()
        self._index_built = False

    def build_index(self, where_filter: Optional[dict] = None) -> None:
        """Build/rebuild the BM25 index."""
        self.bm25_index.build_from_collection(self.collection, where_filter)
        self._index_built = True

    def search(
        self,
        query: str,
        top_k: int = 50,
        where_filter: Optional[dict] = None,
        rebuild_index: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Perform hybrid search combining vector and BM25 results.

        Args:
            query: Search query
            top_k: Number of results to return
            where_filter: Optional filter for ChromaDB
            rebuild_index: Force rebuild of BM25 index
        """
        # Rebuild index if needed
        if rebuild_index or not self._index_built:
            self.build_index(where_filter)

        # Vector search
        vector_start = time.time()
        vector_results = self.collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )
        vector_time = time.time() - vector_start

        # Format vector results
        formatted_vector = []
        if vector_results["documents"] and vector_results["documents"][0]:
            for doc_id, doc, meta, dist in zip(
                vector_results["ids"][0],
                vector_results["documents"][0],
                vector_results["metadatas"][0],
                vector_results["distances"][0],
            ):
                formatted_vector.append(
                    {
                        "id": doc_id,
                        "text": doc,
                        "meta": meta,
                        "vector_distance": float(dist),  # Convert potential numpy float
                    }
                )
        logger.debug(f"Vector search: {len(formatted_vector)} results in {vector_time*1000:.1f}ms")

        # BM25 search
        bm25_start = time.time()
        bm25_results = self.bm25_index.search(query, top_k=top_k)
        bm25_time = time.time() - bm25_start
        logger.debug(f"BM25 search: {len(bm25_results)} results in {bm25_time*1000:.1f}ms")

        # RRF fusion
        fused = reciprocal_rank_fusion(formatted_vector, bm25_results)
        logger.debug(f"RRF fusion: {len(fused)} unique docs")

        return fused


# --- FlashRank Reranker ---


class RerankerService:
    """Cross-encoder reranking using FlashRank."""

    def __init__(
        self,
        model_name: str = "ms-marco-MiniLM-L-12-v2",
        max_length: int = 512,
    ):
        self.ranker = Ranker(model_name=model_name, max_length=max_length)

    def rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Rerank documents using cross-encoder and return top_k results.

        Args:
            query: The search query
            documents: List of documents with 'text' or 'content' field
            top_k: Number of top results to return
        """
        if not documents:
            return []

        start_time = time.time()

        # Prepare passages for FlashRank
        passages = []
        for i, doc in enumerate(documents):
            text = doc.get("text", doc.get("content", ""))
            passages.append({"id": str(i), "text": text, "meta": doc})

        # Rerank
        request = RerankRequest(query=query, passages=passages)
        ranked = self.ranker.rerank(request)

        # Return top_k with scores
        results = []
        for r in ranked[:top_k]:
            original_doc = r["meta"]
            results.append(
                {
                    **original_doc,
                    "rerank_score": float(r["score"]),  # Convert numpy float32 to Python float
                }
            )

        elapsed = time.time() - start_time
        logger.debug(f"Reranking: {len(documents)} docs -> top {len(results)} in {elapsed*1000:.1f}ms")

        return results


# --- Collection Statistics ---


def get_collection_stats(collection: chromadb.Collection) -> dict[str, Any]:
    """Get statistics about the collection."""
    count = collection.count()
    return {
        "document_count": count,
        "estimated_memory_mb": count * 0.01,  # Rough estimate
    }
