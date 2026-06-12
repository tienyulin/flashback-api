from fastapi import APIRouter

from api.routers import flashback, restore_points, system

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(restore_points.router)
api_router.include_router(flashback.router)
