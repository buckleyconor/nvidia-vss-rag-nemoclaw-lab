#!/usr/bin/env bash
# scripts/demo/02-anomaly.sh — beat 2: anomaly detected (01 core feature 2;
# 02 beat table).
#
# Run on the learner VM DURING the session, after beat 1 (01-baseline.sh).
# The ANOMALY segment (fixtures/video, role: anomaly — e.g. a motor bearing
# with abnormal thermal/vibration behaviour) is played; VSS raises an alert
# identifying the affected equipment (LVS UI).
#
# The alert (equipment + clip reference) is what beats 3-5 hang on: the
# agent's work order cites it (anomaly_ref) and ties back to this beat.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VIDEO_DIR="${VIDEO_DIR:-/data/video}"
MANIFEST="$REPO_ROOT/fixtures/video/manifest.yaml"
fail() { echo "02-anomaly: FAIL — $*" >&2; exit 1; }

echo "== preconditions =="
curl -sf -m 10 http://127.0.0.1:8000/health >/dev/null \
    || fail "VSS agent :8000/health not answering (beat 1 prerequisites — run 20-start.sh + 30-verify-stack.sh)"
curl -sf -m 10 http://127.0.0.1:38111/v1/ready >/dev/null \
    || fail "LVS backend :38111/v1/ready not answering (beat 1 prerequisites)"
echo "VSS agent + LVS healthy"

echo "== the anomaly segment =="
ANOMALY=""
EQUIPMENT=""
if [ -f "$MANIFEST" ]; then
    # flat-YAML parse (stdlib only); on error the python exits non-zero and
    # set -e stops this script with the message on stderr.
    INFO=$(python3 - "$MANIFEST" <<'PY'
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
    m = re.match(r"^\s*(role|file|equipment):\s*(\S+)", line)
    if m and cur is not None:
        cur[m.group(1)] = m.group(2)
anomalies = [c for c in clips if c.get("role") == "anomaly" and c.get("file")]
if not anomalies:
    sys.exit("02-anomaly: FAIL — manifest has no role: anomaly clip (M6: beat 2 needs the anomaly segment)")
c = anomalies[0]
print(c["file"], c.get("equipment", "<equipment from the manifest>"))
PY
)
    read -r ANOMALY EQUIPMENT <<< "$INFO"
    if [ ! -f "$VIDEO_DIR/$ANOMALY" ]; then
        [ -f "$REPO_ROOT/fixtures/video/$ANOMALY" ] \
            || fail "anomaly clip $ANOMALY missing from fixtures/video/ and $VIDEO_DIR"
        mkdir -p "$VIDEO_DIR"
        cp -n "$REPO_ROOT/fixtures/video/$ANOMALY" "$VIDEO_DIR/"
    fi
    echo "anomaly segment: $ANOMALY (equipment: $EQUIPMENT)"
else
    ANOMALY="${1:-}"
    if [ -z "$ANOMALY" ]; then
        # no manifest: the learner names the clip (or it is already staged)
        if compgen -G "$VIDEO_DIR/*.mp4" >/dev/null; then
            echo "no manifest — confirm the staged anomaly segment at $VIDEO_DIR (the learner knows which clip it is)"
        else
            fail "no manifest and no staged clips: run scripts/demo/01-baseline.sh first, or pass the anomaly clip name as \$1"
        fi
    else
        [ -f "$VIDEO_DIR/$ANOMALY" ] || fail "clip $ANOMALY not staged at $VIDEO_DIR (copy it there first)"
        echo "anomaly segment: $ANOMALY (learner-named; no manifest)"
    fi
fi

echo ""
echo "== beat 2 procedure (the learner does this in the UI) =="
echo "1. With the pipeline healthy from beat 1, play the anomaly segment ($ANOMALY${EQUIPMENT:+ on $EQUIPMENT})."
echo "2. Watch the LVS UI: the alert logic FIRES — an alert is raised and the affected equipment is identified."
echo ""
echo "expected observation (02 beat 2): alert raised, affected equipment identified."
echo "note for beat 3: the work order the agent files later cites THIS alert (anomaly_ref) — keep the alert's clip reference + timestamp on screen."
echo "02-anomaly: ready — next: scripts/demo/03-agent-kickoff.sh"
