"""
MCP Protocol Endpoints

HTTP endpoints for MCP tool calls (daemon mode).
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from logging_config import get_logger

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


# --- Tool Schemas ---

MCP_TOOL_SCHEMAS = [
    {
        "name": "orient_session",
        "description": "Entry point for starting a session. Returns indexed status, skeleton, tech stack, active initiative, and staleness detection.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Absolute path to the project repository",
                },
            },
            "required": ["project_path"],
        },
    },
    {
        "name": "search_cortex",
        "description": "Search the Cortex memory for relevant code, documentation, or notes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"},
                "repository": {"type": "string", "description": "Repository identifier for filtering"},
                "min_score": {"type": "number", "description": "Minimum relevance score (0-1)"},
                "branch": {"type": "string", "description": "Optional branch filter"},
                "initiative": {"type": "string", "description": "Initiative ID or name to filter results"},
                "include_completed": {"type": "boolean", "default": True, "description": "Include content from completed initiatives"},
                "types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by document types. Valid: code, skeleton, note, commit, insight, tech_stack, initiative. Example: ['note', 'insight'] for understanding-only search.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "ingest_code_into_cortex",
        "description": "Ingest a codebase directory into Cortex memory with AST-aware chunking.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to codebase root"},
                "repository": {"type": "string", "description": "Optional repository identifier (defaults to directory name)"},
                "force_full": {"type": "boolean", "default": False, "description": "Force full re-ingestion"},
                "include_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Glob patterns for selective ingestion. Only files matching at least one pattern are indexed (e.g., ['src/**', 'tests/**'])",
                },
                "use_cortexignore": {
                    "type": "boolean",
                    "default": True,
                    "description": "Load ignore patterns from global ~/.cortex/cortexignore and .cortexignore files",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "commit_to_cortex",
        "description": "Save a session summary and re-index changed files. IMPORTANT: Write a comprehensive summary that captures the FULL context of this session, including: (1) What was implemented/changed and WHY, (2) Key architectural decisions made, (3) Problems encountered and how they were solved, (4) Non-obvious patterns or gotchas discovered, (5) Future work or TODOs identified. This summary will be retrieved in future sessions to restore context, so include enough detail to resume this work months later.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Detailed summary of the session: what changed, why, decisions made, problems solved, and future TODOs"},
                "changed_files": {"type": "array", "items": {"type": "string"}, "description": "List of modified file paths"},
                "repository": {"type": "string", "description": "Repository identifier"},
                "initiative": {"type": "string", "description": "Initiative ID or name to tag (uses focused initiative if not specified)"},
            },
            "required": ["summary", "changed_files"],
        },
    },
    {
        "name": "save_note_to_cortex",
        "description": "Save a note, documentation snippet, or decision to Cortex memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Note content"},
                "title": {"type": "string", "description": "Optional title"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags"},
                "repository": {"type": "string", "description": "Repository identifier"},
                "initiative": {"type": "string", "description": "Initiative ID or name to tag (uses focused initiative if not specified)"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "insight_to_cortex",
        "description": "Save architectural insights linked to specific code files. **Use this tool proactively** when you've done significant code analysis and want to preserve your understanding. Examples: 'This module uses the observer pattern', 'The auth flow has a race condition here'. Insights are linked to files so future searches return both code AND your previous analysis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "insight": {"type": "string", "description": "The analysis/understanding to save"},
                "files": {"type": "array", "items": {"type": "string"}, "description": "List of file paths this insight is about (REQUIRED)"},
                "title": {"type": "string", "description": "Optional title for the insight"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags for categorization"},
                "repository": {"type": "string", "description": "Repository identifier (auto-detected if not provided)"},
                "initiative": {"type": "string", "description": "Initiative ID or name to tag (uses focused initiative if not specified)"},
            },
            "required": ["insight", "files"],
        },
    },
    {
        "name": "set_repo_context",
        "description": "Set static tech stack context for a repository. This context is returned by orient_session and helps Claude understand the codebase. IMPORTANT: Only include stable, structural information that won't become stale. DO include: languages, frameworks, architecture patterns, module responsibilities, design philosophy. DO NOT include: version numbers, phase/status indicators, counts (e.g., '7 modules'), dates, or anything that changes frequently.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {
                    "type": "string",
                    "description": "Repository identifier (e.g., 'Cortex', 'my-app')",
                },
                "tech_stack": {
                    "type": "string",
                    "description": "Technologies, patterns, architecture description. Focus on stable structural info, not specifics that get stale.",
                },
            },
            "required": ["repository", "tech_stack"],
        },
    },
    {
        "name": "set_initiative",
        "description": "(Legacy) Set or update the current initiative/workstream for a repository. Use create_initiative instead.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {
                    "type": "string",
                    "description": "Repository identifier",
                },
                "name": {
                    "type": "string",
                    "description": "Initiative/epic name",
                },
                "status": {
                    "type": "string",
                    "description": "Current state/progress (optional)",
                },
            },
            "required": ["repository", "name"],
        },
    },
    {
        "name": "create_initiative",
        "description": "Create a new initiative for a repository. Initiatives track multi-session work like epics, migrations, or features. New commits and notes are automatically tagged with the focused initiative.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {
                    "type": "string",
                    "description": "Repository identifier (e.g., 'Cortex', 'my-app')",
                },
                "name": {
                    "type": "string",
                    "description": "Initiative name (e.g., 'Auth Migration', 'Performance Optimization')",
                },
                "goal": {
                    "type": "string",
                    "description": "Optional goal/description for the initiative",
                },
                "auto_focus": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to focus this initiative on creation (default: true)",
                },
            },
            "required": ["repository", "name"],
        },
    },
    {
        "name": "list_initiatives",
        "description": "List all initiatives for a repository with optional status filtering.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {
                    "type": "string",
                    "description": "Repository identifier",
                },
                "status": {
                    "type": "string",
                    "enum": ["all", "active", "completed"],
                    "default": "all",
                    "description": "Filter by status: 'all', 'active', or 'completed'",
                },
            },
            "required": ["repository"],
        },
    },
    {
        "name": "focus_initiative",
        "description": "Set focus to an initiative. New commits and notes will be tagged with this initiative.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {
                    "type": "string",
                    "description": "Repository identifier",
                },
                "initiative": {
                    "type": "string",
                    "description": "Initiative ID or name to focus",
                },
            },
            "required": ["repository", "initiative"],
        },
    },
    {
        "name": "complete_initiative",
        "description": "Mark an initiative as completed with a summary. The initiative and its associated commits/notes remain searchable but with recency decay.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "initiative": {
                    "type": "string",
                    "description": "Initiative ID or name to complete",
                },
                "summary": {
                    "type": "string",
                    "description": "Completion summary describing what was accomplished",
                },
                "repository": {
                    "type": "string",
                    "description": "Repository identifier (optional if using initiative ID)",
                },
            },
            "required": ["initiative", "summary"],
        },
    },
    {
        "name": "get_repo_context",
        "description": "Get stored tech stack and initiative context for a repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {
                    "type": "string",
                    "description": "Repository identifier",
                },
            },
            "required": ["repository"],
        },
    },
    {
        "name": "configure_cortex",
        "description": "Configure Cortex runtime settings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "min_score": {"type": "number", "description": "Minimum relevance score (0-1)"},
                "verbose": {"type": "boolean", "description": "Enable verbose output"},
                "top_k_retrieve": {"type": "integer", "description": "Candidates before reranking"},
                "top_k_rerank": {"type": "integer", "description": "Results after reranking"},
                "llm_provider": {"type": "string", "description": "LLM provider: anthropic, claude-cli, ollama, openrouter, or none"},
                "recency_boost": {"type": "boolean", "description": "Enable recency boosting for notes/commits"},
                "recency_half_life_days": {"type": "number", "description": "Days until recency boost decays to ~0.5"},
                "enabled": {"type": "boolean", "description": "Enable or disable Cortex memory system"},
            },
        },
    },
    {
        "name": "get_skeleton",
        "description": "Get the file tree structure for a repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {"type": "string", "description": "Repository name"},
            },
        },
    },
    {
        "name": "get_cortex_version",
        "description": "Get Cortex daemon build and version information. Pass expected_commit to check if rebuild is needed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expected_commit": {
                    "type": "string",
                    "description": "Git commit hash to compare against (e.g., local HEAD). If provided, returns needs_rebuild field.",
                },
            },
        },
    },
    {
        "name": "recall_recent_work",
        "description": "Recall recent commits and notes for a repository. Returns a timeline view of recent work, grouped by day, with initiative context. Answers 'What did I work on this week?' without manual search queries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {
                    "type": "string",
                    "description": "Repository identifier",
                },
                "days": {
                    "type": "integer",
                    "default": 7,
                    "description": "Number of days to look back (default: 7)",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Maximum number of items to return (default: 20)",
                },
                "include_code": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include code changes in results (default: false, notes/commits only)",
                },
            },
            "required": ["repository"],
        },
    },
    {
        "name": "summarize_initiative",
        "description": "Generate a narrative summary of an initiative's progress. Gathers all commits and notes tagged with the initiative and synthesizes a timeline with key decisions, problems solved, and current state.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "initiative": {
                    "type": "string",
                    "description": "Initiative ID or name",
                },
                "repository": {
                    "type": "string",
                    "description": "Repository identifier (optional if using initiative ID)",
                },
            },
            "required": ["initiative"],
        },
    },
    {
        "name": "validate_insight",
        "description": "Validate a stored insight against current code state. Use this after re-reading linked files to confirm whether a stale insight is still accurate. Can mark invalid insights as deprecated and optionally create a replacement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "insight_id": {
                    "type": "string",
                    "description": "The insight ID to validate (e.g., 'insight:abc123')",
                },
                "validation_result": {
                    "type": "string",
                    "enum": ["still_valid", "partially_valid", "no_longer_valid"],
                    "description": "Your assessment after re-reading the linked files",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes about what changed or why validation failed",
                },
                "deprecate": {
                    "type": "boolean",
                    "default": False,
                    "description": "If True and validation_result is 'no_longer_valid', mark insight as deprecated",
                },
                "replacement_insight": {
                    "type": "string",
                    "description": "If deprecating, optionally provide updated insight content to save as replacement",
                },
                "repository": {
                    "type": "string",
                    "description": "Repository identifier (optional)",
                },
            },
            "required": ["insight_id", "validation_result"],
        },
    },
    {
        "name": "get_autocapture_status",
        "description": "Get status of the auto-capture system including hook installation, LLM provider availability, configuration, and recent capture statistics.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "configure_autocapture",
        "description": "Configure auto-capture settings. Changes are persisted to ~/.cortex/config.yaml.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "enabled": {
                    "type": "boolean",
                    "description": "Enable or disable auto-capture",
                },
                "llm_provider": {
                    "type": "string",
                    "enum": ["anthropic", "ollama", "openrouter", "claude-cli"],
                    "description": "Primary LLM provider for summarization",
                },
                "auto_commit_async": {
                    "type": "boolean",
                    "description": "When true (default), hook exits fast and daemon processes in background. When false, hook waits for LLM summary + commit to complete.",
                },
                "sync_timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds for sync mode (default: 60, range: 10-300)",
                },
                "min_tokens": {
                    "type": "integer",
                    "description": "Minimum token threshold for significant sessions",
                },
                "min_file_edits": {
                    "type": "integer",
                    "description": "Minimum file edit threshold for significant sessions",
                },
                "min_tool_calls": {
                    "type": "integer",
                    "description": "Minimum tool call threshold for significant sessions",
                },
            },
        },
    },
]


def _get_tool_map():
    """Lazy import of tool functions to avoid circular imports."""
    from src.tools import (
        commit_to_cortex,
        complete_initiative,
        configure_cortex,
        create_initiative,
        focus_initiative,
        get_repo_context,
        get_cortex_version,
        get_skeleton,
        ingest_code_into_cortex,
        insight_to_cortex,
        list_initiatives,
        orient_session,
        recall_recent_work,
        save_note_to_cortex,
        search_cortex,
        set_initiative,
        set_repo_context,
        summarize_initiative,
        validate_insight,
    )
    from src.tools.autocapture import (
        get_autocapture_status,
        configure_autocapture,
    )
    return {
        "orient_session": orient_session,
        "search_cortex": search_cortex,
        "ingest_code_into_cortex": ingest_code_into_cortex,
        "commit_to_cortex": commit_to_cortex,
        "save_note_to_cortex": save_note_to_cortex,
        "insight_to_cortex": insight_to_cortex,
        "set_repo_context": set_repo_context,
        "set_initiative": set_initiative,
        "create_initiative": create_initiative,
        "list_initiatives": list_initiatives,
        "focus_initiative": focus_initiative,
        "complete_initiative": complete_initiative,
        "get_repo_context": get_repo_context,
        "configure_cortex": configure_cortex,
        "get_skeleton": get_skeleton,
        "get_cortex_version": get_cortex_version,
        "recall_recent_work": recall_recent_work,
        "summarize_initiative": summarize_initiative,
        "validate_insight": validate_insight,
        "get_autocapture_status": get_autocapture_status,
        "configure_autocapture": configure_autocapture,
    }


# --- Endpoints ---


@router.get("/tools/list")
def mcp_list_tools() -> dict[str, Any]:
    """
    List available MCP tools.

    Returns tool definitions in MCP protocol format.
    """
    logger.info("MCP tools/list requested")
    return {"tools": MCP_TOOL_SCHEMAS}


@router.post("/tools/call")
def mcp_call_tool(request: MCPToolCallRequest) -> MCPToolResult:
    """
    Execute an MCP tool.

    Args:
        name: Tool name
        arguments: Tool arguments

    Returns:
        Tool result or error
    """
    logger.info(f"MCP tools/call: {request.name}")

    tool_map = _get_tool_map()
    tool_fn = tool_map.get(request.name)

    if not tool_fn:
        logger.error(f"Unknown tool: {request.name}")
        return MCPToolResult(
            content={"error": f"Unknown tool: {request.name}"},
            isError=True,
        )

    try:
        result = tool_fn(**request.arguments)
        logger.debug(f"Tool {request.name} completed successfully")
        return MCPToolResult(content=result)
    except Exception as e:
        logger.error(f"Tool {request.name} failed: {e}")
        return MCPToolResult(
            content={"error": str(e)},
            isError=True,
        )
