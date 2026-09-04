---
id: HOL-1362-01
title: 'NVIDIA Service Blueprint: VSS + RAG + NemoClaw'
slug: nvidia-service-bp-vss-rag-nemoclaw
audience:
  - 'AI/ML engineers evaluating agentic video pipelines for industrial use cases'
  - 'Solution architects and field technical specialists planning video-based predictive maintenance deployments'
prerequisites:
  - 'Comfort with the Linux shell and curl (Module 1 probes endpoints with curl)'
  - 'SSH access to the learner VM (instructor runbook; single-user host)'
  - 'No prior VSS, Enterprise RAG, or NemoClaw experience — each component is introduced as the guide uses it'
duration_minutes: 100
objectives:
  - 'Verify the running VSS + Enterprise RAG + NemoClaw stack on one VM and explain why the video and retrieval models run locally on the GPU while the reasoning LLM is served from a shared off-VM endpoint'
  - 'Run pre-recorded normal-state and anomaly video clips through the VSS pipeline and observe the healthy baseline and the alert that identifies the affected equipment'
  - 'Kick off NemoClaw with a single instruction, answer its human-in-the-loop prompts, and watch it retrieve equipment manuals, logs, and the maintenance schedule with visible tool calls and reasoning'
  - 'Verify the work order the agent files in the mock CMMS — its grouped citations and the delivered notification — with no human step after the instruction'
  - 'Triage a second, different-kind anomaly and observe the agent filing a monitoring note instead of a work order (optional extension)'
environment:
  baseline: 'vCD VM (Ubuntu 24.04 x86, 32 vCPU / 256 GB RAM / 2 TB NVMe, 1x RTX PRO 6000 96 GB full PCIe passthrough, /dev/shm 32 GB) with the full stack running before the session: auth-shim, VSS (agent, LVS, RT-VLM with the local 8B-class VLM), Enterprise RAG (server + six retriever NIMs), the NemoClaw sandbox, and the mock work-order service'
  credentials:
    - 'learner-vm / (instructor-issued SSH to the vCD learner VM — single-user host; every endpoint in this guide runs on that host)'
  urls:
    - 'http://localhost:8090 — mock CMMS (work-order UI + API, /health) — the beat-4 reveal surface'
    - 'http://localhost:18789 — OpenClaw UI (NemoClaw dashboard port-forward default; prep may record a different port in prep-log.md)'
    - 'http://localhost:8000 — VSS agent (/health)'
    - 'http://localhost:8081 — RAG server (/v1/health)'
    - 'http://localhost:8080 — auth-shim (/v1/models)'
    - 'http://127.0.0.1:38111 — VSS LVS backend (/v1/ready)'
    - 'http://127.0.0.1:8018 — RT-VLM local VLM (/v1/health/ready)'
  preloaded:
    - 'VSS stack v3.2.1 (prep-cloned; agent :8000, LVS :38111, RT-VLM :8018 with the local 8B-class VLM at 40% of the GPU)'
    - 'Enterprise RAG v2.6.2 (prep-cloned; server :8081, six retriever NIMs on the GPU)'
    - 'NemoClaw v0.0.118 sandbox (OpenClaw UI; the reasoning LLM served from the shared off-VM endpoint via the auth-shim)'
    - '/data/video — pre-recorded clips (two normal-state, one anomaly segment; equipment M-3021)'
    - '/data/corpus — equipment manuals, maintenance logs, and the preventive maintenance schedule'
    - 'RAG index — Elasticsearch collection demo_corpus, pre-built before the session (indexing is a non-goal)'
    - 'mock work-order service :8090 — work-order list empty at session start'
