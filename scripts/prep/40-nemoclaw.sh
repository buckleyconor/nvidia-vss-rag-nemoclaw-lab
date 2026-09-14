#!/usr/bin/env bash
# 40-nemoclaw.sh — NemoClaw sandbox install + network-policy extension
# (03 layout; 02 component 4; build doc Phase 5).
#
# Run on the learner vCD VM (also called by 20-start.sh as its step 5/5).
#
#   1. A FRESH OpenClaw is required for a first install (build doc 9.1):
#      a foreign `demo` sandbox (no lab model) STOPS the script — remove
#      it first (instructor action). Re-running against THIS lab's own
#      sandbox is a supported repair path: onboarding is skipped and the
#      policy is re-applied idempotently (2026-09-10 dry-run).
#   2. Network-policy extension: the VSS preset grants VSS on :8000 only.
#      The lab policy file (generated here into state/, gitignored) is the
#      preset PLUS the lab endpoints — auth-shim :8080 and mock-wo :8090,
#      the agent port (operator-dashboard-spec ADR-V08). Deliberately NOT
#      granted: RAG :8081 (the agent's only knowledge path is VSS frag —
#      ADR-V01/V06) and mock-wo :8091, the operator port that carries the
#      approval gate. The generated policy is checked for both below.
#      2026-09-13 recorded deviation: the vendor v3.2.1 VSS preset ITSELF
#      grants host.openshell.internal:8081 (the standard VSS dev profile's
#      RAG port — the developer-machine assumption that the preset would be
#      clean was wrong). The generated file is therefore stripped of the
#      FORBIDDEN_ENDPOINTS entries BEFORE the check below; the check stays
#      as the last line of defence (a surviving entry means an unexpected
#      shape and fails prep loudly).
#      Before apply, entries that overlap the sandbox's built-in baseline
#      are stripped (NemoClaw rejects host:port overlaps with conflicting
#      metadata — "network endpoint ambiguity validation failed",
#      2026-09-10 dry-run).
#   3. The installer runs with the repo's config/nemoclaw.env contract
#      (NEMOCLAW_PROVIDER=custom, NEMOCLAW_ENDPOINT_URL,
#      COMPATIBLE_API_KEY=dummy — a safe constant, 02/04).
#   4. Gates (02 step 5 — 2026-09-10 dry-run reality): host-side
#      `nemoclaw demo status` shows the Nemotron-3.5-Lightning model,
#      provider compatible-endpoint, healthy inference and the applied
#      'vss' policy; the sandbox-side `openclaw nemoclaw status` (via
#      `nemoclaw demo exec`) shows the registration box; the lab endpoint
#      (auth-shim:8080) is probed directly. The endpoint URL itself is not
#      exposed in status output (credential-safe design). The installed
#      version is compared to the pinned v0.0.118 (08 item 28): a
#      mismatch is a loudly recorded PREP FINDING, never a silent
#      substitution.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VSS_DIR="${VSS_DIR:-$HOME/vss-public}"
WORK_DIR="$REPO_ROOT/state"
POLICY_FILE="$WORK_DIR/nemoclaw-policy.yaml"
INIT_LOG="$WORK_DIR/nemoclaw-init.log"
PRESET="${PRESET:-$VSS_DIR/assets/vss_nemoclaw_policy.yaml}"
SANDBOX="demo"
NEMOCLAW_WANT="0.0.118"
# The model the probe and the agent use (02 contract, TC-035/TC-037): the
# lab's served model id. The vendor script defaults NEMOCLAW_MODEL to
# NVIDIA's HOSTED model when --model is absent — the local endpoint 404s
# on it ("The model ... does not exist"), so the probe must carry the
# served id explicitly (2026-09-10 dry-run).
MODEL_ID="nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4"
LAB_ENDPOINTS=(8080 8090)
# Ports the sandbox must never reach. 8091 is the operator dashboard: if the
# agent could reach it, it could approve its own proposals (ADR-V08).
FORBIDDEN_ENDPOINTS=(8091 8081)

PREP_LOG="$REPO_ROOT/prep-log.md"
log() { printf '%s\n' "$*" >> "$PREP_LOG"; }
fail() { echo "40-nemoclaw: FAIL — $*" >&2; exit 1; }

