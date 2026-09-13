"""L1 API tests — the CMMS contract that carries over (02), plus the operator
surface of the dashboard: fleet, parts, documents, media, SPA serving,
asks, telemetry ingest, pack activation, reset, 413/422 discipline.
"""

import json
import sqlite3

import pytest

from app import db
from conftest import (ASSET, INCIDENT_WO, PACK_ID, add_evidence, inject, to_decide)


def _approved_work_order(operator, agent):
    _incident_id, proposal, _ = to_decide(operator, agent)
    operator.post(f"/api/v1/proposals/{proposal['id']}/decision", json={"action": "approve"})
    return operator.get("/api/v1/work-orders").json()[0]


# -- CMMS records ---------------------------------------------------------------

def test_work_order_read_routes_on_both_ports(agent, operator):
    wo = _approved_work_order(operator, agent)
    for client in (agent, operator):
        assert [w["id"] for w in client.get("/api/v1/work-orders").json()] == [wo["id"]]
        assert client.get(f"/api/v1/work-orders/{wo['id']}").json()["id"] == wo["id"]
        assert client.get("/api/v1/work-orders/nope").status_code == 404
        assert client.get("/api/v1/work-orders?status=open").json()[0]["id"] == wo["id"]
        assert client.get(f"/api/v1/work-orders?equipment={ASSET}").json()
        assert client.get("/api/v1/work-orders?status=urgent").status_code == 422


def test_patch_work_order_operator_only(agent, operator):
    wo = _approved_work_order(operator, agent)
    url = f"/api/v1/work-orders/{wo['id']}"
    assert agent.patch(url, json={"status": "resolved"}).status_code == 404
    patched = operator.patch(url, json={"status": "in_progress", "assigned_to": None})
    assert patched.status_code == 200
    body = patched.json()
    assert body["status"] == "in_progress" and body["assigned_to"] is None
    assert body["updated_at"] >= wo["updated_at"]
    assert operator.patch(url, json={}).status_code == 422
    assert operator.patch(url, json={"status": None}).status_code == 422
    assert operator.patch(url, json={"status": "done"}).status_code == 422
    assert operator.patch("/api/v1/work-orders/nope",
                          json={"status": "resolved"}).status_code == 404


def test_notifications_filter(agent, operator):
    _approved_work_order(operator, agent)
    assert len(operator.get("/api/v1/notifications").json()) == 1
    assert len(operator.get("/api/v1/notifications?unread=true").json()) == 1
    assert len(operator.get("/api/v1/notifications?unread=false").json()) == 1
    assert operator.get("/api/v1/notifications?unread=maybe").status_code == 422


def test_hostile_ids_are_404_not_500(operator, agent):
    for hostile in ("' OR 1=1 --", "..%2F..%2Fetc%2Fpasswd", "x" * 300):
        assert operator.get(f"/api/v1/incidents/{hostile}").status_code == 404
        assert agent.get(f"/api/v1/proposals/{hostile}").status_code == 404


# -- body limit ------------------------------------------------------------------

@pytest.mark.parametrize("port", ["agent", "operator"])
def test_body_over_256kb_is_413(request, port):
    client = request.getfixturevalue(port)
    path = "/api/v1/evidence" if port == "agent" else "/api/v1/incidents/inject"
    response = client.post(path, content=b"{" + b" " * (300 * 1024) + b"}",
                           headers={"content-type": "application/json"})
    assert response.status_code == 413
    assert "256 KB" in response.json()["detail"]


def test_chunked_body_over_limit_is_413(agent):
    def chunks():
        for _ in range(300):
            yield b" " * 1024

    response = agent.post("/api/v1/evidence", content=chunks(),
                          headers={"content-type": "application/json"})
    assert response.status_code == 413


# -- fleet, parts, incidents -----------------------------------------------------

def test_fleet_status_follows_incident(agent, operator):
    fleet = operator.get("/api/v1/fleet").json()
    assert fleet["pack_id"] == PACK_ID
    statuses = {a["asset_id"]: a["status"] for a in fleet["assets"]}
    assert statuses == {"M-1": "normal", "M-2": "normal"}
    m1 = next(a for a in fleet["assets"] if a["asset_id"] == "M-1")
    assert m1["injectable"] == ["M1-BEARING", "M1-TREND"]
    incident = inject(operator)
    assert operator.get("/api/v1/fleet/M-1").json()["status"] == "alarm"
    assert agent.get("/api/v1/fleet/M-1").json()["incident"] == incident["id"]
    assert operator.get("/api/v1/fleet/M-2").json()["status"] == "normal"
    assert operator.get("/api/v1/fleet/nope").status_code == 404