modules:
  - {
      n: 1,
      slug: explore-the-stack,
      title: 'Explore the Running Stack',
      goal: 'The learner can name where each component runs and confirm the stack is healthy: seven GPU compute processes, all endpoints up, the local LLM NIM absent, and the mock CMMS visibly empty.',
      est_minutes: 15,
    }
  - {
      n: 2,
      slug: establish-the-baseline,
      title: 'Establish the Baseline',
      goal: 'The learner runs the normal-state clips through VSS and sees the pipeline running healthy with no alerts — the contrast the anomaly beat depends on.',
      est_minutes: 15,
    }
  - {
      n: 3,
      slug: detect-the-anomaly,
      title: 'Detect the Anomaly',
      goal: 'The learner plays the anomaly segment, VSS raises the alert identifying equipment M-3021, and the learner records the alert clip reference and timestamp the work order will later cite.',
      est_minutes: 15,
    }
  - {
      n: 4,
      slug: run-the-agentic-diagnosis,
      title: 'Run the Agentic Diagnosis',
      goal: 'The learner kicks NemoClaw off with one instruction, answers the four HITL prompts, and watches the agent retrieve manuals, logs, and the schedule with visible tool calls, retrieved documents, and reasoning.',
      est_minutes: 20,
    }
  - {
      n: 5,
      slug: verify-the-work-order,
      title: 'Verify the Work Order',
      goal: 'The learner verifies the agent-filed work order at the top of the mock CMMS — its fields, its citations grouped by source, and the delivered in-app notification — with no human step after the instruction.',
      est_minutes: 10,
    }
  - {
      n: 6,
      slug: triage-a-second-anomaly,
      title: 'Triage a Second Anomaly',
      goal: 'The learner injects a second, different-kind anomaly and observes the agent triaging it to a monitoring note instead of a work order — the agent decides rather than script-follows.',
      est_minutes: 20,
    }
---

## Why this guide

Equipment failures develop gradually, and the gap from first anomaly to
maintenance action is only as fast as the engineer on shift: review video, dig
through manuals, logs, and maintenance records, and often escalate before the
root cause is understood — while downtime keeps costing money. This lab closes
that gap in one visible chain. On a single pre-provisioned VM, **VSS** detects
the anomaly in pre-recorded factory video, **NemoClaw** — kicked off by one
instruction from the learner — retrieves grounded context from **Enterprise
RAG** (the same manuals, logs, and maintenance schedule the engineer would
read, with the retrieval and the reasoning visible on screen), and **files a
work order in a mock CMMS** as its action. The learner caused it with one
instruction; every step after that is the agent's work, shown on screen as it
happens.

The lab deliberately does not teach VSS internals (ingestion, chunking,
captioning) or RAG internals (indexing, vector search) — both have their own
hands-on labs. This guide is the **agentic glue**: video alert → agent-driven
RAG diagnosis → autonomous work order.

The learning arc follows observation → guided → independent:

1. **Observe** (Module 1): verify the pre-provisioned stack — where each
   component runs, what the GPU budget looks like, and why the reasoning LLM
   is shared and off-VM while the video and retrieval models are local.
2. **Guided hands-on** (Modules 2–5): run the normal-state clips (the
   baseline), play the anomaly segment (the alert), kick off NemoClaw (the
   visible diagnosis), and verify the work order the agent filed (the aha —
   no human step in between).
3. **Independent application** (Module 6): inject a second, different-kind
   anomaly and watch the agent triage it differently — a monitoring note
   instead of a work order.

By the end, the learner has reproduced the aha moment from a clean start and
can point at the agent's visible tool calls and retrieved documents as the
evidence of the diagnosis — not just the final answer.

## Module roadmap

One entry per module — narrative, depends-on, teaching points, in learner
order. The frontmatter `modules` list is the machine-readable source; keep the
two in sync.

- **Module 1 — Explore the Running Stack** (15 min). The learner confirms the
  pre-provisioned baseline the whole lab runs on: probe the auth-shim
  (`/v1/models` lists the shared Nano Omni model), the VSS agent and LVS
  backend, the RT-VLM, the RAG server, and the mock CMMS; check the GPU state
  (seven compute processes, ~70 GB committed, the local LLM NIM on :30081
  absent); open the mock CMMS UI and note that the work-order list is **empty**
  (that is the surface Module 5 will fill); open the OpenClaw UI and confirm
  NemoClaw shows the custom endpoint and the Nano Omni model. This is the
  "is the lab alive" checkpoint every later module assumes, and it introduces
  every vocabulary item the guide reuses: auth-shim, shared endpoint, mock
  CMMS, LVS, OpenClaw UI. Depends on: none. Teaching points: the endpoint map
  (who talks to whom, over which port), the GPU residency question (which
  models are local and which are shared, and the footprint reason), and what a
  healthy lab looks like before a single clip is played. Environment delta:
  assumes the `lab-prep.md` verify state (full stack up, index built, CMMS
  empty); leaves behind nothing — pure orientation. Success criteria: all
  endpoint probes return 200; `nvidia-smi` shows 7 compute processes; nothing
  listens on :30081; the mock CMMS list is empty; NemoClaw status shows the
  shared endpoint + Nano Omni.
