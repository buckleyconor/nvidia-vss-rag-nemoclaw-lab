#!/usr/bin/env bash
# nemoclaw-keepalive.sh — persistent NemoClaw gateway session (lab-owned, 2026-09-13).
#
# ROOT CAUSE this service exists for (see prep-log 2026-09-13 "nemoclaw
# post-reboot flap" section): the OpenShell host gateway (v0.0.106) is a
# CLI-session-scoped process. When the LAST attached CLI client detaches,
# the gateway shuts down, and its shutdown handler STOPS the sandbox
# container it manages ("Stopped Docker sandbox containers during gateway
# shutdown", SIGTERM -> exit 143). Empirically on this VM (2026-09-13):
# every gateway instance lived exactly as long as the heal ladder's CLI
# session (~97-102s) and died 0-4s after the last `nemoclaw` call exited,
# killing the sandbox with it. A long-lived attached client prevents the
# shutdown — verified 2026-09-13: with `nemoclaw demo logs --follow`
# attached, the gateway + container survived the heal ladder's final CLI
# detach and stayed up indefinitely.
#
# This service holds exactly that attachment for as long as the stack is
# up, and revives the stack with the heal ladder (flock-guarded, loop-
# guarded) when it is down. It runs under systemd (Restart=always), so it
# is also the post-reboot bring-up path alongside the 90s-settle boot
# service — the two coordinate through the ladder's flock.
#
# Run by lab-nemoclaw-keepalive.service (root). Safe to run manually:
#   sudo /usr/local/lib/lab/nemoclaw-keepalive.sh
set -uo pipefail   # no -e: a failing probe/attach must not kill the loop

REPO="${LAB_REPO:-/home/demouser/projects/nvidia-vss-rag-nemoclaw-lab}"
CLI="${NEMO_CLI:-/root/.local/bin/nemoclaw}"
HEAL="${LAB_HEAL:-/usr/local/lib/lab/nemoclaw-heal.sh}"
STATE_DIR="${LAB_HEALTH_STATE_DIR:-/var/lib/lab-health}"
LOG="/var/log/nemoclaw-keepalive.log"
LADDER_PIDFILE="$STATE_DIR/keepalive-ladder.pid"
SANDBOX="demo"
GW_PORT="${NEMOCLAW_GATEWAY_PORT:-8085}"
DASH_PORT="${NEMOCLAW_DASHBOARD_PORT:-18789}"

# --- environment contract (same as the heal ladder) -------------------------
if [ -f "$REPO/config/nemoclaw.env" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$REPO/config/nemoclaw.env"
    set +a
fi
export NEMOCLAW_GATEWAY_PORT="$GW_PORT"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG"; }

mkdir -p "$STATE_DIR"

probes_ok() {
    curl -fsS -o /dev/null --max-time 5 "http://127.0.0.1:$((GW_PORT + 1))/healthz" || return 1
    curl -fsS -o /dev/null --max-time 5 "http://127.0.0.1:$DASH_PORT/" || return 1
    return 0
}

ladder_running() {
    local pid
    pid=$(cat "$LADDER_PIDFILE" 2>/dev/null || echo "")
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

say "nemoclaw-keepalive: started (pid $$; gateway :$GW_PORT, health :$((GW_PORT + 1)), dashboard :$DASH_PORT)"

while true; do
    if probes_ok; then
        # Hold a persistent CLI client session. The vendor gateway shuts
        # down (and stops the sandbox container) when the last client
        # detaches — this is the client that must not go away. The 1h
        # timeout is only a safety bound: a stuck attach re-binds cleanly.
        say "ATTACH — holding 'nemoclaw $SANDBOX logs --follow' (re-attach on break)"
        timeout 3600 "$CLI" "$SANDBOX" logs --follow --tail 20 >>"$LOG" 2>&1 || true
        say "DETACH — logs stream ended (gateway down? stack flapped? re-checking)"
        continue
    fi

    # Stack down: revive with the heal ladder in the BACKGROUND, then tight-
    # loop so we attach as soon as the ladder's tier 2 brings the gateway up
    # — BEFORE the ladder's final CLI call detaches (the window in which the
    # gateway would otherwise shut the sandbox down).
    if ! ladder_running; then
        say "REVIVE — stack down; launching the heal ladder in the background"
        nohup "$HEAL" >>"$LOG" 2>&1 &
        echo $! > "$LADDER_PIDFILE"
    else
        say "REVIVE — ladder already running; waiting for the gateway"
    fi
    while ! probes_ok; do
        if ladder_running; then
            sleep 2
        else
            say "REVIVE — ladder finished, probes still down; backing off 60s"
            sleep 60
            break
        fi
    done
done
