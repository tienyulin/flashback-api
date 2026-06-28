"""Endpoint tests — one or more per acceptance criterion (spec §3/§8).

Test names carry the AC id they verify. All against MockOracleRepository.
"""

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
# health / status / reads
# ---------------------------------------------------------------------------


def test_ac_hl_1_health():
    """AC-HL-1: /health returns the ok payload."""
    assert client.get("/health").json() == {"status": "ok"}


def test_ac_st_1_status_fields_and_preconditions():
    """AC-ST-1: status exposes DB fields and the P1-P3 precondition flags."""
    body = client.get("/flashback/status").json()
    assert body["log_mode"] == "ARCHIVELOG"
    assert body["db_state"] == "OPEN"
    assert body["current_scn"] == 2_000_000
    assert body["fra_usage_percent"] == 40.0
    assert body["preconditions"] == {
        "P1_archivelog": True,
        "P2_flashback_on": True,
        "P3_fra_space": True,
    }


def test_ac_rpl_1_list_restore_points_scn_ascending():
    """AC-RPL-1: restore points list ordered by SCN ascending."""
    body = client.get("/restore_points").json()
    assert [rp["name"] for rp in body["restore_points"]] == ["BEFORE_UPGRADE_20260611"]


def test_ac_rb_1_recyclebin_droptime_descending():
    """AC-RB-1: recycle bin entries newest drop first."""
    entries = client.get("/recyclebin").json()["entries"]
    assert [e["original_name"] for e in entries] == ["BONUS"]


def test_ac_rb_2_owner_filter_case_insensitive():
    """AC-RB-2: owner filter is case-insensitive and excludes non-owners."""
    assert client.get("/recyclebin?owner=scott").json()["entries"] != []
    assert client.get("/recyclebin?owner=NOBODY").json()["entries"] == []


def test_ac_au_1_audit_log_limit_clamped():
    """AC-AU-1: an oversized limit is clamped, not rejected."""
    assert client.get("/audit/log?limit=99999").status_code == 200


# ---------------------------------------------------------------------------
# restore points
# ---------------------------------------------------------------------------


def test_ac_rpc_1_create_executes_uppercased():
    """AC-RPC-1: create upper-cases the name and persists the restore point."""
    resp = client.post("/restore_points", json={"name": "before_test_20260612", "dry_run": False})
    assert resp.status_code == 200
    rp = resp.json()["restore_point"]
    assert rp["name"] == "BEFORE_TEST_20260612"
    assert len(client.get("/restore_points").json()["restore_points"]) == 2


def test_ac_rpc_2_dry_run_returns_checks_no_state_change():
    """AC-RPC-2: dry-run reports checks and changes no state."""
    resp = client.post("/restore_points", json={"name": "x"})
    body = resp.json()
    assert body["dry_run"] is True
    assert body["would_create"] == "X"
    assert set(body["checks"]) == {"P3_fra_space", "no_duplicate_name"}
    assert body["checks"]["no_duplicate_name"]["ok"] is True
    assert len(client.get("/restore_points").json()["restore_points"]) == 1


