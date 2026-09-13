#!/usr/bin/env bash
# health-watch.sh — lab stack health probes + tiered self-heal (09 boot story).
#
# Run by the lab-health-watch.timer (5 min cadence; installed by
# 50-resilience.sh) and safe to run manually:  sudo /usr/local/lib/lab/health-watch.sh
#
# Design rules (2026-09-10, dry-run):
#   * Probe REAL health (the HTTP gates 20-start verifies), not just
#     process liveness — a container can be Up while serving nothing.
#   * Tiered remediation:
#       - container dead/crashed  -> docker start
#       - container up, probe failing after grace -> docker restart
#       - gateway/dashboard/inference unhealthy -> nemoclaw-heal.sh ladder
#         (vendor recover -> demo start -> 40-nemoclaw re-run -> clean
#         re-onboard; loop-limited; 2026-09-11: `demo recover` alone was
#         not enough — the schema-8 state wall needed the clean re-onboard)
#       - docker daemon down      -> systemctl restart docker
#       - GPU wedge (nvidia-smi fails) -> CRIT log, NO action (a reboot
#         is the only fix; that is a human act, never a watchdog act)
#   * Exited-0 containers are never restarted (deliberate completion —
#     one-shots and clean shutdowns; the doctrine: never override a
#     deliberate act).
#   * Cooldown per target (default 10 min between actions) and
#     escalation: >= 3 actions on one target within an hour -> stop
#     touching it for an hour and log CRIT (a flapping loop is worse
#     than a failed service; the instructor sees the journal).
#   * Grace: a container (re)started within its grace window is not
#     restarted for probe failures (VLM: 20 min — its cold start is real;
#     everything else: 5 min).
set -uo pipefail   # deliberately NO -e: a failing probe must not kill the watch

STATE_DIR="${LAB_HEALTH_STATE_DIR:-/var/lib/lab-health}"
LOG="${LAB_HEALTH_LOG:-/var/log/lab-health.log}"
COOLDOWN="${LAB_HEALTH_COOLDOWN:-600}"        # seconds between actions per target
ESCALATE_N="${LAB_HEALTH_ESCALATE_N:-3}"      # actions in the window that escalate
ESCALATE_WINDOW="${LAB_HEALTH_ESCALATE_WINDOW:-3600}"
ESCALATE_HOLD="${LAB_HEALTH_ESCALATE_HOLD:-3600}"
GRACE="${LAB_HEALTH_GRACE:-300}"              # generic grace after (re)start
VLM_GRACE="${LAB_HEALTH_VLM_GRACE:-1200}"     # vss-rtvi-vlm cold start (5-15 min)
NEMO_CLI="${NEMO_CLI:-${HOME:-/root}/.local/bin/nemoclaw}"
PROBE_TIMEOUT=10

mkdir -p "$STATE_DIR"
NOW=$(date +%s)
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG" >&2; }

# --- per-target action state (cooldown + escalation) ------------------------
can_act() {  # $1=target ; returns 1 (with a log line) when the target must be left alone
    local last
    last=$(cat "$STATE_DIR/$1.last" 2>/dev/null || echo 0)
    if [ $((NOW - last)) -lt "$COOLDOWN" ]; then
        say "SKIP(cooldown) $1 — last action $(( (NOW - last) / 60 ))m ago (< $((COOLDOWN / 60 ))m)"
        return 1
    fi
    local hist="$STATE_DIR/$1.history" n
    if [ -f "$hist" ]; then
        awk -v t=$((NOW - ESCALATE_WINDOW)) '$1 >= t' "$hist" > "$hist.tmp" && mv "$hist.tmp" "$hist"
        n=$(wc -l < "$hist")
    else
        n=0
    fi
    if [ "$n" -ge "$ESCALATE_N" ]; then
        say "CRIT ESCALATED $1 — $n actions in the last $((ESCALATE_WINDOW / 60))m; holding $((ESCALATE_HOLD / 60 ))m for a human: see $LOG"
        return 1
    fi
    return 0
}
acted() {  # $1=target — call AFTER a successful remediation
    echo "$NOW" > "$STATE_DIR/$1.last"
    echo "$NOW" >> "$STATE_DIR/$1.history"
}

