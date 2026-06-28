"""System routes: health, aggregated precondition status, and the audit log."""

from fastapi import APIRouter, Depends, Query

from api.openapi_responses import INTERNAL_500, ok
from core.deps import get_service
from services.flashback_service import FlashbackService

router = APIRouter()


@router.get(
    "/health",
    summary="存活檢查（liveness probe）",
    responses={
        200: ok({"status": "ok"}),
        500: INTERNAL_500,
    },
)
async def health():
    """Health check."""
    return {"status": "ok"}


@router.get(
    "/flashback/status",
    summary="彙總 DB 狀態與 P1-P3 前置條件快照（SOP §2）",
    responses={
        200: ok(
            {
                "db_state": "OPEN",
                "log_mode": "ARCHIVELOG",
                "flashback_on": True,
                "fra_usage_percent": 42.0,
                "preconditions": {
                    "P1_archivelog": True,
                    "P2_flashback_on": True,
                    "P3_fra_space": True,
                },
            }
        ),
        500: INTERNAL_500,
    },
)
async def flashback_status(svc: FlashbackService = Depends(get_service)):
    """Aggregated precondition checks P1-P4 (SOP §2)."""
    return svc.status()


@router.get(
    "/audit/log",
    summary="稽核軌跡，最新的排最前（SOP §8）",
    responses={
        200: ok(
            {
                "entries": [
                    {
                        "timestamp": "2026-06-28T10:00:00",
                        "operator": "dev",
                        "operation": "flashback_table",
                        "target": "HR.EMPLOYEES",
                        "dry_run": True,
                        "result": "dry_run",
                    }
                ]
            }
        ),
        500: INTERNAL_500,
    },
)
async def audit_log(
    limit: int = Query(default=100, description="回傳的稽核紀錄筆數上限（自動夾在 1-1000）"),
    svc: FlashbackService = Depends(get_service),
):
    """Audit trail, newest first (SOP §8)."""
    limit = max(1, min(limit, 1000))
    return {"entries": svc.list_audit(limit)}
