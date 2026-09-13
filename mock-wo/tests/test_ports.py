"""ADR-V08 — port isolation. The security-relevant tests: every operator
route is absent from the agent app, and the agent's write routes are absent
from the operator app. An operator route reachable on :8090 is a defect.
"""

import pytest
from fastapi.routing import APIRoute

from conftest import to_decide

OPERATOR_ONLY = [
    ("GET", "/api/v1/stream"),
    ("GET", "/api/v1/packs"),
    ("POST", "/api/v1/packs/test-motors/activate"),
    ("GET", "/api/v1/packs/test-motors/documents"),
    ("GET", "/api/v1/packs/test-motors/documents/manual-01"),
    ("GET", "/media/clips/test-motors/anomaly.mp4"),
    ("GET", "/api/v1/incidents"),
    ("POST", "/api/v1/incidents/inject"),
    ("POST", "/api/v1/incidents/x/retry"),
    ("GET", "/api/v1/incidents/x/events"),
    ("POST", "/api/v1/incidents/x/ask"),
    ("GET", "/api/v1/incidents/x/asks"),
    ("POST", "/api/v1/proposals/x/decision"),
    ("PATCH", "/api/v1/work-orders/x"),
    ("GET", "/api/v1/notifications"),
    ("GET", "/api/v1/audit"),
    ("POST", "/api/v1/demo/reset"),
]

AGENT_ONLY = [
    ("POST", "/api/v1/proposals"),
    ("POST", "/api/v1/evidence"),
    ("POST", "/api/v1/agent-events"),
    ("POST", "/ragproxy/v1/search"),
    ("GET", "/ragproxy/v1/health"),
]


def _routes(app):
    table = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                table.add((method, route.path))
    return table


def test_no_mutating_route_on_both_ports(agent_app, operator_app):
    agent = _routes(agent_app)
    operator = _routes(operator_app)
    shared = agent & operator
    assert shared, "read routes are expected on both ports"
    assert all(method == "GET" for method, _ in shared), sorted(shared)


def test_decision_route_is_not_registered_on_agent_app(agent_app):
    paths = {path for _, path in _routes(agent_app)}
    assert "/api/v1/proposals/{proposal_id}/decision" not in paths
    # The only PATCH on the agent port is the ragproxy passthrough to RAG.
    assert {path for method, path in _routes(agent_app) if method == "PATCH"} == {
        "/ragproxy/v1/{path:path}"}


@pytest.mark.parametrize("method,path", OPERATOR_ONLY)
def test_operator_routes_are_404_on_agent_port(agent, method, path):
    response = agent.request(method, path, json={})
    assert response.status_code == 404, (method, path, response.status_code)


@pytest.mark.parametrize("method,path", AGENT_ONLY)
def test_agent_routes_are_404_on_operator_port(operator, method, path):
    response = operator.request(method, path, json={})
    assert response.status_code == 404, (method, path, response.status_code)


def test_agent_cannot_approve_its_own_proposal(agent, operator):
    """The concrete D1 scenario: the agent files a proposal and then tries
    the decision endpoint on the only port it can reach."""
    _incident_id, proposal, _ = to_decide(operator, agent)
    attempt = agent.post(f"/api/v1/proposals/{proposal['id']}/decision",
                         json={"action": "approve"})
    assert attempt.status_code == 404
    assert agent.get("/api/v1/work-orders").json() == []
    assert agent.get(f"/api/v1/proposals/{proposal['id']}").json()["state"] == "pending"


@pytest.mark.parametrize("path", ["/api/v1/work-orders", "/api/v1/notes"])
def test_removed_public_create_routes(agent, operator, path):
    """§6.1: work orders and notes are no longer created by public POST."""
    assert agent.post(path, json={}).status_code == 404
    assert operator.post(path, json={}).status_code == 404


def test_health_identifies_port(agent, operator):
    assert agent.get("/health").json() == {"status": "ok", "db": "ok", "port": "agent"}
    assert operator.get("/health").json() == {"status": "ok", "db": "ok",
                                               "port": "operator"}


def test_agent_port_does_not_serve_the_ui(agent):
    assert agent.get("/").status_code == 404
    assert agent.get("/assets/app.js").status_code == 404
