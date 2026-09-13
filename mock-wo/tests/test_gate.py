"""M4 — the approval gate (ADR-V04, §5.4, §5.5, §8.6). Tested hardest.

Covers proposal validation, the three decision actions, line items, replay
protection (sequential and concurrent), the token-bound execute path, the
ungated monitoring note, and the audit snapshot.
"""

import threading

import pytest

from app import db, ops as ops_module, schemas
from conftest import (ASSET, INCIDENT_NOTE, add_evidence, inject, note_proposal,
                      to_decide, work_order_proposal)


# -- proposal validation ------------------------------------------------------

def test_proposal_moves_incident_through_propose_to_decide(agent, operator):
    incident_id, proposal, evidence = to_decide(operator, agent)
    assert proposal["state"] == "pending"
    assert proposal["kind"] == "work_order"
    assert [li["id"] for li in proposal["line_items"]] == ["li-1", "li-2"]
    assert proposal["evidence_ids"] == [evidence["id"]]
    assert operator.get(f"/api/v1/incidents/{incident_id}").json()["stage"] == "decide"
    stages = [e["stage"] for e in operator.get(
        f"/api/v1/incidents/{incident_id}/events").json()
        if e["type"] == "stage.changed"]
    assert stages == ["detect", "gather", "propose", "decide"]
    # No work order exists before a decision.
    assert operator.get("/api/v1/work-orders").json() == []


def test_proposal_without_evidence_is_rejected(agent, operator):
    incident = inject(operator)
    response = agent.post("/api/v1/proposals", json=work_order_proposal(incident["id"]))
    assert response.status_code == 422
    assert "evidence" in response.json()["detail"]


def test_proposal_equipment_must_match_incident_asset(agent, operator):
    incident = inject(operator)
    add_evidence(agent, incident["id"])
    payload = work_order_proposal(incident["id"])
    payload["draft"]["equipment"] = "M-2"
    response = agent.post("/api/v1/proposals", json=payload)
    assert response.status_code == 422


def test_proposal_unknown_evidence_ids_rejected(agent, operator):
    incident = inject(operator)
    add_evidence(agent, incident["id"])
    response = agent.post("/api/v1/proposals", json=work_order_proposal(
        incident["id"], evidence_ids=["not-an-evidence-row"]))
    assert response.status_code == 422


def test_second_proposal_for_incident_conflicts(agent, operator):
    incident_id, _proposal, _ = to_decide(operator, agent)
    again = agent.post("/api/v1/proposals", json=work_order_proposal(incident_id))
    assert again.status_code == 409


def test_proposal_outside_gather_conflicts(agent, operator, fake_wake):
    fake_wake.fail = True
    incident = inject(operator)  # stays in detect
    response = agent.post("/api/v1/proposals", json=work_order_proposal(incident["id"]))
    assert response.status_code == 409


def test_proposal_unknown_incident_404(agent):
    response = agent.post("/api/v1/proposals", json=work_order_proposal("nope"))
    assert response.status_code == 404


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(kind="purchase_order"),
    lambda p: p["draft"].update(priority="urgent"),
    lambda p: p["draft"].pop("title"),
    lambda p: p.update(impact_if_ignored={"low": 5000, "high": 5000, "unit": "EUR"}),
    lambda p: p.update(confidence_split="70/40"),
    lambda p: p.update(alternate_root_cause="Misalignment"),
])
def test_proposal_shape_violations_are_422(agent, operator, mutate):
    incident = inject(operator)
    add_evidence(agent, incident["id"])
    payload = work_order_proposal(incident["id"])
    mutate(payload)
    assert agent.post("/api/v1/proposals", json=payload).status_code == 422


def test_ambiguous_proposal_shape_accepted(agent, operator):
    incident = inject(operator)
    add_evidence(agent, incident["id"])
    payload = work_order_proposal(
        incident["id"], alternate_root_cause="Shaft misalignment",
        confidence_split="60/40",
        discriminating_test="Laser alignment check on the coupling")
    response = agent.post("/api/v1/proposals", json=payload)
    assert response.status_code == 201
    assert response.json()["confidence_split"] == "60/40"


# -- approve ------------------------------------------------------------------

