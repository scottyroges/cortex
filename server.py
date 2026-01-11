"""
Cortex MCP Server

A local, privacy-first memory system for Claude Code.
Provides RAG capabilities with ChromaDB, FlashRank reranking, and AST-aware chunking.

Environment variables:
    CORTEX_DEBUG: Enable debug logging (default: false)
    CORTEX_LOG_FILE: Log file path (default: $CORTEX_DATA_PATH/cortex.log)
    CORTEX_HTTP: Enable HTTP server for debugging (default: false)
"""

import argparse
import json
import os
import threading
import time
from typing import Optional

from anthropic import Anthropic
from mcp.server.fastmcp import FastMCP

from ingest import ingest_codebase, ingest_files
from logging_config import get_logger, setup_logging
from rag_utils import (
    HybridSearcher,
    RerankerService,
    apply_recency_boost,
    get_chroma_client,
    get_collection_stats,
    get_current_branch,
    get_or_create_collection,
    scrub_secrets,
)

# Initialize logging
setup_logging()
logger = get_logger("server")

# --- Initialize MCP Server ---

mcp = FastMCP("Cortex")

# --- Initialize Services ---

# ChromaDB
_chroma_client = None
_collection = None
_hybrid_searcher = None
_reranker = None
_anthropic_client = None


def get_collection():
    """Lazy initialization of ChromaDB collection."""
    global _chroma_client, _collection
    if _collection is None:
        _chroma_client = get_chroma_client()
        _collection = get_or_create_collection(_chroma_client)
    return _collection


def get_searcher():
    """Lazy initialization of hybrid searcher."""
    global _hybrid_searcher
    if _hybrid_searcher is None:
        _hybrid_searcher = HybridSearcher(get_collection())
    return _hybrid_searcher


def get_reranker():
    """Lazy initialization of reranker."""
    global _reranker
    if _reranker is None:
        _reranker = RerankerService()
    return _reranker


def get_anthropic():
    """Lazy initialization of Anthropic client."""
    global _anthropic_client
    if _anthropic_client is None and os.environ.get("ANTHROPIC_API_KEY"):
        _anthropic_client = Anthropic()
    return _anthropic_client


# --- Runtime Configuration ---


def get_default_header_provider() -> str:
    """Get header provider from env var or default to 'none'."""
    provider = os.environ.get("CORTEX_HEADER_PROVIDER", "none").lower()
    if provider in ("anthropic", "claude-cli", "none"):
        return provider
    return "none"


CONFIG = {
    "min_score": 0.5,
    "verbose": False,
    "enabled": True,
    "top_k_retrieve": 50,
    "top_k_rerank": 5,
    # Header provider: "anthropic" (API), "claude-cli", or "none"
    "header_provider": get_default_header_provider(),
    # Recency boost: applies exponential decay to notes/commits
    "recency_boost": True,
    "recency_half_life_days": 30.0,  # Days until boost decays to ~0.5
}


# --- MCP Tools ---


