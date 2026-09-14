#!/usr/bin/env bash
# 10-clone-blueprints.sh — tag-pinned blueprint clones with SHA recording
# (03 layout; 09 "Exact images & versions"; 04 supply-chain hygiene).
#
# Run on the learner vCD VM, after 00-host-prep.sh and before 20-start.sh.
#
#   VSS v3.2.1 -> ~/vss-public   (09; agent image VSS_AGENT_VERSION=3.2.1)
#   RAG v2.6.2 -> /data/rag      (09; no fallback remains — 08 item 3)
#   NemoClaw v0.0.118 -> ~/NemoClaw (01 pin; the VSS init_nemoclaw.sh runs
#     <dir>/install.sh from there — 2026-09-10 dry-run: "install.sh is not
#     available" without the checkout; build doc 9.1's "one command" claim
#     presumes it exists)
#
# The resolved commit SHAs, the actual LVS .env path (it moves between
# releases — 02), and the vendor files the later scripts rely on are
# recorded to prep-log.md. An existing checkout at the wrong tag is a
# STOP, not an auto-delete (instructor intervention).
set -euo pipefail

VSS_DIR="${VSS_DIR:-$HOME/vss-public}"
RAG_DIR="${RAG_DIR:-/data/rag}"
VSS_URL="https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization.git"
RAG_URL="https://github.com/NVIDIA-AI-Blueprints/rag.git"
VSS_TAG="v3.2.1"
RAG_TAG="v2.6.2"
NEMOCLAW_DIR="${NEMOCLAW_DIR:-$HOME/NemoClaw}"
NEMOCLAW_URL="https://github.com/NVIDIA/NemoClaw.git"
NEMOCLAW_TAG="v0.0.118"

PREP_LOG="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/prep-log.md"
log() { printf '%s\n' "$*" >> "$PREP_LOG"; }
fail() { echo "10-clone-blueprints: FAIL — $*" >&2; exit 1; }

log ""
log "## $(date -u +%Y-%m-%dT%H:%M:%SZ) — 10-clone-blueprints: tag-pinned clones"

clone_pinned() {
    # clone_pinned <dir> <url> <tag>
    # stdout is the RESOLVED SHA and nothing else — every progress line
    # here goes to stderr, or it lands in the caller's $(...) capture.
    local dir="$1" url="$2" tag="$3" sha
    if [ -d "$dir/.git" ]; then
        local cur
        cur=$(git -C "$dir" describe --tags --exact-match 2>/dev/null) || cur="<unknown tag>"
        [ "$cur" = "$tag" ] \
            || fail "$dir exists but is at $cur, want $tag — manual intervention (do not auto-delete a learner clone)"
        echo "reusing existing $dir at $tag" >&2
    elif [ -e "$dir" ]; then
        fail "$dir exists and is not a git checkout — manual intervention"
    else
        echo "cloning $tag -> $dir" >&2
        git clone --branch "$tag" --depth 1 "$url" "$dir"
    fi
    sha=$(git -C "$dir" rev-parse HEAD)
    log "- clone $dir: tag $tag, SHA $sha"
    printf '%s\n' "$sha"
}

echo "== VSS $VSS_TAG -> $VSS_DIR =="
VSS_SHA=$(clone_pinned "$VSS_DIR" "$VSS_URL" "$VSS_TAG")

echo "== RAG $RAG_TAG -> $RAG_DIR =="
RAG_SHA=$(clone_pinned "$RAG_DIR" "$RAG_URL" "$RAG_TAG")

echo "== NemoClaw $NEMOCLAW_TAG -> $NEMOCLAW_DIR =="
# the vendor's init_nemoclaw.sh (VSS repo) defaults NEMOCLAW_REPO_DIR to
# $HOME/NemoClaw and runs ./install.sh from there — the checkout is a
# pre-condition of the 40-nemoclaw.sh step (2026-09-10 dry-run finding).
NEMOCLAW_SHA=$(clone_pinned "$NEMOCLAW_DIR" "$NEMOCLAW_URL" "$NEMOCLAW_TAG")

