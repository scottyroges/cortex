"""
Cortex HTTP Server

Optional FastAPI server for:
- Debug endpoints: DB inspection, raw search
- Phase 2 endpoints: Web clipper, CLI search, notes

Start with CORTEX_HTTP=true or --http flag.
"""

import hashlib
import os
import time
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from logging_config import get_logger
from rag_utils import (
    HybridSearcher,
    RerankerService,
    get_chroma_client,
    get_collection_stats,
    get_or_create_collection,
    scrub_secrets,
)

logger = get_logger("http")

app = FastAPI(
    title="Cortex Debug Server",
    description="Debug and Phase 2 HTTP endpoints for Cortex",
    version="1.0.0",
)

# Lazy-initialized resources
_client = None
_collection = None
_searcher = None
_reranker = None


def get_collection():
    """Get or create the ChromaDB collection."""
    global _client, _collection
    if _collection is None:
        _client = get_chroma_client()
        _collection = get_or_create_collection(_client)
    return _collection


def get_searcher():
    """Get or create the hybrid searcher."""
    global _searcher
    if _searcher is None:
        _searcher = HybridSearcher(get_collection())
    return _searcher


def get_reranker():
    """Get or create the reranker."""
    global _reranker
    if _reranker is None:
        _reranker = RerankerService()
    return _reranker


# =============================================================================
# Debug Endpoints
# =============================================================================


@app.get("/debug/stats")
def debug_stats() -> dict[str, Any]:
    """
    Get collection statistics.

    Returns counts by project, type, and language.
    """
    logger.info("Debug stats requested")
    collection = get_collection()

    # Get all documents with metadata
    results = collection.get(include=["metadatas"])

    stats = {
        "total_documents": len(results["ids"]),
        "by_project": {},
        "by_type": {},
        "by_language": {},
    }

    for meta in results["metadatas"]:
        # Count by project
        project = meta.get("project", "unknown")
        stats["by_project"][project] = stats["by_project"].get(project, 0) + 1

        # Count by type
        doc_type = meta.get("type", "unknown")
        stats["by_type"][doc_type] = stats["by_type"].get(doc_type, 0) + 1

        # Count by language (for code)
        lang = meta.get("language")
        if lang:
            stats["by_language"][lang] = stats["by_language"].get(lang, 0) + 1

    logger.debug(f"Stats: {stats['total_documents']} total docs")
    return stats


@app.get("/debug/sample")
def debug_sample(limit: int = Query(default=10, le=100)) -> list[dict[str, Any]]:
    """
    Get sample documents from the collection.

    Args:
        limit: Maximum number of documents to return (max 100)
    """
    logger.info(f"Debug sample requested: limit={limit}")
    collection = get_collection()

    results = collection.get(
        limit=limit,
        include=["documents", "metadatas"],
    )

    samples = []
    for doc_id, doc, meta in zip(
        results["ids"],
        results["documents"],
        results["metadatas"],
    ):
        samples.append({
            "id": doc_id,
            "content_preview": doc[:200] + "..." if len(doc) > 200 else doc,
            "metadata": meta,
        })

    return samples


@app.get("/debug/list")
def debug_list(
    project: Optional[str] = None,
    doc_type: Optional[str] = Query(default=None, alias="type"),
    limit: int = Query(default=50, le=500),
) -> list[dict[str, Any]]:
    """
    List documents with optional filtering.

    Args:
        project: Filter by project name
        type: Filter by document type (code, note, commit)
        limit: Maximum results
    """
    logger.info(f"Debug list requested: project={project}, type={doc_type}")
    collection = get_collection()

    # Build where filter
    where_filter = None
    if project or doc_type:
        conditions = []
        if project:
            conditions.append({"project": project})
        if doc_type:
            conditions.append({"type": doc_type})

        if len(conditions) == 1:
            where_filter = conditions[0]
        else:
            where_filter = {"$and": conditions}

    results = collection.get(
        where=where_filter,
        limit=limit,
        include=["metadatas"],
    )

    return [
        {"id": doc_id, "metadata": meta}
        for doc_id, meta in zip(results["ids"], results["metadatas"])
    ]


