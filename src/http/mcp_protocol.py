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
        "name": "search_cortex",
        "description": "Search the Cortex memory for relevant code, documentation, or notes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"},
                "scope": {"type": "string", "default": "global", "description": "Search scope"},
                "project": {"type": "string", "description": "Optional project filter"},
                "min_score": {"type": "number", "description": "Minimum relevance score (0-1)"},
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
                "project_name": {"type": "string", "description": "Optional project identifier"},
                "force_full": {"type": "boolean", "default": False, "description": "Force full re-ingestion"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "commit_to_cortex",
        "description": "Save a session summary and re-index changed files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Summary of changes made"},
                "changed_files": {"type": "array", "items": {"type": "string"}, "description": "List of modified file paths"},
                "project": {"type": "string", "description": "Project identifier"},
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
                "project": {"type": "string", "description": "Associated project"},
            },
            "required": ["content"],
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
                "header_provider": {"type": "string", "description": "Header provider: anthropic, claude-cli, or none"},
            },
        },
    },
    {
        "name": "toggle_cortex",
        "description": "Enable or disable Cortex memory system.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "description": "True to enable, False to disable"},
            },
            "required": ["enabled"],
        },
    },
    {
        "name": "get_skeleton",
        "description": "Get the file tree structure for a project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project name"},
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
]


def _get_tool_map():
    """Lazy import of tool functions to avoid circular imports."""
    from src.tools import (
        commit_to_cortex,
        configure_cortex,
        get_cortex_version,
        get_skeleton,
        ingest_code_into_cortex,
        save_note_to_cortex,
        search_cortex,
        toggle_cortex,
    )
    return {
        "search_cortex": search_cortex,
        "ingest_code_into_cortex": ingest_code_into_cortex,
        "commit_to_cortex": commit_to_cortex,
        "save_note_to_cortex": save_note_to_cortex,
        "configure_cortex": configure_cortex,
        "toggle_cortex": toggle_cortex,
        "get_skeleton": get_skeleton,
        "get_cortex_version": get_cortex_version,
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
