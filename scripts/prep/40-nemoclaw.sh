#!/usr/bin/env bash
# 40-nemoclaw.sh — NemoClaw sandbox install + network-policy extension
# (03 layout; 02 component 4; build doc Phase 5).
#
# Run on the learner vCD VM (also called by 20-start.sh as its step 5/5).
#
#   1. Fresh OpenClaw required (build doc 9.1): if the `demo` sandbox
#      already exists this STOPS — remove it first, do not re-onboard over
#      it.
#   2. Network-policy extension: the VSS preset grants VSS on :8000 only.
#      The lab policy file (generated here into state/, gitignored) is the
#      preset PLUS the lab endpoints — RAG :8081, auth-shim :8080,
#      mock-wo :8090 (02: "the NemoClaw network-policy extension
#      pre-approves mock-wo:8090 alongside the build document's list").
#   3. The installer runs with the repo's config/nemoclaw.env contract
#      (NEMOCLAW_PROVIDER=custom, NEMOCLAW_ENDPOINT_URL,
#      COMPATIBLE_API_KEY=dummy — a safe constant, 02/04).
#   4. Gates (02 step 5): openclaw nemoclaw status shows the custom
#      endpoint + Nano Omni model. The installed version is compared to
#      the pinned v0.0.118 (08 item 28): a mismatch is a loudly recorded
#      PREP FINDING, never a silent substitution.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VSS_DIR="${VSS_DIR:-$HOME/vss-public}"
WORK_DIR="$REPO_ROOT/state"
POLICY_FILE="$WORK_DIR/nemoclaw-policy.yaml"
INIT_LOG="$WORK_DIR/nemoclaw-init.log"
PRESET="${PRESET:-$VSS_DIR/assets/vss_nemoclaw_policy.yaml}"
SANDBOX="demo"
NEMOCLAW_WANT="0.0.118"
LAB_ENDPOINTS=(8080 8081 8090)

PREP_LOG="$REPO_ROOT/prep-log.md"
log() { printf '%s\n' "$*" >> "$PREP_LOG"; }
fail() { echo "40-nemoclaw: FAIL — $*" >&2; exit 1; }

[ -d "$VSS_DIR" ] || fail "VSS repo missing at $VSS_DIR — run 10-clone-blueprints.sh first"
[ -f "$REPO_ROOT/config/nemoclaw.env" ] || fail "config/nemoclaw.env missing (repo contract — 02)"
[ -f "$PRESET" ] || fail "VSS NemoClaw policy preset not found at $PRESET (vendor layout moved? record and adapt — 02/09)"
mkdir -p "$WORK_DIR"

echo "== fresh OpenClaw check (build doc 9.1) =="
if command -v openshell >/dev/null 2>&1; then
    if openshell sandbox list 2>/dev/null | sed -E 's/\x1B\[[0-9;]*[[:alpha:]]//g' \
        | awk -v name="$SANDBOX" '$1 == name { found = 1 } END { exit found ? 0 : 1 }'; then
        fail "sandbox '$SANDBOX' already exists — NemoClaw requires a FRESH OpenClaw (build doc 9.1); remove the existing installation first (instructor action), then re-run"
    fi
fi
echo "no existing '$SANDBOX' sandbox — fresh install path"

echo "== generating the lab policy file (preset + lab endpoints) =="
python3 - "$PRESET" "$POLICY_FILE" "${LAB_ENDPOINTS[@]}" <<'PY'
import re
import sys

preset_path, out_path, ports = sys.argv[1], sys.argv[2], sys.argv[3:]
text = open(preset_path).read()

# the preset's vss-backend section grants host.openshell.internal on the
# Docker-bridge CIDRs; the lab endpoints follow the exact same shape.
m = re.search(r"^  vss-backend:\n", text, re.MULTILINE)
if not m:
    sys.exit("40-nemoclaw: FAIL — vss-backend section not found in the preset (vendor layout moved? record and adapt)")
end = re.search(r"^  [a-z_]+:\n", text[m.end():], re.MULTILINE)
section = text[m.end():m.end() + (end.start() if end else len(text) - m.end())]

added, already = [], []
blocks = []
for port in ports:
    if re.search(rf"^\s+port: {port}\b", section, re.MULTILINE):
        already.append(port)
        continue
    added.append(port)
    blocks.append(
        "      - host: host.openshell.internal\n"
        f"        port: {port}\n"
        "        access: full\n"
        "        allowed_ips:\n"
        "          - 172.17.0.0/16\n"
        "          - 172.18.0.0/16\n"
        "          - 172.20.0.0/16\n"
    )

if blocks:
    # insert at the end of the vss-backend endpoints list: right before the
    # section's `binaries:` line (the preset's stable layout at v3.2.1)
    b = re.search(r"^    binaries:\n", section, re.MULTILINE)
    if not b:
        sys.exit("40-nemoclaw: FAIL — vss-backend binaries: marker not found in the preset (vendor layout moved? record and adapt)")
    section = section[:b.start()] + "".join(blocks) + section[b.start():]
    text = text[:m.end()] + section + text[m.end() + len(section):]

