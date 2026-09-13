#!/usr/bin/env bash
# nemoclaw-recover.sh — boot-time NemoClaw repair (runs from
# nemoclaw-recover.service after docker is up).
#
# After a reboot the docker-managed pieces come back on their own (restart
# policies), but the host OpenShell gateway process and the 18789 dashboard
# port-forward are NOT docker-managed and must be (re)established. The
# vendor's own repair command is `nemoclaw demo recover` (repairs a stopped
# sandbox gateway AND host forwards, 2026-09-10 dry-run).
#
# Exit code contract for systemd: ALWAYS 0. On an already-healthy stack the
# vendor command declines with a lifecycle-lock error — that is a healthy
# no-op, and the 5-min health-watch timer is the safety net for the
# partially-settled-boot case.
set -uo pipefail

LOG=/var/log/nemoclaw-recover.log
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG"; }

CLI="${HOME:-/root}/.local/bin/nemoclaw"
if [ ! -x "$CLI" ]; then
    say "NOTE $CLI not present — NemoClaw not installed yet; nothing to recover"
    exit 0
fi

say "nemoclaw demo recover (boot repair attempt)"
out=$(env NEMOCLAW_GATEWAY_PORT=8085 "$CLI" demo recover 2>&1)
rc=$?
if [ $rc -eq 0 ]; then
    say "recover: success"
elif grep -q "sandbox lifecycle lock" <<< "$out"; then
    say "recover: declined (lifecycle lock) — sandbox already healthy; no-op"
else
    say "recover: failed (exit $rc); output tail:"
    tail -8 <<< "$out" | sed 's/^/    /' | tee -a "$LOG"
fi
exit 0
