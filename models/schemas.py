"""Request/response models — field definitions per spec §1/§3."""

from typing import Optional

from pydantic import BaseModel, Field, model_validator

CONFIRM_TOKEN = "I-UNDERSTAND-DATA-LOSS"

# Fixed literals (spec §7.1) — single home; service code must reference these.
NOTE_FT_ROLLBACK = "資料驗證錯誤時可用 prior_scn 再 flashback 回來（SOP §4.1 步驟 2）"
NOTE_FD_BIN_INDEX = "索引仍為 BIN$ 系統名，需手動 rename（SOP §4.2 步驟 3）"
NEXT_STEP_DB_FINALIZE = "人工驗證資料後呼叫 POST /flashback/database/finalize（SOP §5 步驟 4）"
WARNING_FZ_RMAN = "RESETLOGS 完成，舊備份基線失效，立即執行 RMAN 全備（SOP §5 步驟 5）"


# ---------------------------------------------------------------------------
# Domain entities (spec §1)
# ---------------------------------------------------------------------------

class RestorePoint(BaseModel):
    name: str
    scn: int
    time: str
    guarantee: bool
    storage_size: int


class RecycleBinEntry(BaseModel):
    owner: str
    object_name: str
    original_name: str
    droptime: str


class AuditEntry(BaseModel):
    timestamp: str
    operator: str
    operation: str
    target: Optional[str] = None
    target_scn: Optional[int] = None
    target_time: Optional[str] = None
    dry_run: bool = False
    approval_id: Optional[str] = None
    result: str


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class FlashbackTarget(BaseModel):
    """Exactly one of scn / timestamp (spec §3 flashback/table)."""
    scn: Optional[int] = None
    timestamp: Optional[str] = None

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.scn is None) == (self.timestamp is None):
            raise ValueError("target must contain exactly one of: scn, timestamp")
        return self


class DatabaseTarget(BaseModel):
    """Exactly one of restore_point / scn / timestamp (spec §3 flashback/database)."""
    restore_point: Optional[str] = None
    scn: Optional[int] = None
    timestamp: Optional[str] = None

    @model_validator(mode="after")
    def _exactly_one(self):
        given = [v for v in (self.restore_point, self.scn, self.timestamp) if v is not None]
        if len(given) != 1:
            raise ValueError("target must contain exactly one of: restore_point, scn, timestamp")
        return self


class CreateRestorePointRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    guarantee: bool = True
    dry_run: bool = True


class FlashbackTableRequest(BaseModel):
    owner: str
    table_name: str
    target: FlashbackTarget
    enable_row_movement: bool = False
    dry_run: bool = True


class FlashbackDropRequest(BaseModel):
    owner: str
    table_name: str
    rename_to: Optional[str] = None
    dry_run: bool = True


class FlashbackDatabaseRequest(BaseModel):
    target: DatabaseTarget
    dry_run: bool = True
    confirm: Optional[str] = None
    approval_id: Optional[str] = None


class FinalizeRequest(BaseModel):
    dry_run: bool = True
    confirm: Optional[str] = None
    approval_id: Optional[str] = None
