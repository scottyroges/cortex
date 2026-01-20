"""
Autocapture API Endpoints

HTTP endpoints for session auto-capture, including focused initiative lookup,
session summary saving, queue processing, and synchronous processing.
"""

import json as json_module
from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.configs import get_logger
from src.configs.paths import get_data_path

logger = get_logger("http.api.autocapture")

router = APIRouter()


# --- Request/Response Models ---


class SessionSummaryRequest(BaseModel):
    """Request body for session summary (from auto-capture hook)."""
    summary: str
    changed_files: list[str] = []
    repository: str = "global"
    initiative_id: Optional[str] = None  # Initiative ID (preferred)
    initiative: Optional[str] = None  # Initiative name (legacy, deprecated)


class ProcessSyncRequest(BaseModel):
    """Request body for synchronous session processing."""
    session_id: str
    transcript_text: str
    files_edited: list[str] = []
    repository: str = "global"
    initiative_id: Optional[str] = None  # Initiative ID captured at session end


# --- Endpoints ---


@router.get("/focused-initiative")
def get_focused_initiative_endpoint(repository: str = Query(...)) -> dict[str, Any]:
    """
    Get the currently focused initiative for a repository.

    Used by the auto-capture hook to capture initiative context at session end.

    Args:
        repository: Repository name

    Returns:
        Focused initiative info or null if none focused
    """
    from src.tools.initiatives import get_focused_initiative

    try:
        result = get_focused_initiative(repository)
        if result:
            return {
                "status": "success",
                "initiative_id": result.get("initiative_id"),
                "initiative_name": result.get("initiative_name"),
            }
        return {
            "status": "success",
            "initiative_id": None,
            "initiative_name": None,
        }
    except Exception as e:
        logger.warning(f"Failed to get focused initiative: {e}")
        return {
            "status": "error",
            "error": str(e),
            "initiative_id": None,
            "initiative_name": None,
        }


@router.post("/session-summary")
def save_session_summary(request: SessionSummaryRequest) -> dict[str, Any]:
    """
    Save a session summary to Cortex memory.

    Used by the auto-capture hook to save session summaries.
    Delegates to conclude_session for proper initiative handling.

    Args:
        summary: Session summary text
        changed_files: List of files edited in the session
        repository: Repository name (default: "global")
        initiative_id: Initiative ID to tag (preferred)
        initiative: Initiative name to tag (legacy, deprecated)
    """
    from src.tools.memory import conclude_session

    logger.info(f"Save session summary: repository={request.repository}, files={len(request.changed_files)}")

    # Use initiative_id if provided, otherwise fall back to initiative name
    initiative = request.initiative_id or request.initiative

    try:
        result_json = conclude_session(
            summary=request.summary,
            changed_files=request.changed_files,
            repository=request.repository,
            initiative=initiative,
        )
        result = json_module.loads(result_json)

        if result.get("status") == "success":
            return {
                "status": "success",
                "session_id": result.get("session_id"),
                "summary_length": len(request.summary),
                "files_count": len(request.changed_files),
                "initiative": result.get("initiative"),
            }
        else:
            return {
                "status": "error",
                "error": result.get("error", "Unknown error"),
            }
    except Exception as e:
        logger.error(f"Failed to save session summary: {e}")
        return {
            "status": "error",
            "error": str(e),
        }


@router.get("/autocapture/status")
def autocapture_status() -> dict[str, Any]:
    """
    Get auto-capture system status.

    Returns configuration, hook status, and recent captures.
    """
    cortex_data = get_data_path()

    # Check hook installation
    hook_script = cortex_data / "hooks" / "claude_session_end.py"
    hook_log = cortex_data / "hook.log"
    captured_sessions = cortex_data / "captured_sessions.json"
    capture_queue = cortex_data / "capture_queue.json"

    # Count recent captures
    recent_captures = 0
    if captured_sessions.exists():
        try:
            import json
            data = json.loads(captured_sessions.read_text())
            recent_captures = len(data.get("captured", []))
        except Exception:
            pass

    # Count queued sessions
    queued_count = 0
    if capture_queue.exists():
        try:
            import json
            data = json.loads(capture_queue.read_text())
            queued_count = len(data) if isinstance(data, list) else 0
        except Exception:
            pass

    # Get last log entries
    last_logs = []
    if hook_log.exists():
        try:
            lines = hook_log.read_text().strip().split("\n")
            last_logs = lines[-5:]  # Last 5 log entries
        except Exception:
            pass

    return {
        "hook_script_installed": hook_script.exists(),
        "hook_script_path": str(hook_script),
        "captured_sessions_count": recent_captures,
        "queued_sessions_count": queued_count,
        "last_hook_logs": last_logs,
    }


@router.post("/process-queue")
def process_queue() -> dict[str, Any]:
    """
    Trigger immediate processing of the capture queue.

    Called by the session end hook to notify the daemon that
    new sessions are ready for processing.
    """
    from src.tools.autocapture import trigger_processing

    trigger_processing()
    logger.debug("Queue processing triggered")

    return {
        "status": "triggered",
    }


@router.post("/process-sync")
def process_sync(request: ProcessSyncRequest) -> dict[str, Any]:
    """
    Process a session synchronously.

    Unlike /process-queue which just triggers async processing,
    this endpoint does the LLM summarization and commit immediately
    and returns the result. Used by the hook when auto_commit_async=false.

    Args:
        session_id: Session identifier
        transcript_text: Full transcript text for summarization
        files_edited: List of files edited in the session
        repository: Repository name (default: "global")
        initiative_id: Initiative ID captured at session end

    Returns:
        Result with status, summary length, and commit info
    """
    from src.configs.yaml_config import load_yaml_config
    from src.external.llm import get_provider

    logger.info(f"Processing session synchronously: {request.session_id}")

    if not request.transcript_text or not request.transcript_text.strip():
        return {"status": "skipped", "reason": "empty transcript"}

    # Get LLM provider
    try:
        config = load_yaml_config()
        provider = get_provider(config)
        if provider is None:
            return {"status": "error", "error": "No LLM provider available"}
    except Exception as e:
        logger.error(f"Failed to get LLM provider: {e}")
        return {"status": "error", "error": f"No LLM provider: {e}"}

    # Generate summary
    try:
        # Limit transcript to 100k chars
        transcript_text = request.transcript_text[:100000]
        summary = provider.summarize_session(transcript_text)
        if not summary:
            return {"status": "error", "error": "Summarization returned empty result"}
    except Exception as e:
        logger.error(f"Summarization failed: {e}")
        return {"status": "error", "error": f"Summarization failed: {e}"}

    # Save session summary with initiative context
    try:
        save_result = save_session_summary(SessionSummaryRequest(
            summary=summary,
            changed_files=request.files_edited,
            repository=request.repository,
            initiative_id=request.initiative_id,
        ))
        logger.info(f"Session summary saved synchronously: {request.session_id}")
        return {
            "status": "success",
            "session_id": request.session_id,
            "summary_length": len(summary),
            "save_result": save_result,
        }
    except Exception as e:
        logger.error(f"Save session summary failed: {e}")
        return {"status": "error", "error": f"Save session summary failed: {e}"}
