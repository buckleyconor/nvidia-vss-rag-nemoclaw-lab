"""Event bus — the SSE vocabulary of operator-dashboard-spec §6.3.

Every incident event is written to the ``events`` table inside the same
transaction as the state change it describes, with ``seq`` monotonic per
incident. Only after that transaction commits are the events fanned out to
live subscribers, so a client never sees an event for a change that rolled
back, and a client that misses events (slow consumer, reconnect, navigation)
detects the gap from ``seq`` and re-fetches from the log.

Publishers run in FastAPI's worker threads; subscribers are asyncio queues
on the operator server's event loop. Fan-out therefore goes through
``loop.call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import db

EVENT_TYPES = frozenset({
    "stage.changed",
    "analysis.progress",
    "analysis.caption",
    "retrieval.query",
    "retrieval.result",
    "skill.invoked",
    "skill.completed",
    "archive.match",
    "agent.token",
    "evidence.added",
    "ask.answer",
    "proposal.ready",
    "decision.recorded",
    "workorder.created",
    "error",
    # Not tied to one incident: seq 0, not persisted.
    "demo.reset",
    "pack.activated",
})

GLOBAL_EVENTS = frozenset({"demo.reset", "pack.activated"})

QUEUE_LIMIT = 2000


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class Subscriber:
    loop: asyncio.AbstractEventLoop
    queue: "asyncio.Queue[Dict[str, Any]]" = field(
        default_factory=lambda: asyncio.Queue(maxsize=QUEUE_LIMIT))
    overflowed: bool = False


CLOSE = {"type": "__close__"}


class EventBus:
    def __init__(self) -> None:
        self._subscribers: List[Subscriber] = []
        self._lock = threading.Lock()

    def close_all(self) -> None:
        """End every live stream now. Called on shutdown: an open SSE
        connection must not hold the process up (``docker stop`` would wait
        out its kill timeout)."""
        with self._lock:
            subscribers = list(self._subscribers)
        for sub in subscribers:
            try:
                sub.loop.call_soon_threadsafe(_deliver_close, sub)
            except RuntimeError:
                self.unsubscribe(sub)

    # -- subscription -------------------------------------------------------

    def subscribe(self, loop: asyncio.AbstractEventLoop) -> Subscriber:
        sub = Subscriber(loop=loop)
        with self._lock:
            self._subscribers.append(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            if sub in self._subscribers:
                self._subscribers.remove(sub)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    # -- publishing ---------------------------------------------------------

    @staticmethod
    def record(conn: sqlite3.Connection, pending: List[Dict[str, Any]],
               incident_id: str, event_type: str,
               payload: Dict[str, Any]) -> Dict[str, Any]:
        """Persist one incident event inside the caller's transaction and
        queue it for fan-out after commit."""
        if event_type not in EVENT_TYPES or event_type in GLOBAL_EVENTS:
            raise ValueError(f"not an incident event type: {event_type}")
        seq = db.next_seq(conn, incident_id)
        ts = utcnow()
        db.insert_event(conn, incident_id, seq, event_type, payload, ts)
        event = {"type": event_type, "incident_id": incident_id,
                 "seq": seq, "ts": ts, **payload}
        pending.append(event)
        return event

    def publish_global(self, event_type: str,
                       payload: Optional[Dict[str, Any]] = None) -> None:
        if event_type not in GLOBAL_EVENTS:
            raise ValueError(f"not a global event type: {event_type}")
        self.fanout([{"type": event_type, "incident_id": None, "seq": 0,
                      "ts": utcnow(), **(payload or {})}])

    def fanout(self, events: List[Dict[str, Any]]) -> None:
        if not events:
            return
        with self._lock:
            subscribers = list(self._subscribers)
        for sub in subscribers:
            for event in events:
                try:
                    sub.loop.call_soon_threadsafe(_deliver, sub, event)
                except RuntimeError:
                    # The subscriber's loop has closed (server stopping).
                    self.unsubscribe(sub)
                    break


def _deliver_close(sub: Subscriber) -> None:
    # The close marker must arrive even when the queue is full.
    while True:
        try:
            sub.queue.put_nowait(CLOSE)
            return
        except asyncio.QueueFull:
            sub.queue.get_nowait()


def _deliver(sub: Subscriber, event: Dict[str, Any]) -> None:
    try:
        sub.queue.put_nowait(event)
    except asyncio.QueueFull:
        # The client falls behind; it will see a seq gap and re-fetch.
        sub.overflowed = True


def row_to_event(row: sqlite3.Row) -> Dict[str, Any]:
    return {"type": row["type"], "incident_id": row["incident_id"],
            "seq": row["seq"], "ts": row["ts"], **json.loads(row["payload"])}


def format_sse(event: Dict[str, Any]) -> str:
    """One SSE frame. ``id`` is ``<incident_id>:<seq>`` for incident events."""
    lines = [f"event: {event['type']}"]
    if event.get("incident_id"):
        lines.append(f"id: {event['incident_id']}:{event['seq']}")
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    lines.append(f"data: {data}")
    return "\n".join(lines) + "\n\n"
