from typing import Optional

from fastapi import APIRouter, Depends

from api.dependencies import operator_from_key, require_api_key
from core.deps import get_service
from models.schemas import (
    FlashbackDatabaseRequest,
    FlashbackDropRequest,
    FlashbackTableRequest,
    FinalizeRequest,
)
from services.flashback_service import FlashbackService

router = APIRouter()


@router.get("/recyclebin")
async def recyclebin(
    owner: Optional[str] = None, svc: FlashbackService = Depends(get_service)
):
    """Recycle bin contents, newest drop first (SOP §4.2 step 1)."""
    return {"entries": svc.list_recyclebin(owner)}


@router.post("/flashback/table", dependencies=[Depends(require_api_key)])
async def flashback_table(
    request: FlashbackTableRequest,
    svc: FlashbackService = Depends(get_service),
    operator: str = Depends(operator_from_key),
):
    """Rewind a table to a past SCN/timestamp (SOP §4.1). Reversible:
    response carries prior_scn for flashing back again."""
    return svc.flashback_table(request, operator=operator)


@router.post("/flashback/drop", dependencies=[Depends(require_api_key)])
async def flashback_drop(
    request: FlashbackDropRequest,
    svc: FlashbackService = Depends(get_service),
    operator: str = Depends(operator_from_key),
):
    """Restore a dropped table from the recycle bin (SOP §4.2)."""
    return svc.flashback_drop(request, operator=operator)


@router.post("/flashback/database", dependencies=[Depends(require_api_key)])
async def flashback_database(
    request: FlashbackDatabaseRequest,
    svc: FlashbackService = Depends(get_service),
    operator: str = Depends(operator_from_key),
):
    """IRREVERSIBLE: rewind the whole database (SOP §5, approval required).
    Ends in READ ONLY validation state; finalize with /flashback/database/finalize."""
    return svc.flashback_database(request, operator=operator)


@router.post("/flashback/database/finalize", dependencies=[Depends(require_api_key)])
async def finalize_database(
    request: FinalizeRequest,
    svc: FlashbackService = Depends(get_service),
    operator: str = Depends(operator_from_key),
):
    """IRREVERSIBLE: OPEN RESETLOGS after manual validation (SOP §5 steps 4-5)."""
    return svc.finalize_database(request, operator=operator)
