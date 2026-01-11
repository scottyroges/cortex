"""
BM25 Keyword Search

BM25 index for keyword-based search with code-aware tokenization.
"""

import re
import time
from typing import Any, Optional

import chromadb
from rank_bm25 import BM25Okapi

from logging_config import get_logger

logger = get_logger("search.bm25")


def tokenize_code(text: str) -> list[str]:
    """
    Tokenize text for BM25, respecting code naming conventions.

    - Splits camelCase: "calculateTotal" -> ["calculate", "total"]
    - Splits snake_case: "calculate_total" -> ["calculate", "total"]
    - Splits on whitespace and punctuation
    - Lowercases all tokens
    - Filters empty tokens

    Args:
        text: Text to tokenize

    Returns:
        List of tokens
    """
    tokens = []
    # Split on whitespace and punctuation first
    words = re.split(r'[\s\.\,\;\:\(\)\[\]\{\}\"\'\`\#\@\!\?\<\>\=\+\-\*\/\\\|\&\^]+', text)
    for word in words:
        if not word:
            continue
        # Split camelCase: insert split before uppercase letters that follow lowercase
        camel_split = re.sub(r'([a-z])([A-Z])', r'\1_\2', word)
        # Now split on underscores
        sub_tokens = camel_split.lower().split('_')
        tokens.extend(t for t in sub_tokens if t)
    return tokens


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
        """
        Build BM25 index from ChromaDB collection documents.

        Args:
            collection: ChromaDB collection
            where_filter: Optional filter for documents
        """
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

        # Tokenize for BM25 (using code-aware tokenizer)
        tokenized = [tokenize_code(doc) for doc in results["documents"]]
        self.index = BM25Okapi(tokenized)
        elapsed = time.time() - start_time
        logger.debug(f"BM25 index built: {len(self.documents)} docs in {elapsed*1000:.1f}ms")

    def search(self, query: str, top_k: int = 50) -> list[dict[str, Any]]:
        """
        Search using BM25 and return scored documents.

        Args:
            query: Search query
            top_k: Number of results to return

        Returns:
            List of documents with bm25_score
        """
        if not self.index or not self.documents:
            return []

        tokens = tokenize_code(query)
        scores = self.index.get_scores(tokens)

        # Pair documents with scores and sort
        scored_docs = [
            {**doc, "bm25_score": float(score)}
            for doc, score in zip(self.documents, scores)
        ]
        scored_docs.sort(key=lambda x: x["bm25_score"], reverse=True)

        return scored_docs[:top_k]