[ -d "$VSS_DIR" ] || fail "VSS repo missing at $VSS_DIR — run 10-clone-blueprints.sh first"
[ -f "$REPO_ROOT/config/nemoclaw.env" ] || fail "config/nemoclaw.env missing (repo contract — 02)"
[ -f "$PRESET" ] || fail "VSS NemoClaw policy preset not found at $PRESET (vendor layout moved? record and adapt — 02/09)"
mkdir -p "$WORK_DIR"

# --- environment contract (the check, the vendor call and the gate all need it) ---
set -a
# shellcheck disable=SC1090
. "$REPO_ROOT/config/nemoclaw.env"
set +a
[ "${NEMOCLAW_PROVIDER:-}" = "custom" ] || fail "config/nemoclaw.env must set NEMOCLAW_PROVIDER=custom (02 contract)"
# OpenShell gateway port (09 port table, config/nemoclaw.env): NemoClaw's
# DEFAULT gateway port is 8080 (dist/lib/core/ports.js) — the auth-shim's
# port — so the onboarding preflight fails on a lab VM with "Gateway port
# 8080 has multiple listeners" (2026-09-10 dry-run). NEMOCLAW_GATEWAY_PORT
# is the supported knob (gateway-binding.js: a non-default port registers
# the gateway as nemoclaw-<port> and the CLI writes OPENSHELL_SERVER_PORT
# into the gateway service env itself). The value is the lab's port
# contract (sourced above); health/metrics ride +1/+2. The binary's
# health/metrics listeners are off by default (port 0) and it binds
# 127.0.0.1, so the server port is the only one that matters.
export NEMOCLAW_GATEWAY_PORT="${NEMOCLAW_GATEWAY_PORT:-8085}"
export OPENSHELL_SERVER_PORT="$NEMOCLAW_GATEWAY_PORT" OPENSHELL_HEALTH_PORT="$((NEMOCLAW_GATEWAY_PORT + 1))" OPENSHELL_METRICS_PORT="$((NEMOCLAW_GATEWAY_PORT + 2))"
install -d "$HOME/.config/openshell"
printf 'OPENSHELL_SERVER_PORT=%s\nOPENSHELL_HEALTH_PORT=%s\nOPENSHELL_METRICS_PORT=%s\n' \
    "$OPENSHELL_SERVER_PORT" "$OPENSHELL_HEALTH_PORT" "$OPENSHELL_METRICS_PORT" \
    > "$HOME/.config/openshell/gateway.env"
# The onboard SSRF preflight (endpoint-ssrf-preflight.js / trusted-
# private-endpoint.js) only accepts a user-supplied endpoint whose host
# either resolves PUBLIC or is on the trust allowlist AND resolves to an
# operator-trustable private address — RFC1918 yes, loopback NO
# (2026-09-10 dry-run: "resolves to private/internal address
# 127.0.0.1" even with the trust list set). auth-shim is a docker-network
# name; pin it to the VM's real management IP — the shim's nginx binds all
# interfaces and docker-proxy holds 0.0.0.0:8080, so the real IP serves
# identically. Derived, not hardcoded (the learner VM's IP differs): first
# global non-loopback IPv4.
AUTH_SHIM_HOST_IP="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^([0-9]{1,3}\.){3}[0-9]{1,3}$' | grep -vE '^127\.|^169\.254\.' | head -1)"
[ -n "$AUTH_SHIM_HOST_IP" ] || fail "no global non-loopback IPv4 found for the auth-shim host pin (hostname -I)"
sed -i -E '/^[0-9.]+[[:space:]]+auth-shim([[:space:]]|$)/d' /etc/hosts
echo "$AUTH_SHIM_HOST_IP auth-shim" >> /etc/hosts
# The onboard SSRF preflight (endpoint-ssrf-preflight.js) requires a
# user-supplied inference endpoint to resolve to a PUBLIC address unless
# its host is on an explicit trust allowlist (the env var is the
# documented inference-only allowlist, comma-separated hosts).
export NEMOCLAW_TRUSTED_PRIVATE_INFERENCE_HOSTS=auth-shim

sandbox_exists() {
    command -v openshell >/dev/null 2>&1 || return 1
    openshell sandbox list 2>/dev/null | sed -E 's/\x1B\[[0-9;]*[[:alpha:]]//g' \
        | awk -v name="$SANDBOX" '$1 == name { found = 1 } END { exit found ? 0 : 1 }'
}

