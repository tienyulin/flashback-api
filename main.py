"""ASGI entrypoint: builds the FastAPI app, wires the unified error handler,
and warms the singletons at boot (spec §5/§6)."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api import api_router
from core.deps import get_service
from services.flashback_service import FlashbackError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Warm up the singletons so misconfiguration fails at boot."""
    if not os.getenv("FLASHBACK_API_KEY"):
        logger.warning(
            "FLASHBACK_API_KEY not set — mutation endpoints are UNAUTHENTICATED "
            "(dev mode). Set it before exposing this service beyond localhost."
        )
    get_service()
    yield


def create_app() -> FastAPI:
    """Build and configure the FastAPI application (router + unified error handler)."""
    application = FastAPI(
        title="Oracle Flashback Recovery API",
        version="0.1.0",
        description="API over DBA-SOP-014 (sop/oracle-flashback-recovery.md)",
        lifespan=lifespan,
    )
    application.include_router(api_router)

    @application.exception_handler(FlashbackError)
    async def flashback_error_handler(_request: Request, exc: FlashbackError):
        """Render a FlashbackError as the unified error body (spec §6)."""
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "error_code": exc.error_code},
        )

    return application


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8003)
