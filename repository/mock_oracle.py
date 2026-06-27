"""Deterministic in-memory Oracle for MOCK_ORACLE=true (spec §4 mock state).

Simulates the effects of the SQL documented on OracleRepository:
- every mutating operation advances current_scn by 1
- creating a guaranteed restore point consumes 1 GiB of FRA (lets tests
  drive the P3 threshold)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from repository.oracle_client import OracleRepository

GIB = 2**30


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


@dataclass
class _Fra:
    """Fast Recovery Area usage (mirrors v$recovery_file_dest)."""

    limit_bytes: int = 10 * GIB
    used_bytes: int = 4 * GIB
    estimated_flashback_size: int = 2 * GIB


@dataclass
class _FlashbackLog:
    """Flashback retention window (mirrors v$flashback_database_log)."""

    on: bool = True
    oldest_scn: int = 1_500_000
    oldest_time: str = "2026-06-11T09:00:00"
    retention_minutes: int = 1440


@dataclass
class _MockDbState:
    """Scalar v$ snapshot the mock advances as operations run (spec §4)."""

    log_mode: str = "ARCHIVELOG"
    db_state: str = "OPEN"
    current_scn: int = 2_000_000
    resetlogs_time: Optional[str] = None
    fra: _Fra = field(default_factory=_Fra)
    flashback: _FlashbackLog = field(default_factory=_FlashbackLog)


class MockOracleRepository(OracleRepository):
    """In-memory OracleRepository: deterministic state for tests and the mock demo."""

    def __init__(self):
        self.state = _MockDbState()
        self.restore_points: dict[str, dict] = {
            "BEFORE_UPGRADE_20260611": {
                "name": "BEFORE_UPGRADE_20260611",
                "scn": 1_800_000,
                "time": "2026-06-11T22:00:00",
                "guarantee": True,
                "storage_size": 1 * GIB,
            }
        }
        self.tables: dict[tuple[str, str], dict] = {
            ("SCOTT", "EMP"): {"row_movement": True},
            ("SCOTT", "DEPT"): {"row_movement": False},
        }
        self.recyclebin: list[dict] = [
            {
                "owner": "SCOTT",
                "object_name": "BIN$jx8kQ3vT==$0",
                "original_name": "BONUS",
                "droptime": "2026-06-12T08:30:00",
            }
        ]
        self.audit: list[dict] = []

    # ------------------------------------------------------------------

    def _tick(self) -> None:
        self.state.current_scn += 1

    def get_status(self) -> dict:
        st = self.state
        return {
            "log_mode": st.log_mode,
            "flashback_on": st.flashback.on,
            "db_state": st.db_state,
            "current_scn": st.current_scn,
            "oldest_flashback_scn": st.flashback.oldest_scn,
            "oldest_flashback_time": st.flashback.oldest_time,
            "retention_minutes": st.flashback.retention_minutes,
            "fra_limit_bytes": st.fra.limit_bytes,
            "fra_used_bytes": st.fra.used_bytes,
            "estimated_flashback_size": st.fra.estimated_flashback_size,
        }

    def timestamp_to_scn(self, ts: str) -> int:
        # Spec §4 deterministic formula: +1 SCN per second from the oldest
        # flashback baseline, capped at current_scn.
        oldest = datetime.fromisoformat(self.state.flashback.oldest_time)
        target = datetime.fromisoformat(ts)
        seconds = int((target - oldest).total_seconds())
        return min(self.state.flashback.oldest_scn + seconds, self.state.current_scn)

    def list_restore_points(self) -> list[dict]:
        return sorted(self.restore_points.values(), key=lambda rp: rp["scn"])

    def create_restore_point(self, name: str, guarantee: bool) -> dict:
        self._tick()
        rp = {
            "name": name,
            "scn": self.state.current_scn,
            "time": _now(),
            "guarantee": guarantee,
            "storage_size": 1 * GIB if guarantee else 0,
        }
        self.restore_points[name] = rp
        if guarantee:
            self.state.fra.used_bytes += 1 * GIB
        return rp

    def drop_restore_point(self, name: str) -> None:
        rp = self.restore_points.pop(name)
        if rp["guarantee"]:
            self.state.fra.used_bytes -= rp["storage_size"]
        self._tick()

    def list_recyclebin(self, owner: Optional[str] = None) -> list[dict]:
        entries = [e for e in self.recyclebin if owner is None or e["owner"] == owner.upper()]
        return sorted(entries, key=lambda e: e["droptime"], reverse=True)

    def get_table(self, owner: str, table_name: str) -> Optional[dict]:
        return self.tables.get((owner.upper(), table_name.upper()))

    def enable_row_movement(self, owner: str, table_name: str) -> None:
        self.tables[(owner.upper(), table_name.upper())]["row_movement"] = True
        self._tick()

    def flashback_table(self, owner: str, table_name: str, scn: int) -> None:
        self._tick()

    def flashback_drop(self, owner: str, table_name: str, rename_to: Optional[str]) -> dict:
        matches = [
            e
            for e in self.recyclebin
            if e["owner"] == owner.upper() and e["original_name"] == table_name.upper()
        ]
        entry = max(matches, key=lambda e: e["droptime"])  # most recent drop
        self.recyclebin.remove(entry)
        restored_as = (rename_to or table_name).upper()
        self.tables[(owner.upper(), restored_as)] = {"row_movement": False}
        self._tick()
        return {"restored_as": restored_as, "from_entry": entry}

    def flashback_database(self, scn: int) -> None:
        self.state.db_state = "FLASHBACKED"
        self.state.current_scn = scn

    def open_resetlogs(self) -> None:
        self.state.db_state = "OPEN"
        self.state.resetlogs_time = _now()
        self._tick()

    def append_audit(self, entry: dict) -> None:
        self.audit.append(entry)

    def list_audit(self, limit: int) -> list[dict]:
        return list(reversed(self.audit))[:limit]