def test_approve_creates_work_order_and_notification_atomically(agent, operator):
    incident_id, proposal, evidence = to_decide(operator, agent)
    response = operator.post(f"/api/v1/proposals/{proposal['id']}/decision",
                             json={"action": "approve"})
    assert response.status_code == 200, response.text
    decided = response.json()
    assert decided["state"] == "approved"
    work_orders = operator.get("/api/v1/work-orders").json()
    assert len(work_orders) == 1
    wo = work_orders[0]
    assert wo["id"] == decided["decision"]["work_order_id"]
    assert wo["proposal_id"] == proposal["id"]
    assert wo["equipment"] == ASSET and wo["status"] == "open"
    assert wo["citations"] == [{"source_type": "rag", "source_id": evidence["source_id"],
                                "quote": evidence["quote"]}]
    assert "Approved actions:" in wo["description"]
    notifications = operator.get("/api/v1/notifications").json()
    assert [n["work_order_id"] for n in notifications] == [wo["id"]]
    incident = operator.get(f"/api/v1/incidents/{incident_id}").json()
    assert incident["stage"] == "act"
    types = [e["type"] for e in operator.get(
        f"/api/v1/incidents/{incident_id}/events").json()]
    assert types[-3:] == ["decision.recorded", "workorder.created", "stage.changed"]


def test_replay_returns_409_and_creates_nothing(agent, operator):
    _incident_id, proposal, _ = to_decide(operator, agent)
    url = f"/api/v1/proposals/{proposal['id']}/decision"
    assert operator.post(url, json={"action": "approve"}).status_code == 200
    for action in ({"action": "approve"}, {"action": "deny", "reason": "changed mind"}):
        replay = operator.post(url, json=action)
        assert replay.status_code == 409
        assert replay.json()["detail"] == "proposal_already_decided"
    assert len(operator.get("/api/v1/work-orders").json()) == 1