@mcp.tool()
def search_cortex(
    query: str,
    project: Optional[str] = None,
    min_score: Optional[float] = None,
) -> str:
    """
    Search the Cortex memory for relevant code, documentation, or notes.

    Args:
        query: Natural language search query
        project: Optional project filter
        min_score: Minimum relevance score threshold (0-1, overrides config)

    Returns:
        JSON with search results including content, file paths, and scores
    """
    if not CONFIG["enabled"]:
        logger.info("Search rejected: Cortex is disabled")
        return json.dumps({"error": "Cortex is disabled", "results": []})

    logger.info(f"Search query: '{query}' (project={project})")
    start_time = time.time()

    try:
        collection = get_collection()
        searcher = get_searcher()
        reranker = get_reranker()

        # Build filter for branch awareness
        current_branch = get_current_branch("/projects")
        where_filter = None

        if project:
            where_filter = {"project": project}

        # Hybrid search
        search_start = time.time()
        candidates = searcher.search(
            query=query,
            top_k=CONFIG["top_k_retrieve"],
            where_filter=where_filter,
            rebuild_index=True,  # Rebuild for fresh results
        )
        search_time = time.time() - search_start
        logger.debug(f"Hybrid search: {len(candidates)} candidates in {search_time*1000:.1f}ms")

        if not candidates:
            logger.info("Search: no candidates found")
            return json.dumps({
                "query": query,
                "results": [],
                "message": "No results found. Try ingesting code first with ingest_code_into_cortex.",
            })

        # Rerank with FlashRank
        rerank_start = time.time()
        reranked = reranker.rerank(
            query=query,
            documents=candidates,
            top_k=CONFIG["top_k_rerank"],
        )
        rerank_time = time.time() - rerank_start
        logger.debug(f"Reranking: {len(reranked)} results in {rerank_time*1000:.1f}ms")

        # Apply recency boost to notes/commits (not code)
        if CONFIG["recency_boost"]:
            reranked = apply_recency_boost(
                reranked,
                half_life_days=CONFIG["recency_half_life_days"],
            )
            logger.debug(f"Recency boost applied (half_life={CONFIG['recency_half_life_days']}d)")

        # Apply minimum score filter (use boosted_score if available)
        threshold = min_score if min_score is not None else CONFIG["min_score"]
        score_key = "boosted_score" if CONFIG["recency_boost"] else "rerank_score"
        filtered = [r for r in reranked if r.get(score_key, r.get("rerank_score", 0)) >= threshold]
        logger.debug(f"Score filter (>={threshold}): {len(filtered)} results")

        # Log top results
        for i, r in enumerate(filtered[:5]):
            meta = r.get("meta", {})
            logger.debug(f"  [{i}] score={r.get('rerank_score', 0):.3f} file={meta.get('file_path', 'unknown')}")

        # Format response
        results = []
        for r in filtered:
            meta = r.get("meta", {})
            # Use boosted_score if recency boost applied, else rerank_score
            final_score = r.get("boosted_score", r.get("rerank_score", 0))
            result = {
                "content": r.get("text", "")[:2000],  # Truncate long content
                "file_path": meta.get("file_path", "unknown"),
                "project": meta.get("project", "unknown"),
                "branch": meta.get("branch", "unknown"),
                "language": meta.get("language", "unknown"),
                "score": float(round(final_score, 4)),
            }
            # Include recency boost factor in verbose mode
            if CONFIG["verbose"] and "recency_boost" in r:
                result["recency_boost"] = r["recency_boost"]
            results.append(result)

        # Fetch skeleton if we have results with a project
        skeleton_data = None
        detected_project = project
        if not detected_project and results:
            # Use project from first result
            detected_project = results[0].get("project")

        if detected_project and detected_project != "unknown":
            try:
                skeleton_results = collection.get(
                    where={"$and": [{"type": "skeleton"}, {"project": detected_project}]},
                    include=["documents", "metadatas"],
                )
                if skeleton_results["documents"]:
                    skel_meta = skeleton_results["metadatas"][0]
                    skeleton_data = {
                        "project": detected_project,
                        "branch": skel_meta.get("branch", "unknown"),
                        "total_files": skel_meta.get("total_files", 0),
                        "total_dirs": skel_meta.get("total_dirs", 0),
                        "tree": skeleton_results["documents"][0],
                    }
                    logger.debug(f"Skeleton included: {skel_meta.get('total_files', 0)} files")
            except Exception as e:
                logger.debug(f"Skeleton fetch failed: {e}")

        # Fetch project context (domain + status) if we have a project
        context_data = None
        if detected_project and detected_project != "unknown":
            try:
                domain_id = f"{detected_project}:domain_context"
                status_id = f"{detected_project}:project_context"
                context_results = collection.get(
                    ids=[domain_id, status_id],
                    include=["documents", "metadatas"],
                )
                if context_results["documents"]:
                    context_data = {"project": detected_project}
                    for i, doc_id in enumerate(context_results.get("ids", [])):
                        if i < len(context_results.get("documents", [])):
                            doc = context_results["documents"][i]
                            meta = context_results["metadatas"][i] if context_results.get("metadatas") else {}
                            if doc_id == domain_id:
                                context_data["domain"] = {
                                    "content": doc,
                                    "updated_at": meta.get("updated_at", "unknown"),
                                }
                            elif doc_id == status_id:
                                context_data["status"] = {
                                    "content": doc,
                                    "updated_at": meta.get("updated_at", "unknown"),
                                }
                    # Only include if we actually have content
                    if not context_data.get("domain") and not context_data.get("status"):
                        context_data = None
                    else:
                        logger.debug(f"Context included: domain={bool(context_data.get('domain'))}, status={bool(context_data.get('status'))}")
            except Exception as e:
                logger.debug(f"Context fetch failed: {e}")

        response = {
            "query": query,
            "results": results,
            "total_candidates": len(candidates),
            "returned": len(results),
        }

        if skeleton_data:
            response["project_skeleton"] = skeleton_data

        if context_data:
            response["project_context"] = context_data

        if CONFIG["verbose"]:
            response["config"] = CONFIG
            response["branch_context"] = current_branch

        total_time = time.time() - start_time
        logger.info(f"Search complete: {len(results)} results in {total_time*1000:.1f}ms")

        return json.dumps(response, indent=2)

    except Exception as e:
        logger.error(f"Search error: {e}")
        return json.dumps({"error": str(e), "results": []})


