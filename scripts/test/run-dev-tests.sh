#!/usr/bin/env bash
# scripts/test/run-dev-tests.sh — the dev gate (05-test-strategy.md):
# L0 + L1 + L3 + L4, run on the aarch64 dev machine (no GPU, no vendor
# NIMs, no x86 assumptions). Non-interactive and self-terminating.
#
#   1) python3 -m venv .venv   (recreated if missing)
#   2) .venv/bin/pip install -q -r mock-wo/requirements.txt -r mock-wo/requirements-dev.txt
#   3) .venv/bin/ruff check mock-wo/ tests/
#   4) .venv/bin/pytest mock-wo/tests tests -q --cov=mock-wo/app --cov-report=term-missing --cov-fail-under=90
#   5) bash -n on every scripts/**/*.sh (TC-039)
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

echo "== 5/5 script syntax (TC-039: bash -n on every scripts/**/*.sh; shellcheck is absent on the dev machine — not required) =="
SCRIPT_COUNT=0
while IFS= read -r script; do
    bash -n "$script"
    SCRIPT_COUNT=$((SCRIPT_COUNT + 1))
done < <(find scripts -type f -name '*.sh' | sort)
echo "bash -n: $SCRIPT_COUNT script(s) clean"

echo "run-dev-tests: PASS (L0+L1+L3+L4). Closing gate: also run scripts/test/container-smoke.sh (L2)."
