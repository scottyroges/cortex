"""
Search Tool

MCP tool for searching Cortex memory.
"""

import json
import time
from typing import Optional

from logging_config import get_logger
from src.git import get_current_branch
from src.search import apply_recency_boost
from src.tools.services import CONFIG, get_collection, get_reranker, get_repo_path, get_searcher
from src.tools.staleness import check_insight_staleness, check_note_staleness, format_verification_warning

logger = get_logger("tools.search")

# Initiative boost factor for focused initiative content
INITIATIVE_BOOST_FACTOR = 1.3


def _resolve_initiative_id(collection, repository: Optional[str], initiative: str) -> Optional[str]:
    """Resolve initiative name to ID."""
    if initiative.startswith("initiative:"):
        return initiative

    try:
        where_filter = {"$and": [{"type": "initiative"}, {"name": initiative}]}
        if repository:
            where_filter["$and"].append({"repository": repository})

        result = collection.get(where=where_filter, include=[])
        if result["ids"]:
            return result["ids"][0]
    except Exception as e:
        logger.warning(f"Failed to resolve initiative: {e}")

    return None


def _get_focused_initiative_id(collection, repository: str) -> Optional[str]:
    """Get the focused initiative ID for a repository."""
    try:
        focus_id = f"{repository}:focus"
        result = collection.get(ids=[focus_id], include=["metadatas"])
        if result["ids"]:
            return result["metadatas"][0].get("initiative_id")
    except Exception as e:
        logger.warning(f"Failed to get focused initiative: {e}")
    return None