def test_ac_rpc_3_duplicate_name_409():
    """AC-RPC-3: duplicate restore-point name is 409 (ORA-38796)."""
    resp = client.post(
        "/restore_points", json={"name": "BEFORE_UPGRADE_20260611", "dry_run": False}
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "ORA-38796"


def test_ac_rpc_4_fra_at_threshold_409():
    """AC-RPC-4: FRA usage exactly at the threshold fails P3 (ORA-19809)."""
    _mock().state.fra.used_bytes = int(_mock().state.fra.limit_bytes * 0.85)  # exactly 85% = fail
    resp = client.post("/restore_points", json={"name": "x", "dry_run": False})
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "ORA-19809"


def test_ac_rpc_5_guarantee_defaults_true():
    """AC-RPC-5: guarantee defaults to true."""
    resp = client.post("/restore_points", json={"name": "g", "dry_run": False})
    assert resp.json()["restore_point"]["guarantee"] is True


def test_ac_rpd_1_drop_returns_full_record():
    """AC-RPD-1: drop returns the full removed record and clears the list."""
    resp = client.delete("/restore_points/before_upgrade_20260611?dry_run=false")
    assert resp.status_code == 200
    assert resp.json()["dropped"]["guarantee"] is True
    assert client.get("/restore_points").json()["restore_points"] == []


def test_ac_rpd_2_dry_run_would_drop():
    """AC-RPD-2: dry-run drop reports the target without removing it."""
    resp = client.delete("/restore_points/BEFORE_UPGRADE_20260611")
    assert resp.json()["would_drop"]["scn"] == 1_800_000
    assert len(client.get("/restore_points").json()["restore_points"]) == 1


def test_ac_rpd_3_missing_404_even_dry_run():
    """AC-RPD-3: dropping a missing restore point is 404 even in dry-run."""
    resp = client.delete("/restore_points/NOPE")  # dry_run defaults true
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "ORA-38780"


# ---------------------------------------------------------------------------
# flashback table
# ---------------------------------------------------------------------------


def _table_req(**over):
    """Build a flashback/table request body, overriding defaults with kwargs."""
    req = {
        "owner": "SCOTT",
        "table_name": "EMP",
        "target": {"scn": 1_700_000},
        "dry_run": False,
    }
    req.update(over)
    return req


def test_ac_ft_1_executes_with_prior_and_executed_scn():
    """AC-FT-1: execute returns prior_scn and executed_scn and advances the DB."""
    resp = client.post("/flashback/table", json=_table_req())
    assert resp.status_code == 200
    body = resp.json()
    assert body["prior_scn"] == 2_000_000
    assert body["executed_scn"] == 1_700_000
    assert client.get("/flashback/status").json()["current_scn"] > 2_000_000


def test_ac_ft_2_timestamp_resolves_to_scn():
    """AC-FT-2: a timestamp target resolves to an SCN, not current_scn."""
    # mock formula: oldest_scn(1_500_000) + seconds since oldest_time
    resp = client.post(
        "/flashback/table",
        json=_table_req(target={"timestamp": "2026-06-11T09:00:10"}),
    )
    assert resp.status_code == 200
    assert resp.json()["executed_scn"] == 1_500_010  # NOT current_scn


def test_ac_ft_3_dry_run_includes_prior_scn_and_checks():
    """AC-FT-3: dry-run returns prior_scn + checks and applies no row-movement."""
    resp = client.post("/flashback/table", json=_table_req(dry_run=True))
    body = resp.json()
    assert body["dry_run"] is True
    assert body["prior_scn"] == 2_000_000
    assert body["checks"]["P4_within_retention"]["ok"] is True
    # dry_run + enable_row_movement must NOT alter the table
    client.post(
        "/flashback/table",
        json=_table_req(table_name="DEPT", dry_run=True, enable_row_movement=True),
    )
    assert _mock().get_table("SCOTT", "DEPT")["row_movement"] is False


def test_ac_ft_4_unknown_table_404_even_dry_run():
    """AC-FT-4: unknown table is 404 even in dry-run."""
    resp = client.post("/flashback/table", json=_table_req(table_name="GHOST", dry_run=True))
    assert resp.status_code == 404


def test_ac_ft_5_scn_below_oldest_409():
    """AC-FT-5: SCN below the oldest flashback SCN fails P4; the boundary passes."""
    resp = client.post("/flashback/table", json=_table_req(target={"scn": 1_499_999}))
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "ORA-38729"
    # boundary: exactly oldest passes P4
    ok = client.post("/flashback/table", json=_table_req(target={"scn": 1_500_000}))
    assert ok.status_code == 200


def test_ac_ft_5_timestamp_below_oldest_409():
    """AC-FT-5: a timestamp before the oldest flashback time fails P4."""
    resp = client.post(
        "/flashback/table",
        json=_table_req(target={"timestamp": "2026-06-11T08:59:59"}),
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "ORA-38729"


def test_ac_ft_6_future_scn_422():
    """AC-FT-6: a future SCN is rejected with 422."""
    resp = client.post("/flashback/table", json=_table_req(target={"scn": 9_999_999}))
    assert resp.status_code == 422


def test_ac_ft_7_row_movement_disabled_409():
    """AC-FT-7: a table with row movement disabled fails P6 (ORA-08189)."""
    resp = client.post("/flashback/table", json=_table_req(table_name="DEPT"))
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "ORA-08189"


def test_ac_ft_8_auto_enable_row_movement():
    """AC-FT-8: enable_row_movement auto-enables it when every other check passes."""
    resp = client.post(
        "/flashback/table", json=_table_req(table_name="DEPT", enable_row_movement=True)
    )
    assert resp.status_code == 200
    assert _mock().get_table("SCOTT", "DEPT")["row_movement"] is True


def test_ac_ft_8_no_side_effect_when_other_check_fails():
    """Doomed request must not auto-enable row movement (iteration-2 DRIFT-003)."""
    resp = client.post(
        "/flashback/table",
        json=_table_req(table_name="DEPT", enable_row_movement=True, target={"scn": 1_400_000}),
    )
    assert resp.status_code == 409  # P4 fails
    assert _mock().get_table("SCOTT", "DEPT")["row_movement"] is False


def test_ac_ft_9_no_idempotency_both_execute():
    """AC-FT-9: repeated flashbacks both execute (no idempotency)."""
    a = client.post("/flashback/table", json=_table_req())
    b = client.post("/flashback/table", json=_table_req())
    assert a.status_code == b.status_code == 200
    ops = [
        e
        for e in client.get("/audit/log").json()["entries"]
        if e["operation"] == "flashback_table" and e["result"] == "success"
    ]
    assert len(ops) == 2


def test_target_exactly_one_key_422():
    """Target validator: both keys or no keys is a 422."""
    resp = client.post(
        "/flashback/table",
        json=_table_req(target={"scn": 1, "timestamp": "2026-06-12T09:00:00"}),
    )
    assert resp.status_code == 422
    resp = client.post("/flashback/table", json=_table_req(target={}))
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# flashback drop
# ---------------------------------------------------------------------------


def test_ac_fd_1_restores_most_recent_drop():
    """AC-FD-1: restore consumes the recycle-bin entry and restores the table."""
    resp = client.post(
        "/flashback/drop",
        json={"owner": "SCOTT", "table_name": "BONUS", "dry_run": False},
    )
    assert resp.status_code == 200
    assert resp.json()["restored_as"] == "BONUS"
    assert client.get("/recyclebin").json()["entries"] == []


def test_ac_fd_2_rename_to_null_uses_original_name():
    """AC-FD-2: a null rename_to falls back to the original name."""
    resp = client.post(
        "/flashback/drop",
        json={"owner": "SCOTT", "table_name": "BONUS", "rename_to": None, "dry_run": False},
    )
    assert resp.json()["restored_as"] == "BONUS"


def test_ac_fd_3_dry_run_no_state_change():
    """AC-FD-3: dry-run reports the restore target without changing state."""
    resp = client.post("/flashback/drop", json={"owner": "SCOTT", "table_name": "BONUS"})
    assert resp.json()["dry_run"] is True
    assert resp.json()["restored_as"] == "BONUS"
    assert len(client.get("/recyclebin").json()["entries"]) == 1


def test_ac_fd_4_not_in_recyclebin_404():
    """AC-FD-4: a table not in the recycle bin is 404 (ORA-38305)."""
    resp = client.post(
        "/flashback/drop", json={"owner": "SCOTT", "table_name": "GHOST", "dry_run": False}
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "ORA-38305"


def test_ac_fd_5_name_conflict_409_then_rename_ok():
    """AC-FD-5: a name collision is 409 (ORA-38312); rename_to resolves it."""
    _mock().recyclebin.append(
        {
            "owner": "SCOTT",
            "object_name": "BIN$x==$0",
            "original_name": "EMP",
            "droptime": "2026-06-12T08:45:00",
        }
    )
    conflict = client.post(
        "/flashback/drop", json={"owner": "SCOTT", "table_name": "EMP", "dry_run": False}
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "ORA-38312"

    renamed = client.post(
        "/flashback/drop",
        json={"owner": "SCOTT", "table_name": "EMP", "rename_to": "EMP_RESTORED", "dry_run": False},
    )
    assert renamed.status_code == 200
    assert renamed.json()["restored_as"] == "EMP_RESTORED"


# ---------------------------------------------------------------------------
# flashback database + finalize
# ---------------------------------------------------------------------------


def _db_req(**over):
    """Build a flashback/database request body, overriding defaults with kwargs."""
    req = {"target": {"restore_point": "BEFORE_UPGRADE_20260611"}, "dry_run": False}
    req.update(over)
    return req


def test_ac_db_1_full_flow_with_resolved_scn():
    """AC-DB-1: restore-point target resolves to its SCN and flashes the DB back."""
    resp = client.post("/flashback/database", json=_db_req(**CONFIRMED))
    assert resp.status_code == 200
    body = resp.json()
    assert body["db_state"] == "FLASHBACKED"
    assert body["flashed_back_to_scn"] == 1_800_000
    assert client.get("/flashback/status").json()["current_scn"] == 1_800_000


def test_ac_db_1_timestamp_target_resolves():
    """AC-DB-1: a timestamp target resolves via the mock formula."""
    resp = client.post(
        "/flashback/database",
        json=_db_req(target={"timestamp": "2026-06-11T09:01:40"}, **CONFIRMED),
    )
    assert resp.status_code == 200
    assert resp.json()["flashed_back_to_scn"] == 1_500_100  # oldest + 100s


def test_ac_db_2_dry_run_checks_and_resolved_scn():
    """AC-DB-2: dry-run returns checks, resolved SCN, and size estimate; no change."""
    resp = client.post("/flashback/database", json=_db_req(dry_run=True))
    body = resp.json()
    assert body["dry_run"] is True
    assert all(c["ok"] for c in body["checks"].values())
    assert body["resolved_target_scn"] == 1_800_000
    assert body["estimated_flashback_size"] == 2 * 2**30
    assert client.get("/flashback/status").json()["db_state"] == "OPEN"


def test_ac_db_2_dry_run_timestamp_below_oldest_resolves_null():
    """AC-DB-2: when P4 fails in dry-run, the resolved SCN is null."""
    resp = client.post(
        "/flashback/database",
        json=_db_req(target={"timestamp": "2026-06-11T08:00:00"}, dry_run=True),
    )
    body = resp.json()
    assert body["checks"]["P4_within_retention"]["ok"] is False
    assert body["resolved_target_scn"] is None


def test_ac_db_3_missing_confirm_or_approval_428():
    """AC-DB-3: missing confirm token or blank approval_id is 428."""
    assert client.post("/flashback/database", json=_db_req()).status_code == 428
    resp = client.post("/flashback/database", json=_db_req(confirm=CONFIRM_TOKEN, approval_id="  "))
    assert resp.status_code == 428


def test_ac_db_4_unknown_restore_point_404_before_428():
    """AC-DB-4: an unknown restore point is 404 even before the confirm gate."""
    # no confirm given — 404 must win (gate 3 before gate 4)
    resp = client.post("/flashback/database", json=_db_req(target={"restore_point": "NOPE"}))
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "ORA-38780"


def test_ac_db_5_p2_violation_detail_prefix():
    """AC-DB-5: a P2 violation returns 409 with a 'P2 violated' detail and no code."""
    _mock().state.flashback.on = False
    resp = client.post("/flashback/database", json=_db_req(**CONFIRMED))
    assert resp.status_code == 409
    assert resp.json()["error_code"] is None
    assert resp.json()["detail"].startswith("P2 violated")


def test_ac_db_6_not_open_409():
    """AC-DB-6: a second flashback while not OPEN is 409."""
    client.post("/flashback/database", json=_db_req(**CONFIRMED))
    again = client.post("/flashback/database", json=_db_req(**CONFIRMED))
    assert again.status_code == 409


def test_ac_fz_1_finalize_resetlogs():
    """AC-FZ-1: finalize runs OPEN RESETLOGS and warns about RMAN."""
    client.post("/flashback/database", json=_db_req(**CONFIRMED))
    done = client.post("/flashback/database/finalize", json={"dry_run": False, **CONFIRMED})
    assert done.status_code == 200
    assert done.json()["db_state"] == "OPEN"
    assert "RMAN" in done.json()["warning"]


def test_ac_fz_2_dry_run_reports_current_scn():
    """AC-FZ-2: finalize dry-run reports the SCN it would finalize at."""
    client.post("/flashback/database", json=_db_req(**CONFIRMED))
    resp = client.post("/flashback/database/finalize", json={"dry_run": True})
    assert resp.json()["would_finalize_at_scn"] == 1_800_000


def test_ac_fz_3_not_flashbacked_409_even_dry_run():
    """AC-FZ-3: finalizing when not FLASHBACKED is 409 even in dry-run."""
    assert client.post("/flashback/database/finalize", json={}).status_code == 409


def test_ac_fz_4_missing_confirm_428():
    """AC-FZ-4: finalize without the confirm token is 428."""
    client.post("/flashback/database", json=_db_req(**CONFIRMED))
    resp = client.post("/flashback/database/finalize", json={"dry_run": False})
    assert resp.status_code == 428


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------


def test_ac_auth_1_mutations_401_without_key(monkeypatch):
    """AC-AUTH-1: mutations require the API key when one is configured."""
    monkeypatch.setenv("FLASHBACK_API_KEY", "secret-key")
    assert client.post("/restore_points", json={"name": "x"}).status_code == 401
    ok = client.post("/restore_points", json={"name": "x"}, headers={"X-API-Key": "secret-key"})
    assert ok.status_code == 200


def test_ac_auth_2_reads_never_require_key(monkeypatch):
    """AC-AUTH-2: read endpoints never require the API key."""
    monkeypatch.setenv("FLASHBACK_API_KEY", "secret-key")
    assert client.get("/flashback/status").status_code == 200
    assert client.get("/audit/log").status_code == 200


# ---------------------------------------------------------------------------
# audit (spec §7)
# ---------------------------------------------------------------------------


def test_audit_result_patterns_and_operator():
    """Audit log records dry_run / success / rejected results with the operator."""
    client.post("/restore_points", json={"name": "a"})  # dry_run
    client.post("/restore_points", json={"name": "a", "dry_run": False})  # success
    client.post(
        "/restore_points", json={"name": "BEFORE_UPGRADE_20260611", "dry_run": False}
    )  # rejected

    entries = client.get("/audit/log").json()["entries"]
    results = [e["result"] for e in entries]
    assert results[0].startswith("rejected:ORA-38796")  # newest first
    assert "success" in results
    assert "dry_run" in results
    assert all(e["operator"] == "dev" for e in entries)


def test_audit_target_fields_per_operation():
    """Audit target/scn/time/approval fields reflect each operation's inputs."""
    client.post("/flashback/table", json=_table_req(target={"timestamp": "2026-06-11T09:00:10"}))
    entry = client.get("/audit/log").json()["entries"][0]
    assert entry["operation"] == "flashback_table"
    assert entry["target"] == "SCOTT.EMP"
    assert entry["target_scn"] is None  # original form was timestamp
    assert entry["target_time"] == "2026-06-11T09:00:10"

    client.post("/flashback/database", json=_db_req(**CONFIRMED))
    entry = client.get("/audit/log").json()["entries"][0]
    assert entry["target"] == "BEFORE_UPGRADE_20260611"
    assert entry["approval_id"] == "CHG-2026-0612-001"
