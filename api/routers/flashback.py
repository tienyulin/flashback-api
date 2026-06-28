"""Flashback routes: recyclebin, table/drop (reversible), database/finalize (irreversible)."""

from typing import Optional

from fastapi import APIRouter, Depends, Query

from api.dependencies import operator_from_key, require_api_key
from api.openapi_responses import (
    AUTH_401,
    CONFIRM_428,
    INTERNAL_500,
    VALIDATION_422,
    conflict,
    not_found,
    ok,
)
from core.deps import get_service
from models.schemas import (
    FlashbackDatabaseRequest,
    FlashbackDropRequest,
    FlashbackTableRequest,
    FinalizeRequest,
)
from services.flashback_service import FlashbackService

router = APIRouter()


@router.get(
    "/recyclebin",
    summary="查詢資源回收筒中被刪除（DROP）的資料表，最近刪的排最前",
    responses={
        200: ok(
            {
                "entries": [
                    {
                        "owner": "HR",
                        "object_name": "BIN$abc==$0",
                        "original_name": "EMPLOYEES",
                        "droptime": "2026-06-20:10:00:00",
                    }
                ]
            }
        ),
        500: INTERNAL_500,
    },
)
async def recyclebin(
    owner: Optional[str] = Query(
        default=None, description="只列出此 schema/owner 的項目（省略則全部）"
    ),
    svc: FlashbackService = Depends(get_service),
):
    """Recycle bin contents, newest drop first (SOP §4.2 step 1)."""
    return {"entries": svc.list_recyclebin(owner)}


@router.post(
    "/flashback/table",
    dependencies=[Depends(require_api_key)],
    summary="把資料表回溯到過去的時間點或 SCN，救回被誤改、誤刪的資料列（可逆）",
    responses={
        200: ok(
            {
                "dry_run": True,
                "prior_scn": 123456,
                "checks": {"P1_archivelog": {"ok": True}},
            }
        ),
        401: AUTH_401,
        404: not_found("table HR.EMPLOYEES not found"),
        422: VALIDATION_422,
        409: conflict(
            "P6 violated: HR.EMPLOYEES has ROW MOVEMENT disabled — "
            "retry with enable_row_movement=true",
            "ORA-08189",
        ),
    },
)
async def flashback_table(
    request: FlashbackTableRequest,
    svc: FlashbackService = Depends(get_service),
    operator: str = Depends(operator_from_key),
):
    """Rewind a table to a past SCN/timestamp (SOP §4.1). Reversible:
    response carries prior_scn for flashing back again."""
    return svc.flashback_table(request, operator=operator)


@router.post(
    "/flashback/drop",
    dependencies=[Depends(require_api_key)],
    summary="從資源回收筒救回被誤刪（DROP）的整張資料表",
    responses={
        200: ok(
            {
                "dry_run": True,
                "would_restore": {"original_name": "EMPLOYEES"},
                "restored_as": "EMPLOYEES",
            }
        ),
        401: AUTH_401,
        404: not_found(
            "HR.EMPLOYEES is not in the recycle bin (purged, or recyclebin=off)",
            "ORA-38305",
        ),
        409: conflict("table HR.EMPLOYEES already exists — retry with rename_to", "ORA-38312"),
    },
)
async def flashback_drop(
    request: FlashbackDropRequest,
    svc: FlashbackService = Depends(get_service),
    operator: str = Depends(operator_from_key),
):
    """Restore a dropped table from the recycle bin (SOP §4.2)."""
    return svc.flashback_drop(request, operator=operator)


@router.post(
    "/flashback/database",
    dependencies=[Depends(require_api_key)],
    summary="把整個資料庫回溯到誤操作之前的狀態，救回大規模誤刪／誤改（不可逆，需審批）",
    responses={
        200: ok(
            {
                "dry_run": True,
                "checks": {"P1_archivelog": {"ok": True}},
                "estimated_flashback_size": "2GB",
                "resolved_target_scn": 123000,
            }
        ),
        401: AUTH_401,
        404: not_found(
            "restore point 'BEFORE_PATCH' does not exist — see GET /restore_points", "ORA-38780"
        ),
        428: CONFIRM_428,
        409: conflict("P1 violated: database is not in ARCHIVELOG mode"),
    },
)
async def flashback_database(
    request: FlashbackDatabaseRequest,
    svc: FlashbackService = Depends(get_service),
    operator: str = Depends(operator_from_key),
):
    """IRREVERSIBLE: rewind the whole database (SOP §5, approval required).
    Ends in READ ONLY validation state; finalize with /flashback/database/finalize."""
    return svc.flashback_database(request, operator=operator)


@router.post(
    "/flashback/database/finalize",
    dependencies=[Depends(require_api_key)],
    summary="人工驗證後正式套用資料庫回溯（OPEN RESETLOGS，不可逆）",
    responses={
        200: ok({"dry_run": True, "would_finalize_at_scn": 123456}),
        401: AUTH_401,
        428: CONFIRM_428,
        409: conflict(
            "database state is OPEN — nothing to finalize "
            "(expected FLASHBACKED, i.e. read-only validation window)"
        ),
    },
)
async def finalize_database(
    request: FinalizeRequest,
    svc: FlashbackService = Depends(get_service),
    operator: str = Depends(operator_from_key),
):
    """IRREVERSIBLE: OPEN RESETLOGS after manual validation (SOP §5 steps 4-5)."""
    return svc.finalize_database(request, operator=operator)
