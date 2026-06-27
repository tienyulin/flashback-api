"""Restore-point routes: list / create / drop (SOP §3)."""

from fastapi import APIRouter, Depends

from api.dependencies import operator_from_key, require_api_key
from core.deps import get_service
from models.schemas import CreateRestorePointRequest
from services.flashback_service import FlashbackService

router = APIRouter()


@router.get("/restore_points")
async def list_restore_points(svc: FlashbackService = Depends(get_service)):
    """Existing restore points ordered by SCN (SOP §3.2)."""
    return {"restore_points": svc.list_restore_points()}


@router.post("/restore_points", dependencies=[Depends(require_api_key)])
async def create_restore_point(
    request: CreateRestorePointRequest,
    svc: FlashbackService = Depends(get_service),
    operator: str = Depends(operator_from_key),
):
    """Create a (guaranteed) restore point before a risky change (SOP §3.1)."""
    return svc.create_restore_point(
        name=request.name,
        guarantee=request.guarantee,
        dry_run=request.dry_run,
        operator=operator,
    )


@router.delete("/restore_points/{name}", dependencies=[Depends(require_api_key)])
async def drop_restore_point(
    name: str,
    dry_run: bool = True,
    svc: FlashbackService = Depends(get_service),
    operator: str = Depends(operator_from_key),
):
    """Drop a restore point after the change is verified (SOP §3.3/§6)."""
    return svc.drop_restore_point(name=name, dry_run=dry_run, operator=operator)