# --- docker leg --------------------------------------------------------------
docker_leg() {
    if ! docker info >/dev/null 2>&1; then
        can_act docker-daemon || return 0
        say "ACT(docker-daemon) — docker daemon unresponsive; restarting"
        systemctl restart docker && acted docker-daemon
        return 0
    fi
    # every container whose restart policy demands it be running, and whose
    # last exit was NOT a deliberate 0
    local name policy state exitcode
    while IFS='|' read -r name policy state exitcode; do
        name=${name#/}
        case "$policy" in
            unless-stopped|always) ;;
            *) continue ;;
        esac
        case "$state" in
            exited|created) ;;
            *) continue ;;
        esac
        if [ "$state" = "exited" ] && [ "$exitcode" = "0" ]; then
            continue   # deliberate completion (one-shots, clean shutdowns)
            # NB: a 'created' container also reports ExitCode 0 without ever
            # having run — that is a never-started service, NOT a deliberate
            # completion. The old guard skipped it, so a policy-demanding
            # container stuck in 'created' was never recovered across
            # reboots (2026-09-11: kibana stayed 'created' for a full day and
            # the VSS UI dashboard frame 503'd behind haproxy's bk_kibana).
        fi
        # The NemoClaw sandbox container's lifecycle is owned by the heal
        # ladder + lab-nemoclaw-keepalive (2026-09-13): a raw `docker start`
        # leaves it running with no gateway session, and the next CLI
        # session's gateway shutdown stops it again (the post-reboot flap
        # loop) — while the vendor's own recover/start is walled by the
        # schema-8 receipt state. A bare start only burns the escalation
        # budget; the nemoclaw leg (ladder) + keepalive handle it.
        case "$name" in
            openshell-default--demo-*) continue ;;
        esac
        can_act "ctr:$name" || continue
        say "ACT(docker start) $name — state=$state exit=$exitcode (policy $policy)"
        if docker start "$name" >/dev/null 2>&1; then
            acted "ctr:$name"
        else
            say "WARN docker start failed for $name (docker's error above)"
        fi
    done < <(# shellcheck disable=SC2046  # container IDs are space-safe; the split is the point
        docker inspect $(docker ps -aq) --format '{{.Name}}|{{.HostConfig.RestartPolicy.Name}}|{{.State.Status}}|{{.State.ExitCode}}' 2>/dev/null)
}

# --- probe table: gate -> URL -> container -> grace --------------------------
# (container "-" = the NemoClaw leg, handled separately)
GATES="
vss-agent|http://127.0.0.1:8000/health|vss-agent|$GRACE
vss-lvs|http://127.0.0.1:38111/v1/ready|vss-lvs|$GRACE
rtvlm|http://127.0.0.1:8018/v1/health/ready|vss-rtvi-vlm|$VLM_GRACE
auth-shim|http://127.0.0.1:8080/v1/models|auth-shim|$GRACE
rag-server|http://127.0.0.1:8081/v1/health|rag-server|$GRACE
ingestor|http://127.0.0.1:8082/v1/health|ingestor-server|$GRACE
mock-wo|http://127.0.0.1:8090/health|mock-wo|$GRACE
mock-wo-operator|http://127.0.0.1:8091/health|mock-wo|$GRACE
kibana|http://127.0.0.1:5601/kibana/api/status|kibana|$GRACE
"

probe_leg() {
    local label url ctnr grace
    while IFS='|' read -r label url ctnr grace; do
        [ -n "${label:-}" ] || continue
        if curl -fsS -o /dev/null --max-time "$PROBE_TIMEOUT" "$url"; then
            say "OK $label ($url)"
            continue
        fi
        say "PROBE-FAIL $label ($url)"
        local state
        state=$(docker inspect --format '{{.State.Status}}' "$ctnr" 2>/dev/null || echo missing)
        if [ "$state" = "running" ]; then
            # up but not answering: respect the grace window after (re)start
            local since s
            since=$(docker inspect --format '{{.State.StartedAt}}' "$ctnr" 2>/dev/null)
            s=$(date -d "$since" +%s 2>/dev/null || echo 0)
            if [ "$s" -gt 0 ] && [ $((NOW - s)) -lt "$grace" ]; then
                say "GRACE $ctnr — started $(( (NOW - s) / 60 ))m ago (< $((grace / 60 ))m window); no action yet"
                continue
            fi
            can_act "probe:$label" || continue
            say "ACT(docker restart) $ctnr — up but $url not answering"
            if docker restart "$ctnr" >/dev/null 2>&1; then
                acted "probe:$label"
            else
                say "WARN docker restart failed for $ctnr"
            fi
        else
            say "NOTE $label — container $ctnr state=$state; the docker leg handles (re)start"
        fi
    done <<< "$GATES"
}