def test_parts_readable_by_agent(agent):
    parts = agent.get("/api/v1/parts").json()
    assert parts[0]["part_number"] == "6312-2RS" and parts[0]["on_hand_local"] == 0


def test_agent_view_never_carries_ambiguous(agent, operator):
    incident = inject(operator)
    agent_view = agent.get(f"/api/v1/incidents/{incident['id']}").json()
    assert "ambiguous" not in agent_view["definition"]
    assert agent_view["definition"]["downtime_cost_per_hour"] == 4200
    assert "ambiguous" not in json.dumps(agent.get("/api/v1/incidents/current").json())
    operator_view = operator.get(f"/api/v1/incidents/{incident['id']}").json()
    assert operator_view["definition"]["ambiguous"] is True


def test_current_incident(agent, operator):
    assert agent.get("/api/v1/incidents/current").status_code == 404
    incident = inject(operator)
    assert agent.get("/api/v1/incidents/current").json()["id"] == incident["id"]
    assert [i["id"] for i in operator.get("/api/v1/incidents").json()] == [incident["id"]]


def test_inject_unknown_incident_404(operator):
    response = operator.post("/api/v1/incidents/inject",
                             json={"asset_id": "M-2", "incident_id": INCIDENT_WO})
    assert response.status_code == 404


def test_evidence_validation(agent, operator):
    incident = inject(operator)
    base = {"incident_id": incident["id"], "source_type": "vss",
            "source_id": "anomaly.mp4@00:42", "quote": "heat shimmer",
            "claim": "housing hot", "confidence": "medium"}
    assert agent.post("/api/v1/evidence", json=dict(base, t_start=42, t_end=40)).status_code == 422
    assert agent.post("/api/v1/evidence", json=dict(base, t_end=40)).status_code == 422
    assert agent.post("/api/v1/evidence", json=dict(base, confidence="certain")).status_code == 422
    ok = agent.post("/api/v1/evidence", json=dict(base, t_start=40, t_end=44))
    assert ok.status_code == 201
    listed = agent.get(f"/api/v1/incidents/{incident['id']}/evidence").json()
    assert [e["id"] for e in listed] == [ok.json()["id"]]
    assert agent.get("/api/v1/incidents/nope/evidence").status_code == 404


def test_evidence_rejected_after_decision(agent, operator):
    incident_id, _proposal, _ = to_decide(operator, agent)
    response = agent.post("/api/v1/evidence", json={
        "incident_id": incident_id, "source_type": "agent", "source_id": "note",
        "quote": "late", "claim": "late", "confidence": "low"})
    assert response.status_code == 409


# -- documents and media ----------------------------------------------------------

def test_documents_with_sections(operator):
    listing = operator.get(f"/api/v1/packs/{PACK_ID}/documents").json()
    assert listing == [{"id": "manual-01", "content_type": "manual",
                        "file": "manual-01.md", "sha256": None, "available": True}]
    doc = operator.get(f"/api/v1/packs/{PACK_ID}/documents/manual-01").json()
    anchors = [s["anchor"] for s in doc["sections"]]
    assert anchors == ["motor-manual", "4.2", "replacement-procedure"]
    assert "75 °C" in doc["text"]
    assert operator.get(f"/api/v1/packs/{PACK_ID}/documents/nope").status_code == 404
    assert operator.get("/api/v1/packs/nope/documents").status_code == 404