- **Module 2 — Establish the Baseline** (15 min). Beat 1. The learner runs the
  two normal-state clips through VSS (the lab helper
  `scripts/demo/01-baseline.sh` verifies the stack and stages the clips at
  `/data/video`) and watches the pipeline process them: captioning and
  summarization complete, the LVS UI shows a healthy pipeline, and **no alerts
  fire**. This beat exists to establish the normal state, so the anomaly in
  Module 3 has a baseline to contrast against. Depends on: Module 1 (healthy
  stack verified). Teaching points: what "normal" looks like on screen (the
  contrast device), that the analysis runs locally on the GPU (the VLM is the
  cost — ~90% of the measured end-to-end run), and where to look for the
  pipeline state (LVS UI / stack status). Environment delta: assumes Module 1
  state; leaves behind processed normal-state clips in the VSS video store
  (VST) — the pipeline history the anomaly beat will read against. Success
  criteria: both clips processed to completion; LVS UI shows healthy status
  with no alerts; the mock CMMS list is still empty.
- **Module 3 — Detect the Anomaly** (15 min). Beat 2. The learner plays the
  anomaly segment (a motor bearing showing abnormal thermal/vibration
  behaviour; `scripts/demo/02-anomaly.sh` stages it and prints the procedure).
  VSS raises the alert and identifies the affected equipment — **M-3021**.
  The learner reads the alert and records its clip reference and timestamp
  (e.g. `clip-anomaly-01@00:42`): that reference becomes the work orders
  `anomaly_ref` in Module 5, which is what ties the whole chain back to this
  beat. Depends on: Module 2 (the baseline the alert breaks). Teaching points:
  what the alert contains (equipment, clip, timestamp — the evidence the agent
  will cite), the difference between detection (VSS) and response (the agent —
  the slow half of the problem this lab closes), and why the alert alone is
  not enough (an alert without root cause still lands with an engineer who has
  to cold-search the manuals). Environment delta: assumes Module 1–2 state;
  leaves behind the raised alert for M-3021 in the LVS state. Success
  criteria: the alert is raised and visible in the LVS UI; the affected
  equipment is identified as M-3021; the clip reference + timestamp are
  recorded for Module 4.
- **Module 4 — Run the Agentic Diagnosis** (20 min). Beat 3 — the guided half
  of the aha. The learner opens the OpenClaw UI, starts a fresh session, and
  pastes ONE instruction (`scripts/demo/03-agent-kickoff.sh` prints it):
  "I want to generate a video summary report for clip-anomaly-01." NemoClaw
  activates the `vss-generate-video-report-rag` skill and collects the four
  HITL parameters — scenario, events of interest, objects to track, and the
  knowledge-retrieval query — which the learner answers from the alert and the
  equipment context. After that the human hands are off: the agent runs VSS
  analysis with the `frag` knowledge-retrieval tool enabled, and the learner
  watches the tool calls, the retrieved documents (manuals, logs, schedule),
  and the reasoning appear on screen (~90 s–250 s of visible agent work).
  Depends on: Module 3 (the alert and its clip reference). Teaching points: the
  HITL kick-off pattern (the blueprint proven path — one instruction, four
  prompts, then autonomy), reading the agent's visible tool calls and retrieved
  documents as evidence (not just the final answer), and where the RAG
  retrieval enters the flow (the `frag` tool calls the RAG server over
  collection `demo_corpus`). Environment delta: assumes Module 3 state (alert
  raised); leaves behind the generated video summary report and — as its action
  step completes — the work order filed in the mock CMMS (Module 5 verifies
  it). Success criteria: the four HITL parameters are collected; tool calls +
  retrieved documents + reasoning are visible in the OpenClaw UI; the report
  is generated citing RAG-sourced documents; no human input after the last
  HITL answer.
- **Module 5 — Verify the Work Order** (10 min). Beat 4 — the aha, verified.
  The learner opens the mock CMMS at `http://localhost:8090` and finds the new
  work order at the **top** of a list that was empty in Modules 1–3. They open
  the detail page and read the diagnosis: title, description, equipment
  (M-3021), priority, and the citations **grouped by source** (rag / vss /
  agent) — the evidence panel; the `anomaly_ref` matches the alert recorded in
  Module 3. They check the notification feed (`/notifications`): the in-app
  notification was delivered atomically with the work order. Two `curl` calls
  against the API (`GET /api/v1/work-orders`, `GET
  /api/v1/work-orders/{id}`) confirm the same state through the contract the
  agent used. From the single instruction in Module 4, no human step produced
  this — that is the success criterion the whole lab exists to demonstrate.
  Depends on: Module 4 (the agent run that filed the work order). Teaching
  points: verifying the agent's action through the downstream system's own API
  and UI (the action target, not the agents claims), reading grouped citations
  as the evidence trail (which document, which clip, which inference), the
  atomic work-order + notification pair, and the documented non-idempotency
  (a retried agent action would create a second work order — the UI shows
  both). Environment delta: assumes Module 4 state (work order filed); leaves
  behind the verified work order + notification in the mock CMMS. Success
  criteria: the work order appears at the top of the list with equipment
  M-3021; the detail page shows citations grouped by source type; the
  notification feed holds the matching in-app notification; the API `GET`
  returns the same entity.
