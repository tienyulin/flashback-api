"""Request/response models — field definitions per spec §1/§3."""

from typing import Optional

from pydantic import BaseModel, Field, model_validator

CONFIRM_TOKEN = "I-UNDERSTAND-DATA-LOSS"


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
