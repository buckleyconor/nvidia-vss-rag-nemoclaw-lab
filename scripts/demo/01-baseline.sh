#!/usr/bin/env bash
# scripts/demo/01-baseline.sh — beat 1: establish the baseline (01 core
# feature 1; 02 beat table).
#
# Run on the learner VM DURING the session, after 20-start.sh +
# 30-verify-stack.sh. Pre-recorded NORMAL-STATE clips (fixtures/video,
# role: normal) run through VSS; the learner sees the pipeline healthy,
# NO alerts (LVS UI / stack status).
#
# The script verifies the preconditions, stages the normal-state clips at
# /data/video (09 artifact) and prints the procedure. The LVS UI port/URL
# is release-dependent and recorded at prep in prep-log.md (02 open item)
# — this script prints it from there when available. HITL is the learner's
# clicks in the UI; the script only prepares and verifies.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VIDEO_DIR="${VIDEO_DIR:-/data/video}"
MANIFEST="$REPO_ROOT/fixtures/video/manifest.yaml"
PREP_LOG="$REPO_ROOT/prep-log.md"
fail() { echo "01-baseline: FAIL — $*" >&2; exit 1; }

echo "== preconditions =="
curl -sf -m 10 http://127.0.0.1:8000/health >/dev/null \
    || fail "VSS agent :8000/health not answering — run 20-start.sh + 30-verify-stack.sh first"
curl -sf -m 10 http://127.0.0.1:38111/v1/ready >/dev/null \
    || fail "LVS backend :38111/v1/ready not answering — run 20-start.sh + 30-verify-stack.sh first"
echo "VSS agent + LVS healthy"

echo "== staging the normal-state clips at $VIDEO_DIR =="
mkdir -p "$VIDEO_DIR"
if [ -f "$MANIFEST" ]; then
    # the manifest is the clip source of truth (M6, TC-042): id, role
    # (normal|anomaly), file, duration, equipment. Flat YAML — parsed with
    # the stdlib only (no PyYAML dependency on the VM).
    NORMAL_FILES=$(python3 - "$MANIFEST" <<'PY'
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
print("\n".join(
    c["file"] for c in clips
    if c.get("role") == "normal" and c.get("file")
))
PY
)
    if [ -z "$NORMAL_FILES" ]; then
        fail "manifest has no role: normal clips (M6: beat 1 needs a normal-state clip)"
    fi
    while IFS= read -r f; do
        if [ ! -f "$VIDEO_DIR/$f" ]; then
            [ -f "$REPO_ROOT/fixtures/video/$f" ] \
                || fail "manifest clip $f missing from fixtures/video/ and $VIDEO_DIR"
            cp -n "$REPO_ROOT/fixtures/video/$f" "$VIDEO_DIR/"
        fi
        echo "staged: $f"
    done <<< "$NORMAL_FILES"
else
    if ! compgen -G "$VIDEO_DIR/*.mp4" >/dev/null \
        && compgen -G "$REPO_ROOT/fixtures/video/*.mp4" >/dev/null; then
        cp -n "$REPO_ROOT/fixtures/video/"*.mp4 "$VIDEO_DIR"/
        echo "staged every repo fixture clip from fixtures/video/ (no manifest — verify the normal-state set manually)"
    fi
fi
COUNT=$(find "$VIDEO_DIR" -maxdepth 1 -type f -name '*.mp4' 2>/dev/null | wc -l || true)
[ "$COUNT" -gt 0 ] || fail "no .mp4 clips at $VIDEO_DIR after staging (provide the clips or fixtures/video/manifest.yaml — M6)"
echo "staged: $COUNT clip(s) at $VIDEO_DIR"

# NOTE: 'LVS UI.*' — not '[^\n]*': inside a POSIX bracket expression [^\n]
# means 'not a backslash and not the letter n', so the match would stop at
# the first 'n' (2026-09-13: truncated the recorded URL at 'vss-age|n|t-ui').
LVS_UI=$(grep -oE 'LVS UI.*' "$PREP_LOG" 2>/dev/null | tail -1 || true)
echo ""
echo "== beat 1 procedure (the learner does this in the UI) =="
echo "1. Open the LVS UI${LVS_UI:+ ($LVS_UI — recorded at prep)}; the stack is up and the work-order list at http://localhost:8090 is EMPTY (baseline)."
echo "2. Play the staged normal-state clip(s) through VSS (the $COUNT clip(s) at $VIDEO_DIR)."
echo "3. Watch: captioning + summarisation complete, the LVS UI shows a HEALTHY pipeline and NO alerts."
echo ""
echo "expected observation (02 beat 1): pipeline running healthy, no alerts — the anomaly (beat 2) is what breaks that picture."
echo "01-baseline: ready — next: scripts/demo/02-anomaly.sh"
