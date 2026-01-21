"""
Search Tool

MCP tool for searching Cortex memory.
"""

from typing import Optional

from src.configs import get_logger
from src.models import ALL_DOCUMENT_TYPES, SEARCH_PRESETS
from src.tools.search.pipeline import SearchPipeline

logger = get_logger("tools.search")


def search_cortex(
    query: str,
    repository: Optional[str] = None,
    min_score: Optional[float] = None,
    branch: Optional[str] = None,
    initiative: Optional[str] = None,
    include_completed: bool = True,
    types: Optional[list[str]] = None,
    preset: Optional[str] = None,
) -> str:
    """
    Search the Cortex memory for relevant code, documentation, or notes.

    Args:
        query: Natural language search query
        repository: Repository identifier for filtering
        min_score: Minimum relevance score threshold (0-1, overrides config)
        branch: Optional branch filter. Defaults to auto-detect from cwd.
                Metadata types are filtered by branch; notes/commits are not.
        initiative: Optional initiative ID or name to filter results
        include_completed: Include content from completed initiatives (default: True)
        types: Optional list of document types to include. Valid types:
               skeleton, note, session_summary, insight, tech_stack, initiative,
               file_metadata, data_contract, entry_point, dependency.
               Example: ["note", "insight"] for understanding-only search.
        preset: Optional search preset. Overrides types if provided.
               Valid presets:
               - "understanding": insights, notes, session_summaries (why questions)
               - "navigation": file_metadata, entry_points, data_contracts (where questions)
               - "structure": file_metadata, dependencies, skeleton
               - "trace": entry_points, dependencies, data_contracts (debugging)
               - "memory": all semantic memory types

    Returns:
        JSON with search results including content, file paths, and scores
    """
    # Apply preset if provided
    if preset:
        if preset in SEARCH_PRESETS:
            types = SEARCH_PRESETS[preset]
            logger.debug(f"Using preset '{preset}': {types}")
        else:
            logger.warning(f"Unknown preset '{preset}'. Valid: {list(SEARCH_PRESETS.keys())}")

    # Validate types if provided
    if types:
        valid_types_set = set(ALL_DOCUMENT_TYPES)
        invalid_types = set(types) - valid_types_set
        if invalid_types:
            logger.warning(f"Invalid types ignored: {invalid_types}. Valid: {ALL_DOCUMENT_TYPES}")
            types = [t for t in types if t in valid_types_set]
            if not types:
                types = None  # Fall back to no filtering if all invalid

    pipeline = SearchPipeline(
        query=query,
        repository=repository,
        min_score=min_score,
        branch=branch,
        initiative=initiative,
        include_completed=include_completed,
        types=types,
    )
    return pipeline.execute()