# --- NemoClaw leg: host gateway + dashboard forward + inference route ------
# After a reboot the sandbox container comes back (docker policy) but the
# host OpenShell gateway process and the 18789 dashboard forward are dead.
# The 2026-09-11 incident added a third failure class: everything UP (all
# probes green) while the in-sandbox inference route 503'd (vendor state
# wall). So the leg probes inference health too (via the CLI status), and
# the repair is the nemoclaw-heal.sh ladder (vendor `demo recover` is its
# tier 0). On an already-healthy stack the leg is a cheap no-op.
nemoclaw_leg() {
    local need=0
    local gateway_up=0
    if curl -fsS -o /dev/null --max-time 5 http://127.0.0.1:8086/healthz; then
        say "OK nemoclaw gateway healthz"
        gateway_up=1
    else
        say "PROBE-FAIL nemoclaw gateway healthz (127.0.0.1:8086)"
        need=1
    fi
    if ! curl -fsS -o /dev/null --max-time 5 http://127.0.0.1:18789/; then
        say "PROBE-FAIL dashboard forward (127.0.0.1:18789)"
        need=1
    else
        say "OK dashboard forward (127.0.0.1:18789)"
    fi
    # Inference probe (only when the gateway answers — otherwise the status
    # call would just time out and the action is the same). 2026-09-11:
    # the "everything up, route 503" case was invisible to the process
    # probes; this is the probe that catches it.
    if [ "$gateway_up" = 1 ] && [ -x "$NEMO_CLI" ]; then
        if timeout 120 env NEMOCLAW_GATEWAY_PORT=8085 "$NEMO_CLI" demo status 2>/dev/null \
                | grep -qF "Inference: healthy"; then
            say "OK nemoclaw inference route (Inference: healthy)"
        else
            say "PROBE-FAIL nemoclaw inference route (not 'Inference: healthy')"
            need=1
        fi
    fi
    [ "$need" = 1 ] || return 0
    can_act nemoclaw || return 0
    local HEAL=/usr/local/lib/lab/nemoclaw-heal.sh
    if [ -x "$HEAL" ]; then
        say "ACT(nemoclaw-heal ladder) — gateway, forward and/or inference unhealthy"
        local hout hrc=0
        hout=$("$HEAL" 2>&1) || hrc=$?
        tail -8 <<< "$hout" | sed 's/^/    /' | tee -a "$LOG"
        if [ $hrc -eq 0 ]; then
            acted nemoclaw
            say "OK nemoclaw-heal succeeded (gate healthy)"
        else
            say "WARN nemoclaw-heal finished unhealthy (exit $hrc) — its loop guard applies; next attempt after cooldown"
        fi
    else
        # legacy fallback (pre-heal install): the vendor-only repair
        [ -x "$NEMO_CLI" ] || { say "WARN $NEMO_CLI missing — cannot run vendor recover (40-nemoclaw never ran?)"; return 0; }
        say "ACT(nemoclaw recover) — heal script missing; legacy vendor-only repair"
        local out
        if out=$(env NEMOCLAW_GATEWAY_PORT=8085 "$NEMO_CLI" demo recover 2>&1); then
            acted nemoclaw
            say "OK nemoclaw recover succeeded"
        else
            if grep -q "sandbox lifecycle lock" <<< "$out"; then
                say "OK nemoclaw recover declined (lifecycle lock) — the sandbox is healthy; nothing to repair"
                acted nemoclaw   # it WAS the healthy answer; cooldown, not escalation
            else
                say "WARN nemoclaw recover failed (exit $?); output tail:"
                tail -6 <<< "$out" | sed 's/^/    /' | tee -a "$LOG" >&2
            fi
        fi
    fi
}

# --- GPU leg: detection only --------------------------------------------------
gpu_leg() {
    if nvidia-smi -L >/dev/null 2>&1; then
        say "OK gpu ($(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1))"
    else
        say "CRIT GPU WEDGE — nvidia-smi failing; no automatic action (a VM reboot is the only fix; this needs a human/platform)"
    fi
}

say "== health-watch run (uptime $(cut -d' ' -f1 /proc/uptime | cut -d. -f1)s) =="
docker_leg
probe_leg
nemoclaw_leg
gpu_leg
say "== health-watch done =="
exit 0
