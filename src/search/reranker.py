"""
FlashRank Reranker

Cross-encoder reranking for improved search relevance.
"""

import time
from typing import Any

from flashrank import Ranker, RerankRequest

from logging_config import get_logger

logger = get_logger("search.reranker")


class RerankerService:
    """Cross-encoder reranking using FlashRank."""

    def __init__(
        self,
        model_name: str = "ms-marco-MiniLM-L-12-v2",
        max_length: int = 512,
    ):
        """
        Initialize the reranker service.

        Args:
            model_name: FlashRank model name
            max_length: Maximum sequence length
        """
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

        Returns:
            Top k documents with rerank_score added
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
                    "rerank_score": float(r["score"]),
                }
            )

        elapsed = time.time() - start_time
        logger.debug(f"Reranking: {len(documents)} docs -> top {len(results)} in {elapsed*1000:.1f}ms")

        return results
