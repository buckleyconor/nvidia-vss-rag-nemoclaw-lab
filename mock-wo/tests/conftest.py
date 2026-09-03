"""L0/L1 fixtures — fresh temp SQLite DB per test, TestClient app.

`mock-wo/` is put on sys.path so ``import app`` resolves the package the
same way the 03 Dockerfile contract does (uvicorn ``app.main:app``).
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

MOCK_WO_DIR = Path(__file__).resolve().parents[1]
if str(MOCK_WO_DIR) not in sys.path:
    sys.path.insert(0, str(MOCK_WO_DIR))

from app import main  # noqa: E402

# The 02 "Create request example" verbatim — the TC-003 input.
VALID_WORK_ORDER = {
    "title": "Bearing replacement — M-3021 motor drive",
    "description": (
        "Thermal anomaly on motor M-3021 detected at"
        " clip-anomaly-01@00:42. Manual-01 p.12: bearing temp above 75°C"
        " requires replacement per schedule. Recommend priority-high"
        " replacement within 48 h."
    ),
    "equipment": "M-3021",
    "anomaly_ref": "vss-alert-clip-anomaly-01-00:42",
    "priority": "high",
    "assigned_to": "maintenance-team-b",
    "citations": [
        {
            "source_type": "rag",
            "source_id": "manual-01#p12",
            "quote": (
                "Bearing temperature above 75°C: replace per preventive"
                " schedule."
            ),
        },
        {
            "source_type": "vss",
            "source_id": "clip-anomaly-01@00:42",
            "quote": (
                "RT-VLM caption: heat signature on bearing housing,"
                " vibration audible."
            ),
        },
    ],
}

VALID_NOTE = {
    "equipment": "M-3021",
    "description": (
        "Minor vibration trend on M-3021; no work order warranted."
        " Continue monitoring and re-check at next inspection."
    ),
    "anomaly_ref": "vss-alert-clip-anomaly-02-01:15",
}


@pytest.fixture()
def app(tmp_path):
    """A fresh app over a fresh temp DB (function-scoped tmp_path)."""
    return main.create_app(str(tmp_path / "work-orders.db"))


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client