nemoclaw_cli() {
    # the installer drops a PATH-independent shim here (sudo's PATH does
    # not include $HOME/.local/bin); nvm's node bin is the fallback once
    # nvm.sh is sourced below. NO exec: this runs in the script's own
    # shell, so exec would replace the whole script with the CLI process
    # and kill everything after the call (2026-09-10 dry-run: silent
    # death at the policy step).
    if [ -x "$HOME/.local/bin/nemoclaw" ]; then "$HOME/.local/bin/nemoclaw" "$@"; return; fi
    if command -v nemoclaw >/dev/null 2>&1; then nemoclaw "$@"; return; fi
    fail "nemoclaw CLI not found (shim missing at $HOME/.local/bin/nemoclaw — see $INIT_LOG)"
}

echo "== fresh OpenClaw / re-run check (build doc 9.1) =="
if sandbox_exists; then
    # Identity check must test only the grep result: with `set -o pipefail`
    # (line 12), a nonzero `status` exit on an unhealthy sandbox poisons the
    # pipeline and the re-run path fails closed (false "not this lab's
    # install") even when the model line is present. `|| true` isolates the
    # grep. 2026-09-11 dry-run: broken-state re-run hit exactly this.
    if { nemoclaw_cli "$SANDBOX" status 2>/dev/null || true; } | grep -qF "$MODEL_ID"; then
        echo "sandbox '$SANDBOX' already exists with the lab model — re-run path (init_nemoclaw.sh re-runs — required for a clean start; policy re-applied)"
    else
        fail "sandbox '$SANDBOX' exists but is not this lab's install (no $MODEL_ID) — NemoClaw requires a FRESH OpenClaw (build doc 9.1); remove the existing installation first (instructor action), then re-run"
    fi
else
    echo "no existing '$SANDBOX' sandbox — fresh install path"
fi

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
# the ORIGINAL span of the section in `text`. `section` is mutated below,
# so len(section) can no longer be used to find where the section ended —
# using it there swallows len(blocks) characters of the NEXT section.
orig_len = len(section)

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
    )

if blocks:
    # insert at the end of the vss-backend endpoints list: right before the
    # section's `binaries:` line (the preset's stable layout at v3.2.1)
    b = re.search(r"^    binaries:\n", section, re.MULTILINE)
    if not b:
        sys.exit("40-nemoclaw: FAIL — vss-backend binaries: marker not found in the preset (vendor layout moved? record and adapt)")
    section = section[:b.start()] + "".join(blocks) + section[b.start():]
    text = text[:m.end()] + section + text[m.end() + orig_len:]

# NemoClaw (v0.0.118) rejects 'allowed_ips' in USER-SUPPLIED presets
# ("Preset 'vss' contains 'allowed_ips', which is not permitted in
# user-supplied presets" — 2026-09-10 dry-run). The vendor preset uses it
# to pin hostname→CIDR; the lab keeps the host+port scoping and drops the
# IP pinning (recorded deviation — spec/08/09).
text = re.sub(r"^[ \t]+allowed_ips:[ \t]*\n(?:[ \t]+- \S+[ \t]*\n)+", "", text, flags=re.MULTILINE)

open(out_path, "w").write(text)
print(f"lab endpoints added: {added or []}; already granted by the preset: {already or []}")
PY
# --- strip the FORBIDDEN ports from the generated file (2026-09-13) --------
# The vendor preset carries host.openshell.internal:8081 (see the header
# note); an entry is `- host: X` / `port: P` / optional deeper-indented
# lines (access, allowed_ips). Drop whole entries for the forbidden ports.
STRIPPED="$(python3 - "$POLICY_FILE" "${FORBIDDEN_ENDPOINTS[@]}" <<'PY'
import re
import sys

path, ports = sys.argv[1], {p for p in sys.argv[2:]}
lines = open(path).read().split("\n")
out, i, dropped = [], 0, []
while i < len(lines):
    m = re.match(r"^(\s*)- host: ", lines[i])
    if m:
        indent = len(m.group(1))
        j = i + 1
        while j < len(lines) and lines[j].strip() == "":
            j += 1
        pm = re.match(r"^\s+port: (\d+)\s*$", lines[j]) if j < len(lines) else None
        k = j + 1
        while k < len(lines):
            if lines[k].strip() == "":
                k += 1
                continue
            if (len(lines[k]) - len(lines[k].lstrip())) <= indent:
                break
            k += 1
        if pm and pm.group(1) in ports:
            dropped.append(pm.group(1))
            i = k
            continue
    out.append(lines[i])
    i += 1
