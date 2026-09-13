"""L0 — DB init/migration and schema whitelists (no app)."""

import sqlite3

import pytest
from pydantic import ValidationError

from app import db, schemas

TABLES = {"work_orders", "notes", "notifications", "settings", "incidents", "evidence",
          "proposals", "decision_tokens", "decisions", "asks", "events", "audit"}


def test_db_init_creates_tables_and_wal(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_db(str(path))
    conn = sqlite3.connect(str(path))
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert TABLES <= names
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()
    db.init_db(str(path))  # idempotent


def test_db_migrates_pre_dashboard_volume(tmp_path):
    """A lab VM volume created by the previous mock-wo keeps its records and
    gains the proposal_id columns."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE work_orders (id TEXT PRIMARY KEY, title TEXT NOT NULL,
          description TEXT NOT NULL, equipment TEXT NOT NULL, anomaly_ref TEXT NOT NULL,
          priority TEXT NOT NULL, assigned_to TEXT, status TEXT NOT NULL DEFAULT 'open',
          citations TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL);
        CREATE TABLE notes (id TEXT PRIMARY KEY, equipment TEXT NOT NULL,
          description TEXT NOT NULL, anomaly_ref TEXT NOT NULL, created_at TEXT NOT NULL);
        INSERT INTO work_orders VALUES ('w1','t','d','M','a','high',NULL,'open','[]','x','x');
    """)
    conn.commit()
    conn.close()
    db.init_db(str(path))
    conn = db.connect(str(path))
    row = conn.execute("SELECT * FROM work_orders").fetchone()
    assert row["id"] == "w1" and row["proposal_id"] is None
    assert "proposal_id" in {r[1] for r in conn.execute("PRAGMA table_info(notes)")}
    conn.close()


def test_transaction_rolls_back(tmp_path):
    path = str(tmp_path / "tx.db")
    db.init_db(path)
    with pytest.raises(RuntimeError):
        with db.transaction(path) as conn:
            db.set_setting(conn, "k", "v")
            raise RuntimeError("boom")
    with db.transaction(path) as conn:
        assert db.get_setting(conn, "k") is None
        db.set_setting(conn, "k", "v1")
        db.set_setting(conn, "k", "v2")
    conn = db.connect(path)
    assert db.get_setting(conn, "k") == "v2"
    conn.close()


def test_enum_whitelists():
    assert {p.value for p in schemas.Priority} == {"low", "medium", "high", "critical"}
    assert {s.value for s in schemas.Stage} == {"detect", "gather", "propose", "decide",
                                                "act", "closed"}
    assert "monitor" not in {s.value for s in schemas.Stage}
    assert {s.value for s in schemas.ProposalState} == {"pending", "approved", "modified",
                                                        "denied", "auto_filed"}


@pytest.mark.parametrize("split,ok", [("60/40", True), ("50/50", True), ("60/50", False),
                                      ("sixty", False), ("100/0", True)])
def test_confidence_split(split, ok):
    payload = {"incident_id": "i", "kind": "monitoring_note", "root_cause": "r",
               "draft": {"equipment": "M", "description": "d", "anomaly_ref": "a"},
               "confidence_split": split}
    if ok:
        schemas.ProposalIn.model_validate(payload)
    else:
        with pytest.raises(ValidationError):
            schemas.ProposalIn.model_validate(payload)


def test_validated_draft_strips_unknown_fields():
    proposal = schemas.ProposalIn.model_validate({
        "incident_id": "i", "kind": "work_order", "root_cause": "r",
        "draft": {"title": "t", "description": "d", "equipment": "M", "anomaly_ref": "a",
                  "priority": "low", "citations": [{"forged": True}]}})
    assert "citations" not in proposal.validated_draft()


def test_impact_must_be_a_range():
    with pytest.raises(ValidationError):
        schemas.ImpactRange(low=10, high=10, unit="EUR")
    assert schemas.ImpactRange(low=10, high=11, unit="EUR").high == 11


def test_decision_rules():
    schemas.DecisionIn(action="approve")
    schemas.DecisionIn(action="deny", reason="wrong root cause")
    schemas.DecisionIn(action="modify", reason="note", modifications={"assigned_to": None})
    with pytest.raises(ValidationError):
        schemas.DecisionIn(action="deny")
    with pytest.raises(ValidationError):
        schemas.DecisionIn(action="modify", reason="note")
    with pytest.raises(ValidationError):
        schemas.DecisionIn(action="escalate")
