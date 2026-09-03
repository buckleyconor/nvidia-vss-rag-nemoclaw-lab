"""mock-wo FastAPI app — routes, 256 KB body limit, health probe.

Implements the 02 REST contract for milestone 1 (API + schemas; the UI
routes are milestone 2). The app is created by ``create_app(db_path)``;
the module-level ``app`` (uvicorn target, per the 03 Dockerfile contract)
resolves its DB path from ``MOCK_WO_DB_PATH`` (compose sets it).
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, schemas

MAX_BODY_BYTES = 256 * 1024  # 02: request bodies > 256 KB -> 413
MAX_NOTIFICATION_MESSAGE = 500  # 02: Notification.message <= 500


def utcnow() -> str:
    """ISO-8601 UTC with a Z suffix (02: ISO-8601 UTC timestamps)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _work_order_out(row: sqlite3.Row) -> dict:
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
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _note_out(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "equipment": row["equipment"],
        "description": row["description"],
        "anomaly_ref": row["anomaly_ref"],
        "created_at": row["created_at"],
    }


def _notification_out(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "work_order_id": row["work_order_id"],
        "channel": row["channel"],
        "message": row["message"],
        "read_at": row["read_at"],
    }


def _notification_message(wo_id: str, title: str, priority: str,
                          equipment: str) -> str:
    """Compose the in-app feed line (02 example shape), capped at 500."""
    message = (
        f"Work order WO-{wo_id} filed: {title} "
        f"(priority {priority}, equipment {equipment})"
    )
    return message[:MAX_NOTIFICATION_MESSAGE]


