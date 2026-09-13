"""Pydantic models — the mock-wo data model (02) extended for the operator
dashboard (operator-dashboard-spec §5, §6).

Enum whitelists, length caps and list bounds are enforced here; FastAPI
turns every violation into a 422 (never a 500) per the 02 contract.
"""

from __future__ import annotations

import enum
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Priority(str, enum.Enum):
    """Work-order priority — the agent's triage output (02 data model)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WorkOrderStatus(str, enum.Enum):
    """Work-order lifecycle. Always created ``open``; PATCH-able."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class CitationSource(str, enum.Enum):
    """Where a piece of evidence comes from (02: vss | rag | agent)."""

    VSS = "vss"
    RAG = "rag"
    AGENT = "agent"


class Citation(BaseModel):
    """One piece of evidence attached to a work order (02 Citation)."""

    source_type: CitationSource
    source_id: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=2000)


class WorkOrderPatch(BaseModel):
    """PATCH input — partial: ``status`` and/or ``assigned_to``.

    Operator port only (§6.1). An empty patch (no effective field) is
    rejected by the route with 422.
    """

    status: Optional[WorkOrderStatus] = None
    assigned_to: Optional[str] = Field(default=None, max_length=100)


# --------------------------------------------------------------------------
# Incident stages and evidence (§5.2, §5.3)
# --------------------------------------------------------------------------

class Stage(str, enum.Enum):
    """Incident stage. No ``monitor``: that is a fleet state (§3)."""

    DETECT = "detect"
    GATHER = "gather"
    PROPOSE = "propose"
    DECIDE = "decide"
    ACT = "act"
    CLOSED = "closed"


class Confidence(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class InjectIn(BaseModel):
    """POST /api/v1/incidents/inject (operator port)."""

    asset_id: str = Field(min_length=1, max_length=100)
    incident_id: str = Field(min_length=1, max_length=100,
                             description="incident id from the pack manifest")


class EvidenceIn(BaseModel):
    """POST /api/v1/evidence (agent port)."""

    incident_id: str = Field(min_length=1, max_length=100)
    source_type: CitationSource
    source_id: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=2000)
    claim: str = Field(min_length=1, max_length=500)
    t_start: Optional[float] = Field(default=None, ge=0)
    t_end: Optional[float] = Field(default=None, ge=0)
    document_anchor: Optional[str] = Field(default=None, max_length=200)
    confidence: Confidence

    @model_validator(mode="after")
    def _time_range(self) -> "EvidenceIn":
        if (self.t_start is not None and self.t_end is not None
                and self.t_end < self.t_start):
            raise ValueError("t_end must not be earlier than t_start")
        if self.t_end is not None and self.t_start is None:
            raise ValueError("t_end requires t_start")
        return self


# --------------------------------------------------------------------------
# Proposals (§5.4)
# --------------------------------------------------------------------------

class ProposalKind(str, enum.Enum):
    WORK_ORDER = "work_order"
    MONITORING_NOTE = "monitoring_note"


class ProposalState(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    MODIFIED = "modified"
    DENIED = "denied"
    AUTO_FILED = "auto_filed"


class ImpactRange(BaseModel):
    """A range, never a point estimate (§8.7)."""

    low: float = Field(ge=0)
    high: float = Field(ge=0)
    unit: str = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _is_a_range(self) -> "ImpactRange":
        if self.high <= self.low:
            raise ValueError("impact must be a range: high must exceed low")
        return self


class LineItemIn(BaseModel):
    action: str = Field(min_length=1, max_length=200)
    detail: str = Field(default="", max_length=1000)
    part_number: Optional[str] = Field(default=None, max_length=100)
    quantity: Optional[int] = Field(default=None, ge=1, le=10000)


class WorkOrderDraft(BaseModel):
    """The work order the agent proposes. Citations are not accepted:
    they are populated from the incident's evidence at creation (§5.3)."""

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=8000)
    equipment: str = Field(min_length=1, max_length=100)
    anomaly_ref: str = Field(min_length=1, max_length=200)
    priority: Priority
    assigned_to: Optional[str] = Field(default=None, max_length=100)


class MonitoringNoteDraft(BaseModel):
    equipment: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=4000)
    anomaly_ref: str = Field(min_length=1, max_length=200)


_SPLIT_RE = re.compile(r"^(\d{1,3})/(\d{1,3})$")


