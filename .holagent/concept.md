---
solution: "NVIDIA Service Blueprint: VSS + RAG + NemoClaw"
pillar: ai
audience:
  - "AI/ML engineers and solution architects evaluating agentic video pipelines for industrial use cases"
business_problem: "Equipment failures develop gradually, and the gap from first anomaly to maintenance action is only as fast as the engineer on shift, who must review video, then dig through manuals, logs, and maintenance records, often escalating before the root cause is understood, while downtime keeps costing money."
aha_moment: "Beat 4 ('Work order created'): after the learner's single instruction, NemoClaw gathers RAG context over the manuals and logs, reasons with its tool calls visible, and a maintenance work order appears in the mock CMMS."
---

# Concept — NVIDIA Service Blueprint: VSS + RAG + NemoClaw

The story this lab tells. Written before any sizing, spec, or code: if the
narrative does not hold up here, no amount of engineering downstream will save
it. Consumed by `/hol-spec` (stage 2), `/hol-plan` (stage 4), and the launch
collateral (stage 5).

## The business problem

A manufacturer runs equipment monitoring across factory floors. Failures
develop gradually. Detection is slow — humans reviewing video, or reacting
after a breakdown — and when a failure is spotted, the response is slow
because the on-call engineer has to dig through manuals, logs, and
maintenance records, often escalating before the root cause is understood.
Downtime is expensive, and the response quality depends on whoever happens to
be on shift.

## Who cares, and why

| Role                                                                 | What they own                                                          | What this changes for them                                                                                                                                                                                                                                                                                          |
| -------------------------------------------------------------------- | ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Reliability / maintenance engineer (primary — feels the pain)        | On-shift detection of equipment anomalies and the root-cause response that follows | The video system raises the alert and names the affected equipment, and the agent arrives with gathered context — the retrieved documents and its reasoning — plus a filed work order: the engineer verifies and dispatches instead of cold-searching manuals, logs, and records, and escalation happens after the root cause is understood, not before. |
| IT/OT director (secondary — signs for the fix)                       | Downtime cost and response quality; the decision to deploy automated detection-and-response | Response quality stops depending on whoever is on shift: the pipeline produces a documented, evidenced response (visible reasoning and retrieved documents) and triages which anomalies become work orders and which become monitoring notes — and it runs on one VM with a shared off-VM LLM endpoint, so a pilot is a pool of VMs, not a cluster.                |

## The demo story

The arc the learner walks. Each beat is something they _do_ and something they
_see_ — not a feature to be described.

1. **Establish the baseline** — the learner brings the VSS pipeline up on
   pre-recorded clips of factory equipment operating normally and sees it
   running healthy with no alerts. This beat exists to establish the normal
   state, so the later anomaly has a baseline to contrast against.
2. **Anomaly detected** — the learner feeds/plays the anomaly segment (e.g., a
   motor bearing showing abnormal thermal/vibration behaviour) and sees VSS
   raise an alert that identifies the affected equipment.
3. **Agentic diagnosis** — the learner instructs NemoClaw to analyse the
   flagged clip — a human-in-the-loop kick-off, the blueprint's proven path —
   and watches NemoClaw activate and run a RAG search over the equipment
   manuals, logs, and the maintenance schedule; the learner sees the agent's
   gathered context and reasoning — which documents were retrieved, what was
   inferred.
4. **Work order created — the aha** — NemoClaw acts on its diagnosis: it
   creates a work order in the mock CMMS/work-order system and notifies the
   maintenance team. The learner sees the work order appear in the system and
   the notification delivered. From the learner's single instruction onward it
   is end-to-end with no human touching: RAG hits → diagnosis → work order.
5. **Triage (optional extension)** — the learner injects a second anomaly of a
   different kind (or adjusts the trigger) and sees the agent triage
   differently — e.g., no work order, just a monitoring note — showing the
   agent decides rather than script-follows.

## The aha moment

Beat 4, "Work order created" — the ~90 seconds in which, after the learner's
single instruction, the agent autonomously gathers context (RAG hits over the
equipment manuals and logs), reasons, and produces a work order that visibly
appears in the mock CMMS. Visible on screen: the agent's tool calls / RAG
hits, then the work order. The learner caused it with one instruction; every
step after that instruction is the agent's work, shown on screen as it
happens.

