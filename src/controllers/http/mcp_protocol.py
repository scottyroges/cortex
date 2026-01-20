"""
MCP Protocol Endpoints

HTTP endpoints for MCP tool calls (daemon mode).
Uses Pydantic models as the single source of truth for tool schemas.

Consolidated tool set (12 tools):
1. orient_session - Session entry point
2. search_cortex - Search memory
3. recall_recent_work - Timeline view of recent work
4. get_skeleton - File tree structure
5. manage_initiative - CRUD for initiatives
6. save_memory - Save notes and insights
7. conclude_session - End-of-session summary
8. ingest_codebase - Code ingestion
9. validate_insight - Validate stale insights
10. configure_cortex - Configuration and status
11. cleanup_storage - Clean up orphaned data
12. delete_document - Delete a single document
"""

from typing import Any, Callable, Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field, ValidationError

from src.configs import get_logger

logger = get_logger("http.mcp")

router = APIRouter()


# --- Request/Response Models ---


class MCPToolCallRequest(BaseModel):
    """Request body for MCP tool call."""

    name: str
    arguments: dict = {}


class MCPToolResult(BaseModel):
    """Response for MCP tool call."""

    content: Any
    isError: bool = False


# --- Tool Input Models (10 Consolidated Tools) ---
# These Pydantic models are the SINGLE SOURCE OF TRUTH for tool schemas.
# The JSON Schema is auto-generated from these models.


# 1. orient_session
class OrientSessionInput(BaseModel):
    project_path: str = Field(..., description="Absolute path to the project repository")


# 2. search_cortex
class SearchCortexInput(BaseModel):
    query: str = Field(..., description="Natural language search query")
    repository: Optional[str] = Field(None, description="Repository identifier for filtering")
    min_score: Optional[float] = Field(None, description="Minimum relevance score (0-1)")
    branch: Optional[str] = Field(None, description="Optional branch filter")
    initiative: Optional[str] = Field(None, description="Initiative ID or name to filter results")
    include_completed: bool = Field(True, description="Include content from completed initiatives")
    types: Optional[list[str]] = Field(
        None,
        description="Filter by document types. Valid: skeleton, note, session_summary, insight, tech_stack, initiative, file_metadata, data_contract, entry_point, dependency, idiom. Example: ['note', 'insight'] for understanding-only search.",
    )
    preset: Optional[str] = Field(
        None,
        description="Search preset. Overrides types. Valid: 'understanding' (insights, notes), 'navigation' (file_metadata, entry_points), 'structure' (file_metadata, dependencies, skeleton)",
    )


# 3. recall_recent_work
class RecallRecentWorkInput(BaseModel):
    repository: str = Field(..., description="Repository identifier")
    days: int = Field(7, description="Number of days to look back (default: 7)")
    limit: int = Field(20, description="Maximum number of items to return (default: 20)")
    include_code: bool = Field(
        False, description="Include code changes in results (default: false, notes/session_summaries only)"
    )


# 4. get_skeleton
class GetSkeletonInput(BaseModel):
    repository: Optional[str] = Field(None, description="Repository name")


# 5. manage_initiative (consolidated from create/list/focus/complete/summarize)
class ManageInitiativeInput(BaseModel):
    action: Literal["create", "list", "focus", "complete", "summarize"] = Field(
        ..., description="Action to perform: create, list, focus, complete, or summarize"
    )
    repository: str = Field(..., description="Repository identifier (e.g., 'Cortex', 'my-app')")
    name: Optional[str] = Field(
        None, description="Initiative name (required for create)"
    )
    initiative: Optional[str] = Field(
        None, description="Initiative ID or name (required for focus/complete/summarize)"
    )
    goal: Optional[str] = Field(
        None, description="Optional goal/description (for create)"
    )
    auto_focus: bool = Field(
        True, description="Whether to focus this initiative on creation (default: true)"
    )
    summary: Optional[str] = Field(
        None, description="Completion summary (required for complete)"
    )
    status: Literal["all", "active", "completed"] = Field(
        "all", description="Filter by status (for list): 'all', 'active', or 'completed'"
    )


