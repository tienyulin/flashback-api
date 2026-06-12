"""Endpoint tests per spec §8 — all against MockOracleRepository."""
from fastapi.testclient import TestClient

from core import deps
from main import app
from models.schemas import CONFIRM_TOKEN

client = TestClient(app)

CONFIRMED = {"confirm": CONFIRM_TOKEN, "approval_id": "CHG-2026-0612-001"}


def _mock():
    """The live MockOracleRepository behind the current singletons."""
    return deps.get_oracle()


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def test_status_fields_and_preconditions():
    body = client.get("/flashback/status").json()
    assert body["log_mode"] == "ARCHIVELOG"
    assert body["current_scn"] == 2_000_000
    assert body["fra_usage_percent"] == 40.0
    assert body["preconditions"] == {
        "P1_archivelog": True, "P2_flashback_on": True, "P3_fra_space": True,
    }


# ---------------------------------------------------------------------------
# restore points
# ---------------------------------------------------------------------------

def test_list_restore_points_seeded():
    body = client.get("/restore_points").json()
    assert [rp["name"] for rp in body["restore_points"]] == ["BEFORE_UPGRADE_20260611"]


def test_create_restore_point_dry_run_does_not_change_state():
    resp = client.post("/restore_points", json={"name": "before_test_20260612"})
    assert resp.status_code == 200
    assert resp.json()["dry_run"] is True
    assert resp.json()["checks"]["no_duplicate_name"]["ok"] is True
    assert len(client.get("/restore_points").json()["restore_points"]) == 1


def test_create_restore_point_executes():
    resp = client.post(
        "/restore_points", json={"name": "before_test_20260612", "dry_run": False}
    )
    assert resp.status_code == 200
    rp = resp.json()["restore_point"]
    assert rp["name"] == "BEFORE_TEST_20260612"  # uppercased
    assert rp["guarantee"] is True
    assert len(client.get("/restore_points").json()["restore_points"]) == 2


