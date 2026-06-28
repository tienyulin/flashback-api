"""Request-level dependencies shared by routers."""

import os
import secrets

from fastapi import Header, HTTPException

_API_KEY_DESC = "操作者 API 金鑰（mutation 端點需要；啟用驗證時用於授權與稽核身分）"


async def require_api_key(x_api_key: str = Header(default="", description=_API_KEY_DESC)):
    """Reject mutation calls without a valid X-API-Key when auth is enabled.

    Read at request time (not import time) so tests can toggle the env var.
    """
    expected = os.getenv("FLASHBACK_API_KEY")
    if not expected:
        return  # auth disabled (dev mode)
    if not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def operator_from_key(x_api_key: str = Header(default="", description=_API_KEY_DESC)) -> str:
    """Audit operator identity: first 8 chars of the key, or 'dev' (spec §7)."""
    return x_api_key[:8] if x_api_key else "dev"