@mcp.tool()
def ingest_code_into_cortex(
    path: str,
    project_name: Optional[str] = None,
    force_full: bool = False,
) -> str:
    """
    Ingest a codebase directory into Cortex memory.

    Performs AST-aware chunking, secret scrubbing, and delta sync
    (only processes changed files unless force_full=True).

    Args:
        path: Absolute path to the codebase root directory
        project_name: Optional project identifier (defaults to directory name)
        force_full: Force full re-ingestion, ignoring delta sync

    Returns:
        JSON with ingestion statistics
    """
    logger.info(f"Ingesting codebase: path={path}, project={project_name}, force_full={force_full}")
    start_time = time.time()

    try:
        collection = get_collection()
        anthropic = get_anthropic() if CONFIG["header_provider"] == "anthropic" else None

        stats = ingest_codebase(
            root_path=path,
            collection=collection,
            project_id=project_name,
            anthropic_client=anthropic,
            force_full=force_full,
            header_provider=CONFIG["header_provider"],
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


@mcp.tool()
def commit_to_cortex(
    summary: str,
    changed_files: list[str],
    project: Optional[str] = None,
) -> str:
    """
    Save a session summary and re-index changed files.

    Use this at the end of a coding session to capture decisions
    and ensure changed code is indexed.

    Args:
        summary: Summary of the session/changes made
        changed_files: List of file paths that were modified
        project: Project identifier for the files

    Returns:
        JSON with commit status and re-indexing stats
    """
    logger.info(f"Committing to Cortex: {len(changed_files)} files, project={project}")
    start_time = time.time()

    try:
        from datetime import datetime, timezone

        collection = get_collection()
        anthropic = get_anthropic() if CONFIG["header_provider"] == "anthropic" else None

        # Save the summary as a note
        import uuid
        note_id = f"commit:{uuid.uuid4().hex[:8]}"

        branch = get_current_branch("/projects")
        project_id = project or "global"
        timestamp = datetime.now(timezone.utc).isoformat()

        collection.upsert(
            ids=[note_id],
            documents=[f"Session Summary:\n\n{scrub_secrets(summary)}\n\nChanged files: {', '.join(changed_files)}"],
            metadatas=[{
                "type": "commit",
                "project": project_id,
                "branch": branch,
                "files": json.dumps(changed_files),
                "created_at": timestamp,
            }],
        )
        logger.debug(f"Saved commit summary: {note_id}")

        # Re-index the changed files
        reindex_stats = ingest_files(
            file_paths=changed_files,
            collection=collection,
            project_id=project_id,
            anthropic_client=anthropic,
            header_provider=CONFIG["header_provider"],
        )
        logger.debug(f"Re-indexed files: {reindex_stats}")

        # Rebuild search index
        get_searcher().build_index()

        total_time = time.time() - start_time
        logger.info(f"Commit complete: {note_id} in {total_time:.1f}s")

        return json.dumps({
            "status": "success",
            "commit_id": note_id,
            "summary_saved": True,
            "reindex_stats": reindex_stats,
        }, indent=2)

    except Exception as e:
        logger.error(f"Commit error: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e),
        })


@mcp.tool()
def save_note_to_cortex(
    content: str,
    title: Optional[str] = None,
    tags: Optional[list[str]] = None,
    project: Optional[str] = None,
) -> str:
    """
    Save a note, documentation snippet, or decision to Cortex memory.

    Args:
        content: The note content
        title: Optional title for the note
        tags: Optional list of tags for categorization
        project: Associated project identifier

    Returns:
        JSON with note ID and save status
    """
    logger.info(f"Saving note: title='{title}', project={project}")

    try:
        from datetime import datetime, timezone
        import uuid

        collection = get_collection()
        note_id = f"note:{uuid.uuid4().hex[:8]}"
        branch = get_current_branch("/projects")
        timestamp = datetime.now(timezone.utc).isoformat()

        # Build document text
        doc_text = ""
        if title:
            doc_text = f"{title}\n\n"
        doc_text += scrub_secrets(content)

        collection.upsert(
            ids=[note_id],
            documents=[doc_text],
            metadatas=[{
                "type": "note",
                "title": title or "",
                "tags": ",".join(tags) if tags else "",
                "project": project or "global",
                "branch": branch,
                "created_at": timestamp,
            }],
        )

        # Rebuild search index
        get_searcher().build_index()

        logger.info(f"Note saved: {note_id}")

        return json.dumps({
            "status": "saved",
            "note_id": note_id,
            "title": title,
        }, indent=2)

    except Exception as e:
        logger.error(f"Note save error: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e),
        })