## Why this solution

The obvious alternative — a video-analytics tool that only alerts — fixes
detection but not response: the alert still lands with an on-shift engineer
who has to dig through manuals, logs, and maintenance records before any work
order exists, which is exactly the slow half of the problem above. Composing
the three blueprints closes that gap in one visible chain: the video alert is
the agent's input, NemoClaw retrieves grounded context from the same manuals,
logs, and maintenance schedule the engineer would read (visible RAG hits and
reasoning), and the work order it files in the mock CMMS is its action — so
the learner sees, in the same session, the same anomaly that would have been
an alert on a screen become a diagnosed, cited work order. The composition
also holds in a lab footprint a real pool can run: one VM and one 96 GB GPU
host the video and retrieval models while the reasoning LLM is served from a
shared off-VM endpoint, and the project's measured runs show RAG retrieval
and LLM fusion add only a couple of seconds to a ~250 s end-to-end run — the
video analysis is the dominant cost, not the agent. (Context, not something
this lab measures: a partner deployment cited in the project build document
reports footage-to-work-order on a DETECT→REASON→ACT predictive-maintenance
pipeline dropping from 30–45 minutes to roughly 19 seconds across four asset
classes.)

## Success criteria

The lab has done its job when a learner can:

1. Explain the end-to-end alert → diagnosis → work-order flow and where the
   RAG context (the retrieved manuals, logs, and maintenance schedule) enters
   it.
2. Reproduce the aha moment from a clean start — one instruction to the agent,
   then the work order appearing in the mock CMMS with its notification, no
   human step in between.
3. Point at the agent's visible tool calls / retrieved documents on screen as
   the evidence of the diagnosis, not just the final answer.
4. State why the reasoning LLM is shared/off-VM while the video model and the
   RAG retrieval models run locally on the GPU — the footprint/density reason:
   one VM, one 96 GB GPU, a pool of ten learners.

## Non-goals

- VSS internals — video ingestion, chunking, and captioning, and the
  summarisation mechanics: VSS already has its own hands-on lab.
- Enterprise RAG internals — corpus indexing and vector-search mechanics: RAG
  already has its own hands-on lab.
- Anything beyond the agentic glue this lab is: video alert → agent-driven
  RAG diagnosis → autonomous work order. A beat that would need to teach how
  VSS chunks video or how RAG runs vector search belongs in those labs, not
  here.

## Open questions & assumptions

- Assumption: the demo footage is pre-recorded — normal-state clips for beat 1
  and an anomaly segment (e.g., a motor bearing with abnormal
  thermal/vibration behaviour) for beat 2. Open: which factory video clips /
  anomaly corpus to use, and where they come from.
- Open: which VLM the deployed VSS version ships as default — the repo README
  lists Cosmos-Reason2-8B while the current VSS docs name
  `nvidia/cosmos3-nano-reasoner`; the project build document says take the
  version default (both are 8B-class, so the GPU budget is unaffected either
  way, but LVS prompts and alert verification are tuned around it). Confirm
  before sizing.
- Open: the concrete shape of the mock work-order system that beat 4 reveals
  into — tech, ports, data model, and the notification path to the
  maintenance team.
- Open: whether the 10-VM vCD pool (concurrency target 10, one learner per
  VM, not to be exceeded) and the shared off-VM inference endpoint
  (`nemotron-3-nano-omni-30b-a3b-reasoning`, reached through a small nginx
  auth-shim) are pre-provisioned lab infrastructure or in scope for the
  build.
- Assumption: the agentic path is NemoClaw's human-in-the-loop kick-off
  driving the VSS report with the built-in `frag` knowledge-retrieval tool
  enabled via `VSS_AGENT_CONFIG_FILE` → `config_rag.yml` (Jul 2026
  integration method; the older patched-Dockerfile method is superseded).
- Assumption: versions follow the project build document — VSS repo tag
  v3.1.0 with agent image `VSS_AGENT_VERSION=3.2.0`, RAG v2.6.x (v2.6.2, fall
  back to v2.6.0) — the build document still lists confirming the exact tags
  as an open item before cloning; confirm before sizing.
- Assumption: the RAG corpus (manuals, logs, maintenance schedule) is ingested
  before the learner session; indexing is a non-goal, so the lab starts from
  an already-built index.
