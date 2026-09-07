#!/usr/bin/env bash
# 20-start.sh — the start-order orchestrator (02 start-order table,
# non-negotiable; 03 "Start-order script contract").
#
# The VLM must profile an EMPTY GPU first: a greedy container profiling the
# GPU before it breaks the co-residency budget (build-doc failure mode).
# The order is therefore, always:
#   shim+mock-wo -> VSS -> RT-VLM gate -> RAG -> NemoClaw
#
# Modes:
#   --dry-run   print the ordered plan and exit 0 WITHOUT touching Docker,
#               lab.env or the cloned repos (the dev-machine contract —
#               05 TC-040; the dev gate asserts exactly this).
#   (real)      execute the five steps in order, blocking at the RT-VLM gate
#               (the exact 02 command); exits non-zero on any gate failure.
#               Progress is appended to prep-log.md — never keys (04).
#
# Prerequisites (real run): 00-host-prep.sh and 10-clone-blueprints.sh done;
# a real config/lvs.env generated from config/lvs.env.example (placeholders
# filled, secrets injected — the real file is gitignored, 04); lab.env at
# ~/.config/vss/lab.env with the instructor's keys + SHARED_ENDPOINT_URL.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# every relative path below (mock-wo/, compose/) is repo-root relative, and
# the steps `cd "$REPO_ROOT"` to return here — so start there regardless of
# where the script was invoked from.
cd "$REPO_ROOT"
LAB_ENV="${LAB_ENV:-$HOME/.config/vss/lab.env}"
VSS_DIR="${VSS_DIR:-$HOME/vss-public}"
RAG_DIR="${RAG_DIR:-/data/rag}"
PREP_LOG="$REPO_ROOT/prep-log.md"
MODEL_ID="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
DRY_RUN=0

usage() {
    cat <<'EOF'
Usage: 20-start.sh [--dry-run]
  (real)    start shim+mock-wo, VSS, wait for the RT-VLM gate, RAG, NemoClaw
  --dry-run print the ordered start plan and exit 0 (no Docker invocation)
EOF
}

