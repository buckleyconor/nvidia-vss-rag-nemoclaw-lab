#!/usr/bin/env bash
# nemoclaw-heal.sh — tiered NemoClaw repair ladder (lab-owned, 2026-09-11).
#
# Supersedes nemoclaw-recover.sh (vendor-only `demo recover`), which is the
# first tier here but is NOT sufficient on its own: on 2026-09-11 (post-VM-
# reboot) `demo recover` was hard-blocked by a vendor-internal state wall
# ("Hermes portable lifecycle receipt schema-8 requalification requires the
# sandbox lifecycle lock for 'demo'", failedStage=authority) while the
# in-sandbox inference route 503'd ("inference service unavailable") — and
# no amount of recover/stop/start/gateway-restart cleared it. The path that
# DID work (proven end-to-end that day) was a full clean re-onboard + the
# lab's 40-nemoclaw gate. This ladder encodes that, tier by tier:
#
#   gate        model + Inference: healthy + vss policy (the 40-nemoclaw gate)
#   tier 0      vendor `nemoclaw demo recover` (the classic boot repair; on a
#               healthy stack it declines with a lifecycle-lock error = no-op)
#   tier 1      `nemoclaw demo start` (recover a stopped container)
#   tier 2      full `40-nemoclaw.sh` re-run (idempotent: vendor init, lab
#               policy, the in-sandbox auth-shim /etc/hosts pin + policy
#               entry, its own gate)
#   tier 3      NUCLEAR — clean re-onboard: openshell sandbox delete ->
#               nemoclaw demo destroy (reconcile) -> gateway remove ->
#               process kill -> stale state sweep (PRESERVED, never deleted:
#               the 8085 state dir, indeterminate managed-bootstrap journal
#               entries, retained-recovery records) -> fresh non-interactive
#               onboarding (vendor env surface, from the lab contract) ->
#               in-sandbox pin -> `onboard --resume` -> 40-nemoclaw.
#               Loop-limited: max 2 attempts/hour, then CRIT + stop
#               (a human act, never a watchdog act — same doctrine as the
#               GPU-wedge tier in health-watch.sh).
#
# Run by nemoclaw-recover.service at boot (after the 90s settle) and by the
# health-watch NemoClaw leg (5-min cadence). Safe to run manually:
#   sudo /usr/local/lib/lab/nemoclaw-heal.sh
#
# Exit code contract: 0 = gate healthy (whether or not action was needed);
# 1 = still unhealthy (logged; the caller's safety net applies).
set -uo pipefail   # no -e: a failing tier must not kill the ladder

REPO="${LAB_REPO:-/home/demouser/projects/nvidia-vss-rag-nemoclaw-lab}"
CLI="${HOME:-/root}/.local/bin/nemoclaw"
OPENSHELL="${OPENSHELL:-/usr/local/bin/openshell}"
GW_PORT="${NEMOCLAW_GATEWAY_PORT:-8085}"
SANDBOX="demo"
MODEL_ID="nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4"
LOG="${LAB_HEAL_LOG:-/var/log/nemoclaw-heal.log}"
STATE_DIR="${LAB_HEALTH_STATE_DIR:-/var/lib/lab-health}"
STATE="$STATE_DIR/nemoclaw-heal.state"
LOCK="$STATE_DIR/nemoclaw-heal.lock"
NUCLEAR_WINDOW=3600   # 2 failed nuclear attempts within an hour -> CRIT, stop
NUCLEAR_MAX=2

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG"; }

# --- one heal at a time (boot service and health-watch can overlap) --------
mkdir -p "$STATE_DIR"
exec 9>"$LOCK"
flock -n 9 || { echo "nemoclaw-heal: another heal is in progress — no-op" >>"$LOG"; exit 0; }

