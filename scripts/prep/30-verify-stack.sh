#!/usr/bin/env bash
# 30-verify-stack.sh — the full health gate table (03 layout; 09 "Endpoints,
# credentials, artifacts (what 'ready' means)").
#
# Run on the learner vCD VM after 20-start.sh + 25-ingest-corpus.sh.
# Probes every lab endpoint, asserts the local LLM NIM (:30081) is ABSENT
# (a running local LLM NIM is a misconfiguration signal — 02), and records
# the nvidia-smi VRAM measurement to prep-log.md (the L5 checklist in 05
# judges the numbers: VLM ~38 GB not ~86 GB; six NIMs; <= 80 GB total).
#
# Exits non-zero on any probe failure.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RAG_DIR="${RAG_DIR:-/data/rag}"
MODEL_ID="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
PREP_LOG="$REPO_ROOT/prep-log.md"
log() { printf '%s\n' "$*" >> "$PREP_LOG"; }
fail() { echo "30-verify-stack: FAIL — $*" >&2; exit 1; }

FAILURES=0
# check <label> <probe-cmd...>
check() {
    local label="$1"
    shift
    if "$@" >/dev/null 2>&1; then
        echo "PASS  $label"
    else
        echo "FAIL  $label" >&2
        FAILURES=$((FAILURES + 1))
    fi
}

echo "== health gate table (09 endpoints) =="

# auth-shim: /v1/models must LIST the model (not just answer)
shim_models() {
    curl -sf -m 10 http://127.0.0.1:8080/v1/models \
        -H 'Authorization: Bearer dummy' | grep -qF "$MODEL_ID"
}
check "auth-shim :8080/v1/models lists $MODEL_ID" shim_models

check "VSS agent :8000/health" curl -sf -m 10 http://127.0.0.1:8000/health
check "LVS backend :38111/v1/ready" curl -sf -m 10 http://127.0.0.1:38111/v1/ready
check "RT-VLM :8018/v1/health/ready" curl -sf -m 10 http://127.0.0.1:8018/v1/health/ready
check "RAG server :8081/v1/health" curl -sf -m 10 "http://127.0.0.1:8081/v1/health?check_dependencies=true"
check "RAG ingestor :8082/v1/health" curl -sf -m 10 "http://127.0.0.1:8082/v1/health?check_dependencies=true"
check "mock-wo :8090/health" curl -sf -m 10 http://127.0.0.1:8090/health

# the local LLM NIM must NOT be running (02: generation is remote via the
# shared endpoint; its running is a misconfiguration signal)
if curl -sf -m 5 http://127.0.0.1:30081/v2/health/live >/dev/null 2>&1 \
   || curl -sf -m 5 http://127.0.0.1:30081 >/dev/null 2>&1; then
    echo "FAIL  local LLM NIM :30081 must be ABSENT — a local LLM NIM is running (stop it; generation is remote via the shim — 02)" >&2
    FAILURES=$((FAILURES + 1))
else
    echo "PASS  local LLM NIM :30081 absent (LLM is remote — as required)"
fi

# the six lab NIMs: containers running (their Triton health surfaces are
# vendor-internal; the L5 checklist confirms the healthy markers in
# docker ps on the VM)
# resolve by SERVICE name via Compose — container names carry the project
# prefix, which is derived from the compose file's directory, not ours to assume.
for svc in nemotron-embedding-ms nemotron-ranking-ms \
           page-elements graphic-elements table-structure nemotron-ocr; do
    cid=$(docker compose -f "$RAG_DIR/deploy/compose/nims.yaml" ps -q "$svc" 2>/dev/null | head -1 || true)
    if [ -z "$cid" ]; then
        state="missing"
    else
        state=$(docker inspect --format '{{.State.Status}}' "$cid" 2>/dev/null) || state="missing"
    fi
    if [ "$state" = "running" ]; then
        echo "PASS  NIM $svc running"
    else
        echo "FAIL  NIM $svc is '$state', want running" >&2
        FAILURES=$((FAILURES + 1))
    fi
done

echo ""
echo "== nvidia-smi VRAM measurement (recorded — the L5 checklist judges it) =="
if ! command -v nvidia-smi >/dev/null 2>&1; then
    fail "nvidia-smi not found — this script runs on the learner VM (GPU present)"
fi
VRAM_LINE=$(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits | head -1)
echo "GPU memory (MiB): $VRAM_LINE"
APPS_TABLE=$(nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits)
echo "compute apps (pid, MiB):"
echo "${APPS_TABLE:-<none>}"

log ""
log "## $(date -u +%Y-%m-%dT%H:%M:%SZ) — 30-verify-stack: health gate + VRAM (VM $(hostname 2>/dev/null || echo unknown))"
log "- gpu memory used/total (MiB): $VRAM_LINE"
if [ -n "${APPS_TABLE:-}" ]; then
    while IFS= read -r line; do
        log "- compute app: $line"
    done <<< "$APPS_TABLE"
fi
log "  (L5 judgment, 05: VLM VRAM ~38 GB not ~86 GB; six NIMs; 7 compute"
log "   processes <= 80 GB total; this measurement is the evidence)"

[ "$FAILURES" = "0" ] \
    || fail "$FAILURES probe(s) failed — the stack is not ready (fix and re-run)"
echo "30-verify-stack: PASS — all probes green; VRAM recorded in $(basename "$PREP_LOG")"