@mcp.tool()
def configure_cortex(
    min_score: Optional[float] = None,
    verbose: Optional[bool] = None,
    top_k_retrieve: Optional[int] = None,
    top_k_rerank: Optional[int] = None,
    header_provider: Optional[str] = None,
    recency_boost: Optional[bool] = None,
    recency_half_life_days: Optional[float] = None,
) -> str:
    """
    Configure Cortex runtime settings.

    Args:
        min_score: Minimum relevance score threshold (0.0 to 1.0)
        verbose: Enable verbose output with debug info
        top_k_retrieve: Number of candidates to retrieve before reranking
        top_k_rerank: Number of results to return after reranking
        header_provider: Provider for contextual headers: "anthropic", "claude-cli", or "none"
        recency_boost: Enable recency boosting for notes/commits (newer = higher rank)
        recency_half_life_days: Days until recency boost decays to ~0.5 (default 30)

    Returns:
        JSON with updated configuration
    """
    changes = []
    if min_score is not None:
        CONFIG["min_score"] = max(0.0, min(1.0, min_score))
        changes.append(f"min_score={CONFIG['min_score']}")

    if verbose is not None:
        CONFIG["verbose"] = verbose
        changes.append(f"verbose={verbose}")

    if top_k_retrieve is not None:
        CONFIG["top_k_retrieve"] = max(10, min(200, top_k_retrieve))
        changes.append(f"top_k_retrieve={CONFIG['top_k_retrieve']}")

    if top_k_rerank is not None:
        CONFIG["top_k_rerank"] = max(1, min(50, top_k_rerank))
        changes.append(f"top_k_rerank={CONFIG['top_k_rerank']}")

    if header_provider is not None:
        if header_provider in ("anthropic", "claude-cli", "none"):
            CONFIG["header_provider"] = header_provider
            changes.append(f"header_provider={header_provider}")
        else:
            logger.warning(f"Invalid header_provider: {header_provider}. Use 'anthropic', 'claude-cli', or 'none'")

    if recency_boost is not None:
        CONFIG["recency_boost"] = recency_boost
        changes.append(f"recency_boost={recency_boost}")

    if recency_half_life_days is not None:
        CONFIG["recency_half_life_days"] = max(1.0, min(365.0, recency_half_life_days))
        changes.append(f"recency_half_life_days={CONFIG['recency_half_life_days']}")

    if changes:
        logger.info(f"Configuration updated: {', '.join(changes)}")
    else:
        logger.debug("Configure called with no changes")

    return json.dumps({
        "status": "configured",
        "config": CONFIG,
    }, indent=2)