def test_concurrent_approvals_create_exactly_one_work_order(agent, operator, ops):
    _incident_id, proposal, _ = to_decide(operator, agent)
    outcomes = []
    barrier = threading.Barrier(8)

    def decide():
        barrier.wait()
        try:
            ops.decide(proposal["id"], schemas.DecisionIn(action="approve"))
            outcomes.append("ok")
        except ops_module.Conflict:
            outcomes.append("conflict")

    threads = [threading.Thread(target=decide) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("ok") == 1
    assert outcomes.count("conflict") == 7
    assert len(operator.get("/api/v1/work-orders").json()) == 1


def test_execute_path_rejects_a_consumed_or_foreign_token(agent, operator, ops):
    _incident_id, proposal, _ = to_decide(operator, agent)
    operator.post(f"/api/v1/proposals/{proposal['id']}/decision",
                  json={"action": "approve"})
    with db.connect(ops.core.settings.db_path) as conn:
        token = conn.execute("SELECT * FROM decision_tokens").fetchone()
    assert token["consumed_at"] is not None
    full = ops.get_proposal(proposal["id"])
    with ops._tx() as tx:
        incident = db.get_incident(tx.conn, full["incident_id"])
        with pytest.raises(ops_module.Conflict):
            ops._execute_approved(tx, token["token"], full, incident,
                                  full["draft"], [], "now")
        with pytest.raises(ops_module.Conflict):
            ops._execute_approved(tx, "forged-token", full, incident,
                                  full["draft"], [], "now")


def test_partial_line_item_approval(agent, operator):
    _incident_id, proposal, _ = to_decide(operator, agent)
    response = operator.post(f"/api/v1/proposals/{proposal['id']}/decision",
                             json={"action": "approve", "line_items_approved": ["li-1"]})
    assert response.status_code == 200
    assert response.json()["decision"]["line_items_approved"] == ["li-1"]
    wo = operator.get("/api/v1/work-orders").json()[0]
    assert "Order bearing" in wo["description"]
    assert "De-rate" not in wo["description"]


@pytest.mark.parametrize("items", [["li-9"], []])
def test_bad_line_item_selection_is_422(agent, operator, items):
    _incident_id, proposal, _ = to_decide(operator, agent)
    response = operator.post(f"/api/v1/proposals/{proposal['id']}/decision",
                             json={"action": "approve", "line_items_approved": items})
    assert response.status_code == 422
    assert operator.get("/api/v1/work-orders").json() == []


# -- modify -------------------------------------------------------------------

def test_modify_applies_edits_and_preserves_the_draft(agent, operator):
    _incident_id, proposal, _ = to_decide(operator, agent)
    response = operator.post(f"/api/v1/proposals/{proposal['id']}/decision", json={
        "action": "modify", "reason": "Lowered priority: scheduled window",
        "modifications": {"priority": "medium", "assigned_to": "team-a"}})
    assert response.status_code == 200, response.text
    decided = response.json()
    assert decided["state"] == "modified"
    assert decided["draft"]["priority"] == "high"  # draft never overwritten
    assert decided["decision"]["modifications"] == {"priority": "medium",
                                                    "assigned_to": "team-a"}
    wo = operator.get("/api/v1/work-orders").json()[0]
    assert wo["priority"] == "medium" and wo["assigned_to"] == "team-a"


@pytest.mark.parametrize("body", [
    {"action": "modify", "modifications": {"priority": "low"}},          # no note
    {"action": "modify", "reason": "x", "modifications": {}},            # nothing changed
    {"action": "modify", "reason": "x", "modifications": {"equipment": "M-2"}},
    {"action": "approve", "modifications": {"priority": "low"}},
])
def test_modify_rules_are_422(agent, operator, body):
    _incident_id, proposal, _ = to_decide(operator, agent)
    response = operator.post(f"/api/v1/proposals/{proposal['id']}/decision", json=body)
    assert response.status_code == 422


# -- deny ---------------------------------------------------------------------

def test_deny_requires_reason(agent, operator):
    _incident_id, proposal, _ = to_decide(operator, agent)
    url = f"/api/v1/proposals/{proposal['id']}/decision"
    assert operator.post(url, json={"action": "deny"}).status_code == 422
    assert operator.post(url, json={"action": "deny", "reason": "  "}).status_code == 422


def test_deny_closes_incident_without_work_order(agent, operator):
    incident_id, proposal, _ = to_decide(operator, agent)
    response = operator.post(f"/api/v1/proposals/{proposal['id']}/decision",
                             json={"action": "deny", "reason": "wrong root cause"})
    assert response.status_code == 200
    assert response.json()["state"] == "denied"
    assert operator.get("/api/v1/work-orders").json() == []
    incident = operator.get(f"/api/v1/incidents/{incident_id}").json()
    assert incident["stage"] == "closed" and incident["closed_at"]


def test_decision_on_unknown_proposal_404(operator):
    assert operator.post("/api/v1/proposals/nope/decision",
                         json={"action": "approve"}).status_code == 404


# -- monitoring note: proportionate gate -------------------------------------

def test_monitoring_note_files_without_a_gate(agent, operator):
    incident = inject(operator, incident_id=INCIDENT_NOTE)
    add_evidence(agent, incident["id"])
    response = agent.post("/api/v1/proposals", json=note_proposal(incident["id"]))
    assert response.status_code == 201, response.text
    assert response.json()["state"] == "auto_filed"
    notes = operator.get("/api/v1/notes").json()
    assert len(notes) == 1 and notes[0]["proposal_id"] == response.json()["id"]
    assert operator.get("/api/v1/work-orders").json() == []
    events = operator.get(f"/api/v1/incidents/{incident['id']}/events").json()
    final = [e for e in events if e["type"] == "stage.changed"][-1]
    assert final["stage"] == "act" and final["previous"] == "propose"
    assert final["decide"] == "not_required"
    # No decision is possible on an auto-filed note.
    assert operator.post(f"/api/v1/proposals/{response.json()['id']}/decision",
                         json={"action": "approve"}).status_code == 409


def test_note_with_line_items_is_422(agent, operator):
    incident = inject(operator, incident_id=INCIDENT_NOTE)
    add_evidence(agent, incident["id"])
    payload = note_proposal(incident["id"])
    payload["line_items"] = [{"action": "Dispatch"}]
    assert agent.post("/api/v1/proposals", json=payload).status_code == 422


# -- audit --------------------------------------------------------------------

def test_audit_snapshot_survives_reset(agent, operator):
    incident_id, proposal, evidence = to_decide(operator, agent)
    operator.post(f"/api/v1/proposals/{proposal['id']}/decision",
                  json={"action": "deny", "reason": "already addressed"})
    assert operator.post("/api/v1/demo/reset").json() == {"incidents_cleared": 1}
    assert operator.get(f"/api/v1/incidents/{incident_id}").status_code == 404
    audit = operator.get("/api/v1/audit").json()
    kinds = [row["kind"] for row in audit]
    assert kinds == ["reset", "decision", "inject"]
    record = audit[1]["record"]
    assert record["decision"]["action"] == "deny"
    assert record["decision"]["reason"] == "already addressed"
    assert record["proposal"]["draft"]["title"] == "Bearing replacement — M-1"
    assert [e["id"] for e in record["evidence"]] == [evidence["id"]]
    assert record["incident"]["definition"]["ambiguous"] is True  # operator view