@app.get("/debug/get/{doc_id}")
def debug_get(doc_id: str) -> dict[str, Any]:
    """
    Get a specific document by ID.

    Args:
        doc_id: Document ID
    """
    logger.info(f"Debug get requested: doc_id={doc_id}")
    collection = get_collection()

    results = collection.get(
        ids=[doc_id],
        include=["documents", "metadatas", "embeddings"],
    )

    if not results["ids"]:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    return {
        "id": results["ids"][0],
        "content": results["documents"][0],
        "metadata": results["metadatas"][0],
        "has_embedding": results["embeddings"] is not None and len(results["embeddings"]) > 0,
    }


@app.get("/debug/search")
def debug_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=20, le=100),
    rerank: bool = Query(default=False),
) -> dict[str, Any]:
    """
    Raw search for debugging (shows scores and timing).

    Args:
        q: Search query
        limit: Maximum results
        rerank: Whether to apply reranking
    """
    logger.info(f"Debug search: query='{q}', limit={limit}, rerank={rerank}")
    start_time = time.time()

    searcher = get_searcher()

    # Rebuild index for accurate results
    search_start = time.time()
    results = searcher.search(q, top_k=limit, rebuild_index=True)
    search_time = time.time() - search_start

    response = {
        "query": q,
        "timing": {
            "search_ms": round(search_time * 1000, 2),
        },
        "results": [],
    }

    if rerank and results:
        rerank_start = time.time()
        reranker = get_reranker()
        results = reranker.rerank(q, results, top_k=limit)
        rerank_time = time.time() - rerank_start
        response["timing"]["rerank_ms"] = round(rerank_time * 1000, 2)

    for r in results:
        response["results"].append({
            "id": r.get("id"),
            "content_preview": r.get("text", "")[:200],
            "metadata": r.get("meta", {}),
            "scores": {
                "rrf": r.get("rrf_score"),
                "rerank": r.get("rerank_score"),
                "vector_distance": r.get("vector_distance"),
                "bm25": r.get("bm25_score"),
            },
        })

    response["timing"]["total_ms"] = round((time.time() - start_time) * 1000, 2)
    response["result_count"] = len(response["results"])

    logger.debug(f"Debug search complete: {len(response['results'])} results in {response['timing']['total_ms']}ms")
    return response


# =============================================================================
# Phase 2 Endpoints
# =============================================================================


class IngestRequest(BaseModel):
    """Request body for web content ingestion."""
    url: str
    content: str
    title: Optional[str] = None
    tags: Optional[list[str]] = None
    project: str = "web"


class NoteRequest(BaseModel):
    """Request body for note creation."""
    content: str
    title: Optional[str] = None
    tags: Optional[list[str]] = None
    project: str = "notes"


class SearchResponse(BaseModel):
    """Response for search endpoint."""
    query: str
    results: list[dict[str, Any]]
    timing_ms: float


@app.post("/ingest")
def ingest_web(request: IngestRequest) -> dict[str, Any]:
    """
    Ingest web content (for web clipper).

    Args:
        url: Source URL
        content: Page content
        title: Optional title
        tags: Optional tags
        project: Project name (default: "web")
    """
    logger.info(f"Ingesting web content: url={request.url}")

    # Scrub secrets from content
    clean_content = scrub_secrets(request.content)

    # Generate document ID
    doc_id = f"web_{hashlib.md5(request.url.encode()).hexdigest()[:12]}_{uuid.uuid4().hex[:8]}"

    # Build metadata
    metadata = {
        "type": "web",
        "url": request.url,
        "project": request.project,
        "ingested_at": datetime.utcnow().isoformat(),
    }
    if request.title:
        metadata["title"] = request.title
    if request.tags:
        metadata["tags"] = ",".join(request.tags)

    # Add to collection
    collection = get_collection()
    collection.add(
        documents=[clean_content],
        ids=[doc_id],
        metadatas=[metadata],
    )

    logger.info(f"Ingested web content: id={doc_id}")
    return {
        "status": "success",
        "id": doc_id,
        "url": request.url,
        "content_length": len(clean_content),
    }