open(path, "w").write("\n".join(out))
print(" ".join(dropped) if dropped else "none")
PY
)"
[ "$STRIPPED" != "none" ] && log "- recorded deviation: stripped forbidden-port grants ($STRIPPED) from the generated policy — the vendor v3.2.1 VSS preset ships host.openshell.internal:8081 (standard VSS dev RAG port); the lab's ADR-V01/V06/V08 boundary must not reach RAG or the operator port directly (2026-09-13, dev-VM finding)"
for port in "${FORBIDDEN_ENDPOINTS[@]}"; do
    if grep -Eq "^[[:space:]]+port:[[:space:]]*${port}([^0-9]|$)" "$POLICY_FILE"; then
        fail "generated policy grants port $port — the sandbox must never reach it (operator-dashboard-spec ADR-V06/ADR-V08); fix the preset or LAB_ENDPOINTS"
    fi
done
echo "policy check: no grant for ${FORBIDDEN_ENDPOINTS[*]}"
log ""
log "## $(date -u +%Y-%m-%dT%H:%M:%SZ) — 40-nemoclaw: sandbox $SANDBOX"
log "- lab policy file: state/nemoclaw-policy.yaml (VSS preset + lab endpoints ${LAB_ENDPOINTS[*]} — 02)"

echo "== installing NemoClaw (config/nemoclaw.env contract; installer log: state/nemoclaw-init.log) =="
cd "$VSS_DIR"
VENDOR_OK=0
bash deploy/docker/scripts/nemoclaw/init_nemoclaw.sh \
    --sandbox-name "$SANDBOX" \
    --model "$MODEL_ID" \
    --policy-file "$POLICY_FILE" 2>&1 | tee "$INIT_LOG" || VENDOR_OK=1
cd "$REPO_ROOT"
# The vendor script's FINAL step is the same policy-add this script re-runs
# below; on a fresh VM it fails there ("network endpoint ambiguity
# validation failed" — the preset overlaps the built-in baseline applied
# during onboarding) AFTER onboarding has completed (2026-09-10 dry-run).
# Tolerate exactly that; a vendor failure with no sandbox is a hard error.
if [ "$VENDOR_OK" = 1 ] && sandbox_exists; then
    echo "vendor init completed onboarding; its final policy step failed (expected baseline overlap) — applying the lab policy below"
elif [ "$VENDOR_OK" = 1 ]; then
    fail "vendor init failed and no '$SANDBOX' sandbox exists (see $INIT_LOG)"
fi

echo "== applying the lab policy (deduped against the live baseline) =="
sandbox_exists || fail "no '$SANDBOX' sandbox after vendor init (see $INIT_LOG)"
LIVE_POLICY="$WORK_DIR/nemoclaw-live-policy.yaml"
nemoclaw_cli "$SANDBOX" policy get --raw > "$LIVE_POLICY" 2>/dev/null \
    || fail "could not read the live sandbox policy (nemoclaw CLI / gateway down? see $INIT_LOG)"
python3 - "$LIVE_POLICY" "$POLICY_FILE" <<'PY'
import re
import sys

live_path, lab_path = sys.argv[1], sys.argv[2]
live = open(live_path).read()
lab = open(lab_path).read()

# host:port pairs the live baseline already carries (policy add rejects
# overlaps with conflicting metadata: "network endpoint ambiguity
# validation failed", 2026-09-10 dry-run)
live_pairs = set()
for m in re.finditer(r"^\s*- host: ['\"]?([^'\"\s:]+)['\"]?\n\s+port: (\d+)\n", live, re.M):
    live_pairs.add((m.group(1), m.group(2)))
print("live baseline pairs:", sorted(live_pairs))

lines = lab.split("\n")
kept, i, dropped = [], 0, []
while i < len(lines):
    m = re.match(r"^(\s*)- host: ['\"]?([^'\"\s:]+)['\"]?\s*$", lines[i])
    if m:
        indent = len(m.group(1))
        host = m.group(2)
        pm = re.match(r"^\s+port: (\d+)\s*$", lines[i + 1]) if i + 1 < len(lines) else None
        port = pm.group(1) if pm else None
        # entry end: next non-blank line at this entry's indent or shallower
        j = i + 1
        while j < len(lines):
            if lines[j].strip() == "":
                j += 1
                continue
            if (len(lines[j]) - len(lines[j].lstrip())) <= indent:
                break
            j += 1
        if (host, port) in live_pairs:
            dropped.append((host, port))
            i = j
            continue
    kept.append(lines[i])
    i += 1
