"""L0 unit tests — DB init (TC-001) and schema/enum whitelists (TC-002).

These run without the app: ``db.init_db`` and the pydantic models are
exercised directly (05: L0 = DB init + schema/enum whitelists).
"""

import sqlite3

import pytest
from pydantic import ValidationError

from app import db, schemas
from conftest import VALID_WORK_ORDER


def test_tc001_db_init_creates_three_tables_and_wal(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_db(str(path))
    conn = sqlite3.connect(str(path))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"work_orders", "notes", "notifications"} <= tables
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert journal == "wal"
    finally:
        conn.close()


def test_tc002_schema_enums_whitelisted():
    # good enums accepted (raw enum + model level)
    assert schemas.Priority("high") is schemas.Priority.HIGH
    assert schemas.WorkOrderStatus("open") is schemas.WorkOrderStatus.OPEN
    assert schemas.CitationSource("rag") is schemas.CitationSource.RAG
    work_order = schemas.WorkOrderIn(**VALID_WORK_ORDER)
    assert work_order.priority is schemas.Priority.HIGH
    # bad enums rejected by pydantic at the model level (422 at the API;
    # the raw enum constructors raise ValueError instead)
    with pytest.raises(ValidationError):
        schemas.WorkOrderIn(**dict(VALID_WORK_ORDER, priority="urgent"))
    with pytest.raises(ValidationError):
        schemas.WorkOrderPatch(status="yolo")
    with pytest.raises(ValidationError):
        schemas.WorkOrderIn(
            **dict(
                VALID_WORK_ORDER,
                citations=[
                    {"source_type": "email", "source_id": "x",
                     "quote": "q"},
                ],
            )
        )


def test_tc002_full_payload_accepted():
    work_order = schemas.WorkOrderIn(**VALID_WORK_ORDER)
    assert work_order.priority is schemas.Priority.HIGH
    assert len(work_order.citations) == 2


def test_raw_enum_constructors_reject_unknown_values():
    with pytest.raises(ValueError):
        schemas.Priority("urgent")
    with pytest.raises(ValueError):
        schemas.WorkOrderStatus("yolo")
    with pytest.raises(ValueError):
        schemas.CitationSource("email")


def test_schema_length_caps_enforced():
    payload = dict(VALID_WORK_ORDER)
    with pytest.raises(ValidationError):
        schemas.WorkOrderIn(**dict(payload, title="x" * 201))
    with pytest.raises(ValidationError):
        schemas.WorkOrderIn(**dict(payload, description="x" * 8001))
    with pytest.raises(ValidationError):
        schemas.WorkOrderIn(**dict(payload, equipment="x" * 101))
    with pytest.raises(ValidationError):
        schemas.WorkOrderIn(**dict(payload, anomaly_ref="x" * 201))
    # 51 citations -> rejected (0-50 items)
    fifty_one = [
        {"source_type": "rag", "source_id": f"doc-{i}", "quote": "q"}
        for i in range(51)
    ]
    with pytest.raises(ValidationError):
        schemas.WorkOrderIn(**dict(payload, citations=fifty_one))
    # 2001-char citation quote -> rejected
    bad_citation = {
        "source_type": "rag",
        "source_id": "doc-1",
        "quote": "x" * 2001,
    }
    with pytest.raises(ValidationError):
        schemas.WorkOrderIn(**dict(payload, citations=[bad_citation]))


def test_schema_note_caps_enforced():
    with pytest.raises(ValidationError):
        schemas.MonitoringNoteIn(
            equipment="x" * 101,
            description="d",
            anomaly_ref="ref",
        )
    with pytest.raises(ValidationError):
        schemas.MonitoringNoteIn(
            equipment="M-1",
            description="x" * 4001,
            anomaly_ref="ref",
        )
