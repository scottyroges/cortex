"""
Ingest Tool

MCP tool for ingesting codebases into Cortex.
"""

import json
import time
from typing import Optional

from logging_config import get_logger
from src.ingest import ingest_codebase
from src.tools.services import CONFIG, get_anthropic, get_collection, get_searcher

logger = get_logger("tools.ingest")


def ingest_code_into_cortex(
    path: str,
    repository: Optional[str] = None,
    force_full: bool = False,
    include_patterns: Optional[list[str]] = None,
    use_cortexignore: bool = True,
) -> str:
    """
    Ingest a codebase directory into Cortex memory.

    Performs AST-aware chunking, secret scrubbing, and delta sync
    (only processes changed files unless force_full=True).

    Args:
        path: Absolute path to the codebase root directory
        repository: Optional repository identifier (defaults to directory name)
        force_full: Force full re-ingestion, ignoring delta sync
        include_patterns: If provided, only files matching at least one glob pattern are indexed.
                          Patterns are relative to path (e.g., ["src/**", "tests/**"])
        use_cortexignore: If True (default), load ignore patterns from global ~/.cortex/cortexignore
                          and project .cortexignore files

    Returns:
        JSON with ingestion statistics
    """
    logger.info(f"Ingesting codebase: path={path}, repository={repository}, force_full={force_full}, include_patterns={include_patterns}")
    start_time = time.time()

    try:
        collection = get_collection()
        anthropic = get_anthropic() if CONFIG["llm_provider"] == "anthropic" else None

        stats = ingest_codebase(
            root_path=path,
            collection=collection,
            repo_id=repository,
            anthropic_client=anthropic,
            force_full=force_full,
            llm_provider=CONFIG["llm_provider"],
            include_patterns=include_patterns,
            use_cortexignore=use_cortexignore,
        )

        # Rebuild search index after ingestion
        get_searcher().build_index()

        total_time = time.time() - start_time
        logger.info(f"Ingestion complete: {stats.get('files_processed', 0)} files, {stats.get('chunks_created', 0)} chunks in {total_time:.1f}s")

        return json.dumps({
            "status": "success",
            "path": path,
            "stats": stats,
        }, indent=2)

    except Exception as e:
        logger.error(f"Ingestion error: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e),
            "path": path,
        })