echo "== recording the vendor facts the later scripts rely on =="

# VSS: the LVS .env path MOVES between releases (02/08) — locate it now and
# record the actual.
LVS_ENV=$(cd "$VSS_DIR" && find . -name '.env' -path '*lvs*' | head -1)
[ -n "$LVS_ENV" ] || fail "no LVS .env under $VSS_DIR (expected: find . -name '.env' -path '*lvs*')"
log "- VSS LVS .env (actual at $VSS_TAG): $LVS_ENV"

[ -f "$VSS_DIR/deploy/docker/scripts/dev-profile.sh" ] \
    || fail "dev-profile.sh not found in $VSS_DIR (20-start.sh step 2 needs it)"
[ -f "$VSS_DIR/deploy/docker/scripts/nemoclaw/init_nemoclaw.sh" ] \
    || fail "init_nemoclaw.sh not found in $VSS_DIR (40-nemoclaw.sh needs it)"
[ -f "$NEMOCLAW_DIR/install.sh" ] \
    || fail "NemoClaw install.sh not found in $NEMOCLAW_DIR (init_nemoclaw.sh runs it from the checkout)"
[ -d "$VSS_DIR/deploy/docker/developer-profiles/dev-profile-lvs/vss-agent/configs" ] \
    || fail "VSS vss-agent configs dir not found (vendor ships config_rag.yml with frag registered — 20-start.sh verifies it and points the agent at it)"
log "- VSS: dev-profile.sh, init_nemoclaw.sh, vss-agent configs dir all present at $VSS_TAG"

AGENT_VER=$(grep -m1 '^VSS_AGENT_VERSION=' "$VSS_DIR/$LVS_ENV" | cut -d= -f2- | tr -d "'\"" || true)
[ -n "$AGENT_VER" ] \
    || fail "VSS_AGENT_VERSION not found in $VSS_DIR/$LVS_ENV (vendor .env layout moved? record and adapt)"
log "- VSS agent image default at $VSS_TAG: VSS_AGENT_VERSION=$AGENT_VER"
# the agent image tag is ASSUMED to track the release tag (08 item 2) —
# existence on nvcr.io is verified at prep and recorded here:
if docker manifest inspect "nvcr.io/nvidia/vss-agent:${AGENT_VER}" >/dev/null 2>&1; then
    log "- VSS agent image nvcr.io/nvidia/vss-agent:$AGENT_VER: tag exists on nvcr.io"
else
    log "  PREP FINDING: nvcr.io/nvidia/vss-agent:$AGENT_VER not resolvable from this VM"
    log "  (network scope or tag-name assumption wrong — 08 item 2; verify manually"
    log "   against the $VSS_TAG release compose and record the actual value)"
fi

# RAG: the in-tree docs are authoritative for the exact compose invocation
# (09) — verify they and the compose files the scripts use are present.
for f in docs/deploy-docker-self-hosted.md \
         deploy/compose/nims.yaml \
         deploy/compose/vectordb.yaml \
         deploy/compose/docker-compose-ingestor-server.yaml \
         deploy/compose/docker-compose-rag-server.yaml; do
    [ -f "$RAG_DIR/$f" ] || fail "RAG $f not found at $RAG_TAG (vendor layout moved? record and adapt)"
done
ES_IMAGE=$(grep -oE 'docker\.elastic\.co/elasticsearch/elasticsearch:[0-9.]+' \
    "$RAG_DIR/deploy/compose/vectordb.yaml" | head -1 || true)
ES_IMAGE="${ES_IMAGE:-<not found — record as a prep finding>}"
log "- RAG: in-tree docs + the four compose files used by 20-start.sh/25-ingest present at $RAG_TAG"
log "- RAG Elasticsearch (actual at $RAG_TAG): $ES_IMAGE (expected docker.elastic.co/elasticsearch/elasticsearch:9.3.0 — 09; a mismatch is a prep finding)"

echo "10-clone-blueprints: PASS — SHAs recorded in $(basename "$PREP_LOG") (VSS $VSS_SHA, RAG $RAG_SHA, NemoClaw $NEMOCLAW_SHA)"
