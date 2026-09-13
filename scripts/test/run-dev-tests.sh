#!/usr/bin/env bash
# scripts/test/run-dev-tests.sh — the dev gate (05-test-strategy.md):
# L0 + L1 + L3 + L4, run on the aarch64 dev machine (no GPU, no vendor
# NIMs, no x86 assumptions). Non-interactive and self-terminating.
#
#   1) python3 -m venv .venv   (recreated if missing)
#   2) .venv/bin/pip install -q -r mock-wo/requirements.txt -r mock-wo/requirements-dev.txt
#   3) .venv/bin/ruff check mock-wo/ tests/
#   4) .venv/bin/pytest mock-wo/tests tests -q --cov=mock-wo/app --cov-report=term-missing --cov-fail-under=90
#   5) bash -n + shellcheck on every scripts/**/*.sh (TC-039), and
#      `docker compose config` on every compose/*.yml
#
# The CLOSING gate also runs scripts/test/container-smoke.sh (L2) — the
# two commands of 05's "Runner and how tests run". Re-run both at
# environment prep on the VM (x86) — that re-run doubles as the
# target-architecture container check.
#
# Note on step 4: the 05 contract writes --cov=mock-wo.app. The dotted
# module form is not importable — the package is named `app` INSIDE
# mock-wo/ (the Dockerfile contract: python -m app.server), and
# `mock-wo.app` is not a valid module name (the hyphen). The path form
# --cov=mock-wo/app measures the same files (mock-wo/app/*.py) and
# enforces the same >= 90% line-coverage gate.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo "== 1/5 venv =="
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
    echo "created .venv"
else
    echo ".venv present"
fi

echo "== 2/5 pinned deps (03: exact pins, no latest) =="
.venv/bin/pip install -q -r mock-wo/requirements.txt -r mock-wo/requirements-dev.txt

echo "== 3/5 lint (ruff, mock-wo/ + tests/) =="
.venv/bin/ruff check mock-wo/ tests/

echo "== 4/5 pytest: L0+L1 (mock-wo) + L3+L4 (repo-level), coverage >= 90% on mock-wo/app =="
.venv/bin/pytest mock-wo/tests tests -q \
    --cov=mock-wo/app --cov-report=term-missing --cov-fail-under=90

echo "== 4b/5 operator dashboard UI: install from lockfile, typecheck, vitest, build (D6) =="
command -v npm >/dev/null 2>&1 \
    || { echo "run-dev-tests: FAIL — npm not found (Node 22 builds the operator dashboard UI)" >&2; exit 1; }
(
    cd mock-wo/ui
    npm ci --no-audit --no-fund --silent
    npm run --silent typecheck
    npm run --silent test
    npm run --silent build
)
echo "ui: typecheck, tests and build ok (bundle in mock-wo/app/ui_dist)"

echo "== 4c/5 OpenClaw telemetry plugin: typecheck, vitest, build (ADR-V09) =="
(
    cd openclaw/plugins/mock-wo-telemetry
    npm ci --no-audit --no-fund --silent
    npm run --silent typecheck
    npm run --silent test
    npm run --silent build
)
echo "plugin: typecheck, tests and build ok"

echo "== 5/5 script syntax + lint (TC-039: bash -n and shellcheck on every scripts/**/*.sh) =="
SCRIPT_COUNT=0
while IFS= read -r script; do
    bash -n "$script"
    SCRIPT_COUNT=$((SCRIPT_COUNT + 1))
done < <(find scripts -type f -name '*.sh' | sort)
echo "bash -n: $SCRIPT_COUNT script(s) clean"

# bash -n is syntax only: it cannot see an unbound variable, a redirect that
# runs before sudo, or a captured-stdout function. shellcheck can.
SHELLCHECK=""
if [ -x .venv/bin/shellcheck ]; then
    SHELLCHECK=.venv/bin/shellcheck
elif command -v shellcheck >/dev/null 2>&1; then
    SHELLCHECK=shellcheck
fi
if [ -n "$SHELLCHECK" ]; then
    # shellcheck disable=SC2046
    "$SHELLCHECK" -S warning $(find scripts -type f -name '*.sh' | sort)
    echo "shellcheck: clean at -S warning"
else
    echo "run-dev-tests: FAIL — shellcheck not found (pinned as shellcheck-py in mock-wo/requirements-dev.txt)" >&2
    exit 1
fi

echo "== 5b/5 compose projects validate (a service may not join an undeclared network) =="
if command -v docker >/dev/null 2>&1; then
    # rag-override-*.yml are NOT standalone projects: they are lab-owned
    # !override fragments applied via -f on the RAG blueprint's base files
    # at 20-start STEP 4. A service with only `ports: !override []` has no
    # image/build, so standalone validation is structurally impossible;
    # their contract is the MERGED project, validated below against the
    # base (where the RAG clone exists).
    for f in compose/*.yml; do
        case "$f" in
            compose/rag-override-*.yml) continue ;;
        esac
        SHARED_API_KEY=x SHARED_ENDPOINT_URL=http://u/v1 \
            docker compose -f "$f" config -q \
            || { echo "run-dev-tests: FAIL — $f is not a valid compose project" >&2; exit 1; }
        echo "compose config: $f ok"
    done
    RAG_DIR="${RAG_DIR:-/data/rag}"
    # override file | its base (relative to $RAG_DIR) — 20-start STEP 4
    OVERRIDE_BASE="
rag-override-ingestor.yml|deploy/compose/docker-compose-ingestor-server.yaml
rag-override-nims.yml|deploy/compose/nims.yaml
rag-override-rag-server.yml|deploy/compose/docker-compose-rag-server.yaml
rag-override-vectordb.yml|deploy/compose/vectordb.yaml
"
    while IFS='|' read -r ov base; do
        [ -n "${ov:-}" ] || continue
        if [ ! -f "$RAG_DIR/$base" ]; then
            echo "compose config: $ov skipped (RAG base $RAG_DIR/$base absent — the VM re-run covers it)"
            continue
        fi
        [ -f config/rag.env ] && { set -a; . ./config/rag.env; set +a; }
        # the bases interpolate secrets with :? guards (NGC_API_KEY is
        # injected by 20-start from the lab key store); a dummy satisfies
        # the guard — config -q prints nothing, so nothing is logged
        SHARED_API_KEY=x SHARED_ENDPOINT_URL=http://u/v1 NGC_API_KEY=x \
            docker compose -f "$RAG_DIR/$base" -f "compose/$ov" config -q \
            || { echo "run-dev-tests: FAIL — compose/$ov does not merge cleanly onto $RAG_DIR/$base" >&2; exit 1; }
        echo "compose config: $ov (merged on $base) ok"
    done <<< "$OVERRIDE_BASE"
else
    echo "docker CLI absent — compose validation skipped (the VM re-run covers it)"
fi

echo "run-dev-tests: PASS (L0+L1+L3+L4 + UI). Closing gate: also run scripts/test/container-smoke.sh (L2)."
