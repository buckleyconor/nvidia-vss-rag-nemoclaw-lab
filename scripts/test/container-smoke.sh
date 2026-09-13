#!/usr/bin/env bash
# L2 container smoke (05-test-strategy.md, TC-028..TC-031; operator
# dashboard ADR-V08).
#
# Self-contained and self-terminating: docker CLI + stdlib urllib only —
# no pip, no venv. Run from the lab repo root. Host ports 18090/18091 —
# never 8090/8091, so the smoke cannot collide with a learner session.
#
# The container runs with MOCK_WO_DEV_FAKE_CLIENTS=1 and the repo packs
# mounted, so one incident can go inject -> evidence -> proposal -> decision
# without VSS or NemoClaw. That flag is for this smoke and the dev machine
# only.
set -euo pipefail

IMAGE=mock-wo:lab
NAME=mock-wo-smoke
AGENT_PORT=18090
OPERATOR_PORT=18091
HEALTH_DEADLINE=60   # the image now runs two servers; 05 step 3 budget
STATUS_DEADLINE=90   # 05 step 5: bounded wait for the image healthcheck
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

fail() { echo "container-smoke: FAIL — $*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "docker CLI not found"
docker info >/dev/null 2>&1 || fail "docker daemon not reachable"

echo "== TC-028: image builds (host arch; UI stage + runtime stage) =="
docker build -t "$IMAGE" -f "$REPO_ROOT/mock-wo/Dockerfile" "$REPO_ROOT/mock-wo"
docker image inspect "$IMAGE" >/dev/null 2>&1 \
    || fail "TC-028: image $IMAGE not present after build"
if docker run --rm --entrypoint sh "$IMAGE" -c 'command -v node' >/dev/null 2>&1; then
    fail "TC-028: node is present in the runtime image (the UI must be built in the first stage only)"
fi

echo "== TC-029: both ports healthy =="
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" \
    -p "${AGENT_PORT}:8090" -p "${OPERATOR_PORT}:8091" \
    -v "$REPO_ROOT/packs:/packs:ro" -v "$REPO_ROOT/fixtures:/fixtures:ro" \
    -e MOCK_WO_DB_PATH=/tmp/smoke.db -e MOCK_WO_DEV_FAKE_CLIENTS=1 \
    "$IMAGE" >/dev/null

python3 - "$AGENT_PORT" "$OPERATOR_PORT" "$HEALTH_DEADLINE" <<'PY' || fail "TC-029: /health not 200 on both ports within ${HEALTH_DEADLINE} s"
import json, sys, time, urllib.request

agent, operator, deadline = sys.argv[1], sys.argv[2], float(sys.argv[3])
start = time.monotonic()
pending = {"agent": agent, "operator": operator}
while pending:
    for name, port in list(pending.items()):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
                body = json.loads(r.read().decode())
                if r.status == 200 and body.get("port") == name:
                    print(f"{name} ok at {time.monotonic() - start:.1f} s: {body}")
                    del pending[name]
        except Exception:
            pass
    if time.monotonic() - start > deadline:
        sys.exit(1)
    time.sleep(0.5)
PY

echo "== TC-030: gated round-trip across the two ports =="
python3 - "$AGENT_PORT" "$OPERATOR_PORT" <<'PY' || fail "TC-030: round-trip failed"
import json, sys, time, urllib.error, urllib.request

agent = f"http://127.0.0.1:{sys.argv[1]}"
operator = f"http://127.0.0.1:{sys.argv[2]}"


def call(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            text = r.read().decode()
            return r.status, (json.loads(text) if text and text[0] in "[{" else text)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


status, incident = call(operator, "POST", "/api/v1/incidents/inject",
                        {"asset_id": "M-3021", "incident_id": "M3021-BEARING-THERMAL"})
assert status == 201, f"inject -> {status} {incident}"
for _ in range(50):
    if call(operator, "GET", f"/api/v1/incidents/{incident['id']}")[1]["stage"] == "gather":
        break
    time.sleep(0.1)
else:
    raise AssertionError("incident never reached gather")
status, evidence = call(agent, "POST", "/api/v1/evidence", {
    "incident_id": incident["id"], "source_type": "rag", "source_id": "manual-01#4.2",
    "quote": "Bearing temperature above 75°C: replace per preventive schedule.",
    "claim": "Smoke: replacement threshold", "document_anchor": "4.2", "confidence": "high"})
assert status == 201, f"evidence -> {status}"
status, proposal = call(agent, "POST", "/api/v1/proposals", {
    "incident_id": incident["id"], "kind": "work_order", "root_cause": "Smoke test",
    "draft": {"title": "Smoke — bearing replacement", "description": "smoke",
              "equipment": "M-3021", "anomaly_ref": "smoke", "priority": "high"}})
assert status == 201 and proposal["state"] == "pending", f"proposal -> {status} {proposal}"
assert call(operator, "GET", "/api/v1/work-orders")[1] == [], "work order exists before a decision"
# ADR-V08 in the real container: the agent port has no decision route.
status, _ = call(agent, "POST", f"/api/v1/proposals/{proposal['id']}/decision", {"action": "approve"})
assert status == 404, f"agent-port decision -> {status}, want 404"
status, decided = call(operator, "POST", f"/api/v1/proposals/{proposal['id']}/decision",
                       {"action": "approve"})
assert status == 200 and decided["state"] == "approved", f"decision -> {status}"
orders = call(agent, "GET", "/api/v1/work-orders")[1]
assert [o["proposal_id"] for o in orders] == [proposal["id"]], "work order not created by approval"
status, _ = call(operator, "POST", f"/api/v1/proposals/{proposal['id']}/decision", {"action": "approve"})
assert status == 409, f"replay -> {status}, want 409"
print("inject -> evidence -> proposal -> (agent 404) -> approve -> work order -> replay 409")
PY

python3 - "$AGENT_PORT" "$OPERATOR_PORT" <<'PY' || fail "TC-030: operator UI not served"
import sys, urllib.error, urllib.request

agent, operator = sys.argv[1], sys.argv[2]
with urllib.request.urlopen(f"http://127.0.0.1:{operator}/", timeout=10) as r:
    html = r.read().decode()
    assert r.status == 200 and '<div id="root">' in html, "SPA index missing"
    for host in ("fonts.googleapis.com", "fonts.gstatic.com", "cdn.", "unpkg.com"):
        assert host not in html, f"external host {host} in index.html"
try:
    urllib.request.urlopen(f"http://127.0.0.1:{agent}/", timeout=10)
    raise AssertionError("agent port serves the UI")
except urllib.error.HTTPError as e:
    assert e.code == 404, f"agent GET / -> {e.code}, want 404"
print("operator UI served on :8091; agent port serves no UI")
PY

echo "== TC-031: healthcheck wiring =="
status=""
start=$(date +%s)
while [ $(( $(date +%s) - start )) -lt "$STATUS_DEADLINE" ]; do
    status=$(docker inspect --format '{{.State.Health.Status}}' "$NAME" \
        2>/dev/null || echo "")
    [ "$status" = "healthy" ] && break
    sleep 5
done
[ "$status" = "healthy" ] \
    || fail "TC-031: Health status is '${status:-<none>}' after ${STATUS_DEADLINE} s, want 'healthy'"
echo "Health status: healthy"

echo "== graceful stop (an open SSE stream must not hold docker stop) =="
python3 - "$OPERATOR_PORT" <<'PY' &
import sys, urllib.request
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/api/v1/stream", timeout=60) as r:
        r.read()
except Exception:
    pass
PY
sleep 1
stop_start=$(date +%s)
docker stop -t 30 "$NAME" >/dev/null
stop_secs=$(( $(date +%s) - stop_start ))
[ "$stop_secs" -lt 10 ] || fail "docker stop took ${stop_secs} s with an SSE client connected"
echo "stopped in ${stop_secs} s"

cleanup
trap - EXIT
echo "container-smoke: PASS (TC-028..TC-031)"
