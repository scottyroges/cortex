"""
Shared Services

Thread-safe lazy-initialized services shared across all tools and HTTP endpoints.
Uses singleton pattern with double-checked locking for thread safety.
"""

import os
from threading import RLock
from typing import TYPE_CHECKING, Optional

import chromadb
from anthropic import Anthropic

from src.configs.runtime import get_full_config
from src.external.git import is_git_repo
from src.storage import get_chroma_client, get_or_create_collection

# Use TYPE_CHECKING to avoid circular imports at runtime
if TYPE_CHECKING:
    from src.tools.search.hybrid import HybridSearcher
    from src.tools.search.reranker import RerankerService


def get_repo_path() -> Optional[str]:
    """
    Get repository path from current working directory.

    Used by tools to detect the actual repo path for branch detection,
    instead of hardcoding /projects.

    Returns:
        Repository path if cwd is a git repo, None otherwise
    """
    cwd = os.getcwd()
    return cwd if is_git_repo(cwd) else None


class ServiceManager:
    """
    Thread-safe singleton manager for all shared services.

    Provides lazy initialization of ChromaDB client, collection,
    hybrid searcher, reranker, and Anthropic client - ensuring
    each is created only once even under concurrent access.
    """

    _instance: Optional["ServiceManager"] = None
    _lock = RLock()

    def __new__(cls) -> "ServiceManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self._client: Optional[chromadb.PersistentClient] = None
        self._collection: Optional[chromadb.Collection] = None
        self._searcher: Optional["HybridSearcher"] = None
        self._reranker: Optional["RerankerService"] = None
        self._anthropic: Optional[Anthropic] = None
        self._resource_lock = RLock()
        self._initialized = True

    @property
    def collection(self) -> chromadb.Collection:
        """Get or create the ChromaDB collection."""
        if self._collection is None:
            with self._resource_lock:
                if self._collection is None:
                    self._client = get_chroma_client()
                    self._collection = get_or_create_collection(self._client)
        return self._collection

    @property
    def searcher(self) -> "HybridSearcher":
        """Get or create the hybrid searcher."""
        if self._searcher is None:
            with self._resource_lock:
                if self._searcher is None:
                    from src.tools.search.hybrid import HybridSearcher

                    self._searcher = HybridSearcher(self.collection)
        return self._searcher

    @property
    def reranker(self) -> "RerankerService":
        """Get or create the reranker."""
        if self._reranker is None:
            with self._resource_lock:
                if self._reranker is None:
                    from src.tools.search.reranker import RerankerService

                    self._reranker = RerankerService()
        return self._reranker

    @property
    def anthropic(self) -> Optional[Anthropic]:
        """Get or create the Anthropic client (if API key available)."""
        if self._anthropic is None and os.environ.get("ANTHROPIC_API_KEY"):
            with self._resource_lock:
                if self._anthropic is None and os.environ.get("ANTHROPIC_API_KEY"):
                    self._anthropic = Anthropic()
        return self._anthropic

    @property
    def chromadb_client(self) -> chromadb.PersistentClient:
        """Get the ChromaDB client directly."""
        if self._client is None:
            with self._resource_lock:
                if self._client is None:
                    self._client = get_chroma_client()
        return self._client

    def reset(self) -> None:
        """Reset all services (for testing)."""
        with self._resource_lock:
            self._client = None
            self._collection = None
            self._searcher = None
            self._reranker = None
            self._anthropic = None

    def set_collection(self, collection: chromadb.Collection) -> None:
        """Set collection directly (for testing)."""
        with self._resource_lock:
            self._collection = collection
            self._searcher = None  # Reset searcher to use new collection


# Module-level singleton instance
_services = ServiceManager()

# Runtime configuration (mutable)
CONFIG = get_full_config()


# --- Public API ---


def get_collection() -> chromadb.Collection:
    """Get the ChromaDB collection."""
    return _services.collection


def get_searcher() -> "HybridSearcher":
    """Get the hybrid searcher."""
    return _services.searcher


def get_reranker() -> "RerankerService":
    """Get the reranker."""
    return _services.reranker


def get_anthropic() -> Optional[Anthropic]:
    """Get the Anthropic client (if API key available)."""
    return _services.anthropic


def get_chromadb_client() -> chromadb.PersistentClient:
    """Get the ChromaDB client directly."""
    return _services.chromadb_client


def reset_services() -> None:
    """Reset all lazy-initialized services (for testing)."""
    _services.reset()


def set_collection(collection: chromadb.Collection) -> None:
    """Set the collection directly (for testing)."""
    _services.set_collection(collection)


# Backward compatibility alias
reset_resources = reset_services
