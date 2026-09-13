"""Shared fixtures — a self-contained test pack, fake outbound clients, one
Operations core and one TestClient per port (ADR-V08).

`mock-wo/` is put on sys.path so ``import app`` resolves the package the
same way the Dockerfile contract does (``python -m app.server``).
"""

import sys
import textwrap
from pathlib import Path
from typing import List

import pytest
from fastapi.testclient import TestClient

MOCK_WO_DIR = Path(__file__).resolve().parents[1]
REPO = MOCK_WO_DIR.parent
if str(MOCK_WO_DIR) not in sys.path:
    sys.path.insert(0, str(MOCK_WO_DIR))

from app import apps, clients  # noqa: E402
from app.core import Core, Settings  # noqa: E402
from app.ops import Operations  # noqa: E402

PACK_ID = "test-motors"
ASSET = "M-1"
INCIDENT_WO = "M1-BEARING"
INCIDENT_NOTE = "M1-TREND"

PACK_YAML = textwrap.dedent("""\
    pack_id: test-motors
    display_name: Test — Motors
    asset_class: Motors
    scenario: A bearing runs hot.
    knowledge_collection: test_corpus
    fleet:
      - asset_id: M-1
        display_name: Motor M-1
        make_model: ABB M3BP
        commissioned: 2019-04
        location: Line 1
        baseline_clips: [normal.mp4]
        service_history:
          - date: 2025-07-14
            summary: Bearing inspected
            technician: J. Moore
      - asset_id: M-2
        display_name: Motor M-2
    incidents:
      - incident_id: M1-BEARING
        asset_id: M-1
        title: Bearing thermal anomaly
        clip: anomaly.mp4
        outcome_class: work_order
        downtime_cost_per_hour: 4200
        callout_cost: 850
        ambiguous: true
        expected_analysis_seconds: 200
      - incident_id: M1-TREND
        asset_id: M-1
        title: Minor vibration trend
        clip: anomaly.mp4
        outcome_class: monitoring_note
        downtime_cost_per_hour: 4200
        callout_cost: 850
    parts:
      - part_number: 6312-2RS
        description: Deep-groove bearing
        on_hand_local: 0
        on_hand_regional: 2
        regional_site: Regional DC Cork
        oem_lead_days: 6
    skills:
      - vss-generate-video-report-rag
      - vss-ask-video
""")

CORPUS_MANIFEST = textwrap.dedent("""\
    documents:
      - id: manual-01
        content_type: manual
        file: manual-01.md
""")

MANUAL = textwrap.dedent("""\
    # Motor manual

    ## 4.2 Bearing temperature limits

    Bearing temperature above 75 °C: replace per preventive schedule.

    ## Replacement procedure

    Lock out the drive.
""")

CLIP_BYTES = bytes(range(256)) * 4  # 1024 bytes, distinct values for range checks


class FakeVss:
    def __init__(self) -> None:
        self.uploaded: List[str] = []
        self.questions: List[str] = []
        self.fail_upload = False
        self.fail_ask = False
        self.answer = "Yes — fluid is visible under the bearing housing."

    def ensure_clip(self, clip_path: Path) -> str:
        if self.fail_upload:
            raise clients.ClientUnavailable("VST unreachable")
        self.uploaded.append(clip_path.name)
        return clip_path.stem

    def ask(self, sensor: str, question: str) -> clients.AskAnswer:
        if self.fail_ask:
            raise clients.ClientUnavailable("VSS /generate failed")
        self.questions.append(question)
        return clients.AskAnswer(text=self.answer, t_start=40.0, t_end=44.0)


class FakeWake:
    def __init__(self) -> None:
        self.texts: List[str] = []
        self.fail = False

    def wake(self, text: str) -> None:
        if self.fail:
            raise clients.ClientUnavailable("wake hook refused")
        self.texts.append(text)


def write_pack(root: Path, pack_yaml: str = PACK_YAML) -> Path:
    pack = root / PACK_ID
    (pack / "clips").mkdir(parents=True)
    (pack / "corpus").mkdir()
    (pack / "pack.yaml").write_text(pack_yaml, encoding="utf-8")
    (pack / "clips" / "anomaly.mp4").write_bytes(CLIP_BYTES)
    (pack / "clips" / "normal.mp4").write_bytes(CLIP_BYTES)
    (pack / "corpus" / "manifest.yaml").write_text(CORPUS_MANIFEST, encoding="utf-8")
    (pack / "corpus" / "manual-01.md").write_text(MANUAL, encoding="utf-8")
    return pack


