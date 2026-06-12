"""Central settings (spec §5). FLASHBACK_API_KEY is deliberately NOT here:
it is read at request time in api/dependencies.py so tests can toggle it."""

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    mock_oracle: bool
    oracle_dsn: str
    oracle_user: str
    oracle_password: str
    fra_usage_threshold: float


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        mock_oracle=os.getenv("MOCK_ORACLE", "false").lower() == "true",
        oracle_dsn=os.getenv("ORACLE_DSN", ""),
        oracle_user=os.getenv("ORACLE_USER", ""),
        oracle_password=os.getenv("ORACLE_PASSWORD", ""),
        fra_usage_threshold=float(os.getenv("FRA_USAGE_THRESHOLD", "85")),
    )
