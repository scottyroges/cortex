"""
Browse Endpoints

HTTP endpoints for memory browsing and exploration.
"""

from fastapi import APIRouter

from src.controllers.http.browse.read import router as read_router
from src.controllers.http.browse.write import router as write_router
from src.controllers.http.browse.maintenance import router as maintenance_router

__all__ = ["router"]

# Combined router
router = APIRouter()
router.include_router(read_router)
router.include_router(write_router)
router.include_router(maintenance_router)