@app.get("/search")
def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=5, le=20),
    project: Optional[str] = None,
    min_score: float = Query(default=0.3, ge=0.0, le=1.0),
) -> SearchResponse:
    """
    Search memory (for CLI).

    Args:
        q: Search query
        limit: Maximum results (default 5)
        project: Optional project filter
        min_score: Minimum rerank score (default 0.3)
    """
    logger.info(f"Search: query='{q}', limit={limit}, project={project}")
    start_time = time.time()

    # Build filter
    where_filter = {"project": project} if project else None

    # Search
    searcher = get_searcher()
    results = searcher.search(q, top_k=50, where_filter=where_filter, rebuild_index=True)

    # Rerank
    reranker = get_reranker()
    results = reranker.rerank(q, results, top_k=limit)

    # Filter by min_score
    filtered = [r for r in results if r.get("rerank_score", 0) >= min_score]

    timing = round((time.time() - start_time) * 1000, 2)
    logger.debug(f"Search complete: {len(filtered)} results in {timing}ms")

    return SearchResponse(
        query=q,
        results=[
            {
                "content": r.get("text", ""),
                "metadata": r.get("meta", {}),
                "score": r.get("rerank_score"),
            }
            for r in filtered
        ],
        timing_ms=timing,
    )


@app.post("/note")
def save_note(request: NoteRequest) -> dict[str, Any]:
    """
    Save a note (for CLI).

    Args:
        content: Note content
        title: Optional title
        tags: Optional tags
        project: Project name (default: "notes")
    """
    logger.info(f"Saving note: title={request.title}")

    # Generate document ID
    doc_id = f"note_{uuid.uuid4().hex[:16]}"

    # Build content with optional title
    full_content = request.content
    if request.title:
        full_content = f"# {request.title}\n\n{request.content}"

    # Build metadata
    metadata = {
        "type": "note",
        "project": request.project,
        "created_at": datetime.utcnow().isoformat(),
    }
    if request.title:
        metadata["title"] = request.title
    if request.tags:
        metadata["tags"] = ",".join(request.tags)

    # Add to collection
    collection = get_collection()
    collection.add(
        documents=[full_content],
        ids=[doc_id],
        metadatas=[metadata],
    )

    logger.info(f"Saved note: id={doc_id}")
    return {
        "status": "success",
        "id": doc_id,
        "title": request.title,
        "content_length": len(full_content),
    }


@app.get("/health")
def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


# Track server startup time
_startup_time = datetime.utcnow().isoformat() + "Z"


@app.get("/info")
def info() -> dict[str, str]:
    """
    Build and runtime information.

    Returns git commit, build time, and startup time for verifying
    the daemon is running the expected code version.
    """
    return {
        "git_commit": os.environ.get("CORTEX_GIT_COMMIT", "unknown"),
        "build_time": os.environ.get("CORTEX_BUILD_TIME", "unknown"),
        "startup_time": _startup_time,
        "version": "1.0.0",
    }


# =============================================================================
# MCP Protocol Endpoints (for daemon mode)
# =============================================================================


class MCPToolCallRequest(BaseModel):
    """Request body for MCP tool call."""
    name: str
    arguments: dict = {}


class MCPToolResult(BaseModel):
    """Response for MCP tool call."""
    content: Any
    isError: bool = False


# Import tool functions from server module
def _get_tool_map():
    """Lazy import of tool functions to avoid circular imports."""
    from server import (
        search_cortex,
        ingest_code_into_cortex,
        commit_to_cortex,
        save_note_to_cortex,
        configure_cortex,
        toggle_cortex,
        get_skeleton,
        get_cortex_version,
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


# Tool schemas for MCP tools/list response
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


@app.get("/mcp/tools/list")
def mcp_list_tools() -> dict[str, Any]:
    """
    List available MCP tools.

    Returns tool definitions in MCP protocol format.
    """
    logger.info("MCP tools/list requested")
    return {"tools": MCP_TOOL_SCHEMAS}


@app.post("/mcp/tools/call")
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


def run_server(host: str = "0.0.0.0", port: int = 8080):
    """Run the FastAPI server."""
    import uvicorn
    logger.info(f"Starting HTTP server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
