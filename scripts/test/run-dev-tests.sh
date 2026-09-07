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
# mock-wo/ (the 03 Dockerfile contract: uvicorn app.main:app), and
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
    for f in compose/*.yml; do
        SHARED_API_KEY=x SHARED_ENDPOINT_URL=http://u/v1 \
            docker compose -f "$f" config -q \
            || { echo "run-dev-tests: FAIL — $f is not a valid compose project" >&2; exit 1; }
        echo "compose config: $f ok"
    done
else
    echo "docker CLI absent — compose validation skipped (the VM re-run covers it)"
fi

echo "run-dev-tests: PASS (L0+L1+L3+L4). Closing gate: also run scripts/test/container-smoke.sh (L2)."
