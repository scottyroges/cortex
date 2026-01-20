"""
HTTP API Endpoints

REST API endpoints for web clipper, CLI search, notes, autocapture, and admin.
"""

from fastapi import APIRouter

from src.controllers.http.api.core import router as core_router
from src.controllers.http.api.autocapture import router as autocapture_router
from src.controllers.http.api.admin import router as admin_router

# Re-export for backward compatibility (used by tests)
from src.controllers.http.api.autocapture import (
    ProcessSyncRequest,
    SessionSummaryRequest,
    process_sync,
    save_session_summary,
)

__all__ = [
    "router",
    "ProcessSyncRequest",
    "SessionSummaryRequest",
    "process_sync",
    "save_session_summary",
]

# Combined router
router = APIRouter()
router.include_router(core_router)
router.include_router(autocapture_router)
router.include_router(admin_router)
