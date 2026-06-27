"""System routes: health, aggregated precondition status, and the audit log."""

from fastapi import APIRouter, Depends

from core.deps import get_service
from services.flashback_service import FlashbackService

router = APIRouter()


@router.get("/health")
async def health():
    """Health check."""
    return {"status": "ok"}


@router.get("/flashback/status")
async def flashback_status(svc: FlashbackService = Depends(get_service)):
    """Aggregated precondition checks P1-P4 (SOP §2)."""
    return svc.status()


@router.get("/audit/log")
async def audit_log(limit: int = 100, svc: FlashbackService = Depends(get_service)):
    """Audit trail, newest first (SOP §8)."""
    limit = max(1, min(limit, 1000))
    return {"entries": svc.list_audit(limit)}
