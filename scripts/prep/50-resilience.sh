#!/usr/bin/env bash
# 50-resilience.sh — zero-interaction reboot recovery + self-heal layer (09).
#
# Installs/hardens, idempotently:
#   1. Restart policies: RUNNING long-running containers -> unless-stopped
#      (exited/created containers are left as-is and named in the output);
#      named one-shots -> on-failure; vss-kibana-init -> no (the vendor
#      left it on UNBOUNDED on-failure; at first bring-up the kibana
#      container — which the bp_developer_lvs_2d profile DOES run — sat
#      in 'created' state, so the init crash-looped 272+ times; 2026-09-10
#      finding. Root-caused 2026-09-11: kibana started, init re-ran once
#      (exit 0), suppression kept because the imported objects persist in
#      the ES indices and the kibana gate now watches the service).
#   2. /etc/docker/daemon.json: live-restore (an accidental
#      `systemctl restart docker` no longer takes the stack down; the
#      change takes effect at the next daemon restart / reboot, like the
#      dns fallback 20-start wrote).
#   3. Boot repair: nemoclaw-recover.service (the host OpenShell gateway
#      process and the 18789 dashboard forward are NOT docker-managed and
#      die at reboot; the vendor's `nemoclaw demo recover` repairs both).
#   4. Health watch: lab-health-watch.timer (5 min) running
#      health-watch.sh — HTTP-gate probes + tiered self-heal with
#      cooldowns, grace windows and loud escalation (no silent hammering).
#   5. NemoClaw keepalive (persistent gateway client — the 2026-09-13
#      post-reboot flap) and the hook relay (O2 wake bridge) + its token;
#      /etc/lab/lab.env carries LAB_REPO for every unit.
#
# Run on the learner VM after 20-start.sh / 40-nemoclaw.sh (also called by
# 20-start.sh as its final step).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INSTALL_DIR=/usr/local/lib/lab
PREP_LOG="$REPO_ROOT/prep-log.md"
log() { printf '%s\n' "$*" >> "$PREP_LOG"; }
fail() { echo "50-resilience: FAIL — $*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "docker not available (run 00-host-prep.sh first)"
docker info >/dev/null 2>&1 || fail "docker daemon not running"

# --- 1. restart policies ------------------------------------------------------
# Long-running: everything except the named one-shots and the suppressed
# set. One-shots: the vendor init/one-shot containers -> on-failure:5
# (bounded retries: a genuinely broken one-shot is visible and self-
# limiting — an unbounded on-failure loop is how vss-kibana-init reached
# 272 restarts). A one-shot in a 'restarting' loop is always wrong: stop
# it and name it in the log (their work is either done or superseded —
# the recorded-reality trail in prep-log.md says which).
ONE_SHOTS="
sdrc-wait-for-redis
sdrc-wait-for-workloads
sdrc-wdm-env-from-config
sdrc-render-config
sdrc-init-dirs
vss-kafka-topics
vss-broker-health-check
vss-elasticsearch-init
"
SUPPRESSED="vss-kibana-init"

in_list() { local x; for x in $2; do [ "$x" = "$1" ] && return 0; done; return 1; }

changed=0
for c in $(docker ps -aq); do
    name=$(docker inspect --format '{{.Name}}' "$c" | sed 's|^/||')
    state=$(docker inspect --format '{{.State.Status}}' "$c")
    want=""
    if in_list "$name" "$SUPPRESSED"; then want=no
    elif in_list "$name" "$ONE_SHOTS"; then want=on-failure:5
    elif [ "$state" = "running" ]; then want=unless-stopped
    else
        # Only a RUNNING container is a long-running service. unless-stopped
        # restarts on every exit, so promoting an exited-0 one-shot missing
        # from ONE_SHOTS makes it loop after the next reboot (the kibana-init
        # failure), and health-watch `docker start`s created+unless-stopped
        # containers — a never-started (e.g. GPU) container would be started.
        echo "policy $name: left as-is (state=$state — not a running service; classify it in ONE_SHOTS if it is a one-shot)"
        continue
    fi
    have=$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' "$c")
    if [ "$have" != "$want" ]; then
        docker update --restart "$want" "$c" >/dev/null
        changed=$((changed + 1))
        echo "policy $name: $have -> $want"
    fi
done
# the suppressed loop-starter: also stop it if it is (mid-loop) running
for c in $SUPPRESSED; do
    st=$(docker inspect --format '{{.State.Status}}' "$c" 2>/dev/null || echo missing)
    if [ "$st" = "running" ] || [ "$st" = "restarting" ]; then
        docker stop "$c" >/dev/null
        echo "suppressed $c (stopped; its target service is never started by the lab profile)"
    fi
done
# a one-shot stuck in a docker restart loop is always wrong (its work is
# done, superseded, or genuinely broken — prep-log.md records which)
for c in $ONE_SHOTS; do
    st=$(docker inspect --format '{{.State.Status}}' "$c" 2>/dev/null || echo missing)
    [ "$st" = "restarting" ] || continue
    docker stop "$c" >/dev/null
    echo "stopped $c (one-shot in a restart loop — work done or superseded; see prep-log.md)"
done
echo "restart policies: $changed container(s) updated"

# --- 2. daemon.json: live-restore (idempotent merge) --------------------------
python3 - <<'PY'
import json
p = "/etc/docker/daemon.json"
cfg = json.load(open(p))
if cfg.get("live-restore") is not True:
    cfg["live-restore"] = True
    json.dump(cfg, open(p, "w"), indent=4)
    print("daemon.json: live-restore enabled (effective at next daemon restart / reboot)")
else:
    print("daemon.json: live-restore already set")
PY

# --- 3+4. units ----------------------------------------------------------------
[ -f "$REPO_ROOT/scripts/prep/health-watch.sh" ] || fail "health-watch.sh missing (repo layout moved?)"
install -d "$INSTALL_DIR"
# The repo checkout every unit needs (heal tier 2 runs 40-nemoclaw.sh; the
# ladder and keepalive source config/nemoclaw.env from it). Loaded by the
# units via EnvironmentFile and by manual runs of the scripts.
install -d /etc/lab
printf 'LAB_REPO="%s"\n' "$REPO_ROOT" > /etc/lab/lab.env
echo "/etc/lab/lab.env: LAB_REPO=$REPO_ROOT"
install -m 755 "$REPO_ROOT/scripts/prep/health-watch.sh" "$INSTALL_DIR/health-watch.sh"
install -m 755 "$REPO_ROOT/scripts/systemd/nemoclaw-recover.sh" "$INSTALL_DIR/nemoclaw-recover.sh"
install -m 755 "$REPO_ROOT/scripts/systemd/nemoclaw-heal.sh" "$INSTALL_DIR/nemoclaw-heal.sh"
install -m 755 "$REPO_ROOT/scripts/systemd/nemoclaw-keepalive.sh" "$INSTALL_DIR/nemoclaw-keepalive.sh"
install -m 755 "$REPO_ROOT/scripts/systemd/nemoclaw-hook-relay.py" "$INSTALL_DIR/nemoclaw-hook-relay.py"
install -m 644 "$REPO_ROOT/scripts/systemd/lab-health-watch.service" /etc/systemd/system/lab-health-watch.service
install -m 644 "$REPO_ROOT/scripts/systemd/lab-health-watch.timer" /etc/systemd/system/lab-health-watch.timer
install -m 644 "$REPO_ROOT/scripts/systemd/nemoclaw-recover.service" /etc/systemd/system/nemoclaw-recover.service
install -m 644 "$REPO_ROOT/scripts/systemd/lab-nemoclaw-keepalive.service" /etc/systemd/system/lab-nemoclaw-keepalive.service
install -m 644 "$REPO_ROOT/scripts/systemd/lab-nemoclaw-hook-relay.service" /etc/systemd/system/lab-nemoclaw-hook-relay.service
# The relay's bearer token: lab-generated (not the sandbox gateway token), so
# a tier-3 clean re-onboard cannot invalidate it. 20-start.sh creates it
# first (mock-wo starts in STEP 1) — this only fills the gap on a
# standalone 50-resilience run.
HOOK_TOKEN_FILE="${LAB_HOOK_TOKEN_FILE:-/root/.config/lab/nemoclaw-hook-token}"
install -d -m 700 "$(dirname "$HOOK_TOKEN_FILE")"
if [ ! -s "$HOOK_TOKEN_FILE" ]; then
    ( umask 077; python3 -c 'import secrets; print(secrets.token_hex(32))' > "$HOOK_TOKEN_FILE" )
    echo "hook relay token generated at $HOOK_TOKEN_FILE (value never printed — 04)"
fi
systemctl daemon-reload
systemctl enable lab-health-watch.timer nemoclaw-recover.service >/dev/null
systemctl restart lab-health-watch.timer >/dev/null   # pick up the new timer spec
# keepalive: --now starts it if it is not running but never restarts a running
# one — a restart drops the persistent gateway client, and the gateway stops
# the sandbox 0-4 s after its last client leaves (the 2026-09-13 flap). A
# changed keepalive script takes effect at the next reboot.
systemctl enable --now lab-nemoclaw-keepalive.service >/dev/null
# relay: stateless, restart is safe and picks up a changed script.
systemctl enable lab-nemoclaw-hook-relay.service >/dev/null
systemctl restart lab-nemoclaw-hook-relay.service
echo "units enabled: nemoclaw-recover.service (boot), lab-health-watch.timer (5 min), lab-nemoclaw-keepalive.service, lab-nemoclaw-hook-relay.service"

# --- 5. service enablement (reboot: driver + docker) ---------------------------
for s in docker nvidia-persistenced; do
    st=$(systemctl is-enabled "$s" 2>/dev/null || echo unknown)
    [ "$st" = "enabled" ] || { echo "systemctl enable $s"; systemctl enable "$s"; }
done

# --- 6. verify -----------------------------------------------------------------
systemctl is-active lab-health-watch.timer >/dev/null && echo "timer active"
systemctl is-enabled nemoclaw-recover.service >/dev/null && echo "boot repair enabled"
systemctl is-active lab-nemoclaw-keepalive.service >/dev/null && echo "keepalive active"
systemctl is-active lab-nemoclaw-hook-relay.service >/dev/null && echo "hook relay active"
echo "== first health-watch run (manual) =="
"$INSTALL_DIR/health-watch.sh" || true

log ""
log "## $(date -u +%Y-%m-%dT%H:%M:%SZ) — 50-resilience: zero-interaction reboot layer"
log "- restart policies: long-running unless-stopped; one-shots on-failure; vss-kibana-init suppressed (no) — vendor left it on unbounded on-failure; at first bring-up it crash-looped 272+ times against the never-started ('created') kibana container, which the bp_developer_lvs_2d profile DOES run (2026-09-10 finding; root-caused 2026-09-11 — kibana started, init re-ran exit 0, health-watch 'created'+exit-0 guard fixed)"
log "- daemon.json: live-restore=true (effective at next daemon restart/reboot)"
log "- boot repair: nemoclaw-recover.service (vendor 'nemoclaw demo recover' — host gateway + dashboard forward are not docker-managed)"
log "- self-heal: lab-health-watch.timer every 5 min (health-watch.sh: HTTP gates, docker start/restart with cooldown+grace+escalation, vendor recover for the NemoClaw leg, CRIT-only for a GPU wedge)"

echo "50-resilience: PASS — reboot recovery armed (see the 50-resilience section in prep-log.md)"
