"""SQLite (WAL) storage for mock-wo — stdlib only (03 storage decision).

Parameterized queries ONLY — no f-string/concatenated SQL anywhere (04
security: injection mitigation). Hostile id values (path traversal, SQL
fragments) never reach SQL: they are unknown ids -> 404 at the route.

Operator dashboard tables (operator-dashboard-spec §5): incidents, evidence,
proposals, decisions, decision_tokens, asks, events, audit, settings. The
three original CMMS tables keep their shape; work orders and notes gain a
nullable ``proposal_id`` (§5.6) — plain TEXT, not a foreign key, because a
demo reset clears proposals while the CMMS records and the audit trail stay.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS work_orders (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    equipment   TEXT NOT NULL,
    anomaly_ref TEXT NOT NULL,
    priority    TEXT NOT NULL,
    assigned_to TEXT,
    status      TEXT NOT NULL DEFAULT 'open',
    citations   TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id          TEXT PRIMARY KEY,
    equipment   TEXT NOT NULL,
    description TEXT NOT NULL,
    anomaly_ref TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id            TEXT PRIMARY KEY,
    work_order_id TEXT NOT NULL REFERENCES work_orders (id),
    channel       TEXT NOT NULL DEFAULT 'in_app',
    message       TEXT NOT NULL,
    read_at       TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
    id               TEXT PRIMARY KEY,
    pack_id          TEXT NOT NULL,
    asset_id         TEXT NOT NULL,
    pack_incident_id TEXT NOT NULL,
    clip             TEXT NOT NULL,
    stage            TEXT NOT NULL,
    opened_at        TEXT NOT NULL,
    closed_at        TEXT
);

CREATE TABLE IF NOT EXISTS evidence (
    id              TEXT PRIMARY KEY,
    incident_id     TEXT NOT NULL REFERENCES incidents (id) ON DELETE CASCADE,
    source_type     TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    quote           TEXT NOT NULL,
    claim           TEXT NOT NULL,
    t_start         REAL,
    t_end           REAL,
    document_anchor TEXT,
    confidence      TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
    id          TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL UNIQUE REFERENCES incidents (id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    state       TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    decided_at  TEXT
);

CREATE TABLE IF NOT EXISTS decision_tokens (
    token       TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL UNIQUE,
    minted_at   TEXT NOT NULL,
    consumed_at TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    id                  TEXT PRIMARY KEY,
    proposal_id         TEXT NOT NULL UNIQUE,
    action              TEXT NOT NULL,
    reason              TEXT,
    modifications       TEXT,
    line_items_approved TEXT NOT NULL DEFAULT '[]',
    work_order_id       TEXT,
    decided_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asks (
    id          TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents (id) ON DELETE CASCADE,
    question    TEXT NOT NULL,
    status      TEXT NOT NULL,
    answer      TEXT,
    error       TEXT,
    evidence_id TEXT,
    asked_at    TEXT NOT NULL,
    answered_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    incident_id TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    type        TEXT NOT NULL,
    payload     TEXT NOT NULL,
    ts          TEXT NOT NULL,
    PRIMARY KEY (incident_id, seq)
);

CREATE TABLE IF NOT EXISTS audit (
    id          TEXT PRIMARY KEY,
    ts          TEXT NOT NULL,
    kind        TEXT NOT NULL,
    incident_id TEXT,
    pack_id     TEXT,
    asset_id    TEXT,
    record      TEXT NOT NULL
);
"""

# Columns added to pre-dashboard tables. Applied with ALTER TABLE when an
# existing volume predates them, so a lab VM keeps its CMMS history.
_ADDED_COLUMNS = (
    ("work_orders", "proposal_id", "TEXT"),
    ("notes", "proposal_id", "TEXT"),
)


