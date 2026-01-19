"""
Context Tools

MCP tools for managing repository tech stack and initiative context.
"""

import json
from datetime import datetime, timezone
from typing import Optional

from logging_config import get_logger
from src.git import get_current_branch
from src.security import scrub_secrets
from src.tools.services import get_collection, get_repo_path, get_searcher

logger = get_logger("tools.context")


def set_repo_context(
    repository: str,
    tech_stack: str,
) -> str:
    """
    Set static tech stack context for a repository.

    This is typically set once per repository and rarely updated.
    Describes technologies, patterns, and architectural decisions.

    IMPORTANT: Only include stable, structural information that won't become stale.
    DO include: languages, frameworks, architecture patterns, module responsibilities,
    design philosophy.
    DO NOT include: version numbers, phase/status indicators, counts (e.g., '7 modules'),
    dates, or anything that changes frequently.

    Args:
        repository: Repository identifier (e.g., "Cortex", "my-app")
        tech_stack: Technologies, patterns, architecture. Focus on stable structural info.

    Returns:
        JSON with saved tech_stack context ID
    """
    if not repository:
        return json.dumps({
            "error": "Repository name is required",
        })

    if not tech_stack:
        return json.dumps({
            "error": "Tech stack description is required",
        })

    logger.info(f"Setting tech stack for repository: {repository}")

    try:
        collection = get_collection()
        repo_path = get_repo_path()
        branch = get_current_branch(repo_path) if repo_path else "unknown"
        timestamp = datetime.now(timezone.utc).isoformat()

        tech_stack_id = f"{repository}:tech_stack"
        collection.upsert(
            ids=[tech_stack_id],
            documents=[scrub_secrets(tech_stack)],
            metadatas=[{
                "type": "tech_stack",
                "repository": repository,
                "branch": branch,
                "created_at": timestamp,
                "updated_at": timestamp,
            }],
        )

        # Rebuild search index
        get_searcher().build_index()

        logger.info(f"Tech stack saved for repository '{repository}'")

        return json.dumps({
            "status": "saved",
            "repository": repository,
            "tech_stack_id": tech_stack_id,
        }, indent=2)

    except Exception as e:
        logger.error(f"Set repo context error: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e),
        })


def set_initiative(
    repository: str,
    name: str,
    status: Optional[str] = None,
) -> str:
    """
    Set or update the current initiative/workstream for a repository.

    Initiatives are dynamic - updated frequently as work progresses.

    Args:
        repository: Repository identifier (e.g., "Cortex", "my-app")
        name: Initiative/epic name (e.g., "Mongo->Postgres Migration")
        status: Current state (e.g., "Phase 2: Users done, Orders in progress")

    Returns:
        JSON with saved initiative context ID
    """
    if not repository:
        return json.dumps({
            "error": "Repository name is required",
        })

    if not name:
        return json.dumps({
            "error": "Initiative name is required",
        })

    logger.info(f"Setting initiative for repository: {repository}")

    try:
        collection = get_collection()
        repo_path = get_repo_path()
        branch = get_current_branch(repo_path) if repo_path else "unknown"
        timestamp = datetime.now(timezone.utc).isoformat()

        # Build document content
        if status:
            content = f"{name}\n\nStatus: {status}"
        else:
            content = name

        initiative_id = f"{repository}:initiative"
        collection.upsert(
            ids=[initiative_id],
            documents=[scrub_secrets(content)],
            metadatas=[{
                "type": "initiative",
                "repository": repository,
                "initiative_name": name,
                "initiative_status": status or "",
                "branch": branch,
                "created_at": timestamp,
                "updated_at": timestamp,
            }],
        )

        # Rebuild search index
        get_searcher().build_index()

        logger.info(f"Initiative saved for repository '{repository}'")

        return json.dumps({
            "status": "saved",
            "repository": repository,
            "initiative_id": initiative_id,
            "initiative_name": name,
            "initiative_status": status,
        }, indent=2)

    except Exception as e:
        logger.error(f"Set initiative error: {e}")
        return json.dumps({
            "status": "error",
            "error": str(e),
        })


def get_repo_context(
    repository: str,
) -> str:
    """
    Get stored tech stack and initiative context for a repository.

    Retrieves static tech stack info and current initiative/workstream.

    Args:
        repository: Repository identifier

    Returns:
        JSON with tech_stack and initiative context
    """
    if not repository:
        return json.dumps({
            "error": "Repository name is required",
        })

    logger.info(f"Getting context for repository: {repository}")

    try:
        collection = get_collection()

        # Fetch both context types
        tech_stack_id = f"{repository}:tech_stack"
        initiative_id = f"{repository}:initiative"

        results = collection.get(
            ids=[tech_stack_id, initiative_id],
            include=["documents", "metadatas"],
        )

        context = {
            "repository": repository,
            "tech_stack": None,
            "initiative": None,
        }

        # Parse results
        for i, doc_id in enumerate(results.get("ids", [])):
            if i < len(results.get("documents", [])):
                doc = results["documents"][i]
                meta = results["metadatas"][i] if results.get("metadatas") else {}

                if doc_id == tech_stack_id:
                    context["tech_stack"] = {
                        "content": doc,
                        "updated_at": meta.get("updated_at", "unknown"),
                    }
                elif doc_id == initiative_id:
                    context["initiative"] = {
                        "name": meta.get("initiative_name", ""),
                        "status": meta.get("initiative_status", ""),
                        "updated_at": meta.get("updated_at", "unknown"),
                    }

        has_context = context["tech_stack"] or context["initiative"]
        if not has_context:
            return json.dumps({
                "repository": repository,
                "message": "No context found for this repository",
                "hint": "Use set_repo_context for tech stack, set_initiative for workstream",
            })

        logger.info(f"Context retrieved for repository '{repository}'")

        return json.dumps(context, indent=2)

    except Exception as e:
        logger.error(f"Get context error: {e}")
        return json.dumps({"error": str(e)})
