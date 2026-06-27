"""Oracle repository interface + real implementation (spec §4).

Each method's docstring carries the exact SQL the real implementation runs;
MockOracleRepository (repository/mock_oracle.py) simulates the effect.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class OracleRepository(ABC):
    """Data access for all flashback-related Oracle operations."""

    @abstractmethod
    def get_status(self) -> dict:
        """v$database (log_mode, flashback_on, current_scn), v$recovery_file_dest,
        v$flashback_database_log, SHOW PARAMETER db_flashback_retention_target."""

    @abstractmethod
    def timestamp_to_scn(self, ts: str) -> int:
        """SELECT TIMESTAMP_TO_SCN(TO_TIMESTAMP(:ts,'YYYY-MM-DD"T"HH24:MI:SS'))
        FROM dual
        Caller checks the P4 lower bound first; result never exceeds current_scn
        (mock caps explicitly; real Oracle cannot return a future SCN)."""

    @abstractmethod
    def list_restore_points(self) -> list[dict]:
        """SELECT name, scn, time, guarantee_flashback_database, storage_size
        FROM v$restore_point ORDER BY scn"""

    @abstractmethod
    def create_restore_point(self, name: str, guarantee: bool) -> dict:
        """CREATE RESTORE POINT <name> [GUARANTEE FLASHBACK DATABASE]"""

    @abstractmethod
    def drop_restore_point(self, name: str) -> None:
        """DROP RESTORE POINT <name>"""

    @abstractmethod
    def list_recyclebin(self, owner: Optional[str] = None) -> list[dict]:
        """SELECT owner, object_name, original_name, droptime FROM dba_recyclebin
        [WHERE owner = :owner] ORDER BY droptime DESC"""

    @abstractmethod
    def get_table(self, owner: str, table_name: str) -> Optional[dict]:
        """SELECT row_movement FROM dba_tables
        WHERE owner = :owner AND table_name = :table_name"""

    @abstractmethod
    def enable_row_movement(self, owner: str, table_name: str) -> None:
        """ALTER TABLE <owner>.<table_name> ENABLE ROW MOVEMENT"""

    @abstractmethod
    def flashback_table(self, owner: str, table_name: str, scn: int) -> None:
        """FLASHBACK TABLE <owner>.<table_name> TO SCN <scn>"""

    @abstractmethod
    def flashback_drop(self, owner: str, table_name: str, rename_to: Optional[str]) -> dict:
        """FLASHBACK TABLE <owner>.<table_name> TO BEFORE DROP [RENAME TO <rename_to>]
        Restores the most recently dropped version; returns the consumed
        recyclebin entry + restored name."""

    @abstractmethod
    def flashback_database(self, scn: int) -> None:
        """SHUTDOWN IMMEDIATE; STARTUP MOUNT;
        FLASHBACK DATABASE TO SCN <scn>;
        ALTER DATABASE OPEN READ ONLY
        Leaves db_state = FLASHBACKED (read-only validation window)."""

    @abstractmethod
    def open_resetlogs(self) -> None:
        """SHUTDOWN IMMEDIATE; STARTUP MOUNT; ALTER DATABASE OPEN RESETLOGS"""

    @abstractmethod
    def append_audit(self, entry: dict) -> None:
        """Persist one audit entry (real: INSERT INTO flashback_audit_log)."""

    @abstractmethod
    def list_audit(self, limit: int) -> list[dict]:
        """Most recent audit entries, newest first."""


class RealOracleRepository(OracleRepository):
    """Thin wrapper over python-oracledb in SYSDBA mode.

    Lazy import so the package is optional in mock/test environments.
    Skeleton implementation: each method executes the SQL documented on the
    interface; wire-up retained minimal until a real Oracle target exists.
    """

    def __init__(self, dsn: str, user: str, password: str):
        # Optional driver, lazy-imported so mock/test envs need not install it.
        import oracledb  # pylint: disable=import-outside-toplevel

        self._oracledb = oracledb
        self._params = {"dsn": dsn, "user": user, "password": password}
        logger.info("RealOracleRepository configured for dsn=%s", dsn)

    def _conn(self):
        return self._oracledb.connect(mode=self._oracledb.AUTH_MODE_SYSDBA, **self._params)

    # The real implementations execute the SQL from the ABC docstrings.
    # Not exercised in this repo (no Oracle instance); MOCK_ORACLE=true is
    # the supported mode here.
    def get_status(self) -> dict:
        raise NotImplementedError("requires a live Oracle target")

    def timestamp_to_scn(self, ts: str) -> int:
        raise NotImplementedError("requires a live Oracle target")

    def list_restore_points(self) -> list[dict]:
        raise NotImplementedError("requires a live Oracle target")

    def create_restore_point(self, name: str, guarantee: bool) -> dict:
        raise NotImplementedError("requires a live Oracle target")

    def drop_restore_point(self, name: str) -> None:
        raise NotImplementedError("requires a live Oracle target")

    def list_recyclebin(self, owner: Optional[str] = None) -> list[dict]:
        raise NotImplementedError("requires a live Oracle target")

    def get_table(self, owner: str, table_name: str) -> Optional[dict]:
        raise NotImplementedError("requires a live Oracle target")

    def enable_row_movement(self, owner: str, table_name: str) -> None:
        raise NotImplementedError("requires a live Oracle target")

    def flashback_table(self, owner: str, table_name: str, scn: int) -> None:
        raise NotImplementedError("requires a live Oracle target")

    def flashback_drop(self, owner: str, table_name: str, rename_to: Optional[str]) -> dict:
        raise NotImplementedError("requires a live Oracle target")

    def flashback_database(self, scn: int) -> None:
        raise NotImplementedError("requires a live Oracle target")

    def open_resetlogs(self) -> None:
        raise NotImplementedError("requires a live Oracle target")

    def append_audit(self, entry: dict) -> None:
        raise NotImplementedError("requires a live Oracle target")

    def list_audit(self, limit: int) -> list[dict]:
        raise NotImplementedError("requires a live Oracle target")
