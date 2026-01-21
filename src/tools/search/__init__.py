"""
Cortex Search

Hybrid search with BM25, vector similarity, RRF fusion, and reranking.
"""

from src.tools.search.bm25 import BM25Index, tokenize_code
from src.tools.search.filters import (
    INITIATIVE_BOOST_FACTOR,
    apply_initiative_boost,
    build_branch_aware_filter,
    filter_by_initiative,
)
from src.tools.search.hybrid import HybridSearcher, reciprocal_rank_fusion
from src.tools.search.pipeline import SearchPipeline
from src.tools.search.recency import apply_recency_boost
from src.tools.search.reranker import RerankerService
from src.tools.search.type_scoring import DEFAULT_TYPE_MULTIPLIERS, apply_type_boost

# Note: search_cortex is exported from src.tools.search.search
# Import it directly when needed to avoid circular imports with src.configs.services

__all__ = [
    # BM25
    "tokenize_code",
    "BM25Index",
    # Hybrid search
    "reciprocal_rank_fusion",
    "HybridSearcher",
    # Reranker
    "RerankerService",
    # Boosts
    "apply_recency_boost",
    "apply_type_boost",
    "DEFAULT_TYPE_MULTIPLIERS",
    # Filters
    "build_branch_aware_filter",
    "filter_by_initiative",
    "apply_initiative_boost",
    "INITIATIVE_BOOST_FACTOR",
    # Pipeline
    "SearchPipeline",
]
