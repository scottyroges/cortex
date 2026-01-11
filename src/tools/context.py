"""
Context Tools

MCP tools for managing project domain context and status.
"""

import json
from datetime import datetime, timezone
from typing import Optional

from logging_config import get_logger
from src.git import get_current_branch
from src.security import scrub_secrets
from src.tools.services import get_collection, get_searcher

logger = get_logger("tools.context")


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
