"""M1 — incident state machine and inject/kick flow (§3, §5.2, §7.2)."""

import pytest

from app import ops as ops_module
from app.ops import TRANSITIONS
from conftest import INCIDENT_NOTE, INCIDENT_WO, add_evidence, inject, note_proposal, to_decide


def _stages(operator, incident_id):
    return [(e["previous"], e["stage"]) for e in
            operator.get(f"/api/v1/incidents/{incident_id}/events").json()
            if e["type"] == "stage.changed"]


def test_inject_detect_then_gather_when_wake_succeeds(operator, fake_vss, fake_wake):
    incident = inject(operator)
    assert incident["stage"] == "detect"
    assert fake_vss.uploaded == ["anomaly.mp4"]
    assert len(fake_wake.texts) == 1 and incident["id"] in fake_wake.texts[0]
    assert _stages(operator, incident["id"]) == [(None, "detect"), ("detect", "gather")]
    events = operator.get(f"/api/v1/incidents/{incident['id']}/events").json()
    progress = next(e for e in events if e["type"] == "analysis.progress")
    assert progress["eta_seconds"] == 200 and progress["basis"] == "pack_expected_duration"
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))


@pytest.mark.parametrize("failure", ["upload", "wake"])
def test_kick_failure_stays_in_detect_with_visible_error(operator, fake_vss, fake_wake,
                                                         failure):
    if failure == "upload":
        fake_vss.fail_upload = True
    else:
        fake_wake.fail = True
    incident = inject(operator)
    current = operator.get(f"/api/v1/incidents/{incident['id']}").json()
    assert current["stage"] == "detect"
    errors = [e for e in operator.get(f"/api/v1/incidents/{incident['id']}/events").json()
              if e["type"] == "error"]
    assert errors[0]["stage"] == "detect" and errors[0]["recoverable"] is True
    # Retry after the dependency recovers.
    fake_vss.fail_upload = False
    fake_wake.fail = False
    assert operator.post(f"/api/v1/incidents/{incident['id']}/retry").status_code == 202
    assert operator.get(f"/api/v1/incidents/{incident['id']}").json()["stage"] == "gather"
    assert operator.post(f"/api/v1/incidents/{incident['id']}/retry").status_code == 409


def test_missing_clip_is_an_error_not_a_crash(operator, packs_dir):
    (packs_dir / "test-motors" / "clips" / "anomaly.mp4").unlink()
    incident = inject(operator)
    errors = [e for e in operator.get(f"/api/v1/incidents/{incident['id']}/events").json()
              if e["type"] == "error"]
    assert "not present" in errors[0]["message"]


def test_one_incident_at_a_time(operator):
    inject(operator)
    second = operator.post("/api/v1/incidents/inject",
                           json={"asset_id": "M-1", "incident_id": INCIDENT_NOTE})
    assert second.status_code == 409


def test_next_inject_closes_an_incident_resting_in_act(agent, operator):
    first = inject(operator, incident_id=INCIDENT_NOTE)
    add_evidence(agent, first["id"])
    agent.post("/api/v1/proposals", json=note_proposal(first["id"]))
    assert operator.get(f"/api/v1/incidents/{first['id']}").json()["stage"] == "act"
    assert operator.get("/api/v1/fleet/M-1").json()["status"] == "attention"
    second = inject(operator, incident_id=INCIDENT_WO)
    closed = operator.get(f"/api/v1/incidents/{first['id']}").json()
    assert closed["stage"] == "closed" and closed["closed_at"]
    assert operator.get("/api/v1/incidents/current").json()["id"] == second["id"]


def test_transition_table_is_forward_only():
    order = ["detect", "gather", "propose", "decide", "act", "closed"]
    for current, allowed in TRANSITIONS.items():
        if current is None:
            assert allowed == ("detect",)
            continue
        for target in allowed:
            assert order.index(target) > order.index(current), (current, target)


def test_illegal_transition_raises_conflict(agent, operator, ops):
    incident_id, _proposal, _ = to_decide(operator, agent)
    with ops._tx() as tx:
        from app import db
        row = db.get_incident(tx.conn, incident_id)
        with pytest.raises(ops_module.Conflict):
            ops._advance(tx, row, "gather")


def test_events_backfill_after_seq(agent, operator):
    incident_id, _proposal, _ = to_decide(operator, agent)
    everything = operator.get(f"/api/v1/incidents/{incident_id}/events").json()
    tail = operator.get(f"/api/v1/incidents/{incident_id}/events?after_seq=3").json()
    assert tail == everything[3:]
    assert operator.get(f"/api/v1/incidents/{incident_id}/events?after_seq=-5").json() == everything
    assert operator.get("/api/v1/incidents/nope/events").status_code == 404


def test_kick_is_a_no_op_outside_detect(agent, operator, ops, fake_wake):
    incident_id, _proposal, _ = to_decide(operator, agent)
    ops.kick(incident_id)
    assert len(fake_wake.texts) == 1


def test_no_packs_installed(tmp_path):
    from app.core import Core, Settings
    empty = tmp_path / "empty"
    empty.mkdir()
    core = Core.build(Settings(db_path=str(tmp_path / "db.sqlite"), packs_dir=empty))
    operations = ops_module.Operations(core)
    with pytest.raises(ops_module.Unavailable):
        operations.fleet()


def test_default_pack_setting_is_honoured(tmp_path, packs_dir):
    from conftest import PACK_YAML, write_pack
    from app.core import Core, Settings
    other_root = tmp_path / "second"
    other_root.mkdir()
    pack = write_pack(other_root, PACK_YAML.replace("test-motors", "zz-pack"))
    pack.rename(packs_dir / "zz-pack")
    settings = Settings(db_path=str(tmp_path / "db2.sqlite"), packs_dir=packs_dir,
                        default_pack="zz-pack")
    operations = ops_module.Operations(Core.build(settings))
    assert operations.active_pack().pack_id == "zz-pack"
    operations.activate_pack("test-motors")
    assert operations.active_pack().pack_id == "test-motors"
