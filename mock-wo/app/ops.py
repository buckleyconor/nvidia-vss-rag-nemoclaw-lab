"""Operations — the incident state machine and everything that changes state.

Routes stay thin; every state change happens here inside one
``db.transaction`` together with the events that describe it, which are
fanned out only after commit (see ``events``).

State machine (operator-dashboard-spec §3, §5.2)::

    detect ──► gather ──► propose ──► decide ──► act ──► closed
       │          │          │           │
       └──────────┴──────────┴───────────┴──────────────► closed
                             └──(monitoring_note)──► act

- ``detect``: an operator injected a fault; the clip is being submitted and
  the agent woken.
- ``gather``: the agent is working (entered when the wake succeeds).
- ``propose``: entered when the agent files its proposal.
- ``decide``: a ``work_order`` proposal waits for the operator.
- ``act``: the work order (on approve/modify) or the auto-filed monitoring
  note exists. Decide is skipped only for monitoring notes.
- ``closed``: deny, a new injection after act, or a demo reset.

ADR-V04: a work order is created only by ``_execute_approved``, which needs a
decision token minted inside ``decide`` and bound to one proposal. Only the operator app (:8091) registers a route
that calls ``decide``; the agent app (:8090) has none (ADR-V08, enforced by
tests that list each app's route table).
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

from . import db, schemas
from .clients import ClientUnavailable
from .core import Core
from .events import row_to_event, utcnow
from .packs import Pack

MAX_NOTIFICATION_MESSAGE = 500
MAX_CITATIONS = 50

TRANSITIONS: Dict[Optional[str], Tuple[str, ...]] = {
    None: ("detect",),
    "detect": ("gather", "closed"),
    "gather": ("propose", "closed"),
    "propose": ("decide", "act", "closed"),
    "decide": ("act", "closed"),
    "act": ("closed",),
    "closed": (),
}

ACTIVE_PACK_KEY = "active_pack"


class OpError(Exception):
    status = 400

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class NotFound(OpError):
    status = 404


class Conflict(OpError):
    status = 409


class Invalid(OpError):
    status = 422


class Unavailable(OpError):
    status = 503


class _Tx:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.events: List[Dict[str, Any]] = []


class Operations:
    def __init__(self, core: Core):
        self.core = core
        self._pack_lock = threading.Lock()

    # -- plumbing -----------------------------------------------------------

    @contextmanager
    def _tx(self) -> Iterator[_Tx]:
        tx: Optional[_Tx] = None
        with db.transaction(self.core.settings.db_path) as conn:
            tx = _Tx(conn)
            yield tx
        # committed
        self.core.bus.fanout(tx.events)

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = db.connect(self.core.settings.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def _emit(self, tx: _Tx, incident_id: str, event_type: str,
              payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.core.bus.record(tx.conn, tx.events, incident_id,
                                    event_type, payload)

    def _advance(self, tx: _Tx, incident: sqlite3.Row, to: str,
                 extra: Optional[Dict[str, Any]] = None) -> None:
        current = incident["stage"]
        if to not in TRANSITIONS[current]:
            raise Conflict(f"incident is in stage '{current}';"
                           f" cannot move to '{to}'")
        closed_at = utcnow() if to == "closed" else None
        db.set_stage(tx.conn, incident["id"], to, closed_at)
        payload: Dict[str, Any] = {"stage": to, "previous": current}
        if extra:
            payload.update(extra)
        self._emit(tx, incident["id"], "stage.changed", payload)

    # -- packs --------------------------------------------------------------

    def active_pack(self) -> Pack:
        packs = self.core.packs
        if not packs:
            raise Unavailable("no packs installed")
        with self.read() as conn:
            chosen = db.get_setting(conn, ACTIVE_PACK_KEY)
        if chosen in packs:
            return packs[chosen]
        default = self.core.settings.default_pack
        if default in packs:
            return packs[default]
        return packs[sorted(packs)[0]]

    def list_packs(self) -> List[Dict[str, Any]]:
        active = self.active_pack().pack_id if self.core.packs else None
        return [dict(p.summary(), active=(p.pack_id == active))
                for p in sorted(self.core.packs.values(),
                                key=lambda p: p.pack_id)]

    def activate_pack(self, pack_id: str) -> Dict[str, Any]:
        """Switches mock-wo's own pack state only. Container work (vss-agent
        restart with the new KNOWLEDGE_COLLECTION, skill symlinks) is the
        host script's job — mock-wo has no Docker socket (§4a)."""
        if pack_id not in self.core.packs:
            raise NotFound(f"pack '{pack_id}' not installed")
        with self._tx() as tx:
            if db.open_incident(tx.conn) is not None:
                raise Conflict("an incident is in progress; finish or reset"
                               " before switching packs")
            db.set_setting(tx.conn, ACTIVE_PACK_KEY, pack_id)
        self.core.bus.publish_global("pack.activated", {"pack_id": pack_id})
        return self.core.packs[pack_id].summary()

    # -- fleet --------------------------------------------------------------

    def fleet(self) -> Dict[str, Any]:
        pack = self.active_pack()
        with self.read() as conn:
            current = db.open_incident(conn) or db.latest_incident(conn)
        assets = []
        for asset in pack.manifest.fleet:
            status, incident_ref = "normal", None
            if (current is not None and current["pack_id"] == pack.pack_id
                    and current["asset_id"] == asset.asset_id):
                incident_ref = current["id"]
                if current["stage"] in db.OPEN_STAGES:
                    status = "alarm"
                elif current["stage"] == "act":
                    status = "attention"
            data = asset.model_dump(mode="json")
            data.update(status=status, incident=incident_ref,
                        injectable=[i.incident_id for i in pack.manifest.incidents
                                    if i.asset_id == asset.asset_id])
            assets.append(data)
        return {"pack_id": pack.pack_id, "assets": assets}

    def asset(self, asset_id: str) -> Dict[str, Any]:
        for item in self.fleet()["assets"]:
            if item["asset_id"] == asset_id:
                return item
        raise NotFound(f"asset '{asset_id}' not found")

    def parts(self) -> List[Dict[str, Any]]:
        return [p.model_dump(mode="json")
                for p in self.active_pack().manifest.parts]

    # -- incidents ----------------------------------------------------------

    def _incident_row(self, conn: sqlite3.Connection,
                      incident_id: str) -> sqlite3.Row:
        row = db.get_incident(conn, incident_id)
        if row is None:
            raise NotFound(f"incident '{incident_id}' not found")
        return row

    def incident_view(self, row: sqlite3.Row, *, for_agent: bool) -> Dict[str, Any]:
        data = {k: row[k] for k in row.keys()}
        pack = self.core.packs.get(row["pack_id"])
        definition = pack.incident(row["pack_incident_id"]) if pack else None
        data["definition"] = (pack.incident_view(definition, for_agent=for_agent)
                              if definition else None)
        return data

    def list_incidents(self) -> List[Dict[str, Any]]:
        with self.read() as conn:
            return [self.incident_view(r, for_agent=False)
                    for r in db.list_incidents(conn)]

    def get_incident(self, incident_id: str, *, for_agent: bool) -> Dict[str, Any]:
        with self.read() as conn:
            row = self._incident_row(conn, incident_id)
            data = self.incident_view(row, for_agent=for_agent)
            proposal = db.get_proposal_for_incident(conn, incident_id)
            data["proposal_id"] = proposal["id"] if proposal else None
            return data

    def current_incident(self, *, for_agent: bool) -> Optional[Dict[str, Any]]:
        with self.read() as conn:
            row = db.open_incident(conn) or db.latest_incident(conn)
            if row is None:
                return None
        return self.get_incident(row["id"], for_agent=for_agent)

    def inject(self, payload: schemas.InjectIn) -> Dict[str, Any]:
        pack = self.active_pack()
        definition = pack.incident(payload.incident_id)
        if definition is None or definition.asset_id != payload.asset_id:
            raise NotFound(f"incident '{payload.incident_id}' is not defined"
                           f" for asset '{payload.asset_id}' in pack"
                           f" '{pack.pack_id}'")
        incident_id = str(uuid.uuid4())
        with self._tx() as tx:
            if db.open_incident(tx.conn) is not None:
                raise Conflict("an incident is already in progress")
            # A previous incident resting in `act` closes when the next
            # one starts: one incident at a time, rail always truthful.
            previous = db.latest_incident(tx.conn)
            if previous is not None and previous["stage"] == "act":
                self._advance(tx, previous, "closed")
            db.insert_incident(tx.conn, {
                "id": incident_id, "pack_id": pack.pack_id,
                "asset_id": definition.asset_id,
                "pack_incident_id": definition.incident_id,
                "clip": definition.clip, "stage": "detect",
                "opened_at": utcnow(),
            })
            self._emit(tx, incident_id, "stage.changed",
                       {"stage": "detect", "previous": None})
            self._emit(tx, incident_id, "analysis.progress", {
                "chunks_done": None, "chunks_total": None,
                "eta_seconds": definition.expected_analysis_seconds,
                "basis": "pack_expected_duration",
            })
        self._audit("inject", incident_id, pack.pack_id, definition.asset_id,
                    {"incident_id": definition.incident_id,
                     "title": definition.title})
        return self.get_incident(incident_id, for_agent=False)

    def kick(self, incident_id: str) -> None:
        """Submit the clip to VSS and wake the agent. Runs after the inject
        response; success moves detect -> gather, failure is a visible,
        recoverable ``error`` event and the incident stays in detect."""
        with self.read() as conn:
            row = self._incident_row(conn, incident_id)
        if row["stage"] != "detect":
            return
        pack = self.core.packs[row["pack_id"]]
        definition = pack.incident(row["pack_incident_id"])
        clip_path = pack.clip_path(row["clip"])
        try:
            if clip_path is None:
                raise ClientUnavailable(
                    f"clip '{row['clip']}' is not present in the pack")
            sensor = self.core.vss.ensure_clip(clip_path)
            self.core.wake.wake(
                f"mock-wo incident {incident_id}: {definition.title} on asset"
                f" {row['asset_id']}. The clip is loaded in VSS as sensor"
                f" '{sensor}'. Investigate, post evidence and file one"
                f" proposal to mock-wo for incident_id {incident_id}.")
        except ClientUnavailable as exc:
            with self._tx() as tx:
                self._emit(tx, incident_id, "error", {
                    "stage": "detect", "message": str(exc),
                    "recoverable": True})
            return
        with self._tx() as tx:
            current = self._incident_row(tx.conn, incident_id)
            if current["stage"] == "detect":
                self._advance(tx, current, "gather")

    def events_after(self, incident_id: str, after_seq: int) -> List[Dict[str, Any]]:
        with self.read() as conn:
            self._incident_row(conn, incident_id)
            return [row_to_event(r)
                    for r in db.list_events(conn, incident_id, after_seq)]

    # -- evidence -----------------------------------------------------------

    def add_evidence(self, payload: schemas.EvidenceIn) -> Dict[str, Any]:
        row = payload.model_dump(mode="json")
        row.update(id=str(uuid.uuid4()), created_at=utcnow())
        with self._tx() as tx:
            incident = self._incident_row(tx.conn, payload.incident_id)
            if incident["stage"] not in ("gather", "propose"):
                raise Conflict(f"incident is in stage '{incident['stage']}';"
                               " evidence is accepted during gather")
            db.insert_evidence(tx.conn, row)
            self._emit(tx, payload.incident_id, "evidence.added", {"evidence": row})
        return row

    def list_evidence(self, incident_id: str) -> List[Dict[str, Any]]:
        with self.read() as conn:
            self._incident_row(conn, incident_id)
            return [dict(r) for r in db.list_evidence(conn, incident_id)]

    # -- telemetry ----------------------------------------------------------

    def agent_event(self, payload: schemas.AgentEventIn) -> Dict[str, Any]:
        mapped = self.core.telemetry.map(payload.model_dump(mode="json"))
        with self._tx() as tx:
            incident = db.open_incident(tx.conn)
            if incident is None or incident["stage"] == "detect":
                return {"attached": False, "events": 0}
            for event_type, data in mapped:
                self._emit(tx, incident["id"], event_type, data)
        return {"attached": True, "incident_id": incident["id"],
                "events": len(mapped)}

    def retrieval_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """ragproxy observations (ADR-V02) attach to the incident in flight."""
        with self._tx() as tx:
            incident = db.open_incident(tx.conn)
            if incident is None:
                return
            self._emit(tx, incident["id"], event_type, data)

    # -- proposals ----------------------------------------------------------

    def _proposal_out(self, row: sqlite3.Row) -> Dict[str, Any]:
        body = json.loads(row["body"])
        return {"id": row["id"], "incident_id": row["incident_id"],
                "kind": row["kind"], "state": row["state"],
                "created_at": row["created_at"], "decided_at": row["decided_at"],
                **body}

    def get_proposal(self, proposal_id: str) -> Dict[str, Any]:
        with self.read() as conn:
            row = db.get_proposal(conn, proposal_id)
            if row is None:
                raise NotFound(f"proposal '{proposal_id}' not found")
            out = self._proposal_out(row)
            decision = db.get_decision_for_proposal(conn, proposal_id)
            out["decision"] = _decision_out(decision) if decision else None
            return out

    def create_proposal(self, payload: schemas.ProposalIn) -> Dict[str, Any]:
        draft = payload.validated_draft()
        proposal_id = str(uuid.uuid4())
        now = utcnow()
        with self._tx() as tx:
            incident = self._incident_row(tx.conn, payload.incident_id)
            if incident["stage"] != "gather":
                raise Conflict(f"incident is in stage '{incident['stage']}';"
                               " a proposal is accepted during gather")
            if db.get_proposal_for_incident(tx.conn, incident["id"]):
                raise Conflict("proposal_already_exists")
            if draft["equipment"] != incident["asset_id"]:
                raise Invalid(f"draft equipment '{draft['equipment']}' does not"
                              f" match the incident asset"
                              f" '{incident['asset_id']}'")
            evidence = db.list_evidence(tx.conn, incident["id"])
            known = {e["id"] for e in evidence}
            if not known:
                raise Invalid("a proposal needs at least one evidence row"
                              " for its incident (§5.3)")
            unknown = [e for e in payload.evidence_ids if e not in known]
            if unknown:
                raise Invalid(f"evidence_ids not recorded for this incident:"
                              f" {unknown}")
            body = payload.model_dump(
                mode="json", exclude={"incident_id", "kind", "draft",
                                      "line_items"})
            body["draft"] = draft
            body["line_items"] = [dict(li.model_dump(mode="json"), id=f"li-{i}")
                                  for i, li in enumerate(payload.line_items, 1)]
            body["evidence_ids"] = payload.evidence_ids or sorted(known)
            kind = payload.kind.value
            state = ("pending" if kind == "work_order" else "auto_filed")
            db.insert_proposal(tx.conn, {
                "id": proposal_id, "incident_id": incident["id"], "kind": kind,
                "state": state, "body": body, "created_at": now})
            self._advance(tx, incident, "propose")
            proposal_row = db.get_proposal(tx.conn, proposal_id)
            proposal = self._proposal_out(proposal_row)
            self._emit(tx, incident["id"], "proposal.ready", {"proposal": proposal})
            incident = self._incident_row(tx.conn, incident["id"])
            if kind == "work_order":
                self._advance(tx, incident, "decide")
            else:
                note_id = str(uuid.uuid4())
                db.insert_note(tx.conn, note_id, draft, now, proposal_id=proposal_id)
                db.set_proposal_state(tx.conn, proposal_id, "auto_filed", now)
                self._advance(tx, incident, "act",
                              {"decide": "not_required", "note_id": note_id})
        if kind == "monitoring_note":
            self._audit_incident("auto_filed", payload.incident_id)
        return self.get_proposal(proposal_id)

    # -- the gate (operator only) -------------------------------------------

    def decide(self, proposal_id: str, payload: schemas.DecisionIn) -> Dict[str, Any]:
        now = utcnow()
        work_order_id: Optional[str] = None
        notification_id: Optional[str] = None
        with self._tx() as tx:
            row = db.get_proposal(tx.conn, proposal_id)
            if row is None:
                raise NotFound(f"proposal '{proposal_id}' not found")
            if row["state"] != "pending":
                raise Conflict("proposal_already_decided")
            proposal = self._proposal_out(row)
            incident = self._incident_row(tx.conn, row["incident_id"])
            line_ids = [li["id"] for li in proposal["line_items"]]
            approved: List[str] = []
            action = payload.action.value
            if action in ("approve", "modify"):
                approved = (payload.line_items_approved
                            if payload.line_items_approved is not None
                            else line_ids)
                unknown = [i for i in approved if i not in line_ids]
                if unknown:
                    raise Invalid(f"unknown line items: {unknown}")
                if line_ids and not approved:
                    raise Invalid("approve at least one line item, or deny")
                draft = dict(proposal["draft"])
                modifications = None
                if action == "modify":
                    modifications = payload.modifications.model_dump(
                        mode="json", exclude_unset=True)
                    draft.update(modifications)
                # ADR-V04: mint the single-use token bound to this proposal,
                # then execute through the only work-order creation path.
                token = secrets.token_urlsafe(32)
                try:
                    db.insert_token(tx.conn, token, proposal_id, now)
                except sqlite3.IntegrityError as exc:
                    raise Conflict("proposal_already_decided") from exc
                work_order_id, notification_id = self._execute_approved(
                    tx, token, proposal, incident, draft, approved, now)
                state = "approved" if action == "approve" else "modified"
            else:
                modifications = None
                state = "denied"
            decision = {
                "id": str(uuid.uuid4()), "proposal_id": proposal_id,
                "action": action, "reason": payload.reason,
                "modifications": modifications,
                "line_items_approved": approved,
                "work_order_id": work_order_id, "decided_at": now,
            }
            db.insert_decision(tx.conn, decision)
            db.set_proposal_state(tx.conn, proposal_id, state, now)
            self._emit(tx, incident["id"], "decision.recorded", {
                "action": action, "reason": payload.reason,
                "modifications": modifications,
                "line_items_approved": approved})
            if work_order_id:
                self._emit(tx, incident["id"], "workorder.created", {
                    "work_order_id": work_order_id,
                    "notification_id": notification_id})
                self._advance(tx, incident, "act")
            else:
                self._advance(tx, incident, "closed")
        self._audit_incident("decision", row["incident_id"])
        return self.get_proposal(proposal_id)

    def _execute_approved(self, tx: _Tx, token: str, proposal: Dict[str, Any],
                          incident: sqlite3.Row, draft: Dict[str, Any],
                          approved: List[str], now: str) -> Tuple[str, str]:
        """The only work-order creation path. Requires an unconsumed token
        bound to this proposal; consumes it in the same transaction."""
        record = db.get_token(tx.conn, token)
        if (record is None or record["proposal_id"] != proposal["id"]
                or record["consumed_at"] is not None):
            raise Conflict("invalid or consumed decision token")
        if db.consume_token(tx.conn, token, now) != 1:
            raise Conflict("invalid or consumed decision token")
        evidence = db.list_evidence(tx.conn, incident["id"])
        citations = [{"source_type": e["source_type"], "source_id": e["source_id"],
                      "quote": e["quote"]} for e in evidence][:MAX_CITATIONS]
        description = draft["description"]
        chosen = [li for li in proposal["line_items"] if li["id"] in approved]
        if chosen:
            lines = "\n".join(f"- {li['action']}"
                              + (f": {li['detail']}" if li["detail"] else "")
                              for li in chosen)
            description = f"{description}\n\nApproved actions:\n{lines}"[:8000]
        fields = dict(draft, description=description)
        work_order_id = str(uuid.uuid4())
        notification_id = str(uuid.uuid4())
        db.insert_work_order(tx.conn, work_order_id, fields, citations, now,
                             proposal_id=proposal["id"])
        db.insert_notification(tx.conn, notification_id, work_order_id,
                               _notification_message(work_order_id, fields))
        return work_order_id, notification_id

    # -- ask the footage (operator only) ------------------------------------

    def ask(self, incident_id: str, payload: schemas.AskIn) -> Dict[str, Any]:
        ask_id = str(uuid.uuid4())
        with self._tx() as tx:
            incident = self._incident_row(tx.conn, incident_id)
            if incident["stage"] not in ("gather", "propose", "decide"):
                raise Conflict(f"incident is in stage '{incident['stage']}';"
                               " questions are taken while it is open")
            db.insert_ask(tx.conn, {"id": ask_id, "incident_id": incident_id,
                                    "question": payload.question,
                                    "status": "pending", "asked_at": utcnow()})
        return {"id": ask_id, "incident_id": incident_id,
                "question": payload.question, "status": "pending"}

    def answer_ask(self, ask_id: str) -> None:
        with self.read() as conn:
            ask = conn.execute("SELECT * FROM asks WHERE id = ?",
                               (ask_id,)).fetchone()
            if ask is None:
                return
            incident = self._incident_row(conn, ask["incident_id"])
        pack = self.core.packs.get(incident["pack_id"])
        clip_path = pack.clip_path(incident["clip"]) if pack else None
        try:
            if clip_path is None:
                raise ClientUnavailable("clip not present in the pack")
            sensor = self.core.vss.ensure_clip(clip_path)
            answer = self.core.vss.ask(sensor, ask["question"])
        except ClientUnavailable as exc:
            with self._tx() as tx:
                db.finish_ask(tx.conn, ask_id, "failed", None, str(exc), None,
                              utcnow())
                self._emit(tx, incident["id"], "error", {
                    "stage": incident["stage"], "message": str(exc),
                    "recoverable": True, "ask_id": ask_id})
            return
        evidence = {
            "id": str(uuid.uuid4()), "incident_id": incident["id"],
            "source_type": "vss",
            "source_id": f"{incident['clip']}@ask"[:200],
            "quote": answer.text[:2000],
            "claim": f"Operator question: {ask['question']}"[:500],
            "t_start": answer.t_start, "t_end": answer.t_end,
            "document_anchor": None, "confidence": "medium",
            "created_at": utcnow(),
        }
        with self._tx() as tx:
            db.insert_evidence(tx.conn, evidence)
            db.finish_ask(tx.conn, ask_id, "answered", answer.text, None,
                          evidence["id"], utcnow())
            self._emit(tx, incident["id"], "evidence.added", {"evidence": evidence})
            self._emit(tx, incident["id"], "ask.answer", {
                "ask_id": ask_id, "question": ask["question"],
                "answer": answer.text, "evidence_id": evidence["id"]})

    def list_asks(self, incident_id: str) -> List[Dict[str, Any]]:
        with self.read() as conn:
            self._incident_row(conn, incident_id)
            return [dict(r) for r in db.list_asks(conn, incident_id)]

    # -- reset and audit ----------------------------------------------------

    def reset(self) -> Dict[str, Any]:
        with self._tx() as tx:
            count = len(db.list_incidents(tx.conn))
            db.reset_incidents(tx.conn)
        self.core.telemetry.reset()
        self._audit("reset", None, None, None, {"incidents_cleared": count})
        self.core.bus.publish_global("demo.reset", {"incidents_cleared": count})
        return {"incidents_cleared": count}

    def _audit(self, kind: str, incident_id: Optional[str],
               pack_id: Optional[str], asset_id: Optional[str],
               record: Dict[str, Any]) -> None:
        with self._tx() as tx:
            db.insert_audit(tx.conn, {
                "id": str(uuid.uuid4()), "ts": utcnow(), "kind": kind,
                "incident_id": incident_id, "pack_id": pack_id,
                "asset_id": asset_id, "record": record})

    def _audit_incident(self, kind: str, incident_id: str) -> None:
        """Snapshot the full incident record — the audit row must survive
        the reset that deletes the incident (§8.8)."""
        with self.read() as conn:
            incident = self._incident_row(conn, incident_id)
            proposal = db.get_proposal_for_incident(conn, incident_id)
            decision = (db.get_decision_for_proposal(conn, proposal["id"])
                        if proposal else None)
            record = {
                "incident": self.incident_view(incident, for_agent=False),
                "evidence": [dict(e) for e in db.list_evidence(conn, incident_id)],
                "proposal": self._proposal_out(proposal) if proposal else None,
                "decision": _decision_out(decision) if decision else None,
                "asks": [dict(a) for a in db.list_asks(conn, incident_id)],
            }
        self._audit(kind, incident_id, incident["pack_id"], incident["asset_id"],
                    record)

    def audit(self) -> List[Dict[str, Any]]:
        with self.read() as conn:
            return [{"id": r["id"], "ts": r["ts"], "kind": r["kind"],
                     "incident_id": r["incident_id"], "pack_id": r["pack_id"],
                     "asset_id": r["asset_id"], "record": json.loads(r["record"])}
                    for r in db.list_audit(conn)]


def _decision_out(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"], "action": row["action"], "reason": row["reason"],
        "modifications": (json.loads(row["modifications"])
                          if row["modifications"] else None),
        "line_items_approved": json.loads(row["line_items_approved"]),
        "work_order_id": row["work_order_id"], "decided_at": row["decided_at"],
    }


def _notification_message(wo_id: str, fields: Dict[str, Any]) -> str:
    """The in-app feed line (02 example shape), capped at 500."""
    message = (f"Work order WO-{wo_id} filed: {fields['title']} "
               f"(priority {fields['priority']}, equipment {fields['equipment']})")
    return message[:MAX_NOTIFICATION_MESSAGE]
