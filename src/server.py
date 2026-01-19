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
    configure_cortex,
    conclude_session,
    get_skeleton,
    ingest_codebase,
    manage_initiative,
    orient_session,
    recall_recent_work,
    save_memory,
    search_cortex,
    validate_insight,
)

# Initialize logging
setup_logging()
logger = get_logger("server")

# --- Initialize MCP Server ---

mcp = FastMCP("Cortex")

# --- Register Tools (10 consolidated tools) ---

# 1. Session entry point
mcp.tool()(orient_session)

# 2. Search memory
mcp.tool()(search_cortex)

# 3. Recent work timeline
mcp.tool()(recall_recent_work)

# 4. File tree structure
mcp.tool()(get_skeleton)

# 5. Initiative management (CRUD)
mcp.tool()(manage_initiative)

# 6. Save notes/insights
mcp.tool()(save_memory)

# 7. End-of-session summary
mcp.tool()(conclude_session)

# 8. Code ingestion
mcp.tool()(ingest_codebase)

# 9. Validate stale insights
mcp.tool()(validate_insight)

# 10. Configuration and status
mcp.tool()(configure_cortex)


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
