"""
Orient Tool

MCP tool for session initialization and staleness detection.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from src.configs import get_logger
from src.configs.runtime import get_llm_provider
from src.configs.yaml_config import load_yaml_config
from src.external.git import (
    count_tracked_files,
    get_commits_since,
    get_current_branch,
    get_merge_commits_since,
)
from src.configs.services import get_collection
from src.external.git.subprocess_utils import git_single_line

logger = get_logger("tools.orient")

# =============================================================================
# Constants
# =============================================================================

# Threshold for significant file count change (triggers reindex suggestion)
FILE_COUNT_CHANGE_THRESHOLD = 5

# Recent work defaults for orient_session summary
RECENT_WORK_DAYS = 7
RECENT_WORK_LIMIT = 5


# =============================================================================
# LLM Provider Health Check
# =============================================================================


def check_llm_health() -> dict[str, Any]:
    """
    Check if the configured LLM provider is available.

    Returns:
        Dict with:
            provider: str - Configured provider name
            available: bool - Whether provider is ready
            warning: str - Warning message if not available (optional)
    """
    from src.external.llm import get_available_providers

    config = load_yaml_config()
    provider = get_llm_provider()

    result: dict[str, Any] = {
        "provider": provider,
        "available": False,
    }

    if provider == "none":
        result["warning"] = (
            "No LLM provider configured. Auto-capture summarization disabled. "
            "Set llm.primary_provider in ~/.cortex/config.yaml"
        )
        return result

    # Check if provider is available
    available = get_available_providers(config)
    if provider in available:
        result["available"] = True
    else:
        # Provider-specific messages
        if provider == "claude-cli":
            result["warning"] = (
                "claude-cli configured but not available. "
                "Ensure the summarizer proxy is running (cortex daemon restart)"
            )
        elif provider == "anthropic":
            result["warning"] = (
                "anthropic configured but ANTHROPIC_API_KEY not set"
            )
        elif provider == "openrouter":
            result["warning"] = (
                "openrouter configured but OPENROUTER_API_KEY not set"
            )
        elif provider == "ollama":
            result["warning"] = (
                "ollama configured but server not reachable at localhost:11434"
            )
        else:
            result["warning"] = f"LLM provider '{provider}' not available"

    return result


# =============================================================================
# Staleness Detection
# =============================================================================


@dataclass
class StalenessResult:
    """Result of staleness detection."""

    needs_reindex: bool = False
    reasons: list[str] = field(default_factory=list)


class StalenessDetector:
    """Detects when the index needs refreshing."""

    def __init__(
        self,
        project_path: str,
        indexed_branch: Optional[str],
        current_branch: str,
        indexed_commit: Optional[str],
        indexed_file_count: int,
    ):
        self.project_path = project_path
        self.indexed_branch = indexed_branch
        self.current_branch = current_branch
        self.indexed_commit = indexed_commit
        self.indexed_file_count = indexed_file_count

    def detect(self) -> StalenessResult:
        """Check for all staleness signals."""
        result = StalenessResult()

        if not self.indexed_commit:
            return result

        self._check_branch_change(result)
        self._check_new_commits(result)
        self._check_file_count_change(result)

        return result

    def _check_branch_change(self, result: StalenessResult) -> None:
        """Signal 1: Branch switch detection."""
        if self.indexed_branch and self.current_branch != self.indexed_branch:
            result.needs_reindex = True
            result.reasons.append(
                f"Branch changed: {self.indexed_branch} -> {self.current_branch}"
            )

    def _check_new_commits(self, result: StalenessResult) -> None:
        """Signal 2 & 3: New commits and merges since index."""
        commits_since = get_commits_since(self.project_path, self.indexed_commit)
        if commits_since > 0:
            result.needs_reindex = True
            result.reasons.append(f"{commits_since} new commit(s) since last index")

            # Additional info about merges
            merges = get_merge_commits_since(self.project_path, self.indexed_commit)
            if merges > 0:
                result.reasons.append(f"Including {merges} merge commit(s)")

    def _check_file_count_change(self, result: StalenessResult) -> None:
        """Signal 4: Significant file count change."""
        current_file_count = count_tracked_files(self.project_path)
        file_diff = abs(current_file_count - self.indexed_file_count)
        if file_diff > FILE_COUNT_CHANGE_THRESHOLD:
            result.needs_reindex = True
            result.reasons.append(
                f"File count changed: {self.indexed_file_count} -> {current_file_count}"
            )


# =============================================================================
# Repository Context
# =============================================================================


class RepositoryContext:
    """Fetches and assembles repository context from ChromaDB."""

    def __init__(self, collection, repo_name: str, branch: str):
        self.collection = collection
        self.repo_name = repo_name
        self.branch = branch

    def is_indexed(self) -> bool:
        """Check if repository has indexed file_metadata documents.

        Uses limit=1 for fast existence check.

        Returns:
            True if at least one file_metadata doc exists for this repo
        """
        try:
            result = self.collection.get(
                where={
                    "$and": [
                        {"type": "file_metadata"},
                        {"repository": self.repo_name},
                    ]
                },
                include=[],
                limit=1,
            )
            return len(result.get("ids", [])) > 0
        except Exception as e:
            logger.warning(f"Failed to check index status: {e}")
            return False

    def fetch_skeleton(self) -> Optional[dict]:
        """Fetch skeleton data from collection."""
        try:
            # Try current branch first
            skeleton_id = f"{self.repo_name}:skeleton:{self.branch}"
            result = self.collection.get(
                ids=[skeleton_id],
                include=["documents", "metadatas"],
            )

            if not result["documents"]:
                # Fallback: any skeleton for this repository
                fallback = self.collection.get(
                    where={"$and": [{"type": "skeleton"}, {"repository": self.repo_name}]},
                    include=["documents", "metadatas"],
                )
                if fallback["documents"]:
                    result = {
                        "documents": [fallback["documents"][0]],
                        "metadatas": [fallback["metadatas"][0]],
                    }

            if result["documents"]:
                meta = result["metadatas"][0]
                return {
                    "tree": result["documents"][0],
                    "total_files": meta.get("total_files", 0),
                    "total_dirs": meta.get("total_dirs", 0),
                    "branch": meta.get("branch", "unknown"),
                    "updated_at": meta.get("updated_at"),
                    "indexed_commit": meta.get("indexed_commit"),
                }
        except Exception as e:
            logger.warning(f"Failed to fetch skeleton: {e}")

        return None

    def fetch_tech_stack(self) -> Optional[str]:
        """Fetch tech stack context from collection."""
        try:
            tech_stack_id = f"{self.repo_name}:tech_stack"
            result = self.collection.get(
                ids=[tech_stack_id],
                include=["documents"],
            )
            if result["documents"]:
                return result["documents"][0]
        except Exception as e:
            logger.warning(f"Failed to fetch tech stack: {e}")

        return None

    def fetch_focused_initiative(self) -> Optional[dict]:
        """Fetch focused initiative with stale detection."""
        try:
            from src.tools.initiatives import check_initiative_staleness, STALE_THRESHOLD_DAYS

            # Get focus document
            focus_id = f"{self.repo_name}:focus"
            focus_result = self.collection.get(
                ids=[focus_id],
                include=["metadatas"],
            )

            if not focus_result["ids"]:
                return None

            focus_meta = focus_result["metadatas"][0]
            initiative_id = focus_meta.get("initiative_id", "")

            if not initiative_id:
                return None

            # Get initiative details
            init_result = self.collection.get(
                ids=[initiative_id],
                include=["documents", "metadatas"],
            )

            if not init_result["ids"]:
                return None

            init_meta = init_result["metadatas"][0]
            updated_at = init_meta.get("updated_at", "")

            # Check staleness
            is_stale, days_inactive = check_initiative_staleness(updated_at, STALE_THRESHOLD_DAYS)

            return {
                "id": initiative_id,
                "name": init_meta.get("name", ""),
                "goal": init_meta.get("goal", ""),
                "status": init_meta.get("status", "active"),
                "updated_at": updated_at,
                "days_inactive": days_inactive,
                "stale": is_stale,
                "prompt": "still_working_or_complete" if is_stale else None,
            }

        except Exception as e:
            logger.warning(f"Failed to fetch focused initiative: {e}")

        return None

    def fetch_active_initiatives(self) -> list[dict]:
        """Fetch all active (non-completed) initiatives for a repository."""
        try:
            result = self.collection.get(
                where={
                    "$and": [
                        {"type": "initiative"},
                        {"repository": self.repo_name},
                        {"status": "active"},
                    ]
                },
                include=["metadatas"],
            )

            initiatives = []
            for i, doc_id in enumerate(result.get("ids", [])):
                meta = result["metadatas"][i] if result.get("metadatas") else {}
                initiatives.append({
                    "id": doc_id,
                    "name": meta.get("name", ""),
                    "goal": meta.get("goal", ""),
                })

            return initiatives

        except Exception as e:
            logger.warning(f"Failed to fetch active initiatives: {e}")

        return []

    def fetch_recent_work(self, days: int = RECENT_WORK_DAYS, limit: int = RECENT_WORK_LIMIT) -> list[str]:
        """Fetch brief highlights of recent work (session summaries/notes)."""
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)

            # Query recent session summaries and notes
            results = self.collection.get(
                where={
                    "$and": [
                        {"repository": self.repo_name},
                        {"type": {"$in": ["session_summary", "note"]}},
                    ]
                },
                include=["documents", "metadatas"],
            )

            # Filter by date and extract highlights
            items = []
            for i, doc_id in enumerate(results.get("ids", [])):
                meta = results["metadatas"][i] if results.get("metadatas") else {}
                doc = results["documents"][i] if results.get("documents") else ""

                created_at = meta.get("created_at", "")
                if not created_at:
                    continue

                try:
                    item_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    if item_date < cutoff:
                        continue
                except (ValueError, TypeError):
                    continue

                # Extract highlight
                title = meta.get("title", "")
                if not title and doc:
                    first_line = doc.split("\n")[0].strip()
                    if first_line.lower().startswith("session summary"):
                        lines = [l.strip() for l in doc.split("\n") if l.strip()]
                        title = lines[1] if len(lines) > 1 else first_line
                    else:
                        title = first_line[:100]

                if title:
                    items.append({
                        "created_at": created_at,
                        "highlight": title,
                    })

            # Sort by date descending and limit
            items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            items = items[:limit]

            return [item["highlight"] for item in items]

        except Exception as e:
            logger.warning(f"Failed to fetch recent work: {e}")

        return []


# =============================================================================
# Update Checker
# =============================================================================


def check_version_updates(project_path: str) -> dict[str, Any]:
    """Check for Cortex updates."""
    result: dict[str, Any] = {}

    try:
        from src.tools.orient.version import check_for_updates, get_current_version

        current = get_current_version()
        result["current_version"] = current["version"]
        result["current_commit"] = (
            current["git_commit"][:7]
            if len(current["git_commit"]) >= 7
            else current["git_commit"]
        )

        # Get local HEAD for comparison
        local_head = git_single_line(["rev-parse", "HEAD"], project_path)

        update_info = check_for_updates(local_head=local_head)
        if update_info.get("update_available"):
            result["update_available"] = True
            if update_info.get("latest_commit"):
                result["latest_commit"] = update_info["latest_commit"][:7]
            if update_info.get("message"):
                result["update_message"] = update_info["message"]

    except Exception as e:
        logger.debug(f"Could not check for updates: {e}")

    return result


# =============================================================================
# Main Orient Function
# =============================================================================


def orient_session(project_path: str) -> str:
    """
    Entry point for starting a session. Returns everything Claude needs to orient.

    Detects stale index and prompts for reindexing after merges, branch switches,
    or significant code changes.

    Args:
        project_path: Absolute path to the project repository

    Returns:
        JSON with:
            repository: str - Repository name (derived from path)
            branch: str - Current git branch
            indexed: bool - Is this repo indexed?
            last_indexed: str - When was it last indexed?
            file_count: int - How many files indexed?
            needs_reindex: bool - Is the index stale?
            reindex_reason: str - Why reindex is needed (if applicable)
            skeleton: dict - File tree structure (if available)
            tech_stack: str - Technologies and patterns (if set)
            active_initiative: dict - Current workstream (if any)
    """
    logger.info(f"Orienting session for: {project_path}")

    try:
        collection = get_collection()

        # Derive repository name from path
        repo_name = project_path.rstrip("/").split("/")[-1]
        current_branch = get_current_branch(project_path)

        # Fetch repository context
        context = RepositoryContext(collection, repo_name, current_branch)

        # Check if indexed by querying DB for file_metadata docs (fast, limit=1)
        indexed = context.is_indexed()

        # Fetch skeleton for file count and indexed_commit
        skeleton_data = context.fetch_skeleton()

        # Get staleness info from skeleton metadata
        indexed_file_count = skeleton_data.get("total_files", 0) if skeleton_data else 0
        indexed_branch = skeleton_data.get("branch") if skeleton_data else None
        indexed_commit = skeleton_data.get("indexed_commit") if skeleton_data else None

        # Staleness detection using skeleton metadata
        detector = StalenessDetector(
            project_path=project_path,
            indexed_branch=indexed_branch,
            current_branch=current_branch,
            indexed_commit=indexed_commit,
            indexed_file_count=indexed_file_count,
        )
        staleness = detector.detect() if indexed else StalenessResult()
        tech_stack = context.fetch_tech_stack()
        focused_initiative = context.fetch_focused_initiative()
        active_initiatives = context.fetch_active_initiatives()
        recent_work = context.fetch_recent_work()

        # Get last indexed timestamp from skeleton (updated_at)
        last_indexed = skeleton_data.get("updated_at") if skeleton_data else None

        # Build response
        response: dict[str, Any] = {
            "repository": repo_name,
            "branch": current_branch,
            "indexed": indexed,
            "last_indexed": last_indexed or "never",
            "file_count": indexed_file_count,
            "needs_reindex": staleness.needs_reindex,
        }

        if staleness.reasons:
            response["reindex_reason"] = "; ".join(staleness.reasons)

        if skeleton_data:
            response["skeleton"] = skeleton_data

        if tech_stack:
            response["tech_stack"] = tech_stack
        else:
            response["prompt_set_context"] = (
                "No repo context set. Use set_repo_context to describe "
                "this project's tech stack and patterns."
            )

        if recent_work:
            response["recent_work"] = recent_work

        if focused_initiative:
            response["focused_initiative"] = focused_initiative

        if active_initiatives:
            response["active_initiatives"] = active_initiatives

        # Add version/update info
        version_info = check_version_updates(project_path)
        response.update(version_info)

        # Check LLM provider health
        llm_health = check_llm_health()
        if llm_health.get("warning"):
            response["llm_warning"] = llm_health["warning"]
        response["llm_provider"] = llm_health.get("provider", "none")
        response["llm_available"] = llm_health.get("available", False)

        logger.info(f"Orient complete: indexed={indexed}, needs_reindex={staleness.needs_reindex}")

        return json.dumps(response, indent=2)

    except Exception as e:
        logger.error(f"Orient session error: {e}")
        return json.dumps(
            {
                "error": str(e),
                "indexed": False,
                "needs_reindex": False,
            }
        )
