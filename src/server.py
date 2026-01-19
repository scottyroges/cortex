"""
Cortex MCP Server

A local, privacy-first memory system for Claude Code.
Provides RAG capabilities with ChromaDB, FlashRank reranking, and AST-aware chunking.

Environment variables:
    CORTEX_DEBUG: Enable debug logging (default: false)
    CORTEX_LOG_FILE: Log file path (default: $CORTEX_DATA_PATH/daemon.log)
    CORTEX_HTTP: Enable HTTP server for debugging (default: false)
"""

import argparse
import os
import threading

from mcp.server.fastmcp import FastMCP

from logging_config import get_logger, setup_logging
from src.tools import (
    session_summary_to_cortex,
    complete_initiative,
    configure_cortex,
    create_initiative,
    focus_initiative,
    get_cortex_version,
    get_repo_context,
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
from src.tools.ingest import get_ingest_status

# Initialize logging
setup_logging()
logger = get_logger("server")

# --- Initialize MCP Server ---

mcp = FastMCP("Cortex")

# --- Register Tools ---

# Session
mcp.tool()(orient_session)

# Search
mcp.tool()(search_cortex)

# Ingest
mcp.tool()(ingest_code_into_cortex)
mcp.tool()(get_ingest_status)

# Notes
mcp.tool()(save_note_to_cortex)
mcp.tool()(session_summary_to_cortex)
mcp.tool()(insight_to_cortex)
mcp.tool()(validate_insight)

# Context
mcp.tool()(set_repo_context)
mcp.tool()(set_initiative)
mcp.tool()(get_repo_context)

# Initiatives
mcp.tool()(create_initiative)
mcp.tool()(list_initiatives)
mcp.tool()(focus_initiative)
mcp.tool()(complete_initiative)

# Recall (Session Memory)
mcp.tool()(recall_recent_work)
mcp.tool()(summarize_initiative)

# Admin
mcp.tool()(configure_cortex)
mcp.tool()(get_cortex_version)
mcp.tool()(get_skeleton)


# --- Entry Point ---


def start_http_server():
    """Start the FastAPI HTTP server in a background thread."""
    from src.http import run_server
    http_thread = threading.Thread(target=run_server, daemon=True)
    http_thread.start()
    logger.info("HTTP server started on port 8080")


def start_queue_processor():
    """Start the auto-capture queue processor in a background thread."""
    from src.autocapture import start_processor
    start_processor()
    logger.info("Queue processor started")


def start_ingestion_worker():
    """Start the async ingestion worker in a background thread."""
    from src.ingest.async_processor import start_worker
    start_worker()
    logger.info("Ingestion worker started")


def main():
    """Main entry point for the MCP server."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Cortex MCP Server")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Enable HTTP server for debugging and Phase 2 features",
    )
    args = parser.parse_args()

    # Check for CORTEX_HTTP environment variable
    enable_http = args.http or os.environ.get("CORTEX_HTTP", "").lower() in ("true", "1", "yes")

    if enable_http:
        start_http_server()

    # Always start background processors
    start_queue_processor()
    start_ingestion_worker()

    logger.info("Starting Cortex MCP server")
    mcp.run()


if __name__ == "__main__":
    main()
