"""
Cortex HTTP Server

FastAPI-based HTTP endpoints for debugging, Phase 2 features, and MCP protocol.
"""

from datetime import datetime

from fastapi import FastAPI

from src.http.api import router as api_router
from src.http.debug import router as debug_router
from src.http.mcp_protocol import router as mcp_router

# Track server startup time
_startup_time = datetime.utcnow().isoformat() + "Z"


def get_startup_time() -> str:
    """Get the server startup time."""
    return _startup_time


# Create FastAPI app
app = FastAPI(
    title="Cortex Debug Server",
    description="Debug and Phase 2 HTTP endpoints for Cortex",
    version="1.0.0",
)

# Include routers
app.include_router(debug_router, prefix="/debug", tags=["debug"])
app.include_router(api_router, tags=["api"])
app.include_router(mcp_router, prefix="/mcp", tags=["mcp"])


@app.get("/health")
def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


def run_server(host: str = "0.0.0.0", port: int = 8080):
    """Run the FastAPI server."""
    import uvicorn
    from logging_config import get_logger
    logger = get_logger("http")
    logger.info(f"Starting HTTP server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