open(out_path, "w").write(text)
print(f"lab endpoints added: {added or []}; already granted by the preset: {already or []}")
PY
log ""
log "## $(date -u +%Y-%m-%dT%H:%M:%SZ) — 40-nemoclaw: sandbox $SANDBOX"
log "- lab policy file: state/nemoclaw-policy.yaml (VSS preset + lab endpoints ${LAB_ENDPOINTS[*]} — 02)"

echo "== installing NemoClaw (config/nemoclaw.env contract; installer log: state/nemoclaw-init.log) =="
set -a
# shellcheck disable=SC1090
. "$REPO_ROOT/config/nemoclaw.env"
set +a
[ "${NEMOCLAW_PROVIDER:-}" = "custom" ] || fail "config/nemoclaw.env must set NEMOCLAW_PROVIDER=custom (02 contract)"
cd "$VSS_DIR"
bash deploy/docker/scripts/nemoclaw/init_nemoclaw.sh \
    --sandbox-name "$SANDBOX" \
    --policy-file "$POLICY_FILE" 2>&1 | tee "$INIT_LOG"
cd "$REPO_ROOT"

# the installer (and nvm node 22 when it bootstrapped one) put the CLIs on
# a PATH this login shell may not have — the installer's own hint is to
# source nvm.sh.
if [ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]; then
    # shellcheck disable=SC1091
    . "${NVM_DIR:-$HOME/.nvm}/nvm.sh"
fi

echo "== gate: openclaw nemoclaw status (02 step 5) =="
STATUS_OUT=$(openclaw nemoclaw status 2>&1) || fail "openclaw nemoclaw status failed — the sandbox did not come up (see state/nemoclaw-init.log)"
echo "$STATUS_OUT" | sed 's/^/    /'
echo "$STATUS_OUT" | grep -qF "auth-shim:8080" \
    || fail "status does not show the custom endpoint auth-shim:8080 (NEMOCLAW_ENDPOINT_URL not applied — see state/nemoclaw-init.log)"
echo "$STATUS_OUT" | grep -qF "nemotron-3-nano-omni-30b-a3b-reasoning" \
    || fail "status does not show the Nano Omni model (the custom model naming via the shim is not active — see state/nemoclaw-init.log)"
echo "gate ok: custom endpoint + Nano Omni model"

# version pin (08 item 28): the installer at v3.2.1 must install/declare
# v0.0.118 — verify at prep; a mismatch is a PREP FINDING, never a silent
# substitution (it is surfaced, not hidden; the L5 checklist re-checks
# behaviour).
VERSION=""
for cmd in "nemoclaw --version" "openclaw nemoclaw --version" "nemoclaw version"; do
    v=$($cmd 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1) || true
    if [ -n "$v" ]; then
        VERSION="$v"
        break
    fi
done
VERSION="${VERSION#v}"
if [ -n "$VERSION" ]; then
    if [ "$VERSION" = "$NEMOCLAW_WANT" ]; then
        echo "nemoclaw version: $VERSION (matches the pinned v$NEMOCLAW_WANT)"
        log "- nemoclaw version: $VERSION (pinned v$NEMOCLAW_WANT — 08 item 28)"
    else
        echo "40-nemoclaw: PREP FINDING — nemoclaw version is $VERSION, pinned v$NEMOCLAW_WANT (08 item 28: a mismatch is never a silent substitution — surface this to the lab owner)" >&2
        log "  PREP FINDING: nemoclaw version $VERSION != pinned v$NEMOCLAW_WANT (08 item 28)"
    fi
else
    echo "40-nemoclaw: PREP FINDING — the installed nemoclaw version could not be determined from the CLI; verify manually and record it (08 item 28)" >&2
    log "  PREP FINDING: nemoclaw version not observable from the CLI — verify manually (08 item 28)"
fi

# the OpenClaw UI URL (printed by the installer — recorded for the guide,
# 02 open item) and the node the installer actually ran on (00 installed
# Node 20 per 09; the v3.2.1 installer bootstraps Node 22+ via nvm when
# needed — record the actual).
UI_URLS=$(grep -Eo 'https?://[^ "[:cntrl:]]+' "$INIT_LOG" | sort -u | head -5 || true)
if [ -n "$UI_URLS" ]; then
    log "- openclaw UI URL(s) from the installer log:"
    while IFS= read -r u; do
        log "    $u"
    done <<< "$UI_URLS"
fi
log "- dashboard port-forward: ${NEMOCLAW_DASHBOARD_PORT:-18789} (installer default)"
log "- node actually in use at install time: $(node --version 2>/dev/null || echo unknown) (00 installed Node 20 per 09; the v3.2.1 installer requires Node 22+ and bootstraps via nvm — actual recorded here)"
log "- gate: openclaw nemoclaw status shows auth-shim:8080 + nemotron-3-nano-omni-30b-a3b-reasoning"

echo "40-nemoclaw: PASS — sandbox '$SANDBOX' ready (see the 40-nemoclaw section in prep-log.md)"