def test_clip_full_and_ranged(operator):
    url = f"/media/clips/{PACK_ID}/anomaly.mp4"
    full = operator.get(url)
    assert full.status_code == 200 and len(full.content) == 1024
    assert full.headers["accept-ranges"] == "bytes"
    part = operator.get(url, headers={"Range": "bytes=10-19"})
    assert part.status_code == 206
    assert part.content == bytes(range(10, 20))
    assert part.headers["content-range"] == "bytes 10-19/1024"
    tail = operator.get(url, headers={"Range": "bytes=-4"})
    assert tail.content == bytes([252, 253, 254, 255])
    open_ended = operator.get(url, headers={"Range": "bytes=1020-"})
    assert open_ended.content == bytes([252, 253, 254, 255])
    for bad in ("bytes=2000-3000", "bytes=-", "items=0-1", "bytes=9-3"):
        assert operator.get(url, headers={"Range": bad}).status_code == 416


def test_clip_must_be_declared_by_the_pack(operator, packs_dir):
    (packs_dir / PACK_ID / "clips" / "secret.mp4").write_bytes(b"x")
    assert operator.get(f"/media/clips/{PACK_ID}/secret.mp4").status_code == 404
    assert operator.get(f"/media/clips/{PACK_ID}/..%2Fpack.yaml").status_code == 404


# -- SPA serving ------------------------------------------------------------------

def test_spa_index_assets_and_fallback(operator):
    index = operator.get("/")
    assert index.status_code == 200 and "<div id=root>" in index.text
    assert operator.get("/assets/app.js").text == "console.log('ok')"
    deep = operator.get("/incidents/some-id")
    assert deep.status_code == 200 and "<div id=root>" in deep.text
    assert operator.get("/assets/missing-abc123.js").status_code == 404
    assert operator.get("/favicon.ico").status_code == 404
    api_miss = operator.get("/api/v1/nope")
    assert api_miss.status_code == 404 and api_miss.json() == {"detail": "Not Found"}
    escaped = operator.get("/assets/../../pack.yaml")
    assert escaped.status_code == 404 and "pack_id" not in escaped.text


def test_spa_not_built_is_503(operator, ui_dist):
    (ui_dist / "index.html").unlink()
    response = operator.get("/")
    assert response.status_code == 503


