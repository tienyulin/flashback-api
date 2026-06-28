"""Business rules from the SOP: precondition checks (P1-P6), risk gating
for irreversible operations, audit writes (spec §3/§6/§7)."""

import logging
import os
from datetime import datetime, timezone
from typing import Callable, Optional

from models.schemas import (
    CONFIRM_TOKEN,
    NEXT_STEP_DB_FINALIZE,
    NOTE_FD_BIN_INDEX,
    NOTE_FT_ROLLBACK,
    WARNING_FZ_RMAN,
    FlashbackDatabaseRequest,
    FlashbackDropRequest,
    FlashbackTableRequest,
    FinalizeRequest,
)
from repository.oracle_client import OracleRepository

logger = logging.getLogger(__name__)


class FlashbackError(Exception):
    """Maps an SOP precondition violation to HTTP (spec §6 error model)."""

    def __init__(self, status_code: int, detail: str, error_code: Optional[str] = None):
        self.status_code = status_code
        self.detail = detail
        self.error_code = error_code
        super().__init__(detail)


def _fra_threshold() -> float:
    return float(os.getenv("FRA_USAGE_THRESHOLD", "85"))


class FlashbackService:
    """SOP business rules: precondition gating, risk confirmation, audit (spec §3/§6/§7)."""

    def __init__(self, oracle: OracleRepository):
        self.oracle = oracle

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def status(self) -> dict:
        """Return DB status plus the P1-P3 precondition snapshot (spec §3)."""
        s = self.oracle.get_status()
        usage = s["fra_used_bytes"] / s["fra_limit_bytes"] * 100
        return {
            **s,
            "fra_usage_percent": round(usage, 1),
            "preconditions": {
                "P1_archivelog": s["log_mode"] == "ARCHIVELOG",
                "P2_flashback_on": s["flashback_on"],
                "P3_fra_space": usage < _fra_threshold(),
            },
        }

    def list_restore_points(self) -> list[dict]:
        """List existing restore points (read-only)."""
        return self.oracle.list_restore_points()

    def list_recyclebin(self, owner: Optional[str]) -> list[dict]:
        """List recycle-bin entries, optionally filtered by owner (read-only)."""
        return self.oracle.list_recyclebin(owner)

    def list_audit(self, limit: int) -> list[dict]:
        """Return the most recent audit records, newest first (read-only)."""
        return self.oracle.list_audit(limit)

    # ------------------------------------------------------------------
    # Precondition checks (SOP §2) — raise FlashbackError on violation
    # ------------------------------------------------------------------

    def _check_p1_archivelog(self, s: dict):
        if s["log_mode"] != "ARCHIVELOG":
            raise FlashbackError(409, "P1 violated: database is not in ARCHIVELOG mode")

    def _check_p2_flashback_on(self, s: dict):
        if not s["flashback_on"]:
            raise FlashbackError(409, "P2 violated: flashback logging is not enabled")

    def _check_p3_fra(self, s: dict):
        usage = s["fra_used_bytes"] / s["fra_limit_bytes"] * 100
        if usage >= _fra_threshold():
            raise FlashbackError(
                409,
                f"P3 violated: FRA usage {usage:.1f}% >= {_fra_threshold():.0f}% — "
                "enlarge DB_RECOVERY_FILE_DEST_SIZE or drop expired backups / used "
                "guaranteed restore points",
                error_code="ORA-19809",
            )

    def _check_p4_within_retention(
        self, s: dict, target_scn: Optional[int], target_time: Optional[str]
    ):
        if target_scn is not None and target_scn < s["oldest_flashback_scn"]:
            raise FlashbackError(
                409,
                f"P4 violated: target SCN {target_scn} is older than oldest flashback "
                f"SCN {s['oldest_flashback_scn']} — use RMAN point-in-time recovery",
                error_code="ORA-38729",
            )
        if target_time is not None and target_time < s["oldest_flashback_time"]:
            raise FlashbackError(
                409,
                f"P4 violated: target time {target_time} is older than oldest flashback "
                f"time {s['oldest_flashback_time']} — use RMAN point-in-time recovery",
                error_code="ORA-38729",
            )

    def _require_confirmation(self, confirm: Optional[str], approval_id: Optional[str]):
        """Risk gate for irreversible operations (spec §2 general rules)."""
        if confirm != CONFIRM_TOKEN or not (approval_id or "").strip():
            raise FlashbackError(
                428,
                f"irreversible operation requires confirm='{CONFIRM_TOKEN}' "
                "and a non-empty approval_id (change-approval ticket)",
            )

    # ------------------------------------------------------------------
    # Audit (spec §7)
    # ------------------------------------------------------------------

    def _audit(self, operator: str, operation: str, result: str, **fields):
        """Append one audit record (spec §7).

        Optional ``fields`` carry the operation target and context:
        ``target``, ``target_scn``, ``target_time``, ``dry_run``, ``approval_id``.
        """
        self.oracle.append_audit(
            {
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                "operator": operator,
                "operation": operation,
                "target": fields.get("target"),
                "target_scn": fields.get("target_scn"),
                "target_time": fields.get("target_time"),
                "dry_run": fields.get("dry_run", False),
                "approval_id": fields.get("approval_id"),
                "result": result,
            }
        )

    def _run_checks(self, checks: dict[str, Callable[[], None]]) -> dict[str, dict]:
        """Run named precondition checks; collect pass/fail without raising."""
        results: dict[str, dict] = {}
        for name, fn in checks.items():
            try:
                fn()
                results[name] = {"ok": True}
            except FlashbackError as e:
                results[name] = {"ok": False, "detail": e.detail, "error_code": e.error_code}
        return results

    @staticmethod
    def _raise_first_failure(checks: dict[str, dict], originals: dict[str, Callable[[], None]]):
        """Re-run the first failed check so it raises with its real status/error_code."""
        for name, result in checks.items():
            if not result["ok"]:
                originals[name]()  # re-raise with proper status/error_code

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def create_restore_point(
        self, name: str, guarantee: bool, dry_run: bool, operator: str
    ) -> dict:
        """Create a (guaranteed) restore point after the FRA-space + name checks."""
        name = name.upper()
        s = self.oracle.get_status()

        def check_duplicate():
            if any(rp["name"] == name for rp in self.oracle.list_restore_points()):
                raise FlashbackError(
                    409,
                    f"restore point '{name}' already exists — rename or DELETE it first",
                    error_code="ORA-38796",
                )

        originals = {
            "P3_fra_space": lambda: self._check_p3_fra(s),
            "no_duplicate_name": check_duplicate,
        }
        checks = self._run_checks(originals)

        if dry_run:
            self._audit(
                operator, "create_restore_point", target=name, dry_run=True, result="dry_run"
            )
            return {"dry_run": True, "would_create": name, "checks": checks}

        try:
            self._raise_first_failure(checks, originals)
            rp = self.oracle.create_restore_point(name, guarantee)
        except FlashbackError as e:
            self._audit(
                operator,
                "create_restore_point",
                target=name,
                result=f"rejected:{e.error_code or e.detail}",
            )
            raise
        self._audit(operator, "create_restore_point", target=name, result="success")
        return {"dry_run": False, "restore_point": rp}

    def drop_restore_point(self, name: str, dry_run: bool, operator: str) -> dict:
        """Drop a restore point by name; 404 if it does not exist."""
        name = name.upper()
        existing = {rp["name"]: rp for rp in self.oracle.list_restore_points()}
        if name not in existing:
            self._audit(
                operator,
                "drop_restore_point",
                target=name,
                dry_run=dry_run,
                result="rejected:ORA-38780",
            )
            raise FlashbackError(
                404,
                f"restore point '{name}' does not exist — see GET /restore_points",
                error_code="ORA-38780",
            )
        if dry_run:
            self._audit(operator, "drop_restore_point", target=name, dry_run=True, result="dry_run")
            return {"dry_run": True, "would_drop": existing[name]}
        self.oracle.drop_restore_point(name)
        self._audit(operator, "drop_restore_point", target=name, result="success")
        return {"dry_run": False, "dropped": existing[name]}

    def flashback_table(self, req: FlashbackTableRequest, operator: str) -> dict:
        """Flashback one table to an SCN/timestamp (reversible; gated by P1/P4/P6)."""
        owner, table = req.owner.upper(), req.table_name.upper()
        target_label = f"{owner}.{table}"
        s = self.oracle.get_status()

        table_info = self.oracle.get_table(owner, table)
        if table_info is None:
            self._audit(
                operator,
                "flashback_table",
                target=target_label,
                dry_run=req.dry_run,
                result="rejected:table-not-found",
            )
            raise FlashbackError(404, f"table {target_label} not found")

        if req.target.scn is not None and req.target.scn > s["current_scn"]:
            raise FlashbackError(
                422,
                f"target SCN {req.target.scn} is in the future "
                f"(current_scn={s['current_scn']})",
            )

        def check_p6():
            info = self.oracle.get_table(owner, table)
            assert info is not None  # table existence already verified above
            if not info["row_movement"]:
                raise FlashbackError(
                    409,
                    f"P6 violated: {target_label} has ROW MOVEMENT disabled — "
                    "retry with enable_row_movement=true",
                    error_code="ORA-08189",
                )

        originals = {
            "P1_archivelog": lambda: self._check_p1_archivelog(s),
            "P4_within_retention": lambda: self._check_p4_within_retention(
                s, req.target.scn, req.target.timestamp
            ),
            "P6_row_movement": check_p6,
        }
        checks = self._run_checks(originals)

        if req.dry_run:
            # AC-FT-3: prior_scn included so the caller records the rollback
            # point before executing; enable_row_movement is NOT applied.
            self._audit(
                operator,
                "flashback_table",
                target=target_label,
                target_scn=req.target.scn,
                target_time=req.target.timestamp,
                dry_run=True,
                result="dry_run",
            )
            return {"dry_run": True, "prior_scn": s["current_scn"], "checks": checks}

        try:
            # Auxiliary mutation (auto ENABLE ROW MOVEMENT) only after every
            # OTHER precondition is known to pass — a doomed request must not
            # leave side effects (iteration-2 audit DRIFT-003).
            others = {k: v for k, v in checks.items() if k != "P6_row_movement"}
            self._raise_first_failure(others, originals)
            if req.enable_row_movement and not checks["P6_row_movement"]["ok"]:
                self.oracle.enable_row_movement(owner, table)
                checks["P6_row_movement"] = {"ok": True}
            self._raise_first_failure(checks, originals)

            prior_scn = self.oracle.get_status()["current_scn"]
            # Spec target-resolution order: P4 checked on the original input
            # form above; timestamp resolves to SCN only now (AC-FT-2).
            if req.target.scn is not None:
                executed_scn = req.target.scn
            else:
                assert req.target.timestamp is not None  # target validator: scn xor timestamp
                executed_scn = self.oracle.timestamp_to_scn(req.target.timestamp)
            self.oracle.flashback_table(owner, table, executed_scn)
        except FlashbackError as e:
            self._audit(
                operator,
                "flashback_table",
                target=target_label,
                target_scn=req.target.scn,
                target_time=req.target.timestamp,
                result=f"rejected:{e.error_code or e.detail}",
            )
            raise
        except Exception as e:
            self._audit(
                operator,
                "flashback_table",
                target=target_label,
                target_scn=req.target.scn,
                target_time=req.target.timestamp,
                result=f"error:{e}",
            )
            raise

        self._audit(
            operator,
            "flashback_table",
            target=target_label,
            target_scn=req.target.scn,
            target_time=req.target.timestamp,
            result="success",
        )
        return {
            "dry_run": False,
            "flashed_back": target_label,
            "prior_scn": prior_scn,
            "executed_scn": executed_scn,
            "note": NOTE_FT_ROLLBACK,
        }

    def flashback_drop(self, req: FlashbackDropRequest, operator: str) -> dict:
        """Restore a dropped table from the recycle bin (reversible)."""
        owner, table = req.owner.upper(), req.table_name.upper()
        target_label = f"{owner}.{table}"

        in_bin = [e for e in self.oracle.list_recyclebin(owner) if e["original_name"] == table]
        if not in_bin:
            self._audit(
                operator,
                "flashback_drop",
                target=target_label,
                dry_run=req.dry_run,
                result="rejected:ORA-38305",
            )
            raise FlashbackError(
                404,
                f"{target_label} is not in the recycle bin (purged, or recyclebin=off) — "
                "use RMAN or export from an auxiliary database",
                error_code="ORA-38305",
            )

        restored_name = (req.rename_to or table).upper()
        if self.oracle.get_table(owner, restored_name) is not None:
            self._audit(
                operator,
                "flashback_drop",
                target=target_label,
                dry_run=req.dry_run,
                result="rejected:ORA-38312",
            )
            raise FlashbackError(
                409,
                f"table {owner}.{restored_name} already exists — retry with rename_to",
                error_code="ORA-38312",
            )

        if req.dry_run:
            self._audit(
                operator, "flashback_drop", target=target_label, dry_run=True, result="dry_run"
            )
            return {"dry_run": True, "would_restore": in_bin[0], "restored_as": restored_name}

        result = self.oracle.flashback_drop(owner, table, req.rename_to)
        self._audit(operator, "flashback_drop", target=target_label, result="success")
        return {
            "dry_run": False,
            **result,
            "note": NOTE_FD_BIN_INDEX,
        }

    def flashback_database(self, req: FlashbackDatabaseRequest, operator: str) -> dict:
        """Flashback the whole DB to an SCN/time/restore-point (irreversible; confirm-gated)."""
        s = self.oracle.get_status()

        # Resolve target to an SCN first — a nonexistent restore point is 404
        # regardless of dry_run.
        target_scn, target_time = req.target.scn, req.target.timestamp
        if req.target.restore_point is not None:
            name = req.target.restore_point.upper()
            rp = {p["name"]: p for p in self.oracle.list_restore_points()}.get(name)
            if rp is None:
                self._audit(
                    operator,
                    "flashback_database",
                    target=name,
                    dry_run=req.dry_run,
                    result="rejected:ORA-38780",
                )
                raise FlashbackError(
                    404,
                    f"restore point '{name}' does not exist — see GET /restore_points",
                    error_code="ORA-38780",
                )
            target_scn = rp["scn"]

        rp_name = req.target.restore_point.upper() if req.target.restore_point else None

        originals = {
            "P1_archivelog": lambda: self._check_p1_archivelog(s),
            "P2_flashback_on": lambda: self._check_p2_flashback_on(s),
            "P3_fra_space": lambda: self._check_p3_fra(s),
            "P4_within_retention": lambda: self._check_p4_within_retention(
                s, target_scn, target_time
            ),
            "db_state_open": lambda: self._check_db_open(s),
        }
        checks = self._run_checks(originals)

        def resolve_scn():
            """Spec resolution order: P4 on the original form, then timestamp
            resolves via the repository (read-only; capped at current_scn)."""
            if target_scn is not None:
                return target_scn
            assert target_time is not None  # target validator: scn xor timestamp xor restore_point
            return self.oracle.timestamp_to_scn(target_time)

        if req.dry_run:
            # AC-DB-2: timestamp resolves only when P4 passed, else null.
            resolved = resolve_scn() if checks["P4_within_retention"]["ok"] else None
            self._audit(
                operator,
                "flashback_database",
                target=rp_name,
                target_scn=target_scn,
                target_time=target_time,
                dry_run=True,
                approval_id=req.approval_id,
                result="dry_run",
            )
            return {
                "dry_run": True,
                "checks": checks,
                "estimated_flashback_size": s["estimated_flashback_size"],
                "resolved_target_scn": resolved,
            }

        self._require_confirmation(req.confirm, req.approval_id)
        try:
            self._raise_first_failure(checks, originals)
            flashed_scn = resolve_scn()
            self.oracle.flashback_database(flashed_scn)
        except FlashbackError as e:
            self._audit(
                operator,
                "flashback_database",
                target=rp_name,
                target_scn=target_scn,
                target_time=target_time,
                approval_id=req.approval_id,
                result=f"rejected:{e.error_code or e.detail}",
            )
            raise
        except Exception as e:
            self._audit(
                operator,
                "flashback_database",
                target=rp_name,
                target_scn=target_scn,
                target_time=target_time,
                approval_id=req.approval_id,
                result=f"error:{e}",
            )
            raise

        self._audit(
            operator,
            "flashback_database",
            target=rp_name,
            target_scn=target_scn,
            target_time=target_time,
            approval_id=req.approval_id,
            result="success",
        )
        return {
            "dry_run": False,
            "db_state": "FLASHBACKED",
            "flashed_back_to_scn": flashed_scn,
            "next_step": NEXT_STEP_DB_FINALIZE,
        }

    def _check_db_open(self, s: dict):
        if s["db_state"] != "OPEN":
            raise FlashbackError(
                409,
                f"database state is {s['db_state']} — another flashback is in "
                "progress (finalize or recover it first)",
            )

    def finalize_database(self, req: FinalizeRequest, operator: str) -> dict:
        """Commit a flashbacked DB via OPEN RESETLOGS (irreversible; confirm-gated)."""
        s = self.oracle.get_status()
        if s["db_state"] != "FLASHBACKED":
            self._audit(
                operator,
                "finalize_database",
                dry_run=req.dry_run,
                approval_id=req.approval_id,
                result="rejected:not-flashbacked",
            )
            raise FlashbackError(
                409,
                f"database state is {s['db_state']} — nothing to finalize "
                "(expected FLASHBACKED, i.e. read-only validation window)",
            )
        if req.dry_run:
            self._audit(
                operator,
                "finalize_database",
                dry_run=True,
                approval_id=req.approval_id,
                result="dry_run",
            )
            return {"dry_run": True, "would_finalize_at_scn": s["current_scn"]}

        self._require_confirmation(req.confirm, req.approval_id)
        self.oracle.open_resetlogs()
        self._audit(operator, "finalize_database", approval_id=req.approval_id, result="success")
        return {
            "dry_run": False,
            "db_state": "OPEN",
            "warning": WARNING_FZ_RMAN,
        }