def _apply_initiative_boost(
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


def _filter_by_initiative(results: list, initiative_id: str, include_completed: bool = True) -> list:
    """Filter results to only include those from a specific initiative."""
    filtered = []
    for result in results:
        meta = result.get("meta", {})
        result_init_id = meta.get("initiative_id")

        # Include if matches initiative
        if result_init_id == initiative_id:
            filtered.append(result)
        # Include code that's not tagged with any initiative (belongs to whole repo)
        elif meta.get("type") == "code" and not result_init_id:
            filtered.append(result)

    return filtered


def build_branch_aware_filter(
    repository: Optional[str] = None,
    branches: Optional[list[str]] = None,
) -> Optional[dict]:
    """
    Build ChromaDB where filter that applies branch filtering
    only to code and skeleton documents.

    Notes, commits, tech_stack, initiatives are never filtered by branch.

    Args:
        repository: Optional repository filter
        branches: List of branches to include for code/skeleton

    Returns:
        ChromaDB where filter dict, or None if no filtering needed
    """
    if not branches or branches == ["unknown"]:
        # No branch filtering if unknown
        return {"repository": repository} if repository else None

    # Types filtered by branch: code, skeleton
    # Types NOT filtered: note, commit, tech_stack, initiative
    branch_filter = {
        "$or": [
            # Code/skeleton: filter by branch
            {"$and": [
                {"type": {"$in": ["code", "skeleton"]}},
                {"branch": {"$in": branches}}
            ]},
            # Non-code types: always include (cross-branch)
            {"type": {"$in": ["note", "commit", "tech_stack", "initiative"]}}
        ]
    }

    if repository:
        return {"$and": [{"repository": repository}, branch_filter]}

    return branch_filter


def search_cortex(
    query: str,
    repository: Optional[str] = None,
    min_score: Optional[float] = None,
    branch: Optional[str] = None,
    initiative: Optional[str] = None,
    include_completed: bool = True,
) -> str:
    """
    Search the Cortex memory for relevant code, documentation, or notes.

    Args:
        query: Natural language search query
        repository: Repository identifier for filtering
        min_score: Minimum relevance score threshold (0-1, overrides config)
        branch: Optional branch filter. Defaults to auto-detect from cwd.
                Code/skeleton are filtered by branch; notes/commits are not.
        initiative: Optional initiative ID or name to filter results
        include_completed: Include content from completed initiatives (default: True)

    Returns:
        JSON with search results including content, file paths, and scores
    """
    repo = repository
    if not CONFIG["enabled"]:
        logger.info("Search rejected: Cortex is disabled")
        return json.dumps({"error": "Cortex is disabled", "results": []})

    logger.info(f"Search query: '{query}' (repository={repo}, branch={branch}, initiative={initiative})")
    start_time = time.time()

    try:
        collection = get_collection()
        searcher = get_searcher()
        reranker = get_reranker()

        # Determine branch context
        repo_path = get_repo_path()
        current_branch = get_current_branch(repo_path) if repo_path else "unknown"

        # Use explicit branch if provided, otherwise auto-detect
        effective_branch = branch if branch else current_branch

        # Build branch list: current + main (unless already on main/master)
        branches = [effective_branch]
        if effective_branch not in ("main", "master", "unknown"):
            branches.append("main")

        # Build smart where filter (code filters by branch, notes don't)
        where_filter = build_branch_aware_filter(
            repository=repo,
            branches=branches,
        )
        logger.debug(f"Branch filter: effective={effective_branch}, branches={branches}")

        # Resolve initiative filter if provided
        initiative_id = None
        if initiative:
            initiative_id = _resolve_initiative_id(collection, repo, initiative)
            if initiative_id:
                logger.debug(f"Initiative filter: {initiative_id}")

        # Get focused initiative for boosting (if no specific initiative filter)
        focused_initiative_id = None
        if not initiative_id and repo:
            focused_initiative_id = _get_focused_initiative_id(collection, repo)

        # Hybrid search
        search_start = time.time()
        candidates = searcher.search(
            query=query,
            top_k=CONFIG["top_k_retrieve"],
            where_filter=where_filter,
            rebuild_index=True,
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

        # Apply initiative filtering if requested
        if initiative_id:
            reranked = _filter_by_initiative(reranked, initiative_id, include_completed)
            logger.debug(f"Initiative filter applied: {len(reranked)} results remain")

        # Apply initiative boost for focused initiative (if no explicit filter)
        if focused_initiative_id and not initiative_id:
            reranked = _apply_initiative_boost(reranked, focused_initiative_id)
            logger.debug(f"Initiative boost applied for focused: {focused_initiative_id}")

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
        staleness_check_enabled = CONFIG.get("staleness_check_enabled", True)
        staleness_check_limit = CONFIG.get("staleness_check_limit", 10)
        verification_required_count = 0

        for idx, r in enumerate(filtered):
            meta = r.get("meta", {})
            doc_type = meta.get("type", "")
            final_score = r.get("boosted_score", r.get("rerank_score", 0))
            result = {
                "content": r.get("text", "")[:2000],
                "file_path": meta.get("file_path", "unknown"),
                "repository": meta.get("repository", "unknown"),
                "branch": meta.get("branch", "unknown"),
                "language": meta.get("language", "unknown"),
                "score": float(round(final_score, 4)),
            }

            # Add staleness info for insights and notes (limit checks for performance)
            if staleness_check_enabled and idx < staleness_check_limit:
                if doc_type == "insight":
                    staleness = check_insight_staleness(meta, repo_path)
                    if staleness.get("verification_required") or staleness.get("level") != "fresh":
                        result["staleness"] = staleness
                        warning = format_verification_warning(staleness, meta)
                        if warning:
                            result["verification_warning"] = warning
                        if staleness.get("verification_required"):
                            verification_required_count += 1
                elif doc_type in ("note", "commit"):
                    staleness = check_note_staleness(meta)
                    if staleness.get("verification_required") or staleness.get("level") != "fresh":
                        result["staleness"] = staleness
                        warning = format_verification_warning(staleness, meta)
                        if warning:
                            result["verification_warning"] = warning
                        if staleness.get("verification_required"):
                            verification_required_count += 1

            # Add initiative info if present
            if meta.get("initiative_id"):
                result["initiative_id"] = meta.get("initiative_id")
                result["initiative_name"] = meta.get("initiative_name", "")
            if CONFIG["verbose"]:
                if "recency_boost" in r:
                    result["recency_boost"] = r["recency_boost"]
                if "initiative_boost" in r:
                    result["initiative_boost"] = r["initiative_boost"]
            results.append(result)

        # Fetch skeleton if we have results with a repository
        skeleton_data = None
        detected_repo = repo
        if not detected_repo and results:
            detected_repo = results[0].get("repository")

        if detected_repo and detected_repo != "unknown":
            try:
                # Try to get skeleton for current branch first
                skeleton_results = collection.get(
                    where={"$and": [
                        {"type": "skeleton"},
                        {"repository": detected_repo},
                        {"branch": {"$in": branches}},
                    ]},
                    include=["documents", "metadatas"],
                )
                # Fallback to any skeleton for this repository if branch-specific not found
                if not skeleton_results["documents"]:
                    skeleton_results = collection.get(
                        where={"$and": [{"type": "skeleton"}, {"repository": detected_repo}]},
                        include=["documents", "metadatas"],
                    )
                if skeleton_results["documents"]:
                    skel_meta = skeleton_results["metadatas"][0]
                    skeleton_data = {
                        "repository": detected_repo,
                        "branch": skel_meta.get("branch", "unknown"),
                        "total_files": skel_meta.get("total_files", 0),
                        "total_dirs": skel_meta.get("total_dirs", 0),
                        "tree": skeleton_results["documents"][0],
                    }
                    logger.debug(f"Skeleton included: {skel_meta.get('total_files', 0)} files (branch={skel_meta.get('branch')})")
            except Exception as e:
                logger.debug(f"Skeleton fetch failed: {e}")

        # Fetch repository context (tech_stack + initiative)
        context_data = None
        if detected_repo and detected_repo != "unknown":
            try:
                tech_stack_id = f"{detected_repo}:tech_stack"
                initiative_id = f"{detected_repo}:initiative"
                context_results = collection.get(
                    ids=[tech_stack_id, initiative_id],
                    include=["documents", "metadatas"],
                )
                if context_results["documents"]:
                    context_data = {"repository": detected_repo}
                    for i, doc_id in enumerate(context_results.get("ids", [])):
                        if i < len(context_results.get("documents", [])):
                            doc = context_results["documents"][i]
                            meta = context_results["metadatas"][i] if context_results.get("metadatas") else {}
                            if doc_id == tech_stack_id:
                                context_data["tech_stack"] = {
                                    "content": doc,
                                    "updated_at": meta.get("updated_at", "unknown"),
                                }
                            elif doc_id == initiative_id:
                                context_data["initiative"] = {
                                    "name": meta.get("initiative_name", ""),
                                    "status": meta.get("initiative_status", ""),
                                    "updated_at": meta.get("updated_at", "unknown"),
                                }
                    if not context_data.get("tech_stack") and not context_data.get("initiative"):
                        context_data = None
                    else:
                        logger.debug(f"Context included: tech_stack={bool(context_data.get('tech_stack'))}, initiative={bool(context_data.get('initiative'))}")
            except Exception as e:
                logger.debug(f"Context fetch failed: {e}")

        response = {
            "query": query,
            "results": results,
            "total_candidates": len(candidates),
            "returned": len(results),
        }

        # Add staleness summary if any results require verification
        if verification_required_count > 0:
            response["staleness_summary"] = {
                "verification_required_count": verification_required_count,
                "message": f"{verification_required_count} result(s) may be stale and require verification before trusting.",
            }

        if skeleton_data:
            response["repository_skeleton"] = skeleton_data

        if context_data:
            response["repository_context"] = context_data

        if CONFIG["verbose"]:
            response["config"] = CONFIG
            response["branch_context"] = current_branch

        total_time = time.time() - start_time
        logger.info(f"Search complete: {len(results)} results in {total_time*1000:.1f}ms")

        return json.dumps(response, indent=2)

    except Exception as e:
        logger.error(f"Search error: {e}")
        return json.dumps({"error": str(e), "results": []})
