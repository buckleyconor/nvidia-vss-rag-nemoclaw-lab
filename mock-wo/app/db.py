"""SQLite (WAL) storage for mock-wo — stdlib only (03 storage decision).

Parameterized queries ONLY — no f-string/concatenated SQL anywhere (04
security: injection mitigation). Hostile id values (path traversal, SQL
fragments) never reach SQL: they are unknown ids -> 404 at the route.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

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
"""


def init_db(path: str) -> None:
    """Create the three tables on a fresh/tmp DB path and enable WAL.

    Idempotent (IF NOT EXISTS). ``PRAGMA journal_mode=WAL`` persists in the
    database file, so every later connection (including a re-opened app —
    TC-019) runs in WAL mode.
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()
    finally:
        conn.close()


def connect(path: str) -> sqlite3.Connection:
    """One connection per request (03: single-worker uvicorn; WAL allows
    concurrent readers while a writer holds the write lock).

    ``check_same_thread=False`` is required: FastAPI runs sync route
    handlers in a worker thread but runs dependency teardown on the event
    loop, so the connection is opened and closed in different threads.
    The connection is request-scoped and never shared across requests.
    """
    conn = sqlite3.connect(str(path), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def insert_work_order(
    conn: sqlite3.Connection,
    wo_id: str,
    fields: Dict[str, Any],
    citations: List[Dict[str, Any]],
    now: str,
) -> None:
    conn.execute(
        "INSERT INTO work_orders (id, title, description, equipment,"
        " anomaly_ref, priority, assigned_to, status, citations,"
        " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            wo_id,
            fields["title"],
            fields["description"],
            fields["equipment"],
            fields["anomaly_ref"],
            fields["priority"],
            fields.get("assigned_to"),
            "open",
            json.dumps(citations, ensure_ascii=False),
            now,
            now,
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
    cur = conn.execute(
        "SELECT * FROM work_orders WHERE id = ?", (wo_id,)
    )
    return cur.fetchone()


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
    cur = conn.execute(query, args)
    return cur.fetchall()


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
) -> None:
    conn.execute(
        "INSERT INTO notes (id, equipment, description, anomaly_ref,"
        " created_at) VALUES (?, ?, ?, ?, ?)",
        (note_id, fields["equipment"], fields["description"],
         fields["anomaly_ref"], now),
    )


def list_notes(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM notes ORDER BY created_at DESC, rowid DESC"
    )
    return cur.fetchall()


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
    cur = conn.execute(query)
    return cur.fetchall()
