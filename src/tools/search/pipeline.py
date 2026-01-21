"""
Search Pipeline

Orchestrates the full search process: hybrid search, reranking,
boosting, staleness checks, and result formatting.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Optional

from src.configs import get_logger
from src.configs.services import CONFIG, get_collection, get_reranker, get_repo_path, get_searcher
from src.external.git import get_current_branch
from src.tools.initiatives.focus import get_focus_id
from src.tools.initiatives.utils import resolve_initiative_id
from src.tools.search.filters import apply_initiative_boost, build_branch_aware_filter, filter_by_initiative
from src.tools.search.recency import apply_recency_boost
from src.tools.search.type_scoring import apply_type_boost
from src.tools.search.staleness import check_insight_staleness, check_note_staleness, format_verification_warning

logger = get_logger("search.pipeline")


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
            self._initiative_id = resolve_initiative_id(
                self._collection, self.repository, self.initiative
            )
            if self._initiative_id:
                logger.debug(f"Initiative filter: {self._initiative_id}")

        # Get focused initiative for boosting (if no specific initiative filter)
        if not self._initiative_id and self.repository:
            self._focused_initiative_id = get_focus_id(
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
            ranked = filter_by_initiative(ranked, self._initiative_id, self.include_completed)
            logger.debug(f"Initiative filter applied: {len(ranked)} results remain")

        # Apply initiative boost for focused initiative (if no explicit filter)
        if self._focused_initiative_id and not self._initiative_id:
            ranked = apply_initiative_boost(ranked, self._focused_initiative_id)
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
            "created_at": meta.get("created_at"),
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
