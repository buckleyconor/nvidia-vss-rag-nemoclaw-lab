"""The two ASGI apps — ADR-V08.

- ``create_agent_app``    → :8090, the only mock-wo port in the NemoClaw
  network policy. Proposal and evidence writes, telemetry ingest, read-only
  investigation routes, ragproxy.
- ``create_operator_app`` → :8091, never in the policy. The SPA, SSE, the
  decision gate, inject, pack activation, demo reset, audit, work-order
  PATCH, media and documents.

Each route is registered on exactly one app. Read routes both sides need are
registered twice, as separate route objects, so each app's route table can be
listed and audited on its own (tests do exactly that).
"""

from __future__ import annotations

import asyncio
import mimetypes
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.encoders import jsonable_encoder
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db, events, packs as packs_mod, ragproxy, schemas
from .bodylimit import BodyLimitMiddleware
from .ops import OpError, Operations
from .work_orders import note_out, notification_out, work_order_out

KEEPALIVE_SECONDS = 15.0


def _base_app(title: str, ops: Operations, lifespan=None) -> FastAPI:
    app = FastAPI(title=title, version="2.0.0", docs_url=None, redoc_url=None,
                  openapi_url="/api/v1/openapi.json", lifespan=lifespan)

    @app.exception_handler(OpError)
    async def _op_error(_request: Request, exc: OpError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422,
                            content={"detail": jsonable_encoder(exc.errors())})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException):
        return _http_error(exc)

    app.add_middleware(BodyLimitMiddleware)
    app.state.ops = ops
    return app


def _register_reads(app: FastAPI, ops: Operations, *, for_agent: bool) -> None:
    @app.get("/health")
    def health():
        try:
            with ops.read() as conn:
                conn.execute("SELECT 1").fetchone()
        except Exception:
            return JSONResponse(status_code=503,
                                content={"status": "degraded", "db": "error"})
        body = {"status": "ok", "db": "ok",
                "port": "agent" if for_agent else "operator"}
        if ops.core.settings.dev_fake_clients:
            body["dev_fake_clients"] = True
        return body

    @app.get("/api/v1/fleet")
    def fleet():
        return ops.fleet()

    @app.get("/api/v1/fleet/{asset_id}")
    def asset(asset_id: str):
        return ops.asset(asset_id)

    @app.get("/api/v1/parts")
    def parts():
        return ops.parts()

    @app.get("/api/v1/incidents/current")
    def current_incident():
        incident = ops.current_incident(for_agent=for_agent)
        if incident is None:
            raise HTTPException(status_code=404, detail="no current incident")
        return incident

    @app.get("/api/v1/incidents/{incident_id}")
    def incident(incident_id: str):
        return ops.get_incident(incident_id, for_agent=for_agent)

    @app.get("/api/v1/incidents/{incident_id}/evidence")
    def evidence(incident_id: str):
        return ops.list_evidence(incident_id)

    @app.get("/api/v1/proposals/{proposal_id}")
    def proposal(proposal_id: str):
        return ops.get_proposal(proposal_id)

    @app.get("/api/v1/work-orders")
    def list_work_orders(status: Optional[str] = None,
                         equipment: Optional[str] = None):
        if status is not None:
            try:
                status = schemas.WorkOrderStatus(status).value
            except ValueError:
                raise HTTPException(status_code=422,
                                    detail=f"invalid status filter '{status}'")
        with ops.read() as conn:
            return [work_order_out(r) for r in
                    db.list_work_orders(conn, status=status, equipment=equipment)]

    @app.get("/api/v1/work-orders/{wo_id}")
    def get_work_order(wo_id: str):
        with ops.read() as conn:
            row = db.get_work_order(conn, wo_id)
        if row is None:
            raise HTTPException(status_code=404,
                                detail=f"work order '{wo_id}' not found")
        return work_order_out(row)

    @app.get("/api/v1/notes")
    def list_notes():
        with ops.read() as conn:
            return [note_out(r) for r in db.list_notes(conn)]


# ==========================================================================
# :8090 — agent port
# ==========================================================================

def create_agent_app(ops: Operations) -> FastAPI:
    proxy = ragproxy.create_router(ops)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        await proxy.close_client()

    app = _base_app("mock-wo agent API", ops, lifespan=lifespan)
    _register_reads(app, ops, for_agent=True)

    @app.post("/api/v1/evidence", status_code=201)
    def add_evidence(payload: schemas.EvidenceIn):
        return ops.add_evidence(payload)

    @app.post("/api/v1/proposals", status_code=201)
    def create_proposal(payload: schemas.ProposalIn):
        return ops.create_proposal(payload)

    @app.post("/api/v1/agent-events", status_code=202)
    def agent_event(payload: schemas.AgentEventIn):
        return ops.agent_event(payload)

    app.include_router(proxy)
    return app


