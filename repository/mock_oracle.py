"""Deterministic in-memory Oracle for MOCK_ORACLE=true (spec §4 mock state).

Simulates the effects of the SQL documented on OracleRepository:
- every mutating operation advances current_scn by 1
- creating a guaranteed restore point consumes 1 GiB of FRA (lets tests
  drive the P3 threshold)
"""

from datetime import datetime, timezone
from typing import Optional

from repository.oracle_client import OracleRepository

GIB = 2**30


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


class MockOracleRepository(OracleRepository):
    def __init__(self):
        self.log_mode = "ARCHIVELOG"
        self.flashback_on = True
        self.db_state = "OPEN"
        self.current_scn = 2_000_000
        self.oldest_flashback_scn = 1_500_000
        self.oldest_flashback_time = "2026-06-11T09:00:00"
        self.retention_minutes = 1440
        self.fra_limit_bytes = 10 * GIB
        self.fra_used_bytes = 4 * GIB
        self.estimated_flashback_size = 2 * GIB
        self.resetlogs_time: Optional[str] = None

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
        self.current_scn += 1

    def get_status(self) -> dict:
        return {
            "log_mode": self.log_mode,
            "flashback_on": self.flashback_on,
            "db_state": self.db_state,
            "current_scn": self.current_scn,
            "oldest_flashback_scn": self.oldest_flashback_scn,
            "oldest_flashback_time": self.oldest_flashback_time,
            "retention_minutes": self.retention_minutes,
            "fra_limit_bytes": self.fra_limit_bytes,
            "fra_used_bytes": self.fra_used_bytes,
            "estimated_flashback_size": self.estimated_flashback_size,
        }

    def list_restore_points(self) -> list[dict]:
        return sorted(self.restore_points.values(), key=lambda rp: rp["scn"])

    def create_restore_point(self, name: str, guarantee: bool) -> dict:
        self._tick()
        rp = {
            "name": name,
            "scn": self.current_scn,
            "time": _now(),
            "guarantee": guarantee,
            "storage_size": 1 * GIB if guarantee else 0,
        }
        self.restore_points[name] = rp
        if guarantee:
            self.fra_used_bytes += 1 * GIB
        return rp

    def drop_restore_point(self, name: str) -> None:
        rp = self.restore_points.pop(name)
        if rp["guarantee"]:
            self.fra_used_bytes -= rp["storage_size"]
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
            e for e in self.recyclebin
            if e["owner"] == owner.upper() and e["original_name"] == table_name.upper()
        ]
        entry = max(matches, key=lambda e: e["droptime"])  # most recent drop
        self.recyclebin.remove(entry)
        restored_as = (rename_to or table_name).upper()
        self.tables[(owner.upper(), restored_as)] = {"row_movement": False}
        self._tick()
        return {"restored_as": restored_as, "from_entry": entry}

    def flashback_database(self, scn: int) -> None:
        self.db_state = "FLASHBACKED"
        self.current_scn = scn

    def open_resetlogs(self) -> None:
        self.db_state = "OPEN"
        self.resetlogs_time = _now()
        self._tick()

    def append_audit(self, entry: dict) -> None:
        self.audit.append(entry)

    def list_audit(self, limit: int) -> list[dict]:
        return list(reversed(self.audit))[:limit]