@mcp.tool()
def get_skeleton(
    project: Optional[str] = None,
) -> str:
    """
    Get the file tree structure for a project.

    Returns the stored skeleton (tree output) for file-path grounding.
    The skeleton is auto-generated during ingest_code_into_cortex.

    Args:
        project: Project name (required)

    Returns:
        JSON with tree structure and metadata
    """
    if not project:
        return json.dumps({
            "error": "Project name is required",
            "hint": "Provide the project name used during ingestion",
        })

    logger.info(f"Getting skeleton for project: {project}")

    try:
        collection = get_collection()
        branch = get_current_branch("/projects")

        # Try current branch first, then fall back to any branch
        doc_id = f"{project}:skeleton:{branch}"
        result = collection.get(ids=[doc_id], include=["documents", "metadatas"])

        if not result["documents"]:
            # Try to find skeleton for any branch
            all_results = collection.get(
                where={"$and": [{"type": "skeleton"}, {"project": project}]},
                include=["documents", "metadatas"],
            )
            if all_results["documents"]:
                result = {
                    "documents": [all_results["documents"][0]],
                    "metadatas": [all_results["metadatas"][0]],
                }

        if not result["documents"]:
            return json.dumps({
                "error": f"No skeleton found for project '{project}'",
                "hint": "Run ingest_code_into_cortex first to generate the skeleton",
            })

        metadata = result["metadatas"][0]
        tree = result["documents"][0]

        logger.info(f"Skeleton found: {metadata.get('total_files', 0)} files, {metadata.get('total_dirs', 0)} dirs")

        return json.dumps({
            "project": project,
            "branch": metadata.get("branch", "unknown"),
            "generated_at": metadata.get("generated_at", "unknown"),
            "total_files": metadata.get("total_files", 0),
            "total_dirs": metadata.get("total_dirs", 0),
            "tree": tree,
        }, indent=2)

    except Exception as e:
        logger.error(f"Get skeleton error: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
def set_context_in_cortex(
    project: str,
    domain: Optional[str] = None,
    project_status: Optional[str] = None,
) -> str:
    """
    Set domain context and/or project status for a project.

    Domain context is static tech stack info (e.g., "NestJS backend, PostgreSQL, React frontend").
    Project status is dynamic state (e.g., "Migration V1: Phase 2 - auth module complete").

    Args:
        project: Project identifier (required)
        domain: Static tech stack/architecture description
        project_status: Dynamic project status or current work state

    Returns:
        JSON with saved context IDs
    """
    from datetime import datetime, timezone

    if not domain and not project_status:
        return json.dumps({
            "error": "At least one of 'domain' or 'project_status' must be provided",
        })

    logger.info(f"Setting context for project: {project}")
    saved = {}

    try:
        collection = get_collection()
        branch = get_current_branch("/projects")
        timestamp = datetime.now(timezone.utc).isoformat()

        if domain:
            domain_id = f"{project}:domain_context"
            collection.upsert(
                ids=[domain_id],
                documents=[scrub_secrets(domain)],
                metadatas=[{
                    "type": "domain_context",
                    "project": project,
                    "branch": branch,
                    "updated_at": timestamp,
                }],
            )
            saved["domain_context_id"] = domain_id
            logger.debug(f"Saved domain context: {domain_id}")

        if project_status:
            status_id = f"{project}:project_context"
            collection.upsert(
                ids=[status_id],
                documents=[scrub_secrets(project_status)],
                metadatas=[{
                    "type": "project_context",
                    "project": project,
                    "branch": branch,
                    "updated_at": timestamp,
                }],
            )
            saved["project_context_id"] = status_id
            logger.debug(f"Saved project context: {status_id}")

        # Rebuild search index
        get_searcher().build_index()

        logger.info(f"Context saved for project '{project}'")

        return json.dumps({
            "status": "saved",
            "project": project,
            **saved,
        }, indent=2)

    except Exception as e:
        logger.error(f"Set context error: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e),
        })


@mcp.tool()
def update_project_status(
    status: str,
    project: Optional[str] = None,
) -> str:
    """
    Quick update for project status.

    Convenience wrapper for updating just the project status without touching domain context.

    Args:
        status: Current project status or work state (e.g., "Phase 2 blocked on API review")
        project: Project identifier (auto-detects from recent search if not provided)

    Returns:
        JSON with saved status ID
    """
    from datetime import datetime, timezone

    if not project:
        return json.dumps({
            "error": "Project name is required",
            "hint": "Provide the project identifier",
        })

    logger.info(f"Updating project status: {project}")

    try:
        collection = get_collection()
        branch = get_current_branch("/projects")
        timestamp = datetime.now(timezone.utc).isoformat()

        status_id = f"{project}:project_context"
        collection.upsert(
            ids=[status_id],
            documents=[scrub_secrets(status)],
            metadatas=[{
                "type": "project_context",
                "project": project,
                "branch": branch,
                "updated_at": timestamp,
            }],
        )

        # Rebuild search index
        get_searcher().build_index()

        logger.info(f"Project status updated: {status_id}")

        return json.dumps({
            "status": "saved",
            "project": project,
            "project_context_id": status_id,
        }, indent=2)

    except Exception as e:
        logger.error(f"Update status error: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e),
        })


