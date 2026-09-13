"""Row -> JSON shapes for the CMMS records (02 contract, unchanged fields;
``proposal_id`` added by operator-dashboard-spec §5.6)."""

from __future__ import annotations

import json
import sqlite3


def work_order_out(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "equipment": row["equipment"],
        "anomaly_ref": row["anomaly_ref"],
        "priority": row["priority"],
        "assigned_to": row["assigned_to"],
        "status": row["status"],
        "citations": json.loads(row["citations"]),
        "proposal_id": row["proposal_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def note_out(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "equipment": row["equipment"],
        "description": row["description"],
        "anomaly_ref": row["anomaly_ref"],
        "proposal_id": row["proposal_id"],
        "created_at": row["created_at"],
    }


def notification_out(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "work_order_id": row["work_order_id"],
        "channel": row["channel"],
        "message": row["message"],
        "read_at": row["read_at"],
    }