lab = "\n".join(kept)

# drop sections left with no endpoints (empty `endpoints:` is not a valid
# preset entry)
lines2 = lab.split("\n")
out, i = [], 0
sec = re.compile(r"^  [a-z0-9][a-z0-9_-]*:\s*$")
while i < len(lines2):
    if sec.match(lines2[i]):
        j = i + 1
        while j < len(lines2) and not sec.match(lines2[j]):
            j += 1
        body = "\n".join(lines2[i:j])
        if not re.search(r"^\s*- host: ", body, re.M):
            print("dropping empty section:", lines2[i].strip().rstrip(":"))
            i = j
            continue
    out.append(lines2[i])
    i += 1
lab = "\n".join(out)

open(lab_path, "w").write(lab)
print("dropped entries already in the live baseline:", dropped)
if not re.search(r"^\s*- host: ", lab, re.M):
    print("lab policy fully covered by the live baseline — nothing left to add")
PY
if grep -qE '^\s*- host: ' "$POLICY_FILE"; then
    nemoclaw_cli "$SANDBOX" policy-add --from-file "$POLICY_FILE" --yes
else
    echo "live policy already covers the whole lab file — skipping policy-add (idempotent re-run)"
fi

# --- lab-owned fix (2026-09-11, recorded deviation — prep-log): the
# in-sandbox inference route execution. The in-sandbox supervisor dials the
# route backend (NEMOCLAW_ENDPOINT_URL) DIRECTLY from the sandbox netns —
# not via the vCD egress proxy — and resolves the name against the
# container's own /etc/hosts. Two things are needed, and BOTH are lost on
# container recreation (stop/start, rebuild, fresh onboarding):
#   1. `auth-shim` must resolve inside the container — pin it to the
#      openshell-docker network's gateway IP (the VM host, which serves
#      the shim on 0.0.0.0:8080 via docker-proxy; the shim's nginx binds
#      all interfaces, so the gateway IP serves identically — same shape
#      as the host /etc/hosts pin above).
#   2. the sandbox egress policy must permit the name:port — the built-in
#      baseline only covers the host.openshell.internal names, so the
#      supervisor's dial of `auth-shim:8080` is denied without the entry
#      (a one-off lab preset, same shape as the vss-backend lab endpoints).
# The egress-proxy path that made this work in the 2026-09-10 dry run 403s
# the lab names after the VM reboot (platform tenant egress state —
# escalated to the vCD), so the direct path must stand on its own.
SBX_CID="$(docker ps -q --filter "name=openshell-default--$SANDBOX" --filter status=running | head -1)"
[ -n "$SBX_CID" ] || fail "no running sandbox container for '$SANDBOX' (docker daemon down?)"
if ! docker exec -i "$SBX_CID" sh -c 'grep -qE "[[:space:]]auth-shim([[:space:]]|$)" /etc/hosts'; then
    SW_NET_GW="$(docker network inspect openshell-docker --format '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true)"
    [ -n "$SW_NET_GW" ] || fail "could not derive the openshell-docker network gateway IP for the in-sandbox auth-shim pin"
    docker exec -i "$SBX_CID" sh -c "echo '$SW_NET_GW auth-shim' >> /etc/hosts"
    echo "auth-shim pinned in the sandbox /etc/hosts -> $SW_NET_GW (the VM host serving the shim on 0.0.0.0:8080 — 2026-09-11 fix)"
    log "- in-sandbox auth-shim pin applied (-> $SW_NET_GW): container /etc/hosts, needed for the supervisor's direct route-backend dial (2026-09-11 fix)"
fi
SHIM_POLICY_FILE="$WORK_DIR/lab-auth-shim-policy.yaml"
cat > "$SHIM_POLICY_FILE" <<'YAML'
# Lab one-off (2026-09-11, recorded deviation — prep-log): pre-approve the
# inference endpoint name (auth-shim:8080) for the sandbox egress policy —
# see the companion /etc/hosts pin in 40-nemoclaw.sh. Same shape as the
# vss-backend lab endpoints (02); allowed_ips omitted (user-supplied
# presets may not carry it — v0.0.118).
preset:
  name: lab-auth-shim
  description: "lab inference endpoint (auth-shim) — 02"

