"""
Hybrid Search with RRF Fusion

Combines vector search and BM25 using Reciprocal Rank Fusion.
"""

import time
from typing import Any, Optional

import chromadb

from logging_config import get_logger
from src.search.bm25 import BM25Index

logger = get_logger("search.hybrid")


def reciprocal_rank_fusion(
    vector_results: list[dict[str, Any]],
    bm25_results: list[dict[str, Any]],
    k: int = 60,
) -> list[dict[str, Any]]:
    """
    Combine vector and BM25 results using Reciprocal Rank Fusion.

    RRF score = sum(1 / (k + rank)) for each result list

    Args:
        vector_results: Results from vector search
        bm25_results: Results from BM25 search
        k: RRF constant (default 60)

    Returns:
        Combined results sorted by RRF score
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
        """
        Build/rebuild the BM25 index.

        Args:
            where_filter: Optional filter for documents
        """
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

        Returns:
            Combined results with RRF scores
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
                        "vector_distance": float(dist),
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

        # Limit to top_k results
        return fused[:top_k]