- **Module 6 — Triage a Second Anomaly** (20 min). Beat 5 — the optional
  extension that proves the agent decides. The learner injects a second
  anomaly of a different kind (a different clip, or the same clip with adjusted
  trigger parameters in the HITL prompts) and runs the same one-instruction
  flow. This time the agents verdict differs: the diagnosis lands as a
  **monitoring note** — no work order. The learner finds the note in the mock
  CMMS (`/notes`) and confirms the work-order list has not grown. The contrast
  with Module 5 is the lesson: the same pipeline, the same instruction shape,
  a different engineering outcome — the agent triaged, it did not
  script-follow. Depends on: Modules 4–5 (the work-order path to contrast
  against). Teaching points: triage as an agent output (note vs. work order —
  the downstream action the triage decides), the monitoring-note entity
  (deliberately standalone — not linked to a work order), and what would make
  the learner trust this in a real deployment (visible reasoning + the
  documented, evidenced response). Environment delta: assumes Modules 1–5
  state; leaves behind the monitoring note in the mock CMMS and an unchanged
  work-order list. Success criteria: the second run completes with the agents
  reasoning visible; a monitoring note appears in the mock CMMS notes list;
  the work-order list is unchanged from Module 5.

## Environment & lab prep summary (points at lab-prep.md)

The environment is fully pre-provisioned before the learner starts: a single
vCD VM (Ubuntu 24.04, 32 vCPU / 256 GB RAM / 2 TB NVMe, one RTX PRO 6000 96 GB
on full PCIe passthrough) running the entire stack — the auth-shim, the VSS
stack (agent, LVS, RT-VLM with the local 8B-class VLM), the Enterprise RAG
stack (server + six retriever NIMs), the NemoClaw sandbox, and the mock
work-order service — with the RAG index already built (collection
`demo_corpus`) and the pre-recorded clips and corpus in place. Nothing in this
guide installs software, pulls images, starts or stops the stack, or mutates
the environment; the learner only reads state, plays clips, and types one
instruction. The learner is the single OS user on their own VM (SSH access per
the instructor runbook); the mock CMMS is deliberately unauthenticated (VM-
local port, single user). The full handoff for the environment team —
baseline, preloaded software, credentials, URLs/hosts/ports, network access,
expected starting artifacts, and the sixteen verification checks — lives in
`lab-prep.md`.

## Open questions / assumptions

- **Guide ID is assigned.** `HOL-1362-01` is the platform-assigned ID (H1 and
  catalogue frontmatter carry the same value — verified by the launch check at
  publish).
- **LVS UI URL/port and OpenClaw UI URL are prep-recorded** (release-dependent
  — spec 02 open item). The guide references the values recorded in
  `prep-log.md` at prep; the OpenClaw dashboard port-forward default is 18789,
  which the credentials block carries as the fallback.
- **Beat-5 fixture content is curated at prep (ADR-004).** The second
  anomaly clip is swapped in at environment prep with the rest of the fixture
  content; if it is not available in a session, Module 6 degrades to running
  the same clip with adjusted HITL parameters (the module body states both
  paths).
- **Agent-run duration varies** (~90 s observed to ~250 s for the single
  measured end-to-end run; RAG retrieval and LLM fusion add only seconds — the
  VLM is the whole cost). Module 4's budget (20 min) covers the long pole plus
  reading.
- **Time budget.** 15 + 15 + 15 + 20 + 10 + 20 = 95 min of modules, + ~5 for
  the Introduction = 100 = `duration_minutes`, within the 30–120 min guide
  bound.
- **The mock CMMS port is a single constant** in one compose file (spec 02
  open item): if the OpenClaw UI ever lands on :8090, the lab owner resolves
  it at prep — the guide carries :8090 as the CMMS surface throughout.
