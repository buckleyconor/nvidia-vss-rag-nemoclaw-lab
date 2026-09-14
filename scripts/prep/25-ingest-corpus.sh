#!/usr/bin/env bash
# 25-ingest-corpus.sh — prep-time corpus ingest (03 layout; 02 interface
# contract: :8082/v1/documents, multipart documents=@file +
# data={"collection_name":"demo_corpus"}; rework 2026-09-14 #18/#12: PATCH +
# blocking — v2.6.2 rejects POST re-uploads with "already exists" inside an
# HTTP 200 body (main.py:637) and returns 200 + task_id before a
# non-blocking upload runs (server.py:330); PATCH replaces existing docs).
#
# The ingestor raises "Collection ... does not exist" (HTTP 500, main.py:415)
# for a missing collection — on a fresh VM every upload failed (probe (b)
# 2026-09-14), so this script creates the collection if absent.
#
# Run on the learner vCD VM AFTER 20-start.sh (the RAG ingestor must be up)
# and BEFORE the learner session — the index is ready before the session;
# indexing is a non-goal and the learner never ingests (01/05).
#
# The corpus lives at /data/corpus (09 artifacts: manuals, logs, maintenance
# schedule — the content types beat 3 retrieves over). The collection name
# is demo_corpus = KNOWLEDGE_COLLECTION (02). Per-file results and the
# document count are recorded to prep-log.md (04: corpus ingest counts are
# ops-visibility, never fixture content).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CORPUS_DIR="${CORPUS_DIR:-/data/corpus}"
INGESTOR_URL="http://127.0.0.1:8082"
COLLECTION="demo_corpus"

PREP_LOG="$REPO_ROOT/prep-log.md"
log() { printf '%s\n' "$*" >> "$PREP_LOG"; }
fail() { echo "25-ingest-corpus: FAIL — $*" >&2; exit 1; }

[ -d "$CORPUS_DIR" ] || fail "corpus dir $CORPUS_DIR missing (00-host-prep.sh creates it; stage the lab's manuals/logs/schedule there — 09)"
FILES=$(find "$CORPUS_DIR" -maxdepth 1 -type f \( -name '*.pdf' -o -name '*.md' \) | sort)
[ -n "$FILES" ] || fail "no .pdf/.md files in $CORPUS_DIR — nothing to ingest"

echo "== ingestor health ($INGESTOR_URL) =="
curl -sf --retry 60 --retry-delay 10 --retry-all-errors -m 30 \
    "$INGESTOR_URL/v1/health?check_dependencies=true" >/dev/null \
    || fail "ingestor :8082/v1/health not 2xx within the retry budget (run 20-start.sh first)"
echo "ingestor up"

# create the collection if absent (idempotent; POST /v1/collection, 2026-09-14
# probe: missing collection => HTTP 500 "does not exist" on every upload)
if ! curl -sf -m 30 "$INGESTOR_URL/v1/collections" | grep -qF "\"$COLLECTION\""; then
    curl -sf -m 60 -X POST "$INGESTOR_URL/v1/collection" -H 'Content-Type: application/json' \
        -d "{\"collection_name\":\"$COLLECTION\"}" >/dev/null \
        || fail "could not create collection $COLLECTION (POST /v1/collection)"
    log "- created collection $COLLECTION"
    echo "created collection '$COLLECTION'"
fi

echo "== ingesting into collection '$COLLECTION' =="
COUNT=0
FAILED=""
while IFS= read -r file; do
    COUNT=$((COUNT + 1))
    # PATCH + blocking=true: the 2xx arrives only after ingestion is judged,
    # and an existing document is replaced (re-runs are idempotent — probe
    # (d) 2026-09-14: a POST re-upload is HTTP 200 with "already exists" in
    # failed_documents, so a 2xx check alone cannot judge the upload).
    if RESP=$(curl -sf -m 900 \
        -X PATCH "$INGESTOR_URL/v1/documents" \
        -F "documents=@$file" \
        -F "data={\"collection_name\":\"$COLLECTION\",\"blocking\":true}") \
        && python3 -c 'import json,sys; r=json.loads(sys.argv[1]); sys.exit(1 if r.get("failed_documents") or r.get("validation_errors") else 0)' "$RESP"; then
        echo "ok: $(basename "$file")"
    else
        if [ -n "${RESP:-}" ]; then printf '%s\n' "${RESP:0:500}" >&2; fi
        echo "25-ingest-corpus: WARNING — $file did not ingest (re-run this script after fixing the cause; PATCH makes re-runs replace, not duplicate)" >&2
        FAILED="$FAILED $(basename "$file")"
    fi
done <<< "$FILES"

log ""
log "## $(date -u +%Y-%m-%dT%H:%M:%SZ) — 25-ingest-corpus: collection $COLLECTION"
log "- documents ingested: $COUNT from $CORPUS_DIR (prep-time only — 01/05)"
[ -n "$FAILED" ] || log "- all $COUNT documents ingested (PATCH, blocking=true, failed_documents empty)"
if [ -n "$FAILED" ]; then
    log "  PREP FINDING: documents NOT ingested:$FAILED"
fi
log "- collection name: $COLLECTION (= KNOWLEDGE_COLLECTION, 02)"
log "  (the pre-built RAG index artifact slot in fixtures/rag-index/ is the"
log "   optional fast path — its restore format is prep-defined, 08)"

if [ -n "$FAILED" ]; then
    fail "one or more documents failed to ingest:$FAILED"
fi
echo "25-ingest-corpus: PASS — $COUNT documents in collection '$COLLECTION' (index ready before the session)"