def test_ui_bundle_has_no_external_urls_when_built():
    """D6 offline constraint: when the real bundle exists, it references no
    CDN or external font host."""
    from app.core import APP_DIR
    dist = APP_DIR / "ui_dist"
    if not (dist / "index.html").is_file():
        pytest.skip("UI bundle not built in this checkout")
    for path in dist.rglob("*"):
        if path.suffix in (".html", ".css", ".js"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for host in ("fonts.googleapis.com", "fonts.gstatic.com", "cdn.jsdelivr",
                         "unpkg.com", "cdnjs.cloudflare.com"):
                assert host not in text, (path, host)


# -- asks (§8.6) -------------------------------------------------------------------

def test_ask_the_footage_records_evidence_and_audit(agent, operator, fake_vss):
    incident_id, proposal, _ = to_decide(operator, agent)
    response = operator.post(f"/api/v1/incidents/{incident_id}/ask",
                             json={"question": "Is there fluid under the housing?"})
    assert response.status_code == 202
    asks = operator.get(f"/api/v1/incidents/{incident_id}/asks").json()
    assert asks[0]["status"] == "answered"
    assert asks[0]["answer"] == fake_vss.answer
    evidence = operator.get(f"/api/v1/incidents/{incident_id}/evidence").json()
    asked = next(e for e in evidence if e["id"] == asks[0]["evidence_id"])
    assert asked["source_type"] == "vss" and asked["t_start"] == 40.0
    types = [e["type"] for e in operator.get(f"/api/v1/incidents/{incident_id}/events").json()]
    assert "ask.answer" in types
    operator.post(f"/api/v1/proposals/{proposal['id']}/decision", json={"action": "approve"})
    record = operator.get("/api/v1/audit").json()[0]["record"]
    assert record["asks"][0]["question"] == "Is there fluid under the housing?"


def test_ask_failure_is_a_visible_error(agent, operator, fake_vss):
    incident_id, _proposal, _ = to_decide(operator, agent)
    fake_vss.fail_ask = True
    operator.post(f"/api/v1/incidents/{incident_id}/ask", json={"question": "Any smoke?"})
    asks = operator.get(f"/api/v1/incidents/{incident_id}/asks").json()
    assert asks[0]["status"] == "failed" and "failed" in asks[0]["error"]
    errors = [e for e in operator.get(f"/api/v1/incidents/{incident_id}/events").json()
              if e["type"] == "error"]
    assert errors and errors[-1]["recoverable"] is True


def test_ask_rules(agent, operator):
    incident_id, proposal, _ = to_decide(operator, agent)
    assert operator.post(f"/api/v1/incidents/{incident_id}/ask",
                         json={"question": "?"}).status_code == 422
    assert operator.post("/api/v1/incidents/nope/ask",
                         json={"question": "Any smoke?"}).status_code == 404
    operator.post(f"/api/v1/proposals/{proposal['id']}/decision",
                  json={"action": "deny", "reason": "no"})
    assert operator.post(f"/api/v1/incidents/{incident_id}/ask",
                         json={"question": "Any smoke?"}).status_code == 409


# -- telemetry ingest (ADR-V09) ----------------------------------------------------

def test_agent_events_map_to_skill_and_token_events(agent, operator):
    unattached = agent.post("/api/v1/agent-events", json={"hook": "llm_output", "text": "hi"})
    assert unattached.status_code == 202 and unattached.json()["attached"] is False
    incident = inject(operator)
    for event in (
        {"hook": "llm_output", "run_id": "r1", "text": "I will check the manual."},
        {"hook": "before_tool_call", "run_id": "r1", "tool_name": "read",
         "params": {"path": "/sandbox/skills/vss-generate-video-report-rag/SKILL.md"}},
        {"hook": "after_tool_call", "run_id": "r1", "tool_name": "exec", "duration_ms": 5},
        {"hook": "agent_end", "run_id": "r1"},
    ):
        assert agent.post("/api/v1/agent-events", json=event).status_code == 202
    events = operator.get(f"/api/v1/incidents/{incident['id']}/events").json()
    mapped = [(e["type"], e.get("skill_name")) for e in events
              if e["type"] in ("agent.token", "skill.invoked", "skill.completed")]
    assert mapped == [("agent.token", None),
                      ("skill.invoked", "vss-generate-video-report-rag"),
                      ("skill.completed", "vss-generate-video-report-rag")]
    invoked = next(e for e in events if e["type"] == "skill.invoked")
    assert invoked["rationale"] == "I will check the manual."
    # Telemetry never moves the incident.
    assert operator.get(f"/api/v1/incidents/{incident['id']}").json()["stage"] == "gather"


def test_agent_event_schema(agent):
    assert agent.post("/api/v1/agent-events", json={"hook": "set_stage"}).status_code == 422


# -- packs, reset -----------------------------------------------------------------

def test_pack_listing_and_activation(operator):
    packs = operator.get("/api/v1/packs").json()
    assert packs[0]["pack_id"] == PACK_ID and packs[0]["active"] is True
    assert packs[0]["skills"] == ["vss-generate-video-report-rag", "vss-ask-video"]
    assert operator.post(f"/api/v1/packs/{PACK_ID}/activate").json()["pack_id"] == PACK_ID
    assert operator.post("/api/v1/packs/nope/activate").status_code == 404
    inject(operator)
    assert operator.post(f"/api/v1/packs/{PACK_ID}/activate").status_code == 409


def test_reset_keeps_cmms_records_and_audit(agent, operator):
    wo = _approved_work_order(operator, agent)
    assert operator.post("/api/v1/demo/reset").json() == {"incidents_cleared": 1}
    assert operator.get("/api/v1/incidents").json() == []
    assert operator.get("/api/v1/work-orders").json()[0]["id"] == wo["id"]
    assert operator.get("/api/v1/fleet/M-1").json()["status"] == "normal"
    assert operator.get("/api/v1/audit").json()[0]["kind"] == "reset"


def test_health_degraded_when_db_unreachable(agent, ops, monkeypatch):
    def broken(_path):
        raise sqlite3.OperationalError("disk gone")

    monkeypatch.setattr(db, "connect", broken)
    response = agent.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "error"}


def test_evidence_added_is_immediately_listed_on_operator(agent, operator):
    incident = inject(operator)
    row = add_evidence(agent, incident["id"])
    events = operator.get(f"/api/v1/incidents/{incident['id']}/events?after_seq=2").json()
    assert events[-1]["type"] == "evidence.added"
    assert events[-1]["evidence"]["id"] == row["id"]
    assert all(e["seq"] > 2 for e in events)