fail() { echo "20-start: FAIL — $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; fail "unknown argument: $1" ;;
    esac
    shift
done

# The ordered plan — one testable source of truth for the non-negotiable
# order (03: "keep the non-negotiable ordering in one testable place
# instead of in prose"). The STEP labels are asserted by tests/
# test_start_order.py (TC-040).
plan() {
    echo "20-start: start order (02 table, non-negotiable):"
    echo "  STEP 1/5  auth-shim + mock-wo      (gate: :8080/v1/models lists the model; :8090/health ok — mock-wo is CPU-only, deliberately started with the shim so the CMMS UI is visibly empty before beats 1-2)"
    echo "  STEP 2/5  VSS stack                (the VLM claims 40% of the EMPTY GPU; gate: agent :8000/health, LVS :38111/v1/ready)"
    echo "  STEP 3/5  RT-VLM ready gate        (curl --retry 90 --retry-delay 10 --retry-all-errors http://127.0.0.1:8018/v1/health/ready — NIM load 5-15 min; VLM VRAM ~38 GB, not ~86 GB)"
    echo "  STEP 4/5  RAG stack                (the lab's six retrieval NIMs, never the LLM NIM; gate: :8081/v1/health, :8082/v1/health, six NIM containers running)"
    echo "  STEP 5/5  NemoClaw sandbox         (40-nemoclaw.sh: init_nemoclaw.sh with config/nemoclaw.env; gate: openclaw nemoclaw status shows the custom endpoint + Nano Omni)"
}

if [ "$DRY_RUN" = "1" ]; then
    plan
    echo "20-start: --dry-run: plan printed; no Docker invoked; exiting 0."
    exit 0
fi

# ---------------------------------------------------------------------------
# real run
# ---------------------------------------------------------------------------
log() { printf '%s\n' "$*" >> "$PREP_LOG"; }
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# wait_http <retries> <delay-s> <timeout-per-try-s> <url>
wait_http() {
    local retries="$1" delay="$2" tmo="$3" url="$4"
    curl -sf --retry "$retries" --retry-delay "$delay" \
         --retry-all-errors -m "$tmo" "$url" >/dev/null \
        || fail "gate failed: $url did not answer 2xx within the retry budget"
    echo "gate ok: $url"
}

[ -f "$LAB_ENV" ] || fail "lab.env not found at $LAB_ENV (instructor-injected — 04)"
set -a
# shellcheck disable=SC1090
. "$LAB_ENV"
set +a
[ -n "${NGC_CLI_API_KEY:-}" ] || fail "NGC_CLI_API_KEY empty in $LAB_ENV"
[ -n "${SHARED_API_KEY:-}" ] || fail "SHARED_API_KEY empty in $LAB_ENV"
[ -n "${SHARED_ENDPOINT_URL:-}" ] || fail "SHARED_ENDPOINT_URL empty in $LAB_ENV"
command -v docker >/dev/null 2>&1 || fail "docker CLI not found (run 00-host-prep.sh first)"
docker info >/dev/null 2>&1 || fail "docker daemon not reachable (run 00-host-prep.sh first)"

echo "20-start: real run — recorded in $(basename "$PREP_LOG")"
log ""
log "## $(now) — 20-start: start order (real run, VM $(hostname 2>/dev/null || echo unknown))"

# ---- STEP 1/5: auth-shim + mock-wo ----------------------------------------
echo ""
echo "== STEP 1/5  auth-shim + mock-wo =="
echo "building mock-wo:lab on the VM (arch check for x86 — 03/05)"
docker build -t mock-wo:lab -f mock-wo/Dockerfile mock-wo >/dev/null
echo "starting auth-shim (compose/docker-compose.shim.yml, env from $LAB_ENV — values never printed)"
# lab.env was sourced with `set -a` above, so SHARED_* are already exported
# and Compose picks them up from the environment. Deliberately NOT
# --env-file: that re-parses lab.env with Compose's KEY=VAL parser, which
# reads `export FOO=bar` as a key named "export FOO" and strips quotes
# differently from the shell that sources the same file.
docker compose -f compose/docker-compose.shim.yml up -d >/dev/null
echo "starting mock-wo (compose/mock-wo.yml)"
docker compose -f compose/mock-wo.yml up -d >/dev/null
SHIM_OK=""
for _ in $(seq 1 60); do
    if curl -sf http://127.0.0.1:8080/v1/models -H 'Authorization: Bearer dummy' 2>/dev/null \
        | grep -qF "$MODEL_ID"; then
        SHIM_OK=1
        break
    fi
    sleep 2
done
[ -n "$SHIM_OK" ] \
    || fail "shim gate failed: GET :8080/v1/models does not list $MODEL_ID (stop — every later phase depends on it, build doc Phase 1)"
wait_http 30 5 10 "http://127.0.0.1:8090/health"
log "- 20-start step 1: auth-shim up (model $MODEL_ID listed via :8080), mock-wo up (:8090/health ok)"

# ---- STEP 2/5: VSS (VLM claims 40% of the EMPTY GPU) -----------------------
echo ""
echo "== STEP 2/5  VSS stack =="
[ -d "$VSS_DIR" ] || fail "VSS repo missing at $VSS_DIR — run 10-clone-blueprints.sh first"
[ -f "$REPO_ROOT/config/lvs.env" ] \
    || fail "config/lvs.env missing — generate the real file from config/lvs.env.example (fill placeholders; keys injected; never commit it — 04)"
if grep -q '<PLACEHOLDER' "$REPO_ROOT/config/lvs.env"; then
    fail "config/lvs.env still carries <PLACEHOLDER> values — fill them before starting (04)"
fi
LVS_ENV=$(cd "$VSS_DIR" && find . -name '.env' -path '*lvs*' | head -1)
[ -n "$LVS_ENV" ] \
    || fail "no LVS .env under $VSS_DIR (expected: find . -name '.env' -path '*lvs*' — 02)"
LVS_ENV="$VSS_DIR/${LVS_ENV#./}"
LVS_DIR="$(dirname "$LVS_ENV")"
echo "applying the repo LVS .env overlay to $LVS_ENV (values + the three API keys from lab.env)"
python3 - "$LVS_ENV" "$REPO_ROOT/config/lvs.env" <<'PY'
import os
import re
import sys

lvs_path, overlay_path = sys.argv[1], sys.argv[2]
with open(lvs_path) as f:
    lines = f.read().splitlines()

def upsert(key, value):
    key_re = re.compile(rf"^{re.escape(key)}=")
    entry = f"{key}={value}"
    for i, ln in enumerate(lines):
        if key_re.match(ln):
            lines[i] = entry
            return
    lines.append(entry)

with open(overlay_path) as f:
    for raw in f:
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        key, _, value = s.partition("=")
        upsert(key.strip(), value.strip())

# the three API keys: lab.env -> VSS .env at start (04); never in the repo
for key in ("NGC_CLI_API_KEY", "NVIDIA_API_KEY", "RAG_API_KEY"):
    value = os.environ.get(key, "")
    if value:
        upsert(key, f"'{value}'")

with open(lvs_path, "w") as f:
    f.write("\n".join(lines) + "\n")
PY
# the repo's frag-enabling agent config (02: VSS_AGENT_CONFIG_FILE ->
# config_rag.yml; the default config.yml has frag OFF). Prep verifies the
# content against the release's copy and records any diff (08).
install -Dm 644 "$REPO_ROOT/config/config_rag.yml" \
    "$LVS_DIR/vss-agent/configs/config_rag.yml"
LLM_MODE=$(grep -E '^LLM_MODE=' "$REPO_ROOT/config/lvs.env" | tail -1 | cut -d= -f2- | tr -d "'\"" || true)
REMOTE_LLM=no
VSS_ARGS=(up -p lvs -H RTXPRO6000BW --vlm-env-file "$REPO_ROOT/config/vlm.env")
if [ "$LLM_MODE" = "remote" ]; then
    # CLI equivalent of the .env LLM_MODE=remote (02 config contract — the
    # value is verified at prep; requires LLM_ENDPOINT_URL on the host).
    LLM_ENDPOINT_URL=$(grep -E '^LLM_ENDPOINT_URL=' "$REPO_ROOT/config/lvs.env" | tail -1 | cut -d= -f2- | tr -d "'\"" || true)
    [ -n "$LLM_ENDPOINT_URL" ] || fail "LLM_MODE=remote but LLM_ENDPOINT_URL missing from config/lvs.env"
    export LLM_ENDPOINT_URL
    VSS_ARGS+=(--use-remote-llm)
    REMOTE_LLM=yes
fi
echo "starting VSS (dev-profile.sh up, profile lvs, hardware RTXPRO6000BW, vlm-env-file config/vlm.env, remote LLM via shim: $REMOTE_LLM)"
DEV_PROFILE=$(find "$VSS_DIR" -type f -name dev-profile.sh | head -1)
[ -n "$DEV_PROFILE" ] \
    || fail "dev-profile.sh not found under $VSS_DIR (vendor layout moved? record and adapt — 02/08)"
cd "$(dirname "$DEV_PROFILE")/.."
"$DEV_PROFILE" "${VSS_ARGS[@]}"
cd "$REPO_ROOT"
wait_http 90 10 30 "http://127.0.0.1:8000/health"
wait_http 90 10 30 "http://127.0.0.1:38111/v1/ready"
log "- 20-start step 2: VSS up (agent :8000/health, LVS :38111/v1/ready; LLM_MODE=$LLM_MODE; LVS .env at $LVS_ENV)"

# ---- STEP 3/5: RT-VLM ready gate (the exact 02 command) --------------------
echo ""
echo "== STEP 3/5  RT-VLM ready gate (blocks until the VLM is ready; NIM load 5-15 min) =="
curl --retry 90 --retry-delay 10 --retry-all-errors -sf \
    http://127.0.0.1:8018/v1/health/ready >/dev/null \
    || fail "RT-VLM gate failed after 90x10 s retries — the VLM never became ready; STOP (do not start the RAG stack before the gate, 02)"
echo "gate ok: http://127.0.0.1:8018/v1/health/ready"
log "- 20-start step 3: RT-VLM gate passed at $(now) (curl --retry 90 --retry-delay 10 --retry-all-errors :8018/v1/health/ready)"
log "  (VLM VRAM measurement ~38 GB — not ~86 GB — is the L5 item in 30-verify-stack.sh / prep-log)"

# ---- STEP 4/5: RAG stack ----------------------------------------------------
echo ""
echo "== STEP 4/5  RAG stack =="
[ -d "$RAG_DIR" ] || fail "RAG repo missing at $RAG_DIR — run 10-clone-blueprints.sh first"
cd "$RAG_DIR"
# the repo's APP_* contract (config/rag.env) + NGC_API_KEY for the NIMs.
# Deliberately NOT sourcing the blueprint's deploy/compose/.env: it points
# the embedding endpoint at the vlm-embedding NIM, which the lab never
# starts (see the APP_EMBEDDINGS_SERVERURL note in config/rag.env).
set -a
# shellcheck disable=SC1090
. "$REPO_ROOT/config/rag.env"
set +a
export NGC_API_KEY="$NGC_CLI_API_KEY"
USERID="$(id -u)"
export USERID
echo "starting the lab's six retrieval NIMs (explicit service names — the LLM NIM is NEVER started; the :30081-absent invariant, 02/09)"
echo "first run pulls NIM images + weights: budget 45-70 min (build doc Phase 2)"
docker compose -f deploy/compose/nims.yaml up -d \
    nemotron-embedding-ms nemotron-ranking-ms \
    page-elements graphic-elements table-structure nemotron-ocr
echo "starting the vector DB (Elasticsearch is the default profile; Milvus is opt-in and costs a second GPU budget)"
docker compose -f deploy/compose/vectordb.yaml up -d
echo "starting the ingestor (prep-time only — the learner never ingests)"
docker compose -f deploy/compose/docker-compose-ingestor-server.yaml up -d
echo "starting the RAG server (:8081)"
docker compose -f deploy/compose/docker-compose-rag-server.yaml up -d
cd "$REPO_ROOT"
wait_http 60 10 30 "http://127.0.0.1:8081/v1/health"
wait_http 60 10 30 "http://127.0.0.1:8082/v1/health"
# resolve each NIM by SERVICE name via Compose — container names carry the
# project prefix, which is derived from the compose file's directory and is
# not ours to assume.
for svc in nemotron-embedding-ms nemotron-ranking-ms \
           page-elements graphic-elements table-structure nemotron-ocr; do
    cid=$(docker compose -f "$RAG_DIR/deploy/compose/nims.yaml" ps -q "$svc" 2>/dev/null | head -1 || true)
    [ -n "$cid" ] \
        || fail "RAG gate failed: NIM service $svc has no container (six NIMs healthy — 02 step 4)"
    state=$(docker inspect --format '{{.State.Status}}' "$cid" 2>/dev/null) || state="missing"
    [ "$state" = "running" ] \
        || fail "RAG gate failed: NIM service $svc is '$state', want running (six NIMs healthy — 02 step 4)"
done
log "- 20-start step 4: RAG up (:8081/v1/health, :8082/v1/health; six NIM containers running: nemotron-embedding-ms, nemotron-ranking-ms, page-elements, graphic-elements, table-structure, nemotron-ocr; embedding endpoint = nemotron-embedding-ms per config/rag.env)"

# ---- STEP 5/5: NemoClaw sandbox ---------------------------------------------
echo ""
echo "== STEP 5/5  NemoClaw sandbox =="
bash "$REPO_ROOT/scripts/prep/40-nemoclaw.sh"
log "- 20-start step 5: NemoClaw sandbox ready (see the 40-nemoclaw section in prep-log.md)"

echo "20-start: PASS — all five steps complete; run scripts/prep/25-ingest-corpus.sh, then 30-verify-stack.sh"