def init_db(path: str) -> None:
    """Create every table on a fresh DB, migrate an older one, enable WAL.

    Idempotent. ``PRAGMA journal_mode=WAL`` persists in the database file,
    so every later connection (including a re-opened app) runs in WAL mode.
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(SCHEMA)
        for table, column, decl in _ADDED_COLUMNS:
            existing = {row[1] for row in conn.execute(
                "SELECT * FROM pragma_table_info(?)", (table,))}
            if column not in existing:
                # Identifiers come from the constant tuple above, never
                # from input; SQLite cannot bind identifiers.
                conn.execute(
                    "ALTER TABLE " + table + " ADD COLUMN " + column
                    + " " + decl)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()
    finally:
        conn.close()


def connect(path: str) -> sqlite3.Connection:
    """A short-lived autocommit connection; transactions are explicit.

    ``check_same_thread=False`` because FastAPI may open a connection in a
    worker thread and close it on the event loop. A connection is never
    shared across requests.
    """
    conn = sqlite3.connect(str(path), timeout=10.0, check_same_thread=False,
                           isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def transaction(path: str) -> Iterator[sqlite3.Connection]:
    """``BEGIN IMMEDIATE`` .. COMMIT, rolled back on any exception.

    IMMEDIATE takes the write lock up front, so a read-check-write sequence
    (e.g. "proposal still pending? then decide") cannot interleave with a
    second writer — the replay-protection guarantee rests on this.
    """
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
    finally:
        conn.close()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# --------------------------------------------------------------------------
# CMMS records
# --------------------------------------------------------------------------

def insert_work_order(
    conn: sqlite3.Connection,
    wo_id: str,
    fields: Dict[str, Any],
    citations: List[Dict[str, Any]],
    now: str,
    proposal_id: Optional[str] = None,
) -> None:
    conn.execute(
        "INSERT INTO work_orders (id, title, description, equipment,"
        " anomaly_ref, priority, assigned_to, status, citations,"
        " created_at, updated_at, proposal_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            wo_id,
            fields["title"],
            fields["description"],
            fields["equipment"],
            fields["anomaly_ref"],
            fields["priority"],
            fields.get("assigned_to"),
            "open",
            dumps(citations),
            now,
            now,
            proposal_id,
        ),
    )


def insert_notification(
    conn: sqlite3.Connection,
    notif_id: str,
    work_order_id: str,
    message: str,
) -> None:
    conn.execute(
        "INSERT INTO notifications (id, work_order_id, channel, message)"
        " VALUES (?, ?, 'in_app', ?)",
        (notif_id, work_order_id, message),
    )


def get_work_order(conn: sqlite3.Connection, wo_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM work_orders WHERE id = ?", (wo_id,)).fetchone()


def list_work_orders(
    conn: sqlite3.Connection,
    status: Optional[str] = None,
    equipment: Optional[str] = None,
) -> List[sqlite3.Row]:
    query = "SELECT * FROM work_orders"
    clauses: List[str] = []
    args: List[str] = []
    if status is not None:
        clauses.append("status = ?")
        args.append(status)
    if equipment is not None:
        clauses.append("equipment = ?")
        args.append(equipment)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    # Newest first (02); rowid breaks created_at ties deterministically.
    query += " ORDER BY created_at DESC, rowid DESC"
    return conn.execute(query, args).fetchall()


def update_status(conn: sqlite3.Connection, wo_id: str,
                  status: str, now: str) -> None:
    """Static parameterized UPDATE — status leg of a PATCH."""
    conn.execute(
        "UPDATE work_orders SET status = ?, updated_at = ? WHERE id = ?",
        (status, now, wo_id),
    )


def update_assigned(conn: sqlite3.Connection, wo_id: str,
                    assigned_to: Optional[str], now: str) -> None:
    """Static parameterized UPDATE — assigned_to leg of a PATCH.
    ``None`` clears the assignment (sets NULL)."""
    conn.execute(
        "UPDATE work_orders SET assigned_to = ?, updated_at = ?"
        " WHERE id = ?",
        (assigned_to, now, wo_id),
    )


def insert_note(
    conn: sqlite3.Connection,
    note_id: str,
    fields: Dict[str, Any],
    now: str,
    proposal_id: Optional[str] = None,
) -> None:
    conn.execute(
        "INSERT INTO notes (id, equipment, description, anomaly_ref,"
        " created_at, proposal_id) VALUES (?, ?, ?, ?, ?, ?)",
        (note_id, fields["equipment"], fields["description"],
         fields["anomaly_ref"], now, proposal_id),
    )


def list_notes(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM notes ORDER BY created_at DESC, rowid DESC"
    ).fetchall()


def list_notifications(
    conn: sqlite3.Connection, unread_only: bool = False
) -> List[sqlite3.Row]:
    # The notifications table has no created_at column — rowid order is the
    # insertion order (newest first per the 02 contract).
    if unread_only:
        query = (
            "SELECT * FROM notifications WHERE read_at IS NULL"
            " ORDER BY rowid DESC"
        )
    else:
        query = "SELECT * FROM notifications ORDER BY rowid DESC"
    return conn.execute(query).fetchall()


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

def get_setting(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?)"
        " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


# --------------------------------------------------------------------------
# Incidents
# --------------------------------------------------------------------------

OPEN_STAGES = ("detect", "gather", "propose", "decide")


def insert_incident(conn: sqlite3.Connection, fields: Dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO incidents (id, pack_id, asset_id, pack_incident_id,"
        " clip, stage, opened_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (fields["id"], fields["pack_id"], fields["asset_id"],
         fields["pack_incident_id"], fields["clip"], fields["stage"],
         fields["opened_at"]),
    )


def get_incident(conn: sqlite3.Connection,
                 incident_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()


def list_incidents(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM incidents ORDER BY opened_at DESC, rowid DESC"
    ).fetchall()


def open_incident(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    """The incident in flight (detect..decide), if any — at most one."""
    return conn.execute(
        "SELECT * FROM incidents WHERE stage IN (?, ?, ?, ?)"
        " ORDER BY opened_at DESC, rowid DESC LIMIT 1",
        OPEN_STAGES,
    ).fetchone()


def latest_incident(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM incidents WHERE closed_at IS NULL"
        " ORDER BY opened_at DESC, rowid DESC LIMIT 1"
    ).fetchone()


def set_stage(conn: sqlite3.Connection, incident_id: str, stage: str,
              closed_at: Optional[str]) -> None:
    conn.execute(
        "UPDATE incidents SET stage = ?, closed_at = ? WHERE id = ?",
        (stage, closed_at, incident_id),
    )


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------

def insert_evidence(conn: sqlite3.Connection, row: Dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO evidence (id, incident_id, source_type, source_id,"
        " quote, claim, t_start, t_end, document_anchor, confidence,"
        " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["incident_id"], row["source_type"], row["source_id"],
         row["quote"], row["claim"], row.get("t_start"), row.get("t_end"),
         row.get("document_anchor"), row["confidence"], row["created_at"]),
    )


def list_evidence(conn: sqlite3.Connection,
                  incident_id: str) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM evidence WHERE incident_id = ?"
        " ORDER BY created_at, rowid",
        (incident_id,),
    ).fetchall()


# --------------------------------------------------------------------------
# Proposals, tokens, decisions
# --------------------------------------------------------------------------

def insert_proposal(conn: sqlite3.Connection, row: Dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO proposals (id, incident_id, kind, state, body,"
        " created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (row["id"], row["incident_id"], row["kind"], row["state"],
         dumps(row["body"]), row["created_at"]),
    )


def get_proposal(conn: sqlite3.Connection,
                 proposal_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()


def get_proposal_for_incident(conn: sqlite3.Connection,
                              incident_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM proposals WHERE incident_id = ?",
        (incident_id,)).fetchone()


def set_proposal_state(conn: sqlite3.Connection, proposal_id: str,
                       state: str, decided_at: Optional[str]) -> None:
    conn.execute(
        "UPDATE proposals SET state = ?, decided_at = ? WHERE id = ?",
        (state, decided_at, proposal_id),
    )


def insert_token(conn: sqlite3.Connection, token: str, proposal_id: str,
                 now: str) -> None:
    """UNIQUE(proposal_id): a second mint for the same proposal raises
    IntegrityError — the storage-level backstop for replay protection."""
    conn.execute(
        "INSERT INTO decision_tokens (token, proposal_id, minted_at)"
        " VALUES (?, ?, ?)",
        (token, proposal_id, now),
    )


def get_token(conn: sqlite3.Connection, token: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM decision_tokens WHERE token = ?", (token,)).fetchone()


def consume_token(conn: sqlite3.Connection, token: str, now: str) -> int:
    cur = conn.execute(
        "UPDATE decision_tokens SET consumed_at = ?"
        " WHERE token = ? AND consumed_at IS NULL",
        (now, token),
    )
    return cur.rowcount


def insert_decision(conn: sqlite3.Connection, row: Dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO decisions (id, proposal_id, action, reason,"
        " modifications, line_items_approved, work_order_id, decided_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["proposal_id"], row["action"], row.get("reason"),
         dumps(row["modifications"]) if row.get("modifications") is not None
         else None,
         dumps(row.get("line_items_approved") or []),
         row.get("work_order_id"), row["decided_at"]),
    )


def get_decision_for_proposal(conn: sqlite3.Connection,
                              proposal_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM decisions WHERE proposal_id = ?",
        (proposal_id,)).fetchone()


# --------------------------------------------------------------------------
# Asks (operator questions to the footage — §8.6)
# --------------------------------------------------------------------------

def insert_ask(conn: sqlite3.Connection, row: Dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO asks (id, incident_id, question, status, asked_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (row["id"], row["incident_id"], row["question"], row["status"],
         row["asked_at"]),
    )


def finish_ask(conn: sqlite3.Connection, ask_id: str, status: str,
               answer: Optional[str], error: Optional[str],
               evidence_id: Optional[str], now: str) -> None:
    conn.execute(
        "UPDATE asks SET status = ?, answer = ?, error = ?, evidence_id = ?,"
        " answered_at = ? WHERE id = ?",
        (status, answer, error, evidence_id, now, ask_id),
    )


def list_asks(conn: sqlite3.Connection, incident_id: str) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM asks WHERE incident_id = ? ORDER BY asked_at, rowid",
        (incident_id,),
    ).fetchall()


# --------------------------------------------------------------------------
# Event log (SSE backfill — §6.3 `seq`)
# --------------------------------------------------------------------------

def next_seq(conn: sqlite3.Connection, incident_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM events"
        " WHERE incident_id = ?",
        (incident_id,),
    ).fetchone()
    return int(row["n"])


def insert_event(conn: sqlite3.Connection, incident_id: str, seq: int,
                 event_type: str, payload: Dict[str, Any], ts: str) -> None:
    conn.execute(
        "INSERT INTO events (incident_id, seq, type, payload, ts)"
        " VALUES (?, ?, ?, ?, ?)",
        (incident_id, seq, event_type, dumps(payload), ts),
    )


def list_events(conn: sqlite3.Connection, incident_id: str,
                after_seq: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM events WHERE incident_id = ? AND seq > ?"
        " ORDER BY seq",
        (incident_id, after_seq),
    ).fetchall()


# --------------------------------------------------------------------------
# Audit (survives demo reset — §8.8)
# --------------------------------------------------------------------------

def insert_audit(conn: sqlite3.Connection, row: Dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO audit (id, ts, kind, incident_id, pack_id, asset_id,"
        " record) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["ts"], row["kind"], row.get("incident_id"),
         row.get("pack_id"), row.get("asset_id"), dumps(row["record"])),
    )


def list_audit(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM audit ORDER BY ts DESC, rowid DESC").fetchall()


def reset_incidents(conn: sqlite3.Connection) -> None:
    """Demo reset: clears incident state; keeps the audit trail and the
    CMMS records (work orders, notes, notifications)."""
    for statement in (
        "DELETE FROM events",
        "DELETE FROM asks",
        "DELETE FROM evidence",
        "DELETE FROM decisions",
        "DELETE FROM decision_tokens",
        "DELETE FROM proposals",
        "DELETE FROM incidents",
    ):
        conn.execute(statement)