def test_create_duplicate_restore_point_409():
    resp = client.post(
        "/restore_points",
        json={"name": "BEFORE_UPGRADE_20260611", "dry_run": False},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "ORA-38796"


def test_create_restore_point_fra_full_409():
    _mock().fra_used_bytes = int(_mock().fra_limit_bytes * 0.9)  # 90% > 85%
    resp = client.post("/restore_points", json={"name": "x", "dry_run": False})
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "ORA-19809"


def test_drop_restore_point():
    resp = client.delete("/restore_points/before_upgrade_20260611?dry_run=false")
    assert resp.status_code == 200
    assert resp.json()["dropped"]["guarantee"] is True
    assert client.get("/restore_points").json()["restore_points"] == []


def test_drop_missing_restore_point_404():
    resp = client.delete("/restore_points/NOPE?dry_run=false")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "ORA-38780"


# ---------------------------------------------------------------------------
# flashback table
# ---------------------------------------------------------------------------

def _table_req(**over):
    req = {
        "owner": "SCOTT", "table_name": "EMP",
        "target": {"scn": 1_700_000}, "dry_run": False,
    }
    req.update(over)
    return req


def test_flashback_table_dry_run_returns_checks():
    resp = client.post("/flashback/table", json=_table_req(dry_run=True))
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert body["checks"]["P4_within_retention"]["ok"] is True
    assert body["checks"]["P6_row_movement"]["ok"] is True


def test_flashback_table_executes_with_prior_scn():
    resp = client.post("/flashback/table", json=_table_req())
    assert resp.status_code == 200
    body = resp.json()
    assert body["prior_scn"] == 2_000_000
    assert client.get("/flashback/status").json()["current_scn"] > 2_000_000


def test_flashback_table_row_movement_disabled_409():
    resp = client.post("/flashback/table", json=_table_req(table_name="DEPT"))
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "ORA-08189"


def test_flashback_table_auto_enable_row_movement():
    resp = client.post(
        "/flashback/table", json=_table_req(table_name="DEPT", enable_row_movement=True)
    )
    assert resp.status_code == 200
    assert _mock().get_table("SCOTT", "DEPT")["row_movement"] is True


def test_flashback_table_beyond_retention_409():
    resp = client.post(
        "/flashback/table", json=_table_req(target={"scn": 1_400_000})
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "ORA-38729"


def test_flashback_table_unknown_table_404():
    resp = client.post("/flashback/table", json=_table_req(table_name="GHOST"))
    assert resp.status_code == 404


def test_flashback_table_target_must_be_exactly_one():
    resp = client.post(
        "/flashback/table",
        json=_table_req(target={"scn": 1, "timestamp": "2026-06-12T09:00:00"}),
    )
    assert resp.status_code == 422


def test_flashback_table_future_scn_422():
    resp = client.post("/flashback/table", json=_table_req(target={"scn": 9_999_999}))
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# flashback drop
# ---------------------------------------------------------------------------

def test_flashback_drop_restores_from_recyclebin():
    resp = client.post(
        "/flashback/drop",
        json={"owner": "SCOTT", "table_name": "BONUS", "dry_run": False},
    )
    assert resp.status_code == 200
    assert resp.json()["restored_as"] == "BONUS"
    assert client.get("/recyclebin").json()["entries"] == []


def test_flashback_drop_not_in_recyclebin_404():
    resp = client.post(
        "/flashback/drop",
        json={"owner": "SCOTT", "table_name": "GHOST", "dry_run": False},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "ORA-38305"


def test_flashback_drop_name_conflict_409_then_rename_ok():
    # EMP still exists — restoring a dropped EMP would collide.
    _mock().recyclebin.append({
        "owner": "SCOTT", "object_name": "BIN$x==$0",
        "original_name": "EMP", "droptime": "2026-06-12T08:45:00",
    })
    conflict = client.post(
        "/flashback/drop",
        json={"owner": "SCOTT", "table_name": "EMP", "dry_run": False},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "ORA-38312"

    renamed = client.post(
        "/flashback/drop",
        json={"owner": "SCOTT", "table_name": "EMP",
              "rename_to": "EMP_RESTORED", "dry_run": False},
    )
    assert renamed.status_code == 200
    assert renamed.json()["restored_as"] == "EMP_RESTORED"


# ---------------------------------------------------------------------------
# flashback database + finalize (irreversible gates)
# ---------------------------------------------------------------------------

def _db_req(**over):
    req = {"target": {"restore_point": "BEFORE_UPGRADE_20260611"}, "dry_run": False}
    req.update(over)
    return req


def test_flashback_database_dry_run_state_unchanged():
    resp = client.post("/flashback/database", json=_db_req(dry_run=True))
    assert resp.status_code == 200
    assert resp.json()["dry_run"] is True
    assert all(c["ok"] for c in resp.json()["checks"].values())
    assert client.get("/flashback/status").json()["db_state"] == "OPEN"


def test_flashback_database_requires_confirm_428():
    assert client.post("/flashback/database", json=_db_req()).status_code == 428


def test_flashback_database_requires_approval_id_428():
    resp = client.post(
        "/flashback/database", json=_db_req(confirm=CONFIRM_TOKEN, approval_id="  ")
    )
    assert resp.status_code == 428


def test_flashback_database_unknown_restore_point_404():
    resp = client.post(
        "/flashback/database",
        json=_db_req(target={"restore_point": "NOPE"}, **CONFIRMED),
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "ORA-38780"


def test_flashback_database_full_flow_and_finalize():
    resp = client.post("/flashback/database", json=_db_req(**CONFIRMED))
    assert resp.status_code == 200
    assert resp.json()["db_state"] == "FLASHBACKED"
    assert resp.json()["flashed_back_to_scn"] == 1_800_000

    # second flashback while not OPEN -> 409
    again = client.post("/flashback/database", json=_db_req(**CONFIRMED))
    assert again.status_code == 409

    # finalize without confirm -> 428
    assert client.post(
        "/flashback/database/finalize", json={"dry_run": False}
    ).status_code == 428

    done = client.post(
        "/flashback/database/finalize", json={"dry_run": False, **CONFIRMED}
    )
    assert done.status_code == 200
    assert done.json()["db_state"] == "OPEN"
    assert "RMAN" in done.json()["warning"]


def test_finalize_without_pending_flashback_409():
    resp = client.post(
        "/flashback/database/finalize", json={"dry_run": False, **CONFIRMED}
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

def test_mutations_require_api_key_when_configured(monkeypatch):
    monkeypatch.setenv("FLASHBACK_API_KEY", "secret-key")
    assert client.post("/restore_points", json={"name": "x"}).status_code == 401
    assert client.get("/flashback/status").status_code == 200  # reads stay open
    ok = client.post(
        "/restore_points", json={"name": "x"}, headers={"X-API-Key": "secret-key"}
    )
    assert ok.status_code == 200


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------

def test_audit_records_dry_run_rejected_and_success():
    client.post("/restore_points", json={"name": "a"})                      # dry_run
    client.post("/restore_points", json={"name": "a", "dry_run": False})    # success
    client.post("/restore_points",
                json={"name": "BEFORE_UPGRADE_20260611", "dry_run": False})  # rejected

    entries = client.get("/audit/log").json()["entries"]
    results = [e["result"] for e in entries]
    assert results[0].startswith("rejected:ORA-38796")  # newest first
    assert "success" in results
    assert "dry_run" in results
    assert all(e["operator"] == "dev" for e in entries)