# 6. save_memory (consolidated from save_note + insight)
class SaveMemoryInput(BaseModel):
    content: str = Field(..., description="The content to save (note text or insight analysis)")
    kind: Literal["note", "insight"] = Field(
        ..., description="Type of memory: 'note' for general notes, 'insight' for file-linked analysis"
    )
    title: Optional[str] = Field(None, description="Optional title")
    tags: Optional[list[str]] = Field(None, description="Optional tags for categorization")
    repository: Optional[str] = Field(None, description="Repository identifier")
    initiative: Optional[str] = Field(
        None, description="Initiative ID or name to tag (uses focused initiative if not specified)"
    )
    files: Optional[list[str]] = Field(
        None, description="List of file paths (REQUIRED when kind='insight')"
    )


# 7. conclude_session (renamed from session_summary_to_cortex)
class ConcludeSessionInput(BaseModel):
    summary: str = Field(
        ...,
        description="Detailed summary of the session: what changed, why, decisions made, problems solved, and future TODOs",
    )
    changed_files: list[str] = Field(..., description="List of modified file paths")
    repository: Optional[str] = Field(None, description="Repository identifier")
    initiative: Optional[str] = Field(
        None, description="Initiative ID or name to tag (uses focused initiative if not specified)"
    )


# 8. ingest_codebase (consolidated from ingest + get_ingest_status)
class IngestCodebaseInput(BaseModel):
    action: Literal["ingest", "status"] = Field(
        "ingest", description="Action: 'ingest' to index code, 'status' to check task progress"
    )
    path: Optional[str] = Field(
        None, description="Absolute path to codebase root (required for action='ingest')"
    )
    repository: Optional[str] = Field(
        None, description="Optional repository identifier (defaults to directory name)"
    )
    force_full: bool = Field(False, description="Force full re-ingestion")
    include_patterns: Optional[list[str]] = Field(
        None,
        description="Glob patterns for selective ingestion. Only files matching at least one pattern are indexed (e.g., ['src/**', 'tests/**'])",
    )
    use_cortexignore: bool = Field(
        True, description="Load ignore patterns from global ~/.cortex/cortexignore and .cortexignore files"
    )
    task_id: Optional[str] = Field(
        None, description="Task ID to check status (required for action='status')"
    )


# 9. validate_insight
class ValidateInsightInput(BaseModel):
    insight_id: str = Field(..., description="The insight ID to validate (e.g., 'insight:abc123')")
    validation_result: Literal["still_valid", "partially_valid", "no_longer_valid"] = Field(
        ..., description="Your assessment after re-reading the linked files"
    )
    notes: Optional[str] = Field(
        None, description="Optional notes about what changed or why validation failed"
    )
    deprecate: bool = Field(
        False,
        description="If True and validation_result is 'no_longer_valid', mark insight as deprecated",
    )
    replacement_insight: Optional[str] = Field(
        None, description="If deprecating, optionally provide updated insight content to save as replacement"
    )
    repository: Optional[str] = Field(None, description="Repository identifier (optional)")


