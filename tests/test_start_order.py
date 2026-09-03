"""TC-040 (L3) — the start-order contract of scripts/prep/20-start.sh.

The 02 start order is non-negotiable (the VLM must profile an EMPTY GPU
first); 03 keeps it "in one testable place instead of in prose". This
suite runs the dry run with a RECORDING ``docker`` stub first on PATH:
any Docker invocation of any shape is captured by the stub (which also
fails the run), so a passing test proves the dry run performed no Docker
invocation — the 05 TC-040 expectation:

  * exit 0
  * the printed order contains shim+mock-wo -> VSS -> RT-VLM gate ->
    RAG -> NemoClaw in that relative order
  * no Docker invocation
"""

import os
import re
import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "prep" / "20-start.sh"

# the 02 start order, in its non-negotiable relative order (03).
EXPECTED_ORDER = (
    "auth-shim + mock-wo",
    "VSS stack",
    "RT-VLM ready gate",
    "RAG stack",
    "NemoClaw sandbox",
)

STEP_RE = re.compile(r"^\s*STEP\s+\d+/\d+\s+(.+)$", re.MULTILINE)


def _step_labels(stdout: str) -> list:
    return [m.group(1) for m in STEP_RE.finditer(stdout)]


def test_tc040_start_order_dry_run(tmp_path):
    # recording docker stub: any invocation marks the file and exits 97
    # (which, under the script's set -euo pipefail, also fails the run).
    stub = tmp_path / "docker"
    stub.write_text(
        "#!/bin/sh\n"
        'echo "docker-stub-invoked $*" > "$DOCKER_STUB_MARK"\n'
        "exit 97\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    mark = tmp_path / "docker-stub.mark"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '')}",
        "DOCKER_STUB_MARK": str(mark),
    }

    proc = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO,
        timeout=30,
    )

    assert proc.returncode == 0, (
        f"dry run must exit 0, got {proc.returncode}; stderr: {proc.stderr}"
    )
    labels = _step_labels(proc.stdout)
    assert labels, (
        "dry run printed no STEP lines; stdout:\n" + proc.stdout
    )
    for want in EXPECTED_ORDER:
        assert any(want in label for label in labels), (
            f"start order missing step: {want!r}; printed: {labels}"
        )
    indexes = [
        next(i for i, label in enumerate(labels) if want in label)
        for want in EXPECTED_ORDER
    ]
    assert indexes == sorted(indexes), (
        f"steps out of order (want shim+mock-wo -> VSS -> RT-VLM gate -> "
        f"RAG -> NemoClaw): {labels}"
    )
    assert not mark.exists(), "dry run invoked Docker (TC-040: no Docker invocation)"
    # and the stub never ran, for good measure
    assert "docker-stub-invoked" not in proc.stdout + proc.stderr
