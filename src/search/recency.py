"""
Recency Boosting

Apply time-based boosting to favor newer notes and session summaries.
"""

import math
from datetime import datetime, timezone
from typing import Any

from src.documents import RECENCY_BOOSTED_TYPES


def apply_recency_boost(
    results: list[dict[str, Any]],
    half_life_days: float = 30.0,
    min_boost: float = 0.5,
    boost_types: set[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Apply recency boost to search results based on timestamps.

    Uses exponential decay: boost = max(min_boost, e^(-age_days / half_life))

    Only applies to document types in boost_types (defaults to notes/session_summaries).
    Code chunks are NOT boosted - old code is not less relevant.

    Args:
        results: List of reranked results with 'rerank_score' and 'meta'
        half_life_days: Days until boost decays to ~0.5 (default 30)
        min_boost: Minimum boost factor to prevent old docs from disappearing (default 0.5)
        boost_types: Document types to boost (default: RECENCY_BOOSTED_TYPES)

    Returns:
        Results with adjusted scores, re-sorted by boosted score
    """
    if not results:
        return results

    if boost_types is None:
        boost_types = RECENCY_BOOSTED_TYPES

    now = datetime.now(timezone.utc)
    boosted_results = []

    for result in results:
        meta = result.get("meta", {})
        doc_type = meta.get("type", "")
        original_score = result.get("rerank_score", 0)

        # Only boost specified document types
        if doc_type not in boost_types:
            boosted_results.append({
                **result,
                "boosted_score": original_score,
                "recency_boost": 1.0,
            })
            continue

        # Get timestamp from metadata
        timestamp_str = meta.get("created_at") or meta.get("indexed_at")
        if not timestamp_str:
            # No timestamp - no boost applied
            boosted_results.append({
                **result,
                "boosted_score": original_score,
                "recency_boost": 1.0,
            })
            continue

        try:
            # Parse ISO 8601 timestamp
            doc_time = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            age_days = (now - doc_time).total_seconds() / 86400.0

            # Exponential decay: e^(-age / half_life)
            decay = math.exp(-age_days / half_life_days)
            recency_boost = max(min_boost, decay)

            boosted_score = original_score * recency_boost

            boosted_results.append({
                **result,
                "boosted_score": boosted_score,
                "recency_boost": round(recency_boost, 3),
            })

        except (ValueError, TypeError):
            # Invalid timestamp - no boost
            boosted_results.append({
                **result,
                "boosted_score": original_score,
                "recency_boost": 1.0,
            })

    # Re-sort by boosted score
    boosted_results.sort(key=lambda x: x.get("boosted_score", 0), reverse=True)

    return boosted_results
