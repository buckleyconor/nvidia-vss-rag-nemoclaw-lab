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
MODEL_ID="nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4"
# 2026-09-07 dev-VM finding (recorded in prep-log.md): the shared endpoint
# serves the NVFP4 build under this vLLM id — not the owner-confirmed
# NVIDIA/Nemotron-3.5-Lightning-30B-A3B (spec/08). Recorded reality wins;
# the platform-side alias question is open.
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
    echo "  STEP 5/5  NemoClaw sandbox         (40-nemoclaw.sh: init_nemoclaw.sh with config/nemoclaw.env; gate: openclaw nemoclaw status shows the custom endpoint + Nemotron-3.5-Lightning)"
    echo "  HARDEN    reboot resilience        (50-resilience.sh: restart policies, boot NemoClaw repair, 5-min health watch; idempotent)"
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
echo "starting mock-wo (compose/mock-wo.yml; outbound clients from config/mock-wo.env — operator-dashboard O2/O22)"
# mock-wo's outbound client config (wake hook via the lab hook relay, VSS
# agent :8000, VST :30888 — values verified per VM, 2026-09-13). Real file
# is gitignored (04); the template config/mock-wo.env.example carries the
# placeholders. Absent = the clients stay disabled and the dashboard
# reports visible errors (spec: silence reads as breakage), so no fail here.
if [ -f "$REPO_ROOT/config/mock-wo.env" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$REPO_ROOT/config/mock-wo.env"
    set +a
fi
# The wake hook (O2) is lab-derived, never taken from mock-wo.env, so it is
# exported AFTER the source above:
#  - URL: the hook relay binds the demo-net bridge gateway (created by the
#    shim compose just above). host.docker.internal would resolve to docker0,
#    where the relay does not listen; the subnet is Docker-assigned, so it is
#    read from the network rather than hardcoded.
#  - token: lab-generated once (the relay reads the same file). Not the
#    sandbox gateway token, so a tier-3 clean re-onboard cannot invalidate it.
DEMO_NET_GW=$(docker network inspect demo-net --format '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true)
[ -n "$DEMO_NET_GW" ] || fail "could not read the demo-net gateway IP (docker network inspect demo-net) — the shim compose creates it"
HOOK_TOKEN_FILE="${LAB_HOOK_TOKEN_FILE:-/root/.config/lab/nemoclaw-hook-token}"
install -d -m 700 "$(dirname "$HOOK_TOKEN_FILE")"
if [ ! -s "$HOOK_TOKEN_FILE" ]; then
    ( umask 077; python3 -c 'import secrets; print(secrets.token_hex(32))' > "$HOOK_TOKEN_FILE" )
fi
OPENCLAW_HOOK_URL="http://${DEMO_NET_GW}:18790"
OPENCLAW_HOOK_TOKEN="$(cat "$HOOK_TOKEN_FILE")"
export OPENCLAW_HOOK_URL OPENCLAW_HOOK_TOKEN
echo "wake hook: relay at $OPENCLAW_HOOK_URL (token from $HOOK_TOKEN_FILE — value never printed)"
docker compose -f compose/mock-wo.yml up -d >/dev/null
# The shared endpoint has shown transient slow/hung windows on the dev VM
# (2026-09-07, prep-log finding): a 120 s budget failed twice while the
# endpoint recovered seconds later. 90x5 s mirrors the step-3 RT-VLM
# tolerance (02: external slow starts are normal); platform to stabilize.
SHIM_OK=""
for _ in $(seq 1 90); do
    if curl -sf http://127.0.0.1:8080/v1/models -H 'Authorization: Bearer dummy' 2>/dev/null \
        | grep -qF "$MODEL_ID"; then
        SHIM_OK=1
        break
    fi
    sleep 5
done
[ -n "$SHIM_OK" ] \
    || fail "shim gate failed: GET :8080/v1/models does not list $MODEL_ID (stop — every later phase depends on it, build doc Phase 1)"
# streaming gate (02 step 1; 09 L5 item 1): tokens must arrive incrementally
# through the shim (proxy_buffering off), not as one blob. Three attempts —
# the same transient endpoint slowness the model gate above tolerates.
STREAM_OK=""
for _ in 1 2 3; do
    if STREAM_OUT=$(python3 "$REPO_ROOT/scripts/prep/shim-stream-check.py" "$MODEL_ID" 2>&1); then
        STREAM_OK=1
        break
    fi
    echo "shim streaming check: $STREAM_OUT — retrying in 10 s"
    sleep 10
done
[ -n "$STREAM_OK" ] \
    || fail "shim streaming gate failed: $STREAM_OUT (the shim must stream SSE incrementally — proxy_buffering off, build doc Phase 1)"
echo "gate ok: shim streaming ($STREAM_OUT)"
wait_http 30 5 10 "http://127.0.0.1:8090/health"
wait_http 30 5 10 "http://127.0.0.1:8091/health"
log "- 20-start step 1: auth-shim up (model $MODEL_ID listed via :8080; streaming: $STREAM_OUT), mock-wo up (agent :8090/health ok, operator dashboard :8091/health ok; wake hook $OPENCLAW_HOOK_URL)"

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
        # inline comments are shell syntax, not value syntax — the learner
        # copies lvs.env.example verbatim and its LLM_MODE line carries one
        value = re.split(r"\s+#", value.strip(), 1)[0].strip()
        upsert(key.strip(), value)

# the three API keys: lab.env -> VSS .env at start (04); never in the repo
for key in ("NGC_CLI_API_KEY", "NVIDIA_API_KEY", "RAG_API_KEY"):
    value = os.environ.get(key, "")
    if value:
        upsert(key, f"'{value}'")

with open(lvs_path, "w") as f:
    f.write("\n".join(lines) + "\n")
PY
# VSS v3.2.1 ships config_rag.yml (frag_retrieval registered) beside config.yml
# — use it, never overwrite it. (2026-09-14 review #16/#17: the old repo stub
# replaced the vendor's 424-line config, and dev-profile.sh:1181 forced
# config.yml — frag OFF — into generated.env anyway.)
AGENT_RAG_CONFIG="$LVS_DIR/vss-agent/configs/config_rag.yml"
[ -f "$AGENT_RAG_CONFIG" ] || fail "vendor config_rag.yml missing at $AGENT_RAG_CONFIG (layout moved?)"
grep -q '_type: knowledge_retrieval' "$AGENT_RAG_CONFIG" \
    || fail "vendor config_rag.yml does not register frag (_type: knowledge_retrieval)"
# dev-profile.sh:1181 forces VSS_AGENT_CONFIG_FILE=.../config.yml (frag OFF) into
# generated.env; process env beats --env-file in compose interpolation (same
# mechanism as the RTVI_VLLM_* exports below), so export the IN-CONTAINER path.
export VSS_AGENT_CONFIG_FILE="/vss-agent/deploy/docker/${LVS_DIR#"$VSS_DIR/deploy/docker/"}/vss-agent/configs/config_rag.yml"
LLM_MODE=$(grep -E '^LLM_MODE=' "$REPO_ROOT/config/lvs.env" | tail -1 | cut -d= -f2- | tr -d "'\"" | sed -E 's/[[:space:]]+#.*$//' || true)
# Hardware profile from the real lvs.env: the learner-VM default (10 c1,
# 2026-09-07 platform change) is the vGPU H100; different silicon overrides
# it in its own (gitignored) lvs.env — 2026-09-07 dev VM is a vGPU
# H100L-94C (~94 GB), same profile (prep-log finding).
HARDWARE_PROFILE=$(grep -E '^HARDWARE_PROFILE=' "$REPO_ROOT/config/lvs.env" | tail -1 | cut -d= -f2- | tr -d "'\"" | sed -E 's/[[:space:]]+#.*$//' || true)
[ -n "$HARDWARE_PROFILE" ] || HARDWARE_PROFILE="H100"  # learner default (10 c1, 2026-09-07 platform change); dev/dev-only hardware overrides via lvs.env
REMOTE_LLM=no
# --llm: the vendor's own escape hatch ("Pass --llm <model-name> to
# override") — its host-side model-list fetch of LLM_ENDPOINT_URL/v1/models
# cannot resolve the container name `auth-shim` from the host. The lab
# already verified the model at the shim gate (STEP 1), so pass the known
# id instead of re-discovering it.
VSS_ARGS=(up -p lvs -H "$HARDWARE_PROFILE" --llm "$MODEL_ID" --vlm-env-file "$REPO_ROOT/config/vlm.env")
if [ "$LLM_MODE" = "remote" ]; then
    # CLI equivalent of the .env LLM_MODE=remote (02 config contract — the
    # value is verified at prep; requires LLM_ENDPOINT_URL on the host).
    LLM_ENDPOINT_URL=$(grep -E '^LLM_ENDPOINT_URL=' "$REPO_ROOT/config/lvs.env" | tail -1 | cut -d= -f2- | tr -d "'\"" | sed -E 's/[[:space:]]+#.*$//' || true)
    [ -n "$LLM_ENDPOINT_URL" ] || fail "LLM_MODE=remote but LLM_ENDPOINT_URL missing from config/lvs.env"
    export LLM_ENDPOINT_URL
    VSS_ARGS+=(--use-remote-llm)
    REMOTE_LLM=yes
else
    # exact match is the contract (02): the lab never starts the local LLM
    # NIM — silently skipping --use-remote-llm would break the aha path
    # late in the run. A trailing inline comment (copied from
    # lvs.env.example) is the usual cause of a near-miss value.
    fail "LLM_MODE is '$LLM_MODE' in config/lvs.env, want exactly 'remote' — the lab never starts the local LLM NIM (02); check for a trailing comment on the LLM_MODE line"
fi
echo "starting VSS (dev-profile.sh up, profile lvs, hardware $HARDWARE_PROFILE, vlm-env-file config/vlm.env, remote LLM via shim: $REMOTE_LLM)"
DEV_PROFILE=$(find "$VSS_DIR" -type f -name dev-profile.sh | head -1)
[ -n "$DEV_PROFILE" ] \
    || fail "dev-profile.sh not found under $VSS_DIR (vendor layout moved? record and adapt — 02/08)"
cd "$(dirname "$DEV_PROFILE")/.."
# VLM budget pin — the vendor-supported RTVI_VLLM_* surface (rtvi-vlm-
# docker-compose.yml interpolates them into the vss-rtvi-vlm container
# env; the entrypoint defaults VLLM_GPU_MEMORY_UTILIZATION to 0.7 when
# empty — 2026-09-07 dry-run measured 62.8 GB and the six-NIM
# co-residency, 09 sizing, collapsed: three NIMs OOM-exited). 0.40 ≈ 38
# GB on the ~94 GB card. Compose interpolation precedence: process env
# > --env-file, so this export wins over the vendor's tier values (0.35
# default / get_rtvi_vllm_gpu_memory_utilization) in its generated.env.
# No max-model-len knob exists on this surface — the pool cap is what
# protects the budget (spec/08 finding; the NIM_PASSTHROUGH_ARGS key in
# config/vlm.env is not consumed by this release's RTVI VLM entrypoint).
export RTVI_VLLM_GPU_MEMORY_UTILIZATION=0.40
export RTVI_VLLM_MAX_NUM_SEQS=4
"$DEV_PROFILE" "${VSS_ARGS[@]}"
cd "$REPO_ROOT"
wait_http 90 10 30 "http://127.0.0.1:8000/health"
wait_http 90 10 30 "http://127.0.0.1:38111/v1/ready"
# frag gate: the serving process must be running the exported config_rag.yml —
# if dev-profile.sh's config.yml default won, beat 3 loses its RAG evidence
# (build-doc failure-mode row: "VSS answers ignore the corpus"). The image
# ships no sh/printenv; python3 is the entrypoint interpreter.
AGENT_CFG_RUNNING=$(docker exec vss-agent python3 -c 'import os;print(os.environ.get("VSS_AGENT_CONFIG_FILE",""))' 2>/dev/null || true)
[ "$AGENT_CFG_RUNNING" = "$VSS_AGENT_CONFIG_FILE" ] \
    || fail "vss-agent is not running config_rag.yml — frag is OFF (dev-profile.sh default won; running: $AGENT_CFG_RUNNING)"
log "- 20-start step 2: VSS up (agent :8000/health, LVS :38111/v1/ready; LLM_MODE=$LLM_MODE; HW=$HARDWARE_PROFILE; LVS .env at $LVS_ENV; agent config: $VSS_AGENT_CONFIG_FILE)"

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
# rag-override-*.yml (lab-owned, -f): the blueprint's host-port map assumes a
# standalone deployment; page-elements' 8000, ES's 9200 and rag-frontend's
# 8090 collide with the VSS agent, VSS ES and mock-wo (2026-09-07 dry-run
# finding). Internal RAG services are reached by container name on
# nvidia-rag — the host bindings are dropped, not remapped. One override
# per base file: a compose override may only declare services that exist in
# ITS base file (a phantom service with no image/build makes the merged
# project invalid).
docker compose -f deploy/compose/nims.yaml -f "$REPO_ROOT/compose/rag-override-nims.yml" up -d \
    nemotron-embedding-ms nemotron-ranking-ms \
    page-elements graphic-elements table-structure nemotron-ocr
echo "starting the vector DB (Elasticsearch is the default profile; Milvus is opt-in and costs a second GPU budget)"
docker compose -f deploy/compose/vectordb.yaml -f "$REPO_ROOT/compose/rag-override-vectordb.yml" up -d
echo "starting the ingestor (prep-time only — the learner never ingests)"
# rag-override-ingestor.yml: the ingestor's internal redis publishes host
# 6379 standalone, which the VSS stack's Redis owns in this lab.
docker compose -f deploy/compose/docker-compose-ingestor-server.yaml -f "$REPO_ROOT/compose/rag-override-ingestor.yml" up -d
echo "starting the RAG server (:8081)"
docker compose -f deploy/compose/docker-compose-rag-server.yaml -f "$REPO_ROOT/compose/rag-override-rag-server.yml" up -d
cd "$REPO_ROOT"
wait_http 60 10 30 "http://127.0.0.1:8081/v1/health"
wait_http 60 10 30 "http://127.0.0.1:8082/v1/health"
# Six NIMs HEALTHY (02 step 4), not merely running: a NIM still downloading
# or loading its model is 'running' but serves nothing, and the first real
# failure would otherwise surface in 25-ingest. nims.yaml defines a
# healthcheck per NIM; a container without one is judged on running.
# One shared deadline for all six — the first run downloads weights inside
# the containers (45-70 min, build doc Phase 2).
# Resolve each NIM by SERVICE name via Compose — container names carry the
# project prefix, which is derived from the compose file's directory and is
# not ours to assume.
NIM_SERVICES="nemotron-embedding-ms nemotron-ranking-ms page-elements graphic-elements table-structure nemotron-ocr"
NIM_READY_TIMEOUT="${NIM_READY_TIMEOUT:-5400}"
nim_state() {
    local cid
    cid=$(docker compose -f "$RAG_DIR/deploy/compose/nims.yaml" ps -aq "$1" 2>/dev/null | head -1 || true)
    [ -n "$cid" ] || { echo "missing"; return; }
    docker inspect --format '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null \
        || echo "missing"
}
nim_deadline=$(( $(date +%s) + NIM_READY_TIMEOUT ))
while :; do
    pending=""
    for svc in $NIM_SERVICES; do
        st=$(nim_state "$svc")
        case "$st" in
            running/healthy|running/none) ;;
            missing|exited/*|dead/*)
                fail "RAG gate failed: NIM service $svc is '$st' (six NIMs healthy — 02 step 4; docker logs for the cause — an OOM exit means the VLM budget pin did not hold)" ;;
            *) pending="$pending $svc($st)" ;;
        esac
    done
    [ -n "$pending" ] || break
    [ "$(date +%s)" -lt "$nim_deadline" ] \
        || fail "RAG gate failed: NIMs not healthy after ${NIM_READY_TIMEOUT}s:$pending (six NIMs healthy — 02 step 4)"
    echo "waiting for NIMs:$pending"
    sleep 15
done
echo "gate ok: six NIMs healthy"
wait_http 60 10 30 "http://127.0.0.1:8081/v1/health?check_dependencies=true"
log "- 20-start step 4: RAG up (:8081/v1/health?check_dependencies=true, :8082/v1/health; six NIMs healthy: $NIM_SERVICES; embedding endpoint = nemotron-embedding-ms per config/rag.env)"

# ---- STEP 5/5: NemoClaw sandbox ---------------------------------------------
echo ""
echo "== STEP 5/5  NemoClaw sandbox =="
bash "$REPO_ROOT/scripts/prep/40-nemoclaw.sh"
log "- 20-start step 5: NemoClaw sandbox ready (see the 40-nemoclaw section in prep-log.md)"

# ---- HARDEN: reboot resilience (09) ----------------------------------------
# Not a start-order step: this arms the zero-interaction recovery layer
# (restart policies, boot NemoClaw repair, the 5-min health-watch timer).
# Idempotent; safe to re-run any time.
echo ""
echo "== HARDEN  reboot resilience (50-resilience.sh) =="
bash "$REPO_ROOT/scripts/prep/50-resilience.sh"
log "- 20-start harden: reboot resilience armed (see the 50-resilience section in prep-log.md)"

echo "20-start: PASS — all five steps complete; run scripts/prep/25-ingest-corpus.sh, then 30-verify-stack.sh"
