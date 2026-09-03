"""Pydantic models = the 02 data model (mock-wo entities).

Enum whitelists, length caps and the 0-50 citation bound are enforced here;
FastAPI turns every violation into a 422 (never a 500) per the 02 contract.
"""

from __future__ import annotations

import enum
from typing import List, Optional

from pydantic import BaseModel, Field


class Priority(str, enum.Enum):
    """Work-order priority — the agent's triage output (02 data model)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WorkOrderStatus(str, enum.Enum):
    """Work-order lifecycle. POST always creates ``open``; PATCH-able."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class CitationSource(str, enum.Enum):
    """Where a citation's evidence comes from (02: vss | rag | agent)."""

    VSS = "vss"
    RAG = "rag"
    AGENT = "agent"


class Citation(BaseModel):
    """One piece of evidence attached to a work order (02 Citation)."""

    source_type: CitationSource
    source_id: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=2000)


class WorkOrderIn(BaseModel):
    """POST /api/v1/work-orders input.

    ``status`` / ``id`` / ``created_at`` / ``updated_at`` are not accepted
    (02); generated server-side. Extra unknown fields are ignored
    (pydantic default).
    """

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=8000)
    equipment: str = Field(min_length=1, max_length=100)
    anomaly_ref: str = Field(min_length=1, max_length=200)
    priority: Priority
    assigned_to: Optional[str] = None
    citations: List[Citation] = Field(default_factory=list, max_length=50)


class WorkOrder(BaseModel):
    """Full work-order entity as returned by the API (02 201/200 shape)."""

    id: str
    title: str
    description: str
    equipment: str
    anomaly_ref: str
    priority: Priority
    assigned_to: Optional[str]
    status: WorkOrderStatus
    citations: List[Citation]
    created_at: str
    updated_at: str


class WorkOrderPatch(BaseModel):
    """PATCH input — partial: ``status`` and/or ``assigned_to``.

    An empty patch (no effective field) is rejected by the route with 422
    (02: "PATCH with an empty body -> 422", test-pinned TC-027).
    """

    status: Optional[WorkOrderStatus] = None
    assigned_to: Optional[str] = None


class MonitoringNoteIn(BaseModel):
    """POST /api/v1/notes input (02 MonitoringNote, beat 5)."""

    equipment: str = Field(min_length=1, max_length=100)
    description: str = Field(max_length=4000)
    anomaly_ref: str = Field(min_length=1, max_length=200)


class MonitoringNote(BaseModel):
    """Full monitoring-note entity."""

    id: str
    equipment: str
    description: str
    anomaly_ref: str
    created_at: str


class Notification(BaseModel):
    """In-app feed entry; created atomically with its work order (02)."""

    id: str
    work_order_id: str
    channel: str  # fixed "in_app" — the only channel (02)
    message: str = Field(max_length=500)
    read_at: Optional[str] = None