class ProposalIn(BaseModel):
    """POST /api/v1/proposals (agent port) — the agent's only outcome path."""

    incident_id: str = Field(min_length=1, max_length=100)
    kind: ProposalKind
    root_cause: str = Field(min_length=1, max_length=4000)
    alternate_root_cause: Optional[str] = Field(default=None, max_length=4000)
    confidence_split: Optional[str] = Field(default=None, max_length=7)
    discriminating_test: Optional[str] = Field(default=None, max_length=2000)
    line_items: List[LineItemIn] = Field(default_factory=list, max_length=20)
    draft: Dict[str, Any]
    parts_constraint: Optional[str] = Field(default=None, max_length=2000)
    impact_if_ignored: Optional[ImpactRange] = None
    impact_if_unnecessary: Optional[ImpactRange] = None
    evidence_ids: List[str] = Field(default_factory=list, max_length=50)

    @field_validator("confidence_split")
    @classmethod
    def _split(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        m = _SPLIT_RE.match(value)
        if not m or int(m.group(1)) + int(m.group(2)) != 100:
            raise ValueError("confidence_split must look like '60/40'"
                             " and sum to 100")
        return value

    @model_validator(mode="after")
    def _shape(self) -> "ProposalIn":
        if self.kind is ProposalKind.WORK_ORDER:
            WorkOrderDraft.model_validate(self.draft)
        else:
            MonitoringNoteDraft.model_validate(self.draft)
            if self.line_items:
                raise ValueError("a monitoring_note proposal has no"
                                 " line items")
        if self.alternate_root_cause and not self.confidence_split:
            raise ValueError("alternate_root_cause requires"
                             " confidence_split")
        return self

    def validated_draft(self) -> Dict[str, Any]:
        model = (WorkOrderDraft if self.kind is ProposalKind.WORK_ORDER
                 else MonitoringNoteDraft)
        return model.model_validate(self.draft).model_dump(mode="json")


# --------------------------------------------------------------------------
# Decisions (§5.5)
# --------------------------------------------------------------------------

class DecisionAction(str, enum.Enum):
    APPROVE = "approve"
    MODIFY = "modify"
    DENY = "deny"


class DraftModifications(BaseModel):
    """Field-level edits an operator may make to a work-order draft.
    ``equipment`` and ``anomaly_ref`` tie the order to the incident and are
    not editable."""

    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, min_length=1,
                                       max_length=8000)
    priority: Optional[Priority] = None
    assigned_to: Optional[str] = Field(default=None, max_length=100)


class DecisionIn(BaseModel):
    """POST /api/v1/proposals/{id}/decision (operator port)."""

    action: DecisionAction
    reason: Optional[str] = Field(default=None, max_length=2000)
    modifications: Optional[DraftModifications] = None
    line_items_approved: Optional[List[str]] = Field(default=None,
                                                     max_length=20)

    @model_validator(mode="after")
    def _rules(self) -> "DecisionIn":
        if self.action is DecisionAction.DENY:
            if not (self.reason and self.reason.strip()):
                raise ValueError("deny requires a reason")
        if self.action is DecisionAction.MODIFY:
            if self.modifications is None or not self.modifications.model_fields_set:
                raise ValueError("modify requires at least one modification")
            if not (self.reason and self.reason.strip()):
                raise ValueError("modify requires a note on what changed")
        elif self.modifications is not None:
            raise ValueError("modifications are only accepted with modify")
        return self


class AskIn(BaseModel):
    """POST /api/v1/incidents/{id}/ask (operator port) — §8.6."""

    question: str = Field(min_length=3, max_length=500)


class ActivatePackResult(BaseModel):
    pack_id: str


# --------------------------------------------------------------------------
# Agent telemetry (ADR-V09, O24) — raw OpenClaw hook events
# --------------------------------------------------------------------------

class AgentEventIn(BaseModel):
    """POST /api/v1/agent-events (agent port). Display-only: nothing here
    can change incident, proposal or evidence state."""

    hook: Literal["before_tool_call", "after_tool_call", "llm_output",
                  "agent_end"]
    run_id: Optional[str] = Field(default=None, max_length=200)
    tool_call_id: Optional[str] = Field(default=None, max_length=200)
    tool_name: Optional[str] = Field(default=None, max_length=200)
    params: Optional[Dict[str, Any]] = None
    error: Optional[str] = Field(default=None, max_length=4000)
    duration_ms: Optional[float] = Field(default=None, ge=0)
    text: Optional[str] = Field(default=None, max_length=32000)
