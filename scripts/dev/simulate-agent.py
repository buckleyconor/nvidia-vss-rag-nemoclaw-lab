#!/usr/bin/env python3
"""simulate-agent.py — DEV ONLY. Plays the agent's side of one incident over
HTTP against mock-wo's agent port, so the operator dashboard can be driven on
the dev machine (no GPU, no VSS, no NemoClaw) and rehearsed on the VM before
the real agent is wired in.

It is a stand-in, not a demo path: ADR-V03 (analysis always runs live) rules
out replaying scripted analysis in front of a learner. Everything it posts is
labelled as simulated.

Usage (with mock-wo running, e.g. MOCK_WO_DEV_FAKE_CLIENTS=1):

    scripts/dev/simulate-agent.py                      # waits for an incident in gather
    scripts/dev/simulate-agent.py --pace 2 --kind monitoring_note
    scripts/dev/simulate-agent.py --agent http://127.0.0.1:8090

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

SIM = "[simulated] "


def call(base: str, method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            text = response.read().decode()
            return response.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "null")


def wait_for_gather(agent: str, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, incident = call(agent, "GET", "/api/v1/incidents/current")
        if status == 200 and incident["stage"] == "gather":
            return incident
        time.sleep(1)
    sys.exit("simulate-agent: no incident reached gather — inject a fault first"
             " (with MOCK_WO_DEV_FAKE_CLIENTS=1 on the dev machine)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agent", default="http://127.0.0.1:8090")
    parser.add_argument("--pace", type=float, default=1.5, help="seconds between steps")
    parser.add_argument("--kind", choices=["work_order", "monitoring_note"], default=None,
                        help="defaults to the pack incident's outcome_class")
    parser.add_argument("--wait", type=float, default=120)
    args = parser.parse_args()

    incident = wait_for_gather(args.agent, args.wait)
    definition = incident.get("definition") or {}
    incident_id = incident["id"]
    asset = incident["asset_id"]
    clip = incident["clip"]
    kind = args.kind or definition.get("outcome_class", "work_order")
    print(f"simulate-agent: incident {incident_id} on {asset} ({kind})")

    def step(label, method, path, body):
        status, response = call(args.agent, method, path, body)
        print(f"  {status} {label}")
        if status >= 400:
            sys.exit(f"simulate-agent: {label} failed: {response}")
        time.sleep(args.pace)
        return response

    run = f"sim-{incident_id[:8]}"
    event = lambda **kw: dict(run_id=run, **kw)  # noqa: E731

    step("reasoning", "POST", "/api/v1/agent-events", event(
        hook="llm_output", text=SIM + "An alert on the drive end. I will generate a report"
        " with the maintenance manual as context before proposing anything."))
    step("skill: report with RAG", "POST", "/api/v1/agent-events", event(
        hook="before_tool_call", tool_name="read",
        params={"path": "/sandbox/.openclaw/skills/vss-generate-video-report-rag/SKILL.md"}))
    step("tool call", "POST", "/api/v1/agent-events", event(
        hook="after_tool_call", tool_name="exec", duration_ms=1200))
    video = step("evidence: video", "POST", "/api/v1/evidence", {
        "incident_id": incident_id, "source_type": "vss", "source_id": f"{clip}@00:42",
        "quote": SIM + "Heat shimmer over the drive-end bearing housing; faint high-frequency vibration.",
        "claim": "Heat signature and vibration at the drive-end bearing housing",
        "t_start": 42, "t_end": 47, "confidence": "medium"})
    manual = step("evidence: manual", "POST", "/api/v1/evidence", {
        "incident_id": incident_id, "source_type": "rag", "source_id": "manual-01#4.2",
        "quote": "Bearing temperature above 75°C: replace per preventive schedule.",
        "claim": "The manual requires replacement above 75 °C", "document_anchor": "4.2",
        "confidence": "high"})
    log = step("evidence: log", "POST", "/api/v1/evidence", {
        "incident_id": incident_id, "source_type": "rag", "source_id": "log-01",
        "quote": "Bearing housing 71 °C at shift start; vibration consistent with the 08-21 entry.",
        "claim": "Temperature has trended up across three inspections",
        "confidence": "high"})
    step("skill: ask the video", "POST", "/api/v1/agent-events", event(
        hook="before_tool_call", tool_name="read",
        params={"path": "/sandbox/.openclaw/skills/vss-ask-video/SKILL.md"}))
    step("reasoning", "POST", "/api/v1/agent-events", event(
        hook="llm_output", text=SIM + "6312-2RS is not held locally. Two at Regional DC Cork,"
        " one day transit. Scheduling rather than dispatching now, with a de-rate until then."))
    step("run end", "POST", "/api/v1/agent-events", event(hook="agent_end"))

    ids = [video["id"], manual["id"], log["id"]]
    if kind == "monitoring_note":
        proposal = {
            "incident_id": incident_id, "kind": "monitoring_note",
            "root_cause": SIM + "Vibration trend within tolerance; no replacement threshold crossed.",
            "draft": {"equipment": asset, "anomaly_ref": f"{clip}@00:42",
                      "description": SIM + "Re-check at the next PM-07 window."},
            "evidence_ids": ids,
        }
    else:
        proposal = {
            "incident_id": incident_id, "kind": "work_order",
            "root_cause": SIM + "Drive-end bearing degradation: housing temperature trend plus"
                          " high-frequency vibration, above the manual's replacement threshold.",
            "line_items": [
                {"action": "Order bearing 6312-2RS", "detail": "Two held at Regional DC Cork, one day transit",
                 "part_number": "6312-2RS", "quantity": 1},
                {"action": "De-rate Line 3 to 60%", "detail": "Until the bearing is replaced"},
                {"action": "Schedule replacement", "detail": "Planned window after parts arrive"},
            ],
            "draft": {"title": f"Drive-end bearing replacement — {asset}", "equipment": asset,
                      "anomaly_ref": f"{clip}@00:42", "priority": "high",
                      "assigned_to": "maintenance-team-b",
                      "description": SIM + "Replace the drive-end bearing per manual-01 §4.2."},
            "parts_constraint": SIM + "6312-2RS is not held locally. Two at Regional DC Cork, one day"
                                " transit. Recommend scheduling rather than immediate dispatch, and"
                                " de-rating Line 3 to 60% until then.",
            "impact_if_ignored": {"low": 8400, "high": 50400, "unit": "EUR"},
            "impact_if_unnecessary": {"low": 850, "high": 2600, "unit": "EUR"},
            "evidence_ids": ids,
        }
    result = step("proposal", "POST", "/api/v1/proposals", proposal)
    print(f"simulate-agent: proposal {result['id']} is {result['state']}")


if __name__ == "__main__":
    main()