@mcp.tool()
def get_context_from_cortex(
    project: Optional[str] = None,
) -> str:
    """
    Get stored domain and project context.

    Retrieves the tech stack (domain) and current status for a project.

    Args:
        project: Project identifier (required)

    Returns:
        JSON with domain context and project status
    """
    if not project:
        return json.dumps({
            "error": "Project name is required",
            "hint": "Provide the project identifier",
        })

    logger.info(f"Getting context for project: {project}")

    try:
        collection = get_collection()

        # Fetch both context types
        domain_id = f"{project}:domain_context"
        status_id = f"{project}:project_context"

        results = collection.get(
            ids=[domain_id, status_id],
            include=["documents", "metadatas"],
        )

        context = {
            "project": project,
            "domain": None,
            "project_status": None,
        }

        # Parse results
        for i, doc_id in enumerate(results.get("ids", [])):
            if i < len(results.get("documents", [])):
                doc = results["documents"][i]
                meta = results["metadatas"][i] if results.get("metadatas") else {}

                if doc_id == domain_id:
                    context["domain"] = {
                        "content": doc,
                        "updated_at": meta.get("updated_at", "unknown"),
                    }
                elif doc_id == status_id:
                    context["project_status"] = {
                        "content": doc,
                        "updated_at": meta.get("updated_at", "unknown"),
                    }

        has_context = context["domain"] or context["project_status"]
        if not has_context:
            return json.dumps({
                "project": project,
                "message": "No context found for this project",
                "hint": "Use set_context_in_cortex to set domain and project status",
            })

        logger.info(f"Context retrieved for project '{project}'")

        return json.dumps(context, indent=2)

    except Exception as e:
        logger.error(f"Get context error: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
def toggle_cortex(enabled: bool) -> str:
    """
    Enable or disable Cortex memory system.

    When disabled, search_cortex will return empty results.
    Use this for A/B testing memory vs. no-memory performance.

    Args:
        enabled: True to enable, False to disable

    Returns:
        JSON with current status
    """
    CONFIG["enabled"] = enabled
    logger.info(f"Cortex {'enabled' if enabled else 'disabled'}")

    # Also return stats when enabled
    stats = {}
    if enabled:
        try:
            collection = get_collection()
            stats = get_collection_stats(collection)
            logger.debug(f"Stats: {stats}")
        except Exception:
            pass

    return json.dumps({
        "status": "enabled" if enabled else "disabled",
        "enabled": enabled,
        "stats": stats,
    }, indent=2)


@mcp.tool()
def get_cortex_version(expected_commit: Optional[str] = None) -> str:
    """
    Get Cortex daemon build and version information.

    Returns git commit, build time, and startup time to verify the daemon
    is running the expected code version. Pass expected_commit to check if
    a rebuild is needed.

    Args:
        expected_commit: The git commit hash to compare against (e.g., local HEAD).
                        If provided, returns needs_rebuild indicating if daemon is outdated.

    Returns:
        JSON with version info and whether daemon matches local code
    """
    git_commit = os.environ.get("CORTEX_GIT_COMMIT", "unknown")
    build_time = os.environ.get("CORTEX_BUILD_TIME", "unknown")

    # Get startup time from http_server module
    try:
        from http_server import _startup_time
        startup_time = _startup_time
    except ImportError:
        startup_time = "unknown"

    result = {
        "git_commit": git_commit,
        "build_time": build_time,
        "startup_time": startup_time,
        "version": "1.0.0",
    }

    # Compare against expected commit if provided
    if expected_commit:
        result["expected_commit"] = expected_commit
        # Compare short commits (handle both short and full hashes)
        daemon_short = git_commit[:7] if len(git_commit) >= 7 else git_commit
        expected_short = expected_commit[:7] if len(expected_commit) >= 7 else expected_commit
        result["needs_rebuild"] = daemon_short != expected_short
        if result["needs_rebuild"]:
            result["message"] = f"Daemon is outdated. Run 'cortex daemon rebuild' to update from {daemon_short} to {expected_short}."
        else:
            result["message"] = "Daemon is up to date."

    return json.dumps(result, indent=2)


# --- Entry Point ---


def start_http_server():
    """Start the FastAPI HTTP server in a background thread."""
    from http_server import run_server
    http_thread = threading.Thread(target=run_server, daemon=True)
    http_thread.start()
    logger.info("HTTP server started on port 8080")


if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Cortex MCP Server")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Enable HTTP server for debugging and Phase 2 features",
    )
    args = parser.parse_args()

    # Check for CORTEX_HTTP environment variable
    enable_http = args.http or os.environ.get("CORTEX_HTTP", "").lower() in ("true", "1", "yes")

    if enable_http:
        start_http_server()

    logger.info("Starting Cortex MCP server")
    mcp.run()