network_policies:
  lab-auth-shim:
    name: lab-auth-shim-endpoint
    endpoints:
      - host: auth-shim
        port: 8080
        access: full
YAML
LIVE_NOW="$WORK_DIR/nemoclaw-live-policy-check.yaml"
nemoclaw_cli "$SANDBOX" policy get --raw > "$LIVE_NOW" 2>/dev/null \
    || fail "could not re-read the live sandbox policy for the auth-shim check"
if grep -qE "host: ['\"]?auth-shim" "$LIVE_NOW"; then
    echo "live policy already carries the auth-shim:8080 entry — skipping (idempotent re-run)"
else
    nemoclaw_cli "$SANDBOX" policy add --from-file "$SHIM_POLICY_FILE" --trusted-private-host auth-shim --yes
    echo "lab-auth-shim policy applied (the supervisor's direct dial of auth-shim:8080 is pre-approved)"
    log "- lab-auth-shim policy applied (auth-shim:8080 pre-approved for the supervisor's direct route-backend dial — 2026-09-11 fix)"
fi

# the installer (and nvm node 22 when it bootstrapped one) put the CLIs on
# a PATH this login shell may not have — the installer's own hint is to
# source nvm.sh.
if [ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]; then
    # shellcheck disable=SC1091
    . "${NVM_DIR:-$HOME/.nvm}/nvm.sh"
fi

echo "== gate: 02 step 5 (host status + sandbox-side registration + endpoint probe) =="
STATUS_OUT="$(nemoclaw_cli "$SANDBOX" status 2>&1)" || fail "nemoclaw $SANDBOX status failed — the sandbox did not come up (see $INIT_LOG)"
echo "$STATUS_OUT" | sed 's/^/    /'
echo "$STATUS_OUT" | grep -qF "$MODEL_ID" \
    || fail "status does not show the $MODEL_ID model (the custom model naming via the shim is not active — see $INIT_LOG)"
echo "$STATUS_OUT" | grep -qF "Provider: compatible-endpoint" \
    || fail "status does not show provider compatible-endpoint (the custom endpoint route is not active — see $INIT_LOG)"
echo "$STATUS_OUT" | grep -qF "Inference: healthy" \
    || fail "sandbox inference is not healthy (see $INIT_LOG)"
# vss is one of the applied presets; the Policies line lists them all, and
# the lab-auth-shim one-off (2026-09-11) shifts the order — so match vss
# ANYWHERE in the line, not at a fixed prefix.
echo "$STATUS_OUT" | grep -qE 'Policies: .*vss' \
    || fail "the 'vss' policy preset is not listed as applied (see the policy step above)"
# sandbox-side registration box (the build doc's `openclaw nemoclaw status`
# lives INSIDE the sandbox; the CLI prints the box, then exits non-zero with
# a benign "not a CLI command" note — 2026-09-10 dry-run)
REG_OUT="$(nemoclaw_cli "$SANDBOX" exec --no-tty --timeout 90 -- openclaw nemoclaw status 2>&1)" || true
echo "$REG_OUT" | grep -qF "NemoClaw registered" \
    || fail "sandbox-side registration box not shown (see $INIT_LOG)"
echo "$REG_OUT" | grep -qF "$MODEL_ID" \
    || fail "sandbox-side registration does not show $MODEL_ID (see $INIT_LOG)"
# the lab endpoint the route fronts (the shim — proof the route's upstream
# is the shared Nemotron endpoint, not a vendor default)
curl -fsS --max-time 15 http://auth-shim:8080/v1/models | grep -qF "$MODEL_ID" \
    || fail "auth-shim:8080/v1/models does not list $MODEL_ID (the shared endpoint / shim path is down)"
echo "gate ok: model + compatible-endpoint route + healthy inference + vss policy + sandbox registration + endpoint probe"

# version pin (08 item 28): the installer at v3.2.1 must install/declare
# v0.0.118 — verify at prep; a mismatch is a PREP FINDING, never a silent
# substitution (it is surfaced, not hidden; the L5 checklist re-checks
# behaviour).
VERSION="$(nemoclaw_cli --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
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
log "- gate: nemoclaw $SANDBOX status shows $MODEL_ID + compatible-endpoint + healthy inference + vss policy; sandbox-side openclaw nemoclaw status shows the registration box; auth-shim:8080/v1/models lists the model"

echo "40-nemoclaw: PASS — sandbox '$SANDBOX' ready (see the 40-nemoclaw section in prep-log.md)"