# 10. configure_cortex (expanded to absorb repo context + autocapture)
class ConfigureCortexInput(BaseModel):
    # Runtime config
    min_score: Optional[float] = Field(None, description="Minimum relevance score (0-1)")
    verbose: Optional[bool] = Field(None, description="Enable verbose output")
    top_k_retrieve: Optional[int] = Field(None, description="Candidates before reranking")
    top_k_rerank: Optional[int] = Field(None, description="Results after reranking")
    llm_provider: Optional[str] = Field(
        None, description="LLM provider: anthropic, claude-cli, ollama, openrouter, or none"
    )
    recency_boost: Optional[bool] = Field(
        None, description="Enable recency boosting for notes/session_summaries"
    )
    recency_half_life_days: Optional[float] = Field(
        None, description="Days until recency boost decays to ~0.5"
    )
    enabled: Optional[bool] = Field(None, description="Enable or disable Cortex memory system")
    # Repo context (absorbs set_repo_context)
    repository: Optional[str] = Field(
        None, description="Repository to set tech stack for (requires tech_stack)"
    )
    tech_stack: Optional[str] = Field(
        None, description="Technologies, patterns, architecture description"
    )
    # Autocapture config (absorbs configure_autocapture)
    autocapture_enabled: Optional[bool] = Field(None, description="Enable or disable auto-capture")
    autocapture_llm_provider: Optional[str] = Field(
        None, description="LLM provider for autocapture summarization"
    )
    autocapture_min_tokens: Optional[int] = Field(
        None, description="Minimum token threshold for significant sessions"
    )
    autocapture_min_tool_calls: Optional[int] = Field(
        None, description="Minimum tool call threshold"
    )
    autocapture_min_file_edits: Optional[int] = Field(
        None, description="Minimum file edit threshold"
    )
    autocapture_async: Optional[bool] = Field(
        None, description="Run autocapture async (default: True)"
    )
    # Status query (absorbs get_autocapture_status)
    get_status: bool = Field(
        False, description="If True, return full system status including autocapture"
    )


# 11. cleanup_storage
class CleanupStorageInput(BaseModel):
    action: Literal["preview", "execute"] = Field(
        "preview", description="Action: 'preview' shows what would be deleted, 'execute' performs deletion"
    )
    repository: str = Field(..., description="Repository to clean up")
    path: str = Field(..., description="Absolute path to repository root (for file existence checks)")


# 12. delete_document
class DeleteDocumentInput(BaseModel):
    document_id: str = Field(
        ..., description="The document ID to delete (e.g., 'note:abc123', 'insight:def456')"
    )


# --- Tool Registry ---


class ToolDef:
    """Definition of an MCP tool with its function, input model, and description."""

    def __init__(
        self,
        name: str,
        fn: Callable,
        input_model: type[BaseModel],
        description: str,
    ):
        self.name = name
        self.fn = fn
        self.input_model = input_model
        self.description = description

    def schema(self) -> dict:
        """Generate MCP-compatible JSON schema for this tool."""
        json_schema = self.input_model.model_json_schema()
        # Remove Pydantic metadata that MCP doesn't need
        json_schema.pop("title", None)
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": json_schema,
        }


