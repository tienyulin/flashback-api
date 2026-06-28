"""Restore-point routes: list / create / drop (SOP §3)."""

from fastapi import APIRouter, Depends, Path, Query

from api.dependencies import operator_from_key, require_api_key
from api.openapi_responses import (
    AUTH_401,
    INTERNAL_500,
    VALIDATION_422,
    conflict,
    not_found,
    ok,
)
from core.deps import get_service
from models.schemas import CreateRestorePointRequest
from services.flashback_service import FlashbackService

router = APIRouter()


@router.get(
    "/restore_points",
    summary="列出現有還原點，依 SCN 排序（SOP §3.2）",
    responses={
        200: ok(
            {
                "restore_points": [
                    {
                        "name": "BEFORE_PATCH",
                        "scn": 123456,
                        "time": "2026-06-28:09:00:00",
                        "guarantee": True,
                        "storage_size": 1048576,
                    }
                ]
            }
        ),
        500: INTERNAL_500,
    },
)
async def list_restore_points(svc: FlashbackService = Depends(get_service)):
    """Existing restore points ordered by SCN (SOP §3.2)."""
    return {"restore_points": svc.list_restore_points()}


@router.post(
    "/restore_points",
    dependencies=[Depends(require_api_key)],
    summary="在風險變更前建立（保證型）還原點（SOP §3.1）",
    responses={
        200: ok({"dry_run": True, "would_create": "BEFORE_PATCH", "checks": {}}),
        401: AUTH_401,
        422: VALIDATION_422,
        409: conflict(
            "restore point 'BEFORE_PATCH' already exists — rename or DELETE it first", "ORA-38796"
        ),
    },
)
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


@router.delete(
    "/restore_points/{name}",
    dependencies=[Depends(require_api_key)],
    summary="變更驗證後刪除還原點（SOP §3.3/§6）",
    responses={
        200: ok({"dry_run": True, "would_drop": {"name": "BEFORE_PATCH", "scn": 123456}}),
        401: AUTH_401,
        404: not_found(
            "restore point 'BEFORE_PATCH' does not exist — see GET /restore_points", "ORA-38780"
        ),
    },
)
async def drop_restore_point(
    name: str = Path(description="要刪除的還原點名稱（大小寫不敏感，內部轉大寫）"),
    dry_run: bool = Query(
        default=True, description="僅預演不實際刪除（true 時回報將刪除的還原點）"
    ),
    svc: FlashbackService = Depends(get_service),
    operator: str = Depends(operator_from_key),
):
    """Drop a restore point after the change is verified (SOP §3.3/§6)."""
    return svc.drop_restore_point(name=name, dry_run=dry_run, operator=operator)
