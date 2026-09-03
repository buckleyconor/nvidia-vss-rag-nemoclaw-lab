#!/usr/bin/env bash
# L2 container smoke (05-test-strategy.md, TC-028..TC-031).
#
# Self-contained and self-terminating: docker CLI + stdlib urllib only —
# no pip, no venv (05: "the smoke script needs no pip at all").
# Run from the lab repo root. Host port 18090 — never 8090, so the smoke
# cannot collide with a learner session.
set -euo pipefail

IMAGE=mock-wo:lab
NAME=mock-wo-smoke
PORT=18090
BASE="http://127.0.0.1:${PORT}"
HEALTH_DEADLINE=30   # 05 step 3: 30 s budget
STATUS_DEADLINE=90   # 05 step 5: bounded wait for the image healthcheck

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

fail() { echo "container-smoke: FAIL — $*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "docker CLI not found"
docker info >/dev/null 2>&1 || fail "docker daemon not reachable"

echo "== TC-028: image builds (host arch) =="
docker build -t "$IMAGE" -f mock-wo/Dockerfile mock-wo
docker image inspect "$IMAGE" >/dev/null 2>&1 \
    || fail "TC-028: image $IMAGE not present after build"

echo "== TC-029: container health on host port $PORT =="
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" -p "${PORT}:8090" \
    -e MOCK_WO_DB_PATH=/tmp/smoke.db "$IMAGE" >/dev/null

HEALTH_OK=$(python3 - "$BASE" "$HEALTH_DEADLINE" <<'PY' || echo timeout
import sys, time, urllib.request

base, deadline = sys.argv[1], float(sys.argv[2])
start = time.monotonic()
while True:
    try:
        with urllib.request.urlopen(base + "/health", timeout=3) as r:
            body = r.read().decode()
            if r.status == 200:
                print(f"ok at {time.monotonic() - start:.1f} s: {body}")
                sys.exit(0)
    except Exception:
        pass
    if time.monotonic() - start > deadline:
        sys.exit(1)
    time.sleep(0.5)
PY
)
[ "$HEALTH_OK" != "timeout" ] \
    || fail "TC-029: /health not 200 within ${HEALTH_DEADLINE} s"
echo "$HEALTH_OK"

echo "== TC-030: container API round-trip =="
WORK_ORDER_ID=$(python3 - "$BASE" <<'PY' || fail "TC-030: POST work order failed"
import json, sys, urllib.request

base = sys.argv[1]
payload = {
    "title": "Bearing replacement — M-3021 motor drive",
    "description": (
        "Smoke-test work order: thermal anomaly on motor M-3021 detected"
        " at clip-anomaly-01@00:42."
    ),
    "equipment": "M-3021",
    "anomaly_ref": "vss-alert-clip-anomaly-01-00:42",
    "priority": "high",
    "assigned_to": "maintenance-team-b",
    "citations": [
        {
            "source_type": "rag",
            "source_id": "manual-01#p12",
            "quote": "Bearing temperature above 75°C: replace per"
                     " preventive schedule.",
        },
        {
            "source_type": "vss",
            "source_id": "clip-anomaly-01@00:42",
            "quote": "RT-VLM caption: heat signature on bearing housing,"
                     " vibration audible.",
        },
    ],
}
req = urllib.request.Request(
    base + "/api/v1/work-orders",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=10) as r:
    assert r.status == 201, f"POST -> {r.status}, want 201"
    print(json.loads(r.read().decode())["id"])
PY
)

python3 - "$BASE" "$WORK_ORDER_ID" <<'PY' || fail "TC-030: GET list round-trip failed"
import json, sys, urllib.request

base, wo_id = sys.argv[1], sys.argv[2]
with urllib.request.urlopen(base + "/api/v1/work-orders", timeout=10) as r:
    assert r.status == 200, f"GET list -> {r.status}, want 200"
    ids = [w["id"] for w in json.loads(r.read().decode())]
    assert wo_id in ids, "created work order not in the list"
PY

python3 - "$BASE" <<'PY' || fail "TC-030: GET / (UI) failed"
import sys, urllib.request

base = sys.argv[1]
with urllib.request.urlopen(base + "/", timeout=10) as r:
    assert r.status == 200, f"GET / -> {r.status}, want 200"
    html = r.read().decode()
    assert "Bearing replacement" in html, "title not present in UI HTML"
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

cleanup
trap - EXIT
echo "container-smoke: PASS (TC-028..TC-031)"
