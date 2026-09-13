#!/usr/bin/env bash
# snapshot-state.sh — a point-in-time snapshot of the lab stack (read-only:
# it records, never mutates). Used for the reboot test (05 L5 item 4):
#   sudo scripts/prep/snapshot-state.sh pre-reboot   (before the reboot)
#   sudo scripts/prep/snapshot-state.sh post-reboot  (at T+15 after)
#   diff /var/lib/lab-health/snapshot-pre-reboot.txt /var/lib/lab-health/snapshot-post-reboot.txt
# Contents: every container with state/exit/restart-policy, listening ports,
# GPU residency, the nine health probes, and the watchdog's last run.
set -euo pipefail

LABEL="${1:-pre-reboot}"
OUT="/var/lib/lab-health/snapshot-${LABEL}.txt"
mkdir -p /var/lib/lab-health

PROBES="
http://127.0.0.1:8000/health
http://127.0.0.1:38111/v1/ready
http://127.0.0.1:8018/v1/health/ready
http://127.0.0.1:8080/v1/models
http://127.0.0.1:8081/v1/health
http://127.0.0.1:8082/v1/health
http://127.0.0.1:8090/health
http://127.0.0.1:8086/healthz
http://127.0.0.1:18789/
"

{
    echo "# lab state snapshot — $(date -u +'%Y-%m-%dT%H:%M:%SZ') — label: ${LABEL}"
    echo "# host: $(hostname)"
    echo ""
    echo "## containers (all, with state + restart policy)"
    # shellcheck disable=SC2046  # container IDs are space-safe; the split is the point
    for c in $(docker ps -aq); do
        docker inspect --format '{{.Name}}|{{.State.Status}}|exit={{.State.ExitCode}}|restart={{.HostConfig.RestartPolicy.Name}}' "$c"
    done | sort
    echo ""
    echo "## listening ports"
    ss -ltn | awk 'NR>1 {print $4}' | sort -u
    echo ""
    echo "## gpu"
    nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader 2>/dev/null || echo "nvidia-smi unavailable"
    nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null || true
    echo ""
    echo "## health probes (http codes)"
    for u in $PROBES; do
        [ -n "$u" ] || continue
        printf '%-45s %s\n' "$u" "$(curl -fsS -o /dev/null --max-time 5 -w '%{http_code}' "$u" 2>/dev/null || echo FAIL)"
    done
    echo ""
    echo "## watchdog tail"
    tail -n 12 /var/log/lab-health.log 2>/dev/null || echo "(no watchdog log yet)"
} > "$OUT"

echo "snapshot saved: $OUT ($(wc -l < "$OUT") lines)"
