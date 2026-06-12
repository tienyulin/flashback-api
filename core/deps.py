"""Dependency providers (same lazy lru_cache pattern as wiki-processor).

Lazy so TestClient(app) without lifespan never touches a real Oracle;
production fail-fast comes from the lifespan warm-up in main.py.
"""

import logging
from functools import lru_cache

from core.config import get_settings
from repository.oracle_client import OracleRepository
from services.flashback_service import FlashbackService

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_oracle() -> OracleRepository:
    settings = get_settings()
    if settings.mock_oracle:
        from repository.mock_oracle import MockOracleRepository

        logger.warning("MOCK_ORACLE=true — using in-memory MockOracleRepository")
        return MockOracleRepository()

    from repository.oracle_client import RealOracleRepository

    if not settings.oracle_dsn:
        raise RuntimeError("ORACLE_DSN is required when MOCK_ORACLE is not enabled")
    return RealOracleRepository(
        dsn=settings.oracle_dsn,
        user=settings.oracle_user,
        password=settings.oracle_password,
    )


@lru_cache(maxsize=1)
def get_service() -> FlashbackService:
    return FlashbackService(oracle=get_oracle())


def reset_singletons() -> None:
    """Test seam: drop cached instances so the next request rebuilds."""
    for fn in (get_service, get_oracle):
        fn.cache_clear()
    get_settings.cache_clear()
