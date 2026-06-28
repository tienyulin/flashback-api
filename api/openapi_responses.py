"""Reusable OpenAPI response declarations (doc-only; no runtime effect).

Attached to routes via ``responses=`` so the generated ``openapi.json`` carries
the 4xx/5xx outcomes and examples that AI agents rely on. The error envelope
matches ``FlashbackError`` → spec §6: ``{"detail", "error_code"}``. Status codes
follow the canonical gate order 401 → 422 → 404 → 428 → 409.
"""

from models.schemas import CONFIRM_TOKEN


def _json_example(example: dict) -> dict:
    return {"content": {"application/json": {"example": example}}}


def _error(description: str, detail: str, error_code=None) -> dict:
    return {
        "description": description,
        **_json_example({"detail": detail, "error_code": error_code}),
    }


def ok(example: dict) -> dict:
    """A 200 response declaration carrying a representative success example."""
    return {"description": "Successful Response", **_json_example(example)}


def not_found(detail: str, error_code=None) -> dict:
    """A 404 declaration for a missing target (table / restore point)."""
    return _error("目標資源不存在（resource not found）", detail, error_code)


def conflict(detail: str, error_code=None) -> dict:
    """A 409 declaration for a precondition violation or state conflict."""
    return _error(
        "SOP 前置條件未滿足或狀態衝突（precondition / state conflict）", detail, error_code
    )


AUTH_401 = _error("缺少或錯誤的 X-API-Key（啟用驗證時）", "Invalid or missing X-API-Key")
VALIDATION_422 = _error(
    "請求驗證失敗（request validation failed）",
    "target must contain exactly one of: scn, timestamp",
)
CONFIRM_428 = _error(
    "不可逆操作需 confirm token + approval_id（confirmation required）",
    f"irreversible operation requires confirm='{CONFIRM_TOKEN}' "
    "and a non-empty approval_id (change-approval ticket)",
)
INTERNAL_500 = _error("伺服器內部錯誤（unexpected internal error）", "unexpected error")