# ==========================================================================
# :8091 — operator port
# ==========================================================================

def create_operator_app(ops: Operations) -> FastAPI:
    app = _base_app("mock-wo operator API", ops)
    _register_reads(app, ops, for_agent=False)

    # -- live stream --------------------------------------------------------

    @app.get("/api/v1/stream")
    async def stream():
        loop = asyncio.get_running_loop()
        sub = ops.core.bus.subscribe(loop)

        async def frames():
            try:
                yield ": connected\n\n"
                while True:
                    try:
                        event = await asyncio.wait_for(sub.queue.get(),
                                                       KEEPALIVE_SECONDS)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if event is events.CLOSE:
                        return
                    yield events.format_sse(event)
            finally:
                ops.core.bus.unsubscribe(sub)

        return StreamingResponse(frames(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    # -- packs, documents, media --------------------------------------------

    @app.get("/api/v1/packs")
    def list_packs():
        return ops.list_packs()

    @app.post("/api/v1/packs/{pack_id}/activate")
    def activate_pack(pack_id: str):
        return ops.activate_pack(pack_id)

    def _pack(pack_id: str):
        pack = ops.core.packs.get(pack_id)
        if pack is None:
            raise HTTPException(status_code=404,
                                detail=f"pack '{pack_id}' not installed")
        return pack

    @app.get("/api/v1/packs/{pack_id}/documents")
    def list_documents(pack_id: str):
        pack = _pack(pack_id)
        return [dict(d.model_dump(mode="json"),
                     available=pack.document_path(d.id) is not None)
                for d in pack.documents]

    @app.get("/api/v1/packs/{pack_id}/documents/{doc_id}")
    def get_document(pack_id: str, doc_id: str):
        pack = _pack(pack_id)
        path = pack.document_path(doc_id)
        if path is None:
            raise HTTPException(status_code=404,
                                detail=f"document '{doc_id}' not found")
        text = path.read_text(encoding="utf-8", errors="replace")
        doc = pack.document(doc_id)
        return {"id": doc.id, "content_type": doc.content_type,
                "text": text, "sections": packs_mod.document_sections(text)}

    @app.get("/media/clips/{pack_id}/{name}")
    def clip(pack_id: str, name: str, request: Request):
        path = _pack(pack_id).clip_path(name)
        if path is None:
            raise HTTPException(status_code=404, detail="clip not found")
        return _ranged_file(request, path)

    # -- incidents ----------------------------------------------------------

    @app.get("/api/v1/incidents")
    def list_incidents():
        return ops.list_incidents()

    @app.post("/api/v1/incidents/inject", status_code=201)
    def inject(payload: schemas.InjectIn, background: BackgroundTasks):
        incident = ops.inject(payload)
        background.add_task(ops.kick, incident["id"])
        return incident

    @app.post("/api/v1/incidents/{incident_id}/retry", status_code=202)
    def retry(incident_id: str, background: BackgroundTasks):
        incident = ops.get_incident(incident_id, for_agent=False)
        if incident["stage"] != "detect":
            raise HTTPException(status_code=409,
                                detail="retry is only available in detect")
        background.add_task(ops.kick, incident_id)
        return {"status": "retrying"}

    @app.get("/api/v1/incidents/{incident_id}/events")
    def incident_events(incident_id: str, after_seq: int = 0):
        return ops.events_after(incident_id, max(0, after_seq))

    @app.post("/api/v1/incidents/{incident_id}/ask", status_code=202)
    def ask(incident_id: str, payload: schemas.AskIn,
            background: BackgroundTasks):
        record = ops.ask(incident_id, payload)
        background.add_task(ops.answer_ask, record["id"])
        return record

    @app.get("/api/v1/incidents/{incident_id}/asks")
    def asks(incident_id: str):
        return ops.list_asks(incident_id)

    # -- the gate -----------------------------------------------------------

    @app.post("/api/v1/proposals/{proposal_id}/decision")
    def decide(proposal_id: str, payload: schemas.DecisionIn):
        return ops.decide(proposal_id, payload)

    # -- CMMS ---------------------------------------------------------------

    @app.patch("/api/v1/work-orders/{wo_id}")
    def patch_work_order(wo_id: str, patch: schemas.WorkOrderPatch):
        has_status = "status" in patch.model_fields_set and patch.status is not None
        has_assigned = "assigned_to" in patch.model_fields_set
        if not has_status and not has_assigned:
            raise HTTPException(status_code=422,
                                detail="patch must include 'status' or 'assigned_to'")
        now = events.utcnow()
        with db.transaction(ops.core.settings.db_path) as conn:
            if db.get_work_order(conn, wo_id) is None:
                raise HTTPException(status_code=404,
                                    detail=f"work order '{wo_id}' not found")
            if has_status:
                db.update_status(conn, wo_id, patch.status.value, now)
            if has_assigned:
                db.update_assigned(conn, wo_id, patch.assigned_to, now)
        with ops.read() as conn:
            return work_order_out(db.get_work_order(conn, wo_id))

    @app.get("/api/v1/notifications")
    def list_notifications(unread: Optional[str] = None):
        if unread is not None and unread.lower() not in ("true", "false"):
            raise HTTPException(status_code=422,
                                detail="invalid 'unread' filter (expected true or false)")
        unread_only = unread is not None and unread.lower() == "true"
        with ops.read() as conn:
            return [notification_out(r)
                    for r in db.list_notifications(conn, unread_only=unread_only)]

    @app.get("/api/v1/audit")
    def audit():
        return ops.audit()

    @app.post("/api/v1/demo/reset")
    def reset():
        return ops.reset()

    _mount_spa(app, ops.core.settings.ui_dist)
    return app


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _http_error(exc: StarletteHTTPException) -> JSONResponse:
    """A method this port does not route is reported as 404, not 405.

    ``POST /api/v1/incidents/inject`` on the agent port would otherwise be a
    405 because ``GET /api/v1/incidents/{id}`` shares the path shape, which
    advertises that the path exists on this port. ADR-V08: a route that is
    not on this port is simply not found.
    """
    if exc.status_code == 405:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail},
                        headers=getattr(exc, "headers", None))


RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _ranged_file(request: Request, path: Path) -> Response:
    """Byte-range support so the browser can seek the clip (§8.1, §8.3)."""
    size = path.stat().st_size
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    header = request.headers.get("range")
    if not header:
        return FileResponse(path, media_type=media_type,
                            headers={"Accept-Ranges": "bytes"})
    m = RANGE_RE.match(header.strip())
    if not m or (not m.group(1) and not m.group(2)):
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    if m.group(1):
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else size - 1
    else:
        start = max(0, size - int(m.group(2)))
        end = size - 1
    end = min(end, size - 1)
    if start > end or start >= size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    with path.open("rb") as fh:
        fh.seek(start)
        data = fh.read(end - start + 1)
    return Response(content=data, status_code=206, media_type=media_type,
                    headers={"Content-Range": f"bytes {start}-{end}/{size}",
                             "Accept-Ranges": "bytes"})


API_PREFIXES = ("api/", "media/", "ragproxy/", "health")


def _mount_spa(app: FastAPI, dist: Path) -> None:
    """Serve the vendored React bundle (D6). No CDN, no external fetch: the
    bundle and its fonts are files in ``dist``.

    Implemented as the 404 handler rather than a catch-all route: a
    ``GET /{path}`` route would turn a POST to an agent-only path on this
    port into a 405, and every non-operator route must stay a plain 404
    here (ADR-V08). Unknown non-API GET paths return ``index.html`` so
    client-side routes survive a reload.
    """

    @app.exception_handler(StarletteHTTPException)
    async def _not_found(request: Request, exc: StarletteHTTPException):
        path = request.url.path.lstrip("/")
        if (exc.status_code != 404 or request.method != "GET"
                or path.startswith(API_PREFIXES)):
            return _http_error(exc)
        root = dist.resolve()
        index = root / "index.html"
        if not index.is_file():
            return JSONResponse(status_code=503, content={
                "detail": "operator UI is not built (run the ui build)"})
        if path:
            candidate = (root / path).resolve()
            if candidate.is_file() and root in candidate.parents:
                return FileResponse(candidate)
            if "." in path.rsplit("/", 1)[-1]:
                # A missing file (asset, favicon) is a 404, not the app shell:
                # serving index.html for it would hide a broken build.
                return JSONResponse(status_code=404, content={"detail": "Not Found"})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
