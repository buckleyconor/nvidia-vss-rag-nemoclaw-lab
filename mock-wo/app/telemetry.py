"""Agent telemetry mapping — ADR-V09, O24.

The OpenClaw plugin forwards raw hook events (``before_tool_call``,
``after_tool_call``, ``llm_output``, ``agent_end``). OpenClaw has no skill
hook and no token hook (O24): a skill surfaces as a read of its ``SKILL.md``
followed by ordinary tool calls, and model output arrives once per model
call. This module turns that stream into the §6.3 vocabulary:

- a tool call whose parameters name ``skills/<vss-skill>/SKILL.md`` starts
  ``skill.invoked``; the previous skill in the run completes;
- ``agent_end`` completes the running skill;
- ``llm_output`` becomes ``agent.token`` (per-turn text), and the text the
  model produced since the previous skill started is the next skill's
  ``rationale``. Text is consumed once: a skill with no fresh reasoning has
  no rationale rather than inheriting an earlier one. Never synthesised.

Telemetry is display-only. Nothing here touches incident, proposal or
evidence state; the caller persists the mapped events and nothing else.
Secrets are redacted before anything is stored or rebroadcast.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

SKILL_PATH_RE = re.compile(r"(?:^|[/\\])skills[/\\](vss-[a-z0-9-]+)[/\\]SKILL\.md\b")

_REDACTIONS = (
    (re.compile(r"nvapi-[A-Za-z0-9_\-]{8,}"), "nvapi-[redacted]"),
    (re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s\"']+"), r"\1[redacted]"),
    (re.compile(r"(?i)(x-api-key\s*:\s*)[^\s\"']+"), r"\1[redacted]"),
    (re.compile(r"(?i)((?:api[_-]?key|token|password|secret)[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"),
     r"\1[redacted]"),
)

MAX_TEXT = 8000
MAX_PARAMS = 2000
MAX_RATIONALE = 500


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def _params_summary(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not params:
        return {}
    raw = redact(json.dumps(params, ensure_ascii=False, default=str))
    if len(raw) <= MAX_PARAMS:
        try:
            return json.loads(raw)
        except ValueError:  # pragma: no cover - redaction broke the JSON
            pass
    return {"truncated": raw[:MAX_PARAMS]}


def skill_from_params(params: Optional[Dict[str, Any]]) -> Optional[str]:
    if not params:
        return None
    for value in _walk_strings(params):
        m = SKILL_PATH_RE.search(value)
        if m:
            return m.group(1)
    return None


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


@dataclass
class _ActiveSkill:
    name: str
    started: float
    last_error: Optional[str] = None


@dataclass
class _Run:
    last_text: Optional[str] = None
    skill: Optional[_ActiveSkill] = None


Mapped = List[Tuple[str, Dict[str, Any]]]


class TelemetryMapper:
    """Per-run state. In memory by design: after a restart a run simply
    starts a fresh trace; nothing authoritative lives here."""

    def __init__(self, clock=time.monotonic) -> None:
        self._runs: Dict[str, _Run] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def reset(self) -> None:
        with self._lock:
            self._runs.clear()

    def map(self, event: Dict[str, Any]) -> Mapped:
        run_id = event.get("run_id") or "default"
        with self._lock:
            run = self._runs.setdefault(run_id, _Run())
            hook = event["hook"]
            if hook == "llm_output":
                return self._llm_output(run, event)
            if hook == "before_tool_call":
                return self._before_tool(run, event)
            if hook == "after_tool_call":
                return self._after_tool(run, event)
            # agent_end
            out = self._complete(run)
            self._runs.pop(run_id, None)
            return out

    def _llm_output(self, run: _Run, event: Dict[str, Any]) -> Mapped:
        text = (event.get("text") or "").strip()
        if not text:
            return []
        text = redact(text)[:MAX_TEXT]
        run.last_text = text
        return [("agent.token", {"text": text})]

    def _before_tool(self, run: _Run, event: Dict[str, Any]) -> Mapped:
        name = skill_from_params(event.get("params"))
        if name is None:
            return []
        out = self._complete(run)
        rationale = run.last_text[:MAX_RATIONALE] if run.last_text else None
        run.last_text = None
        run.skill = _ActiveSkill(name=name, started=self._clock())
        out.append(("skill.invoked", {
            "skill_name": name,
            "rationale": rationale,
            "params": _params_summary(event.get("params")),
        }))
        return out

    def _after_tool(self, run: _Run, event: Dict[str, Any]) -> Mapped:
        if run.skill is not None:
            error = event.get("error")
            # The outcome follows the most recent tool call: a skill whose
            # agent recovered from an error completes ok (§8.4a).
            run.skill.last_error = redact(error)[:500] if error else None
        return []

    def _complete(self, run: _Run) -> Mapped:
        skill = run.skill
        if skill is None:
            return []
        run.skill = None
        payload: Dict[str, Any] = {
            "skill_name": skill.name,
            "duration_ms": round((self._clock() - skill.started) * 1000),
            "outcome": "failed" if skill.last_error else "ok",
        }
        if skill.last_error:
            payload["error"] = skill.last_error
        return [("skill.completed", payload)]