def create_app(db_path: Optional[str] = None) -> FastAPI:
    path = db_path or os.environ.get("MOCK_WO_DB_PATH") or ":memory:"
    db.init_db(path)
    app = FastAPI(title="mock-wo", version="1.0.0")
    # Server-rendered UI (02): Jinja2 with autoescape ON (04: hostile text
    # renders escaped — no `| safe` anywhere in the templates).
    templates = Jinja2Templates(
        directory=str(Path(__file__).resolve().parent / "templates")
    )

    def get_db():
        conn = db.connect(path)
        try:
            yield conn
        finally:
            conn.close()

    @app.middleware("http")
    async def enforce_body_limit(request: Request,
                                 call_next: Callable):
        """413 before field validation: the body cap is a request-level
        rule (02), so a 300 KB description is 413, not a 422 (TC-010)."""
        if request.method in ("POST", "PATCH"):
            body = await request.body()
            if len(body) > MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "request body exceeds the 256 KB"
                                       " limit"},
                )
        return await call_next(request)

    @app.get("/health")
    def health() -> object:
        try:
            conn = db.connect(path)
            conn.execute("SELECT 1").fetchone()
            conn.close()
        except sqlite3.Error:
            return JSONResponse(
                status_code=503,
                content={"status": "degraded", "db": "error"},
            )
        # 02 interface table + TC-016. (09/lab-prep restate this check as
        # "Health == healthy"; the app's probe body is the one above.)
        return {"status": "ok", "db": "ok"}

    @app.post("/api/v1/work-orders", status_code=201)
    def create_work_order(payload: schemas.WorkOrderIn,
                          conn=Depends(get_db)) -> dict:
        now = utcnow()
        wo_id = str(uuid.uuid4())
        notif_id = str(uuid.uuid4())
        # Work order + its notification in ONE transaction (02: created
        # atomically with the work order).
        db.insert_work_order(
            conn, wo_id, payload.model_dump(mode="json"),
            [c.model_dump(mode="json") for c in payload.citations], now,
        )
        db.insert_notification(
            conn, notif_id, wo_id,
            _notification_message(
                wo_id, payload.title, payload.priority.value,
                payload.equipment,
            ),
        )
        conn.commit()
        entity = _work_order_out(db.get_work_order(conn, wo_id))
        assert entity is not None  # just inserted
        return entity

    @app.get("/api/v1/work-orders")
    def list_work_orders(
        status: Optional[str] = None,
        equipment: Optional[str] = None,
        conn=Depends(get_db),
    ) -> list:
        if status is not None:
            try:
                status = schemas.WorkOrderStatus(status).value
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=f"invalid status filter '{status}'",
                )
        rows = db.list_work_orders(conn, status=status,
                                   equipment=equipment)
        return [_work_order_out(r) for r in rows]

    @app.get("/api/v1/work-orders/{wo_id}")
    def get_work_order(wo_id: str, conn=Depends(get_db)) -> dict:
        # Any value that is not a stored id (UUIDs, SQL fragments, path
        # segments) is an unknown id -> 404; nothing reaches SQL (04).
        row = db.get_work_order(conn, wo_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"work order '{wo_id}' not found",
            )
        return _work_order_out(row)

    @app.patch("/api/v1/work-orders/{wo_id}")
    def patch_work_order(wo_id: str, patch: schemas.WorkOrderPatch,
                         conn=Depends(get_db)) -> dict:
        # An empty patch is a patch with NO effective field: no keys, or
        # only nulls (a null status changes nothing; a null assigned_to
        # IS effective — it clears the assignment, decision 6).
        has_status = ("status" in patch.model_fields_set
                      and patch.status is not None)
        has_assigned = "assigned_to" in patch.model_fields_set
        if not has_status and not has_assigned:
            raise HTTPException(
                status_code=422,
                detail="patch must include 'status' or 'assigned_to'",
            )
        row = db.get_work_order(conn, wo_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"work order '{wo_id}' not found",
            )
        now = utcnow()
        # Each effective field gets its own static parameterized UPDATE
        # (04: no concatenated SQL); both legs commit as one transaction.
        if has_status:
            db.update_status(conn, wo_id, patch.status.value, now)
        if has_assigned:
            db.update_assigned(conn, wo_id, patch.assigned_to, now)
        conn.commit()
        updated = db.get_work_order(conn, wo_id)
        assert updated is not None  # fetched moments ago
        return _work_order_out(updated)

    @app.post("/api/v1/notes", status_code=201)
    def create_note(payload: schemas.MonitoringNoteIn,
                    conn=Depends(get_db)) -> dict:
        now = utcnow()
        note_id = str(uuid.uuid4())
        db.insert_note(conn, note_id, payload.model_dump(mode="json"), now)
        conn.commit()
        return {
            "id": note_id,
            "equipment": payload.equipment,
            "description": payload.description,
            "anomaly_ref": payload.anomaly_ref,
            "created_at": now,
        }

    @app.get("/api/v1/notes")
    def list_notes(conn=Depends(get_db)) -> list:
        return [_note_out(r) for r in db.list_notes(conn)]

    @app.get("/api/v1/notifications")
    def list_notifications(unread: Optional[str] = None,
                           conn=Depends(get_db)) -> list:
        if unread is not None and unread.lower() not in ("true", "false"):
            raise HTTPException(
                status_code=422,
                detail="invalid 'unread' filter (expected true or false)",
            )
        unread_only = unread is not None and unread.lower() == "true"
        rows = db.list_notifications(conn, unread_only=unread_only)
        return [_notification_out(r) for r in rows]

    # ------------------------------------------------------------------
    # UI routes (02 mock-wo UI surface, milestone 2) — server-rendered,
    # autoescaped, no JS, no CDN. The list view is the beat-4 reveal
    # surface: empty at baseline, the new work order at the top after
    # the agent's POST.
    # ------------------------------------------------------------------

    def _unread_count(conn: sqlite3.Connection) -> int:
        return len(db.list_notifications(conn, unread_only=True))

    @app.get("/", response_class=HTMLResponse)
    def ui_work_order_list(request: Request, conn=Depends(get_db)):
        return templates.TemplateResponse(
            request, "work_orders.html",
            {
                "work_orders": [_work_order_out(r)
                                for r in db.list_work_orders(conn)],
                "notes_count": len(db.list_notes(conn)),
                "unread_count": _unread_count(conn),
            },
        )

    @app.get("/work-orders/{wo_id}", response_class=HTMLResponse)
    def ui_work_order_detail(wo_id: str, request: Request,
                             conn=Depends(get_db)):
        row = db.get_work_order(conn, wo_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"work order '{wo_id}' not found",
            )
        wo = _work_order_out(row)
        # Evidence panel: citations grouped by source_type (02).
        grouped: dict[str, list] = {}
        for c in wo["citations"]:
            grouped.setdefault(c["source_type"], []).append(c)
        return templates.TemplateResponse(
            request, "work_order.html",
            {
                "wo": wo,
                "citations_by_source": grouped,
                "unread_count": _unread_count(conn),
            },
        )

    @app.get("/notes", response_class=HTMLResponse)
    def ui_notes(request: Request, conn=Depends(get_db)):
        return templates.TemplateResponse(
            request, "notes.html",
            {
                "notes": [_note_out(r) for r in db.list_notes(conn)],
                "unread_count": _unread_count(conn),
            },
        )

    @app.get("/notifications", response_class=HTMLResponse)
    def ui_notifications(request: Request, conn=Depends(get_db)):
        return templates.TemplateResponse(
            request, "notifications.html",
            {
                "notifications": [_notification_out(r)
                                  for r in db.list_notifications(conn)],
                "unread_count": _unread_count(conn),
            },
        )

    # The single static CSS file (03 tech table); no JS, no CDN (02).
    app.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).resolve().parent / "static")),
        name="static",
    )

    return app


app = create_app()
