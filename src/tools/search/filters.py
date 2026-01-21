"""
Search Filters and Initiative Boosting

ChromaDB filter builders and initiative-aware result filtering/boosting.
"""

from typing import Optional

from src.configs import get_logger
from src.models import BRANCH_FILTERED_TYPES, METADATA_ONLY_TYPES

logger = get_logger("search.filters")

# Initiative boost factor for focused initiative content
INITIATIVE_BOOST_FACTOR = 1.3


def build_branch_aware_filter(
    repository: Optional[str] = None,
    branches: Optional[list[str]] = None,
    types: Optional[list[str]] = None,
) -> Optional[dict]:
    """
    Build ChromaDB where filter that applies branch filtering
    only to code and skeleton documents.

    Notes, session_summaries, tech_stack, initiatives are never filtered by branch.

    Args:
        repository: Optional repository filter
        branches: List of branches to include for code/skeleton
        types: Optional list of document types to include

    Returns:
        ChromaDB where filter dict, or None if no filtering needed
    """
    # If explicit types requested, build type-aware filter
    if types:
        # Separate branch-filtered types from cross-branch types
        branch_types = [t for t in types if t in BRANCH_FILTERED_TYPES]
        non_branch_types = [t for t in types if t not in BRANCH_FILTERED_TYPES]

        # Build type filter with proper branch handling
        if branch_types and branches and branches != ["unknown"]:
            # Mix of branch-filtered and non-branch types
            conditions = []
            if branch_types:
                conditions.append({
                    "$and": [
                        {"type": {"$in": branch_types}},
                        {"branch": {"$in": branches}}
                    ]
                })
            if non_branch_types:
                conditions.append({"type": {"$in": non_branch_types}})

            type_filter = {"$or": conditions} if len(conditions) > 1 else conditions[0]
        else:
            # Only non-branch types, or no branch filtering needed
            type_filter = {"type": {"$in": types}}

        if repository:
            return {"$and": [{"repository": repository}, type_filter]}
        return type_filter

    # No type filter: use existing branch-aware logic
    if not branches or branches == ["unknown"]:
        # No branch filtering if unknown
        return {"repository": repository} if repository else None

    # Types filtered by branch: skeleton, file_metadata, data_contract, entry_point, dependency
    # Types NOT filtered: note, session_summary, tech_stack, initiative, insight
    branch_filter = {
        "$or": [
            # Code/metadata types: filter by branch
            {"$and": [
                {"type": {"$in": list(BRANCH_FILTERED_TYPES)}},
                {"branch": {"$in": branches}}
            ]},
            # Semantic memory types: always include (cross-branch)
            {"type": {"$in": ["note", "session_summary", "tech_stack", "initiative", "insight"]}}
        ]
    }

    if repository:
        return {"$and": [{"repository": repository}, branch_filter]}

    return branch_filter


def apply_initiative_boost(
    results: list,
    focused_initiative_id: str,
    boost_factor: float = INITIATIVE_BOOST_FACTOR,
) -> list:
    """Apply score boost to results from the focused initiative."""
    for result in results:
        meta = result.get("meta", {})
        if meta.get("initiative_id") == focused_initiative_id:
            current_score = result.get("boosted_score", result.get("rerank_score", 0))
            result["boosted_score"] = current_score * boost_factor
            result["initiative_boost"] = boost_factor

    # Re-sort by boosted_score
    return sorted(results, key=lambda x: x.get("boosted_score", x.get("rerank_score", 0)), reverse=True)


def filter_by_initiative(results: list, initiative_id: str, include_completed: bool = True) -> list:
    """Filter results to only include those from a specific initiative."""
    filtered = []
    for result in results:
        meta = result.get("meta", {})
        result_init_id = meta.get("initiative_id")

        # Include if matches initiative
        if result_init_id == initiative_id:
            filtered.append(result)
        # Include metadata types that aren't tagged (belong to whole repo)
        elif meta.get("type") in METADATA_ONLY_TYPES and not result_init_id:
            filtered.append(result)

    return filtered
