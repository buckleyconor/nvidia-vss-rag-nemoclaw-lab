#!/usr/bin/env bash
# scripts/demo/03-agent-kickoff.sh — beats 3-4: the agentic diagnosis and
# the aha (01 core features 3-4; 02 beat table).
#
# Run on the learner VM DURING the session, after beat 2 (02-anomaly.sh).
# The learner's ONE instruction is the whole trigger (HITL kick-off in the
# OpenClaw UI). From that instruction onward the lab is autonomous — beat
# 4's success criterion is "no human step in between" (01 success
# criterion 2).
#
# This script verifies the preconditions, prints the OpenClaw UI URL, and
# prints the instruction to paste. HITL is interactive — THE SCRIPT
# PRINTS, THE LEARNER TYPES (03 layout note): nothing is sent from here.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST="$REPO_ROOT/fixtures/video/manifest.yaml"
PREP_LOG="$REPO_ROOT/prep-log.md"
DASHBOARD_PORT="${NEMOCLAW_DASHBOARD_PORT:-18789}"
fail() { echo "03-agent-kickoff: FAIL — $*" >&2; exit 1; }

echo "== preconditions =="
curl -sf -m 10 http://127.0.0.1:8000/health >/dev/null \
    || fail "VSS agent :8000/health not answering (beat 2 prerequisites)"
if [ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]; then
    # shellcheck disable=SC1091
    . "${NVM_DIR:-$HOME/.nvm}/nvm.sh"
fi
# the host nemoclaw CLI: the nvm node bin may carry it (40-nemoclaw's
# bootstrap); the pinned install is $HOME/.local/bin/nemoclaw. openclaw
# lives INSIDE the sandbox — never on the host.
NEMO_BIN="$(command -v nemoclaw || true)"
[ -n "$NEMO_BIN" ] || NEMO_BIN="$HOME/.local/bin/nemoclaw"
[ -x "$NEMO_BIN" ] \
    || fail "nemoclaw CLI not found (run scripts/prep/40-nemoclaw.sh — it installs $HOME/.local/bin/nemoclaw)"
# the gateway port contract (config/nemoclaw.env): the CLI's default is
# 8080 — the auth-shim's docker-proxy port — so the call must carry the
# lab's port or it fails with "multiple listeners" (recorded collision).
if [ -f "$REPO_ROOT/config/nemoclaw.env" ]; then
    # shellcheck disable=SC1091
    set -a; . "$REPO_ROOT/config/nemoclaw.env"; set +a
fi
# host-side status (the openclaw box is sandbox-internal; the host CLI
# auto-starts the gateway if it is down — the designed session-start path).
STATUS_OUT=$(NEMOCLAW_GATEWAY_PORT="${NEMOCLAW_GATEWAY_PORT:-8085}" "$NEMO_BIN" demo status 2>&1) || fail "nemoclaw demo status failed (see state/nemoclaw-init.log)"
echo "$STATUS_OUT" | grep -qF "compatible-endpoint" \
    || fail "status does not show Provider: compatible-endpoint (the NemoClaw model is not the custom endpoint — 40-nemoclaw gate)"
echo "$STATUS_OUT" | grep -qF "Nemotron-3.5-Lightning-30B-A3B" \
    || fail "status does not show the shared Nemotron-3.5-Lightning model (40-nemoclaw gate)"
echo "NemoClaw sandbox: custom endpoint + Nemotron-3.5-Lightning model active"

# the anomaly clip id (beat 2's alert) — the <VIDEO_NAME> in the instruction
VIDEO_NAME="<ANOMALY_CLIP>"
if [ -f "$MANIFEST" ]; then
    V=$(python3 - "$MANIFEST" 2>/dev/null <<'PY' || true
import re
import sys

text = open(sys.argv[1]).read()
clips, cur = [], None
for line in text.splitlines():
    if not line.strip() or line.strip().startswith("#"):
        continue
    m = re.match(r"^\s*-\s*id:\s*(\S+)", line)
    if m:
        cur = {"id": m.group(1)}
        clips.append(cur)
        continue
    m = re.match(r"^\s*(role|file):\s*(\S+)", line)
    if m and cur is not None:
        cur[m.group(1)] = m.group(2)
anomalies = [c for c in clips if c.get("role") == "anomaly"]
if anomalies:
    print(anomalies[0]["id"])
PY
)
    if [ -n "$V" ]; then
        VIDEO_NAME="$V"
    fi
fi

# the OpenClaw UI URL: the dashboard port-forward binds 127.0.0.1; the
# port was recorded at prep (40-nemoclaw logs "dashboard port-forward: <port>").
# (The old heuristic grepped ANY url-with-port from prep-log — the NemoClaw
# section's auth-shim:8080 reference made that match the wrong URL.)
DASH_PORT="$(grep -Eo 'dashboard port-forward: [0-9]+' "$PREP_LOG" 2>/dev/null | grep -Eo '[0-9]+' | tail -1)"
[ -n "${DASH_PORT:-}" ] || DASH_PORT="$DASHBOARD_PORT"
UI_URL="http://127.0.0.1:${DASH_PORT}/"

echo ""
echo "== beats 3-4 procedure =="
echo "1. Open the OpenClaw UI:  $UI_URL"
echo "2. Start a fresh session (/new) and paste EXACTLY this one instruction:"
echo ""
echo "     I want to generate a video summary report for ${VIDEO_NAME}."
echo ""
echo "3. Answer the HITL prompts as they appear — the agent collects the"
echo "   four parameters: scenario, events of interest, objects to track,"
echo "   and the (optional) knowledge-retrieval query (02 beat 3; build doc 9.4)."
echo "4. After that: nothing. The agent runs the vss-generate-video-report-rag"
echo "   skill — VSS analysis + RAG retrieval over the corpus with the frag"
echo "   tool — for ~90 s of visible tool calls, retrieved documents and"
echo "   reasoning (02 beat 3: the evidence is on screen, not just the answer)."
echo ""
echo "beat 4 (the aha): with no human step between the instruction and the"
echo "result, the work order lands in the mock CMMS — open http://localhost:8090"
echo "and watch the list go from empty to the new work order at the TOP, with"
echo "its notification in the feed (http://localhost:8090/notifications)."
echo "the detail page groups the citations by source (rag / vss / agent) —"
echo "that is the diagnosis's evidence (02 beat 4)."
echo ""
echo "03-agent-kickoff: ready — the learner types the instruction in the OpenClaw UI"
