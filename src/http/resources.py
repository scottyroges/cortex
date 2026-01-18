"""
HTTP Resource Manager

Thread-safe lazy initialization of shared resources for HTTP endpoints.
Consolidates resource management from api.py and browse.py.
"""

from threading import RLock
from typing import Optional

from src.search import HybridSearcher, RerankerService
from src.storage import get_chroma_client, get_or_create_collection


class ResourceManager:
    """
    Thread-safe singleton manager for shared HTTP resources.

    Provides lazy initialization of ChromaDB client, collection,
    hybrid searcher, and reranker - ensuring each is created only once.
    """

    _instance: Optional["ResourceManager"] = None
    _lock = RLock()

    def __new__(cls) -> "ResourceManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self._client = None
        self._collection = None
        self._searcher = None
        self._reranker = None
        self._resource_lock = RLock()
        self._initialized = True

    @property
    def collection(self):
        """Get or create the ChromaDB collection."""
        if self._collection is None:
            with self._resource_lock:
                if self._collection is None:
                    self._client = get_chroma_client()
                    self._collection = get_or_create_collection(self._client)
        return self._collection

    @property
    def searcher(self) -> HybridSearcher:
        """Get or create the hybrid searcher."""
        if self._searcher is None:
            with self._resource_lock:
                if self._searcher is None:
                    self._searcher = HybridSearcher(self.collection)
        return self._searcher

    @property
    def reranker(self) -> RerankerService:
        """Get or create the reranker."""
        if self._reranker is None:
            with self._resource_lock:
                if self._reranker is None:
                    self._reranker = RerankerService()
        return self._reranker

    def reset(self) -> None:
        """Reset all resources (useful for testing)."""
        with self._resource_lock:
            self._client = None
            self._collection = None
            self._searcher = None
            self._reranker = None
            # Note: _initialized stays True so __init__ doesn't run again,
            # but all resources are cleared for lazy re-initialization


# Module-level singleton instance
_resources = ResourceManager()


def get_collection():
    """Get the ChromaDB collection."""
    return _resources.collection


def get_searcher() -> HybridSearcher:
    """Get the hybrid searcher."""
    return _resources.searcher


def get_reranker() -> RerankerService:
    """Get the reranker."""
    return _resources.reranker


def reset_resources() -> None:
    """Reset all resources."""
    _resources.reset()
