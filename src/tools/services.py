"""
Shared Services

Lazy-initialized services shared across all tools.
"""

import os
from typing import Optional

import chromadb
from anthropic import Anthropic

from src.config import DEFAULT_CONFIG
from src.search import HybridSearcher, RerankerService
from src.storage import get_chroma_client, get_or_create_collection

# --- Lazy-initialized Services ---

_chroma_client: Optional[chromadb.PersistentClient] = None
_collection: Optional[chromadb.Collection] = None
_hybrid_searcher: Optional[HybridSearcher] = None
_reranker: Optional[RerankerService] = None
_anthropic_client: Optional[Anthropic] = None

# Runtime configuration (mutable)
CONFIG = DEFAULT_CONFIG.copy()


def get_collection() -> chromadb.Collection:
    """Lazy initialization of ChromaDB collection."""
    global _chroma_client, _collection
    if _collection is None:
        _chroma_client = get_chroma_client()
        _collection = get_or_create_collection(_chroma_client)
    return _collection


def get_searcher() -> HybridSearcher:
    """Lazy initialization of hybrid searcher."""
    global _hybrid_searcher
    if _hybrid_searcher is None:
        _hybrid_searcher = HybridSearcher(get_collection())
    return _hybrid_searcher


def get_reranker() -> RerankerService:
    """Lazy initialization of reranker."""
    global _reranker
    if _reranker is None:
        _reranker = RerankerService()
    return _reranker


def get_anthropic() -> Optional[Anthropic]:
    """Lazy initialization of Anthropic client."""
    global _anthropic_client
    if _anthropic_client is None and os.environ.get("ANTHROPIC_API_KEY"):
        _anthropic_client = Anthropic()
    return _anthropic_client
