"""
Type-Based Scoring

Apply score multipliers based on document type to prioritize
understanding (insights, notes, commits) over code.

Philosophy: "Code can be grepped. Understanding cannot."
"""

from typing import Any


# Default type multipliers
# Insights are most valuable (unique understanding tied to code)
# Notes and commits capture decisions and context
# Code is indexed but less valuable than native grep/glob
DEFAULT_TYPE_MULTIPLIERS = {
    "insight": 2.0,
    "note": 1.5,
    "commit": 1.5,
    "code": 1.0,
    "skeleton": 1.0,
    "tech_stack": 1.2,
    "initiative": 1.0,
}


def apply_type_boost(
    results: list[dict[str, Any]],
    multipliers: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """
    Apply type-based score multipliers to search results.

    Understanding-type documents (insights, notes, commits) are boosted
    over code chunks to surface semantic memory first.

    Args:
        results: List of results with 'rerank_score' or 'boosted_score' and 'meta'
        multipliers: Custom type multipliers (uses defaults if None)

    Returns:
        Results with adjusted scores, re-sorted by boosted score
    """
    if not results:
        return results

    if multipliers is None:
        multipliers = DEFAULT_TYPE_MULTIPLIERS

    boosted_results = []

    for result in results:
        meta = result.get("meta", {})
        doc_type = meta.get("type", "code")  # Default to "code" if unknown

        # Get the current score (may have recency boost already applied)
        current_score = result.get("boosted_score", result.get("rerank_score", 0))

        # Get multiplier for this type (default to 1.0 for unknown types)
        type_multiplier = multipliers.get(doc_type, 1.0)

        boosted_score = current_score * type_multiplier

        boosted_results.append({
            **result,
            "boosted_score": boosted_score,
            "type_boost": type_multiplier,
        })

    # Re-sort by boosted score
    boosted_results.sort(key=lambda x: x.get("boosted_score", 0), reverse=True)

    return boosted_results
