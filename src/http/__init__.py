"""
Cortex HTTP Server

FastAPI-based HTTP endpoints for browsing, API access, and MCP protocol.
"""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.http.api import router as api_router
from src.http.browse import router as browse_router
from src.http.mcp_protocol import router as mcp_router

# Track server startup time
_startup_time = datetime.now(timezone.utc).isoformat()


def get_startup_time() -> str:
    """Get the server startup time."""
    return _startup_time


# Create FastAPI app
app = FastAPI(
    title="Cortex Server",
    description="HTTP endpoints for Cortex memory browser and API",
    version="1.0.0",
)

# Include routers
app.include_router(browse_router, prefix="/browse", tags=["browse"])
app.include_router(api_router, tags=["api"])
app.include_router(mcp_router, prefix="/mcp", tags=["mcp"])


@app.get("/health")
def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


# Serve static web UI files
STATIC_DIR = Path(__file__).parent.parent.parent / "static"

if STATIC_DIR.exists():
    # Serve static assets (JS, CSS, images)
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/ui/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/ui")
    @app.get("/ui/{full_path:path}")
    async def serve_spa(full_path: str = "") -> FileResponse:
        """Serve the SPA for all /ui/* routes."""
        return FileResponse(STATIC_DIR / "index.html")


def run_server(host: str = "0.0.0.0", port: int = 8080):
    """Run the FastAPI server."""
    import uvicorn
    from logging_config import get_logger
    logger = get_logger("http")
    logger.info(f"Starting HTTP server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
