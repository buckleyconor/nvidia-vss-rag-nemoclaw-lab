#!/usr/bin/env bash
# 25-ingest-corpus.sh — prep-time corpus ingest (03 layout; 02 interface
# contract: POST :8082/v1/documents, multipart documents=@file +
# data={"collection_name":"demo_corpus"}).
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

echo "== ingesting into collection '$COLLECTION' =="
COUNT=0
FAILED=""
while IFS= read -r file; do
    COUNT=$((COUNT + 1))
    if curl -sf -m 600 \
        -X POST "$INGESTOR_URL/v1/documents" \
        -F "documents=@$file" \
        -F "data={\"collection_name\":\"$COLLECTION\"}" >/dev/null; then
        echo "ok: $(basename "$file")"
    else
        echo "25-ingest-corpus: WARNING — $file did not return 2xx (re-run this script after fixing the cause; re-ingest is a prep-time action)" >&2
        FAILED="$FAILED $(basename "$file")"
    fi
done <<< "$FILES"

log ""
log "## $(date -u +%Y-%m-%dT%H:%M:%SZ) — 25-ingest-corpus: collection $COLLECTION"
log "- documents ingested: $COUNT from $CORPUS_DIR (prep-time only — 01/05)"
[ -n "$FAILED" ] || log "- all $COUNT documents returned 2xx"
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