@pytest.fixture()
def packs_dir(tmp_path):
    root = tmp_path / "packs"
    root.mkdir()
    write_pack(root)
    return root


@pytest.fixture()
def ui_dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Operator</title>"
                                     "<div id=root></div>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    return dist


@pytest.fixture()
def fake_vss():
    return FakeVss()


@pytest.fixture()
def fake_wake():
    return FakeWake()


@pytest.fixture()
def settings(tmp_path, packs_dir, ui_dist):
    return Settings(db_path=str(tmp_path / "mock-wo.db"), packs_dir=packs_dir,
                    ui_dist=ui_dist, rag_upstream="http://rag-server:8081")


@pytest.fixture()
def core(settings, fake_vss, fake_wake):
    return Core.build(settings, vss=fake_vss, wake=fake_wake)


@pytest.fixture()
def ops(core):
    return Operations(core)


@pytest.fixture()
def agent_app(ops):
    return apps.create_agent_app(ops)


@pytest.fixture()
def operator_app(ops):
    return apps.create_operator_app(ops)


@pytest.fixture()
def agent(agent_app):
    with TestClient(agent_app) as client:
        yield client


@pytest.fixture()
def operator(operator_app):
    with TestClient(operator_app) as client:
        yield client


# --------------------------------------------------------------------------
# flow helpers
# --------------------------------------------------------------------------

def inject(operator, incident_id=INCIDENT_WO, asset_id=ASSET):
    response = operator.post("/api/v1/incidents/inject",
                             json={"asset_id": asset_id, "incident_id": incident_id})
    assert response.status_code == 201, response.text
    return response.json()


def evidence_payload(incident_id, **overrides):
    payload = {
        "incident_id": incident_id,
        "source_type": "rag",
        "source_id": "manual-01#4.2",
        "quote": "Bearing temperature above 75 °C: replace per preventive schedule.",
        "claim": "Housing temperature exceeds the replacement threshold",
        "document_anchor": "4.2",
        "confidence": "high",
    }
    payload.update(overrides)
    return payload


def add_evidence(agent, incident_id, **overrides):
    response = agent.post("/api/v1/evidence",
                          json=evidence_payload(incident_id, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def work_order_proposal(incident_id, **overrides):
    payload = {
        "incident_id": incident_id,
        "kind": "work_order",
        "root_cause": "Drive-end bearing degradation",
        "line_items": [
            {"action": "Order bearing", "detail": "6312-2RS from Cork",
             "part_number": "6312-2RS", "quantity": 1},
            {"action": "De-rate Line 1 to 60%", "detail": "until replacement"},
        ],
        "draft": {
            "title": "Bearing replacement — M-1",
            "description": "Replace the drive-end bearing.",
            "equipment": ASSET,
            "anomaly_ref": "clip anomaly.mp4@00:42",
            "priority": "high",
            "assigned_to": "maintenance-team-b",
        },
        "parts_constraint": "Not held locally; two at Regional DC Cork.",
        "impact_if_ignored": {"low": 8000, "high": 25000, "unit": "EUR"},
        "impact_if_unnecessary": {"low": 850, "high": 2400, "unit": "EUR"},
    }
    payload.update(overrides)
    return payload


def note_proposal(incident_id):
    return {
        "incident_id": incident_id,
        "kind": "monitoring_note",
        "root_cause": "Vibration within tolerance, trending",
        "draft": {"equipment": ASSET,
                  "description": "Re-check at the next PM-07 window.",
                  "anomaly_ref": "clip anomaly.mp4@01:15"},
    }


def to_decide(operator, agent):
    """inject -> gather -> evidence -> proposal (decide). Returns ids."""
    incident = inject(operator)
    evidence = add_evidence(agent, incident["id"])
    response = agent.post("/api/v1/proposals", json=work_order_proposal(incident["id"]))
    assert response.status_code == 201, response.text
    return incident["id"], response.json(), evidence