# --- environment contract (same as 40-nemoclaw.sh: the repo's env file) ----
if [ -f "$REPO/config/nemoclaw.env" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$REPO/config/nemoclaw.env"
    set +a
fi
export NEMOCLAW_GATEWAY_PORT="${NEMOCLAW_GATEWAY_PORT:-8085}"
export OPENSHELL_SERVER_PORT="$NEMOCLAW_GATEWAY_PORT"
export OPENSHELL_HEALTH_PORT="$((NEMOCLAW_GATEWAY_PORT + 1))"
export OPENSHELL_METRICS_PORT="$((NEMOCLAW_GATEWAY_PORT + 2))"
# The onboard SSRF preflight only accepts a user-supplied private endpoint
# whose host is on this allowlist (see 40-nemoclaw.sh for the full story).
export NEMOCLAW_TRUSTED_PRIVATE_INFERENCE_HOSTS="${NEMOCLAW_TRUSTED_PRIVATE_INFERENCE_HOSTS:-auth-shim}"
# Vendor non-interactive surface (init_nemoclaw.sh export_provider_env):
# values come from the env, no TTY prompts (2026-09-11: an interactive
# --fresh aborted with "Installation cancelled" under a non-TTY sudo).
export NEMOCLAW_MODEL="$MODEL_ID"
export NEMOCLAW_NON_INTERACTIVE=1
export NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1
export NEMOCLAW_SANDBOX_NAME="$SANDBOX"

[ -x "$CLI" ] || { say "NOTE $CLI not present — NemoClaw not installed yet; nothing to heal"; exit 0; }

# --- the gate (the 40-nemoclaw gate, read from CLI status) ------------------
gate() {
    local out
    out="$(timeout 120 env NEMOCLAW_GATEWAY_PORT="$GW_PORT" "$CLI" demo status 2>&1)" || {
        say "gate: status call failed (CLI/gateway down?)"; return 1; }
    grep -qF "$MODEL_ID" <<<"$out" || { say "gate: model missing from status"; return 1; }
    grep -qF "Inference: healthy" <<<"$out" || { say "gate: inference not healthy"; return 1; }
    grep -qE 'Policies: .*vss' <<<"$out" || { say "gate: vss policy not listed"; return 1; }
    say "gate: healthy (model + inference + vss policy)"
    return 0
}

# --- tier 3 loop guard -------------------------------------------------------
nuclear_attempts_recent() {
    [ -f "$STATE" ] || { echo 0; return; }
    local now ts_ n=0
    now=$(date +%s)
    # count "<epoch> nuclear" lines newer than the window
    while read -r ts_ _; do
        [ -n "$ts_" ] || continue
        [ $((now - ts_)) -le "$NUCLEAR_WINDOW" ] && n=$((n + 1))
    done < <(grep ' nuclear$' "$STATE" 2>/dev/null)
    echo "$n"
}
nuclear_allowed() {
    local n; n=$(nuclear_attempts_recent)
    [ "$n" -lt "$NUCLEAR_MAX" ]
}
record() { echo "$(date +%s) $1" >>"$STATE"; tail -20 "$STATE" >"$STATE.tmp" && mv "$STATE.tmp" "$STATE"; }

say "nemoclaw-heal: started (pid $$)"
gate && { say "nemoclaw-heal: already healthy — no action"; exit 0; }
say "nemoclaw-heal: gate FAILED — entering the ladder"

# --- tier 0: the vendor's own boot repair ------------------------------------
say "tier 0: vendor 'nemoclaw $SANDBOX recover' (classic boot repair)"
out0="$(env NEMOCLAW_GATEWAY_PORT="$GW_PORT" "$CLI" demo recover 2>&1)"; rc0=$?
tail -6 <<<"$out0" | sed 's/^/    /' | tee -a "$LOG"
if [ $rc0 -eq 0 ]; then
    say "tier 0: recover succeeded"
elif grep -q "schema-8" <<<"$out0"; then
    # 2026-09-11: this specific wall ("Hermes portable lifecycle receipt
    # schema-8 requalification requires the sandbox lifecycle lock") is a
    # vendor-internal state block, NOT a healthy no-op — it persists across
    # stop/start/gateway-restart and only the clean re-onboard (tier 3) clears
    # it. Classified distinctly so the log trail is honest.
    say "tier 0: BLOCKED by the vendor schema-8 receipt wall (state stuck) — continuing the ladder"
elif grep -q "lifecycle lock" <<<"$out0"; then
    say "tier 0: declined (lifecycle lock) — healthy no-op"
else
    say "tier 0: recover failed (exit $rc0) — continuing"
fi
record "recover"
gate && exit 0

# --- tier 1: a stopped container ---------------------------------------------
say "tier 1: 'nemoclaw $SANDBOX start' (recover a stopped container)"
out1="$(env NEMOCLAW_GATEWAY_PORT="$GW_PORT" "$CLI" demo start 2>&1)"; rc1=$?
tail -4 <<<"$out1" | sed 's/^/    /' | tee -a "$LOG"
[ $rc1 -eq 0 ] && say "tier 1: start ok" || say "tier 1: start reported a problem (exit $rc1) — continuing"
record "start"
sleep 15
gate && exit 0

# --- tier 2: the lab's canonical re-run (idempotent) --------------------------
say "tier 2: 40-nemoclaw.sh re-run (vendor init + lab policy + auth-shim pin + gate)"
out2="$(timeout 900 bash "$REPO/scripts/prep/40-nemoclaw.sh" 2>&1)"; rc2=$?
tail -8 <<<"$out2" | sed 's/^/    /' | tee -a "$LOG"
[ $rc2 -eq 0 ] && say "tier 2: 40-nemoclaw passed" || say "tier 2: 40-nemoclaw failed (exit $rc2) — continuing"
record "40-nemoclaw"
gate && exit 0

# --- tier 3: nuclear — clean re-onboard (proven 2026-09-11 path) -------------
if ! nuclear_allowed; then
    say "CRIT tier 3 refused: >= $NUCLEAR_MAX nuclear attempts in the last ${NUCLEAR_WINDOW}s (see $STATE) — stopping; this needs a human (instructor action), never a watchdog act"
    exit 1
fi
say "tier 3: NUCLEAR clean re-onboard (the sandbox workspace is re-created; corpus/VSS state is docker-managed and unaffected — recorded in prep-log)"
record "nuclear"

# 1. remove the sandbox the vendor's own way (identity-bound delete first,
#    then the NemoClaw reconcile — the sequence that cleared the 2026-09-11
#    retained-attempt block)
env HOME=/root "$OPENSHELL" sandbox delete "$SANDBOX" 2>&1 | sed 's/^/    /' | tee -a "$LOG" || true
env NEMOCLAW_GATEWAY_PORT="$GW_PORT" "$CLI" demo destroy --yes 2>&1 | tail -4 | sed 's/^/    /' | tee -a "$LOG" || true

# 2. drop the host gateway + host-side supervisor (clean process state; the
#    CLI re-raises the gateway on the next call)
for p in $(ps -eo pid,args | grep 'openshell-gateway\[nemoclaw' | awk '{print $1}'); do
    kill "$p" 2>/dev/null || true
done
sleep 4

# 3. sweep the stale user state — PRESERVED, never deleted (lab doctrine:
#    every sweep is reversible; the vendor's own guidance is "preserve every
#    durable recovery record")
SWEEP_TS="$(date -u +%Y%m%dT%H%M%SZ)"
GATEWAY_STATE="/root/.nemoclaw/gateways/$GW_PORT"
if [ -d "$GATEWAY_STATE" ]; then
    env HOME=/root "$OPENSHELL" gateway remove "nemoclaw-$GW_PORT" 2>&1 | sed 's/^/    /' | tee -a "$LOG" || true
    mv "$GATEWAY_STATE" "$GATEWAY_STATE.heal-$SWEEP_TS" \
        && say "tier 3: gateway state dir preserved at $GATEWAY_STATE.heal-$SWEEP_TS" \
        || say "tier 3: could not move the gateway state dir (busy?)"
fi
JOURNAL="/root/.local/state/nemoclaw/openshell-docker-gateway-$GW_PORT/managed-bootstrap"
if [ -d "$JOURNAL" ]; then
    PRES="/root/.nemoclaw/preserved-bootstrap-$SWEEP_TS"
    for f in "$JOURNAL"/*.json; do
        [ -e "$f" ] || continue
        [ -e "$f.finalized" ] && continue
        mkdir -p "$PRES"
        mv "$f" "$PRES/" 2>/dev/null && say "tier 3: indeterminate journal entry preserved: $(basename "$f")"
        [ -e "$f.decision" ] && mv "$f.decision" "$PRES/" 2>/dev/null || true
    done
fi

# 4. fresh non-interactive onboarding (vendor env surface; step 7's in-sandbox
#    smoke is EXPECTED to fail here — the fresh container lacks the auth-shim
#    pin; the resume after the pin completes it)
say "tier 3: fresh onboarding (this takes a few minutes)"
env HOME=/root "$CLI" onboard --fresh --non-interactive --name "$SANDBOX" --tool-disclosure progressive 2>&1 \
    | tail -12 | sed 's/^/    /' | tee -a "$LOG"

# 5. the in-sandbox auth-shim pin (same fix as 40-nemoclaw.sh — applied early
#    so the resume's step-7 smoke passes)
CID="$(docker ps -q --filter "name=openshell-default--$SANDBOX" --filter status=running | head -1)"
if [ -n "$CID" ]; then
    if ! docker exec -i "$CID" sh -c 'grep -qE "[[:space:]]auth-shim([[:space:]]|$)" /etc/hosts'; then
        SW_NET_GW="$(docker network inspect openshell-docker --format '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true)"
        [ -n "$SW_NET_GW" ] || say "WARN tier 3: could not derive the openshell-docker gateway IP for the pin"
        docker exec -i "$CID" sh -c "echo '$SW_NET_GW auth-shim' >> /etc/hosts" \
            && say "tier 3: auth-shim pinned in the sandbox /etc/hosts -> $SW_NET_GW"
    fi
fi

# 6. resume (completes the onboarding's step 7 against the now-reachable endpoint)
env HOME=/root "$CLI" onboard --resume --name "$SANDBOX" --tool-disclosure progressive 2>&1 \
    | tail -6 | sed 's/^/    /' | tee -a "$LOG" \
    || say "tier 3: resume reported nothing resumable (onboarding may have completed — the gate decides)"

# 7. the lab's own gate (applies the lab policy + pin idempotently as well)
say "tier 3: 40-nemoclaw.sh (lab gate)"
timeout 900 bash "$REPO/scripts/prep/40-nemoclaw.sh" 2>&1 | tail -8 | sed 's/^/    /' | tee -a "$LOG"

if gate; then
    say "nemoclaw-heal: REPAIRED via tier 3 (nuclear clean re-onboard) — full trail in $LOG; state preserved under /root/.nemoclaw/*.heal-* and preserved-bootstrap-*"
    exit 0
fi
say "CRIT tier 3 exhausted and the gate still fails — stopping (loop guard now in effect for ${NUCLEAR_WINDOW}s); a human is required (instructor action): see $LOG and the 2026-09-11 prep-log section"
exit 1
