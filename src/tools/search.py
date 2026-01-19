"""
Search Tool

MCP tool for searching Cortex memory.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Optional

from logging_config import get_logger
from src.documents import (
    ALL_DOCUMENT_TYPES,
    BRANCH_FILTERED_TYPES,
    METADATA_ONLY_TYPES,
    SEARCH_PRESETS,
)
from src.git import get_current_branch
from src.search import apply_recency_boost, apply_type_boost
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
        # Include metadata types that aren't tagged (belong to whole repo)
        elif meta.get("type") in METADATA_ONLY_TYPES and not result_init_id:
            filtered.append(result)

    return filtered


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


# Valid types imported from src.documents: ALL_DOCUMENT_TYPES
# Branch-filtered types imported from src.documents: BRANCH_FILTERED_TYPES
# Search presets imported from src.documents: SEARCH_PRESETS


@dataclass
class SearchPipeline:
    """
    Encapsulates the search pipeline for Cortex memory.

    Breaks down the search process into clear phases:
    1. Context resolution (branch, initiative)
    2. Hybrid search execution
    3. Ranking (rerank, recency boost, initiative boost)
    4. Result formatting with staleness checks
    5. Context fetching (skeleton, tech_stack)
    """

    query: str
    repository: Optional[str] = None
    min_score: Optional[float] = None
    branch: Optional[str] = None
    initiative: Optional[str] = None
    include_completed: bool = True
    types: Optional[list[str]] = None

    # Resolved context (set during execution)
    _collection: object = field(default=None, repr=False)
    _repo_path: Optional[str] = field(default=None, repr=False)
    _current_branch: str = field(default="unknown", repr=False)
    _effective_branch: str = field(default="unknown", repr=False)
    _branches: list = field(default_factory=list, repr=False)
    _initiative_id: Optional[str] = field(default=None, repr=False)
    _focused_initiative_id: Optional[str] = field(default=None, repr=False)
    _candidates: list = field(default_factory=list, repr=False)

    def execute(self) -> str:
        """Execute the full search pipeline and return JSON response."""
        if not CONFIG["enabled"]:
            logger.info("Search rejected: Cortex is disabled")
            return json.dumps({"error": "Cortex is disabled", "results": []})

        logger.info(
            f"Search query: '{self.query}' "
            f"(repository={self.repository}, branch={self.branch}, initiative={self.initiative})"
        )
        start_time = time.time()

        try:
            # Initialize resources
            self._collection = get_collection()
            searcher = get_searcher()
            reranker = get_reranker()

            # Phase 1: Resolve context
            self._resolve_branch_context()
            self._resolve_initiative_context()

            # Phase 2: Execute hybrid search
            candidates = self._execute_search(searcher)
            if not candidates:
                logger.info("Search: no candidates found")
                return json.dumps({
                    "query": self.query,
                    "results": [],
                    "message": "No results found. Try ingesting code first with ingest_code_into_cortex.",
                })

            # Phase 3: Apply ranking
            ranked = self._apply_ranking(reranker, candidates)

            # Phase 4: Format results with staleness checks
            results, verification_count = self._format_results(ranked)

            # Phase 5: Fetch additional context
            detected_repo = self._detect_repository(results)
            skeleton_data = self._fetch_skeleton(detected_repo)
            context_data = self._fetch_context(detected_repo)

            # Build response
            response = self._build_response(
                results, candidates, verification_count, skeleton_data, context_data
            )

            total_time = time.time() - start_time
            logger.info(f"Search complete: {len(results)} results in {total_time*1000:.1f}ms")

            return json.dumps(response, indent=2)

        except Exception as e:
            logger.error(f"Search error: {e}")
            return json.dumps({"error": str(e), "results": []})

    def _resolve_branch_context(self) -> None:
        """Resolve branch context for filtering."""
        self._repo_path = get_repo_path()
        self._current_branch = get_current_branch(self._repo_path) if self._repo_path else "unknown"

        # Use explicit branch if provided, otherwise auto-detect
        self._effective_branch = self.branch if self.branch else self._current_branch

        # Build branch list: current + main (unless already on main/master)
        self._branches = [self._effective_branch]
        if self._effective_branch not in ("main", "master", "unknown"):
            self._branches.append("main")

        logger.debug(f"Branch filter: effective={self._effective_branch}, branches={self._branches}")

    def _resolve_initiative_context(self) -> None:
        """Resolve initiative filtering and boosting context."""
        if self.initiative:
            self._initiative_id = _resolve_initiative_id(
                self._collection, self.repository, self.initiative
            )
            if self._initiative_id:
                logger.debug(f"Initiative filter: {self._initiative_id}")

        # Get focused initiative for boosting (if no specific initiative filter)
        if not self._initiative_id and self.repository:
            self._focused_initiative_id = _get_focused_initiative_id(
                self._collection, self.repository
            )

    def _execute_search(self, searcher) -> list:
        """Execute hybrid search."""
        where_filter = build_branch_aware_filter(
            repository=self.repository,
            branches=self._branches,
            types=self.types,
        )

        search_start = time.time()
        candidates = searcher.search(
            query=self.query,
            top_k=CONFIG["top_k_retrieve"],
            where_filter=where_filter,
        )
        search_time = time.time() - search_start
        logger.debug(f"Hybrid search: {len(candidates)} candidates in {search_time*1000:.1f}ms")

        self._candidates = candidates
        return candidates

    def _apply_ranking(self, reranker, candidates: list) -> list:
        """Apply reranking, type boost, recency boost, initiative filtering/boosting, and score filtering."""
        # Rerank with FlashRank
        rerank_start = time.time()
        ranked = reranker.rerank(
            query=self.query,
            documents=candidates,
            top_k=CONFIG["top_k_rerank"],
        )
        rerank_time = time.time() - rerank_start
        logger.debug(f"Reranking: {len(ranked)} results in {rerank_time*1000:.1f}ms")

        # Apply type-based scoring (insights 2x, notes/session_summaries 1.5x, code 1x)
        if CONFIG.get("type_boost", True):
            type_multipliers = CONFIG.get("type_multipliers")
            ranked = apply_type_boost(ranked, multipliers=type_multipliers)
            logger.debug("Type boost applied (insight=2x, note/session_summary=1.5x)")

        # Apply recency boost to notes/commits (not code)
        if CONFIG["recency_boost"]:
            ranked = apply_recency_boost(
                ranked,
                half_life_days=CONFIG["recency_half_life_days"],
            )
            logger.debug(f"Recency boost applied (half_life={CONFIG['recency_half_life_days']}d)")

        # Apply initiative filtering if requested
        if self._initiative_id:
            ranked = _filter_by_initiative(ranked, self._initiative_id, self.include_completed)
            logger.debug(f"Initiative filter applied: {len(ranked)} results remain")

        # Apply initiative boost for focused initiative (if no explicit filter)
        if self._focused_initiative_id and not self._initiative_id:
            ranked = _apply_initiative_boost(ranked, self._focused_initiative_id)
            logger.debug(f"Initiative boost applied for focused: {self._focused_initiative_id}")

        # Apply minimum score filter
        threshold = self.min_score if self.min_score is not None else CONFIG["min_score"]
        score_key = "boosted_score" if CONFIG["recency_boost"] else "rerank_score"
        filtered = [r for r in ranked if r.get(score_key, r.get("rerank_score", 0)) >= threshold]
        logger.debug(f"Score filter (>={threshold}): {len(filtered)} results")

        # Log top results
        for i, r in enumerate(filtered[:5]):
            meta = r.get("meta", {})
            logger.debug(f"  [{i}] score={r.get('rerank_score', 0):.3f} file={meta.get('file_path', 'unknown')}")

        return filtered

    def _format_results(self, ranked: list) -> tuple[list, int]:
        """Format results with staleness checks."""
        results = []
        staleness_check_enabled = CONFIG.get("staleness_check_enabled", True)
        staleness_check_limit = CONFIG.get("staleness_check_limit", 10)
        verification_required_count = 0

        for idx, r in enumerate(ranked):
            result, requires_verification = self._format_single_result(
                r, idx, staleness_check_enabled, staleness_check_limit
            )
            if requires_verification:
                verification_required_count += 1
            results.append(result)

        return results, verification_required_count

    def _format_single_result(
        self, r: dict, idx: int, staleness_enabled: bool, staleness_limit: int
    ) -> tuple[dict, bool]:
        """Format a single search result."""
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

        requires_verification = False

        # Add staleness info for insights and notes (limit checks for performance)
        if staleness_enabled and idx < staleness_limit:
            if doc_type == "insight":
                staleness = check_insight_staleness(meta, self._repo_path)
                if staleness.get("verification_required") or staleness.get("level") != "fresh":
                    result["staleness"] = staleness
                    warning = format_verification_warning(staleness, meta)
                    if warning:
                        result["verification_warning"] = warning
                    if staleness.get("verification_required"):
                        requires_verification = True
            elif doc_type in ("note", "session_summary"):
                staleness = check_note_staleness(meta)
                if staleness.get("verification_required") or staleness.get("level") != "fresh":
                    result["staleness"] = staleness
                    warning = format_verification_warning(staleness, meta)
                    if warning:
                        result["verification_warning"] = warning
                    if staleness.get("verification_required"):
                        requires_verification = True

        # Add initiative info if present
        if meta.get("initiative_id"):
            result["initiative_id"] = meta.get("initiative_id")
            result["initiative_name"] = meta.get("initiative_name", "")

        if CONFIG["verbose"]:
            if "type_boost" in r:
                result["type_boost"] = r["type_boost"]
            if "recency_boost" in r:
                result["recency_boost"] = r["recency_boost"]
            if "initiative_boost" in r:
                result["initiative_boost"] = r["initiative_boost"]

        return result, requires_verification

    def _detect_repository(self, results: list) -> Optional[str]:
        """Detect repository from results if not specified."""
        detected = self.repository
        if not detected and results:
            detected = results[0].get("repository")
        return detected if detected and detected != "unknown" else None

    def _fetch_skeleton(self, repo: Optional[str]) -> Optional[dict]:
        """Fetch repository skeleton."""
        if not repo:
            return None

        try:
            # Try to get skeleton for current branch first
            skeleton_results = self._collection.get(
                where={"$and": [
                    {"type": "skeleton"},
                    {"repository": repo},
                    {"branch": {"$in": self._branches}},
                ]},
                include=["documents", "metadatas"],
            )
            # Fallback to any skeleton for this repository if branch-specific not found
            if not skeleton_results["documents"]:
                skeleton_results = self._collection.get(
                    where={"$and": [{"type": "skeleton"}, {"repository": repo}]},
                    include=["documents", "metadatas"],
                )
            if skeleton_results["documents"]:
                skel_meta = skeleton_results["metadatas"][0]
                skeleton_data = {
                    "repository": repo,
                    "branch": skel_meta.get("branch", "unknown"),
                    "total_files": skel_meta.get("total_files", 0),
                    "total_dirs": skel_meta.get("total_dirs", 0),
                    "tree": skeleton_results["documents"][0],
                }
                logger.debug(
                    f"Skeleton included: {skel_meta.get('total_files', 0)} files "
                    f"(branch={skel_meta.get('branch')})"
                )
                return skeleton_data
        except Exception as e:
            logger.debug(f"Skeleton fetch failed: {e}")

        return None

    def _fetch_context(self, repo: Optional[str]) -> Optional[dict]:
        """Fetch repository context (tech_stack + initiative)."""
        if not repo:
            return None

        try:
            tech_stack_id = f"{repo}:tech_stack"
            initiative_id = f"{repo}:initiative"
            context_results = self._collection.get(
                ids=[tech_stack_id, initiative_id],
                include=["documents", "metadatas"],
            )
            if context_results["documents"]:
                context_data = {"repository": repo}
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
                    return None
                logger.debug(
                    f"Context included: tech_stack={bool(context_data.get('tech_stack'))}, "
                    f"initiative={bool(context_data.get('initiative'))}"
                )
                return context_data
        except Exception as e:
            logger.debug(f"Context fetch failed: {e}")

        return None

    def _build_response(
        self,
        results: list,
        candidates: list,
        verification_count: int,
        skeleton_data: Optional[dict],
        context_data: Optional[dict],
    ) -> dict:
        """Build the final response dictionary."""
        response = {
            "query": self.query,
            "results": results,
            "total_candidates": len(candidates),
            "returned": len(results),
        }

        # Add staleness summary if any results require verification
        if verification_count > 0:
            response["staleness_summary"] = {
                "verification_required_count": verification_count,
                "message": f"{verification_count} result(s) may be stale and require verification before trusting.",
            }

        if skeleton_data:
            response["repository_skeleton"] = skeleton_data

        if context_data:
            response["repository_context"] = context_data

        if CONFIG["verbose"]:
            response["config"] = CONFIG
            response["branch_context"] = self._current_branch

        return response


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