def _build_tool_registry() -> dict[str, ToolDef]:
    """
    Build the tool registry with lazy imports to avoid circular dependencies.

    Returns a dict mapping tool names to their ToolDef (12 consolidated tools).
    """
    from src.tools import (
        cleanup_storage,
        configure_cortex,
        conclude_session,
        delete_document,
        get_skeleton,
        ingest_codebase,
        manage_initiative,
        orient_session,
        recall_recent_work,
        save_memory,
        search_cortex,
        validate_insight,
    )

    tools = [
        # 1. Session entry point
        ToolDef(
            name="orient_session",
            fn=orient_session,
            input_model=OrientSessionInput,
            description="Entry point for starting a session. Returns indexed status, skeleton, tech stack, active initiative, and staleness detection.",
        ),
        # 2. Search memory
        ToolDef(
            name="search_cortex",
            fn=search_cortex,
            input_model=SearchCortexInput,
            description="Search the Cortex memory for relevant code, documentation, or notes. Use preset='understanding' for notes/insights, preset='navigation' for code structure.",
        ),
        # 3. Recent work timeline
        ToolDef(
            name="recall_recent_work",
            fn=recall_recent_work,
            input_model=RecallRecentWorkInput,
            description="Recall recent session summaries and notes for a repository. Returns a timeline view of recent work, grouped by day. Answers 'What did I work on this week?'",
        ),
        # 4. File tree structure
        ToolDef(
            name="get_skeleton",
            fn=get_skeleton,
            input_model=GetSkeletonInput,
            description="Get the file tree structure for a repository.",
        ),
        # 5. Initiative management (CRUD)
        ToolDef(
            name="manage_initiative",
            fn=manage_initiative,
            input_model=ManageInitiativeInput,
            description="Manage initiatives (multi-session work tracking). Actions: 'create' (new initiative), 'list' (show all), 'focus' (switch active), 'complete' (mark done), 'summarize' (get progress narrative).",
        ),
        # 6. Save notes/insights
        ToolDef(
            name="save_memory",
            fn=save_memory,
            input_model=SaveMemoryInput,
            description="Save knowledge to Cortex memory. Use kind='note' for general notes/decisions. Use kind='insight' for code analysis linked to specific files (files parameter required).",
        ),
        # 7. End-of-session summary
        ToolDef(
            name="conclude_session",
            fn=conclude_session,
            input_model=ConcludeSessionInput,
            description="Save a session summary and re-index changed files. Write a comprehensive summary capturing: what changed and WHY, key decisions, problems solved, gotchas discovered, and TODOs.",
        ),
        # 8. Code ingestion
        ToolDef(
            name="ingest_codebase",
            fn=ingest_codebase,
            input_model=IngestCodebaseInput,
            description="Index a codebase into Cortex memory. Use action='ingest' to start indexing, action='status' to check progress of async tasks.",
        ),
        # 9. Validate stale insights
        ToolDef(
            name="validate_insight",
            fn=validate_insight,
            input_model=ValidateInsightInput,
            description="Validate a stored insight against current code state. Use after re-reading linked files to confirm accuracy. Can deprecate invalid insights and create replacements.",
        ),
        # 10. Configuration and status
        ToolDef(
            name="configure_cortex",
            fn=configure_cortex,
            input_model=ConfigureCortexInput,
            description="Configure Cortex settings, set repository tech stack, configure autocapture, or get system status (get_status=True).",
        ),
        # 11. Cleanup orphaned storage
        ToolDef(
            name="cleanup_storage",
            fn=cleanup_storage,
            input_model=CleanupStorageInput,
            description="Clean up orphaned data from Cortex memory. Removes file_metadata, insights, and dependencies for files that no longer exist. Use action='preview' to see what would be deleted, 'execute' to delete.",
        ),
        # 12. Delete single document
        ToolDef(
            name="delete_document",
            fn=delete_document,
            input_model=DeleteDocumentInput,
            description="Delete a single document from Cortex memory by ID. Use when a note, insight, or other document is stale or no longer applies.",
        ),
    ]

    return {tool.name: tool for tool in tools}


# Lazy-initialized registry
_tool_registry: dict[str, ToolDef] | None = None


def _get_registry() -> dict[str, ToolDef]:
    """Get or initialize the tool registry."""
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = _build_tool_registry()
    return _tool_registry


# --- Endpoints ---


@router.get("/tools/list")
def mcp_list_tools() -> dict[str, Any]:
    """
    List available MCP tools.

    Returns tool definitions in MCP protocol format with auto-generated schemas.
    """
    logger.info("MCP tools/list requested")
    registry = _get_registry()
    return {"tools": [tool.schema() for tool in registry.values()]}


@router.post("/tools/call")
def mcp_call_tool(request: MCPToolCallRequest) -> MCPToolResult:
    """
    Execute an MCP tool with Pydantic validation.

    Args:
        name: Tool name
        arguments: Tool arguments

    Returns:
        Tool result or error
    """
    logger.info(f"MCP tools/call: {request.name}")

    registry = _get_registry()
    tool = registry.get(request.name)

    if not tool:
        logger.error(f"Unknown tool: {request.name}")
        return MCPToolResult(
            content={"error": f"Unknown tool: {request.name}"},
            isError=True,
        )

    try:
        # Validate input with Pydantic model
        validated = tool.input_model.model_validate(request.arguments)
        # Call function with validated arguments
        result = tool.fn(**validated.model_dump(exclude_none=True))
        logger.debug(f"Tool {request.name} completed successfully")
        return MCPToolResult(content=result)
    except ValidationError as e:
        logger.error(f"Tool {request.name} validation failed: {e}")
        return MCPToolResult(
            content={"error": f"Invalid arguments: {e.errors()}"},
            isError=True,
        )
    except Exception as e:
        logger.error(f"Tool {request.name} failed: {e}")
        return MCPToolResult(
            content={"error": str(e)},
            isError=True,
        )
