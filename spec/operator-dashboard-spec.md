# Operator Dashboard — Specification

**Video-triggered agentic operations with a human approval gate**
Extension to `nvidia-vss-rag-nemoclaw-lab` · manufacturing pack first, pack-agnostic framework · single learner per VM

---

## 0. What this changes

This spec was rewritten after reading the repo. Two earlier assumptions were
wrong and both mattered.

**There is no HITL approval gate today.** Beat 4 — the lab's stated "aha" — is
autonomous: after the learner's single kick-off instruction, NemoClaw files the
work order with no human step. The gate is therefore not an addition; it
replaces the lab's central beat. Confirmed decision: **the gate replaces it,
and the lab beats change.**

**There is no Gateway to extend.** The service architecture I assumed lives in
`nemoclaw-lab-cl`, not here. This repo has ten spec documents, a prep chain,
demo scripts, fixtures, and one application — `mock-wo`. Confirmed decision:
**mock-wo becomes the dashboard backend.**

### Revision 2026-09-13 — review decisions

A review against the repo raised eight design questions. These are now decided:

| # | Question | Decision | Where |
|---|---|---|---|
| D1 | The agent could reach the decision endpoint on :8090 | **Operator surface on a separate port (:8091)** that is never in the NemoClaw policy | ADR-V08, §6.2 |
| D2 | Nothing carried skill/token events to mock-wo | **OpenClaw plugin hook** posts agent telemetry to mock-wo | ADR-V09, §6.3 |
| D3 | Audience: self-driven visitor or guided lab? | **Guided HOL lab (HOL-1362-01) is primary.** The dashboard serves the guide | §1, §2 |
| D4 | Skill roster may need VSS services beyond the LVS profile | **Verify first, then decide** — before M4a | ADR-V05, O17 |
| D5 | Per-pack collection vs a baked `KNOWLEDGE_COLLECTION` | **Pack activation restarts vss-agent only**, never RT-VLM | §4a, §5.1 |
| D6 | React/Vite reverses `spec/03` | **Accepted** — vendored, multi-stage build; `spec/03` to be amended | §2, §10 |
| D7 | Which packs are in this build? | **Manufacturing only.** Other packs are future work | §11, §12 |
| D8 | Build doc vs the root plan file | `context-aware-video-agent-build-doc.md` **supersedes** it | `spec/01` |

### On giving up the autonomous aha

Worth being deliberate about this, because the current beat is a good one. What
replaces it is arguably stronger for an enterprise audience: not "it did the
whole thing by itself" but "it did all the work and stopped exactly where a
human should decide." The first invites the objection everyone in the room is
already forming. The second answers it before it's asked.

The design keeps one autonomous outcome to make the point sharper: **monitoring
notes file without a gate, work orders require approval** (§5.4). The gate is
proportionate to consequence rather than blanket, which is how a real system
would be built and reads as considered rather than cautious.

---

## 1. Purpose and scope

Give a learner working through HOL-1362-01 a legible account of an agentic
operations loop: something happens on camera, an agent investigates it against the
organisation's documentation, proposes an action with reasoning, evidence and
cost, and a human decides.

### Goals, in priority order

1. **Legibility** — at any moment it is clear what stage the system is in.
2. **Provenance** — every claim traces to a video timestamp or document
   passage in one click.
3. **Consequence** — the decision has visible stakes in both directions.
4. **Pack agnosticism** — adding a vertical is content authoring, not code.

### Non-goals

- Multi-user or authenticated operation. One learner per VM, as today.
- Replacing the OpenClaw UI for agent configuration.
- Real CMMS integration — remains an explicit lab non-goal.
- Kubernetes. Compose only, for the reasons already recorded in `01-overview`.
- Unguided booth use as a design driver. The dashboard should make sense without
  the guide open, but the guide's module structure decides the flow (D3).
- Packs beyond manufacturing in this build (D7). The framework stays
  pack-agnostic so they remain content work later.

---

## 2. Impact on the existing lab

The gate change is not confined to the UI. These artefacts change.

| Artefact | Change |
|---|---|
| `guide.md` Module 5 | "Verify the Work Order" → "Decide on the Proposal". The learner now acts, not just observes. |
| `guide.md` Module 4 | Diagnosis is watched in the dashboard rather than only the OpenClaw UI |
| `guide.md` Module 3 | Fault injection moves to a dashboard button; alert rules armed via `vss-manage-alerts` |
| `guide.md` Module 1 | Uses `vss-deploy-profile` so the learner meets the skill mechanism on the deployment side before seeing it at runtime — a bookend. **Open (O23):** prep pre-starts the stack under start-order discipline, so the learner cannot redeploy; the module likely shows the skill driving a read-only status/verify path instead |
| `.holagent/05-verify-the-work-order/` | Module plan rewritten |
| `.holagent/concept.md` | Beat 4 restated; success criterion 2 changes |
| `spec/01-overview.md` | Core feature 4 restated |
| `spec/02-architecture.md` | mock-wo contract expands substantially; second port :8091 |
| `spec/03-build-decisions.md` | UI row reverses: React + Vite SPA, vendored, multi-stage Dockerfile with a Node build stage (D6). Compose service publishes 8090 and 8091 |
| `spec/05-test-strategy.md` | Frontend build and tests added; gate-bypass test (agent port cannot decide) |
| `spec/09-environment-footprint.md` | Pending O17 — any VSS services the skill roster needs beyond the LVS profile |
| `scripts/prep/40-nemoclaw.sh` | `LAB_ENDPOINTS` drops 8081; keeps 8080 and 8090; **never** 8091. Installs the telemetry plugin (ADR-V09) |
| RAG compose | Host ports 8071/8072 via a compose override file in this repo, not an edit to the vendor file (ADR-V06) |
| `mock-wo/tests/test_api.py` | `POST /api/v1/work-orders` is no longer the agent's entry point |
| NemoClaw skill / prompt | Agent posts a **proposal**, not a work order |
| NemoClaw network policy | `mock-wo:8090` only. 8081 removed (ADR-V06); the operator port 8091 is never added (ADR-V08) |

### Success criteria, restated

1. Explain the alert → diagnosis → proposal → decision flow and where RAG
   context enters it.
2. Reproduce from a clean start: inject a fault, watch the agent work, decide,
   see the work order appear only after the decision.
3. Point at the agent's evidence on screen — video moments and retrieved
   passages — as the basis of the diagnosis.
4. State why the reasoning LLM is shared and off-VM while the video and
   retrieval models are local.
5. **New:** explain why the work order is gated and the monitoring note is not.

---

## 3. The framework

Six stages, identical across every pack. This is the state machine, the SSE
event vocabulary, and the visual progress rail.

| Stage | System | VSS Agent Skill | Operator sees |
|---|---|---|---|
| **Monitor** | Fleet at rest, alert rules armed | `vss-manage-alerts` | Fleet grid, all normal |
| **Detect** | Alert fires and is verified; incident opened, agent woken | `vss-manage-alerts` | Tile changes state, workspace opens |
| **Gather context** | VSS analyses; frag queries RAG; archive searched for precedent | `vss-generate-video-report-rag`, `vss-search-archive`, `vss-query-analytics` | Live stream — captions, retrieval, precedent, citations |
| **Propose** | Root cause formed, parts checked, evidence clips extracted, action drafted | `vss-manage-video-io-storage` | Analysis and proposal populate |
| **Decide** | System blocks; no work order exists yet | `vss-ask-video` (operator-driven) | Approve / Modify / Deny, with impact — and the ability to interrogate the footage first |
| **Act** | Work order created server-side; notification fires | — | Confirmation, audit entry, fleet normal |

An incident never runs two stages at once and never moves backwards, so the rail
is always truthful. That is what makes it worth showing.

**Monitor is a fleet state, not an incident stage.** The incident's `stage` enum
starts at `detect`. The rail shows Monitor as lit before the incident exists.

**The one permitted skip is Decide, for monitoring notes.** A `monitoring_note`
proposal is auto-filed (§5.4), so the incident goes Propose → Act and the rail
marks Decide as *not required*, not as pending or skipped silently. That visible
difference is the proportionality point from §0.

The skill column is not decoration. The agent **selects** these from an
installed catalog rather than following a fixed procedure, and the dashboard
shows the selection happening (§8.9). This is what turns "the agent decides
rather than script-follows" from a claim into something visible.

---

## 4. Architecture

```
                 shared off-VM endpoint (pre-provisioned)
                 nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
                                ▲ x-api-key
                                │
┌───────────────────────────────┴────────────────────────────────────┐
│ vCD VM — Ubuntu 24.04 · 32 vCPU · 256 GB · 2 TB · RTX PRO 6000 96GB │
│                                                                     │
│  Browser ──► mock-wo :8091   OPERATOR PORT      ← ADR-V08           │
│              ├─ React SPA (bundled, served static)                  │
│              ├─ Operator API: decision, inject, reset, audit        │
│              ├─ SSE       /api/v1/stream                            │
│              ├─ Incident state machine                              │
│              └─ Approval gate + single-use tokens                   │
│              mock-wo :8090   AGENT PORT                             │
│              ├─ Agent API: proposals, evidence, reads               │
│              ├─ Telemetry  /api/v1/agent-events   ← ADR-V09         │
│              └─ ragproxy   /ragproxy/v1/*         ← ADR-V02         │
│              one process, one SQLite (WAL), one event bus           │
│                    │                    ▲                           │
│         wake hook  │                    │ POST /proposals   (:8090) │
│                    ▼                    │ plugin telemetry  (:8090) │
│  NemoClaw (OpenClaw sandbox + OpenShell gateway)                    │
│    telemetry plugin — tool-call + token hooks          ← ADR-V09    │
│    curated VSS Agent Skill catalog (symlinked, per-pack — ADR-V05)  │
│      vss-manage-alerts · vss-generate-video-report-rag              │
│      vss-search-archive · vss-query-analytics                       │
│      vss-manage-video-io-storage · vss-ask-video                    │
│                    ▼                                                │
│  VSS agent :8000 ──frag──► mock-wo ragproxy ──► RAG :8081/v1        │
│   ├─ LVS :38111                       (host 8071 — ADR-V06)         │
│   ├─ RT-VLM :8018 ◄─ cosmos3-reasoner:1.7       └─ 6 NIMs (GPU)     │
│   └─ VST / Redis / Kafka / Elasticsearch 9.3.0 (shared)             │
│                                                                     │
│  auth-shim :8080 (nginx:1.27-alpine)                                │
└─────────────────────────────────────────────────────────────────────┘
```

### ADR-V01 — The agent's only knowledge path is the VSS frag tool

The agent holds no direct RAG tool. It asks VSS; VSS retrieves via frag.

*Rationale.* One retrieval path, one place citations are produced, one prompt
surface to tune. Matches the blueprint's intended design.

*Consequence.* Retrieval is invisible to anyone watching the agent's tool
calls. Hence ADR-V02.

### ADR-V02 — mock-wo proxies RAG so retrieval is observable

`RAG_SERVER_URL` becomes `http://mock-wo:8090/ragproxy/v1` instead of
`http://rag-server:8081/v1`. mock-wo forwards verbatim and emits an SSE event
per query and per result set.

*Rationale.* Gives the Gather-context stage real streaming content without
patching VSS or RAG. Retrieval becomes visible as it happens rather than
appearing retroactively as footnotes.

*Consequence.* mock-wo sits on the retrieval hot path. Retrieval is ~1.3% of
end-to-end runtime (~1.69 s measured), so the latency budget is ample, but the
proxy must forward streaming responses without buffering, must not alter
payloads, and must pass failures through transparently. It is an observer,
never a participant. The `/v1` suffix remains load-bearing.

### ADR-V03 — Analysis always runs live

No cached results, no replay. Roughly four minutes elapse between Detect and
Propose; §9 specifies how that time is filled.

*Rationale.* A learner who suspects the demo is scripted stops believing
everything else in it.

### ADR-V04 — Work-order creation is server-side only

The agent can create a **proposal**. It cannot create a work order. Work-order
creation happens inside mock-wo when an operator approves, guarded by a
single-use token minted server-side, bound to one proposal ID, never present in
the agent's context or prompt.

*Rationale.* Carried over from the `nemoclaw-lab-cl` HITL design, which got
this right. The gate is a real security property — an agent that cannot reach
the execute path cannot bypass the human — not merely a UX affordance. This is
worth saying out loud in the guide; it is the part a security-minded audience
will care about.

*Consequence.* Breaking contract change (§6.1) and a rewrite of the agent's
action step.

*Enforcement — the token is not the gate.* It is minted **after** an operator
approves, so it prevents a second decision on the same proposal, not an agent
that calls the decision endpoint itself. What prevents that is ADR-V08: the
decision path lives on a port the sandbox's network policy never grants.

### ADR-V05 — The agent gets a curated skill catalog, scoped per pack

VSS Agent Skills have two documented usage patterns: **deployment** (a coding
agent brings the stack up) and **runtime** (an always-on agent such as NemoClaw
loads the same skills and becomes the operational interface). This build uses
both — deployment in the prep chain and Module 1, runtime as the spine of the
incident loop.

The lab currently installs one skill. This spec installs **six or seven per
pack**, not the full catalog of sixteen.

*Rationale.* Two reasons, one narrative and one practical.

Narratively, a single hardcoded skill means the agent executes a procedure. A
catalog means it chooses, and the choosing is the most direct evidence
available that reasoning is happening. Beat 5 gains real force: the second
anomaly produces a different *skill sequence*, not merely a different verdict.

Practically, skills are **Early Access, explicitly not for production, and
validated against Claude Opus 4.6**. The shared endpoint serves Nano Omni
30B-A3B — 3 B active parameters. Tool selection across sixteen candidates is
exactly where a small MoE picks a plausible neighbour instead of the right
tool. A narrow catalog raises selection accuracy, keeps the skill trace
readable, and gives a better answer to a security-minded audience than
"we installed everything."

*Consequence.* Each pack declares a skill roster (§5.1). Skills are symlinked
from the cloned VSS checkout and picked up without an agent restart, so a pack
switch can swap the installed set. Skill-selection accuracy against Nano Omni
must be measured before the storyline depends on it (**O11**).

*Footprint unverified — D4, **O17**.* `vss-search-archive` (fusion search over
Cosmos Embed1 embeddings plus CV attribute matching), `vss-query-analytics`, and
`vss-manage-alerts` in CV-verification mode plausibly depend on VSS services the
LVS profile does not deploy — the video-embedding, detection/tracking and
video-analytics-API services whose *deploy* skills are excluded just below.
Nothing of the sort is in the ~70 GB budget (build doc §3) or `spec/09`.

Before M4a, check each roster skill against the v3.2.1 catalog for the services
and GPU it needs. If a skill needs something outside the budget, the choice at
that point is to drop the skill or re-size — not to discover it at M5a. The
roster below is provisional until that check runs.

**Skills deliberately excluded:** `vss-deploy-detection-tracking-2d` / `-3d`,
`vss-generate-video-calibration`, `vss-setup-behavior-analytics`,
`vss-deploy-video-embedding`, `vss-setup-video-analytics-api`,
`vss-deploy-dense-captioning`. Real capabilities, but they belong to the
warehouse and smart-city workflows, not this one. Every skill left out is a
distractor removed from the selection problem.

---

### ADR-V06 — RAG is not published to the host; port allocation is explicit

**Resolves O3.** Two things reduce the reported 8081 conflict before any port
is moved.

First, the conflict in [PR #2027](https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization/pull/2027)
arises on the **`install-vllm` path** — NemoClaw's managed local-inference
onboarding applies a local-inference policy that already claims 8081, so a
subsequent `policy-add` for 8081 is a duplicate. This build uses
`NEMOCLAW_PROVIDER=custom` against the shared endpoint through the auth-shim
and never invokes `install-vllm`, so the local-inference policy may not be
applied at all. **Verify before engineering around it.**

Second, and independent of that: under ADR-V01 and ADR-V02 the agent never
reaches RAG. Knowledge goes agent → VSS → frag → mock-wo ragproxy → RAG.
**NemoClaw's network policy therefore needs no 8081 entry whatsoever**, which
removes the duplicate-policy condition by construction rather than by
workaround.

That leaves only host-side convenience. RAG's ports exist today so a human can
curl them; nothing in the running system needs them published.

#### Port allocation

| Service | Container port | Host publish | Reachable by |
|---|---|---|---|
| auth-shim | 8080 | 8080 | VSS, RAG, NemoClaw, operator |
| mock-wo agent port (agent API + telemetry + ragproxy) | 8090 | 8090 | NemoClaw, VSS |
| mock-wo operator port (SPA + operator API + SSE) | 8091 | 8091 | operator browser only — **never** in the NemoClaw policy (ADR-V08) |
| VSS agent | 8000 | 8000 | NemoClaw, operator |
| LVS backend | 38111 | 38111 | start gate, operator |
| RT-VLM | 8018 | 8018 | start gate, operator |
| **RAG server** | **8081** | **8071** | **mock-wo ragproxy only** |
| **RAG ingestor** | **8082** | **8072** | **prep only** |
| LLM NIM | 30081 | — | must not be running |

**Container ports are unchanged.** Only the host mapping moves, so nothing
inside either blueprint is patched. The remap is a compose override file carried
in this repo and passed with a second `-f`, not an edit to the vendor compose
file. Container-to-container traffic keeps using `rag-server:8081` on
`demo-net`, which is what the ragproxy upstream points at.

If host access is not wanted at all, drop the `ports:` mapping for both
services entirely; the ragproxy still works. Publishing them on 8071/8072 is
the friendlier default for prep and debugging.

#### Dependencies to update

| Where | Change |
|---|---|
| RAG compose `ports:` (override file in this repo) | `8081:8081` → `8071:8081`, `8082:8082` → `8072:8082` |
| `scripts/prep/30-verify-stack.sh` | host health checks → `localhost:8071/v1/health` |
| `scripts/prep/25-ingest-corpus.sh` | ingest → `localhost:8072/v1/documents` |
| `lab-prep.md`, `guide.md` | verification steps |
| `spec/02-architecture.md` | endpoint contract table |
| mock-wo ragproxy upstream | **no change** — `http://rag-server:8081/v1` |
| VSS `RAG_SERVER_URL` | **no change** — already the ragproxy under ADR-V02 |
| NemoClaw network policy (`40-nemoclaw.sh` `LAB_ENDPOINTS`) | **remove** 8081; keep `mock-wo:8090`; **never add 8091** — assert its absence |

Note `30081` is unrelated despite the resemblance — it is the VSS local LLM NIM
that must be absent because generation is remote. Don't let the digits confuse
a prep check.

---

### ADR-V07 — The shared model is one variable, swappable without a rebuild

**Resolves O11 as a build decision:** build on Nano Omni, measure skill
selection, swap the model if the numbers justify it (§12, M4a).

For that to be a cheap decision later, it has to be designed in now.

The constraint is real and comes from `nemoclaw-lab-cl`: NemoClaw bakes
`LLM_BASE_URL`, `LLM_MODEL` and `LLM_API_KEY` into the sandbox **at onboard
time**. Editing `.env` does not move a running agent. Without a repoint path, a
model swap means re-onboarding — rebuilding the sandbox image and resetting the
agent's configuration.

Three requirements follow, specified in §4a rather than left as intent.

The auth-shim already makes the endpoint swappable without touching any
consumer. §4a extends the same property to the model identifier.

**If the swap is needed**, the candidates in ascending order of footprint are:
a larger Nemotron on the shared endpoint (no local GPU cost, the likely first
move), or a locally hosted model — which would contend with the VLM's 40% of
the card and is a materially different sizing conversation.

---

### ADR-V08 — The operator surface is on a separate port the agent cannot reach

**Resolves D1.** The sandbox reaches mock-wo through a network-policy entry for
a host and port, with `access: full`. Anything on that port is reachable by the
agent. In the first draft of §6.2 that included
`POST /proposals/{id}/decision`, and mock-wo is unauthenticated by design (§1).
The agent could have approved its own proposal.

mock-wo therefore listens on **two ports from one process**:

| Port | Surface | Reachable by |
|---|---|---|
| **8090 — agent** | Proposal and evidence writes, telemetry ingest, read-only incident/fleet/parts/work-order routes, ragproxy, `/health` | NemoClaw sandbox, VSS (ragproxy) |
| **8091 — operator** | React SPA, SSE stream, decision, inject, pack activate, demo reset, audit, `PATCH` work orders | Operator browser |

The NemoClaw policy grants 8090 and never 8091.

*Rationale.* Enforcement lives in the sandbox network policy, not in a prompt
or a naming convention. It gives the same property `nemoclaw-lab-cl` got from a
separate Gateway service, without adding a service, and without adding
authentication (which stays a non-goal).

*Consequence.*

- Each route is registered to exactly one port. An operator route reachable on
  8090 is a **security defect**, not a bug. Test it: every operator route
  returns 404 on the agent port, at the router level rather than via
  middleware that could be bypassed by a path variant.
- Two ASGI apps share one SQLite connection pool and one in-memory event bus in
  a single process (two uvicorn servers in one event loop). That keeps the
  single-process SQLite discipline from `spec/03` and lets agent-port writes
  reach operator-port SSE without a broker.
- `40-nemoclaw.sh` asserts 8091 is absent from the generated policy, so a
  future edit that "helpfully" adds it fails prep loudly.

### ADR-V09 — Agent telemetry comes from an OpenClaw plugin hook

**Resolves D2.** The activity stream, skill trace and §9's wait design all
depend on `skill.invoked`, `skill.completed` and `agent.token`. The agent's
reasoning happens inside OpenClaw, and nothing in the first draft carried those
events to mock-wo.

A small OpenClaw plugin, installed into the sandbox at prep, hooks tool and
skill invocation, completion and model output, and posts them to
`POST /api/v1/agent-events` on the agent port. mock-wo validates them, assigns
`seq`, and rebroadcasts them on SSE. The pattern follows `nemoclaw-lab-cl`'s
`nemoclaw-infra-tools` plugin.

*Rationale.* Deterministic. It does not depend on a 3B-active model remembering
to narrate its own work (self-reporting), or on the sandbox's transcript format
staying stable (log tailing).

*Consequence.*

- **Telemetry is display-only.** Agent events never change incident stage,
  proposal state or evidence. Those come only from the state machine and the
  typed agent routes. The sandbox can reach 8090, so the agent could forge
  telemetry. The worst outcome is a misleading activity row, not a state change.
- `rationale` on `skill.invoked` is whatever the model said before the call.
  When it said nothing, the chip shows no rationale. A rationale is never
  synthesised.
- Which hook points OpenClaw exposes at NemoClaw v0.0.118 is unverified
  (**O24**). A skill may surface as a `SKILL.md` read followed by ordinary tool
  calls rather than as a discrete event, in which case the plugin maps one to
  the other. If token streaming is not hookable, `agent.token` degrades to
  per-turn text; skill events remain.
- §9 treats skill events as the guaranteed fallback. That holds once O24 is
  verified, not before.

---

## 4a. Repoint contract

The operation: change which model the system runs on, across all three
consumers, without rebuilding anything and without disturbing the GPU.

Ops entry points live under `scripts/ops/`, next to the prep chain. The repo has
no Makefile, and this spec does not add one.

### The one rule

**A repoint must not restart the VLM.**

If the procedure does `docker compose down/up` on the VSS stack, the VLM
re-profiles the GPU on the way back and you are into start-order discipline
again — gate on RT-VLM, five to fifteen minutes of NIM load, and the co-residency
budget re-established from scratch. Restart the **agent container only**.

This is the failure that gets discovered at 09:00 on a demo morning. It belongs
in the contract, not in someone's memory.

### The single variable

`config/shared-llm.env` — the only place a model identifier appears.

```bash
SHARED_LLM_MODEL=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
SHARED_LLM_ENDPOINT=https://<upstream-host>/v1
SHARED_LLM_API_KEY=<x-api-key value>
```

Consumers reference it, never restate it:

| Consumer | Variable | Sourced from |
|---|---|---|
| VSS LLM role | `LLM_ENDPOINT_URL` → shim; model named in the LVS `.env` | `${SHARED_LLM_MODEL}` |
| RAG generation | `APP_LLM_MODELNAME`, `APP_LLM_SERVERURL` | `${SHARED_LLM_MODEL}` |
| NemoClaw | `NEMOCLAW_ENDPOINT_URL`, model in the sandbox config | `${SHARED_LLM_MODEL}` |
| auth-shim | `UPSTREAM_URL`, `SHARED_API_KEY` | `${SHARED_LLM_ENDPOINT}`, `${SHARED_LLM_API_KEY}` |

Three literal model strings in three files will drift. One will not.

### Procedure — `scripts/ops/repoint-llm.sh`

Ordered. Each step gates on its own verification before the next runs; a
failure stops the sequence rather than leaving the system half-repointed.

**1 · Validate the target before changing anything.**

```bash
curl -sf "${SHARED_LLM_ENDPOINT}/models" -H "x-api-key: ${SHARED_LLM_API_KEY}" \
  | jq -e --arg m "${SHARED_LLM_MODEL}" '.data[] | select(.id == $m)'
```

Fail here if the model is not served. Repointing three consumers at a model
that does not exist is a much worse morning than a failed precondition.

**2 · Re-render and reload the shim.** `envsubst` the template, then
`nginx -s reload` — not a container restart. Existing connections drain.

Gate: `/v1/models` through the shim lists the new model.

**3 · Repoint RAG.** Update `APP_LLM_MODELNAME`, restart the **rag-server**
container only. The six retrieval NIMs and Elasticsearch are untouched — they
hold no model identity and restarting them would disturb GPU allocations for
no reason.

Gate: `/v1/generate` returns; the shim access log shows the new model.

**4 · Repoint VSS.** Update the model name in the LVS `.env`, restart the
**vss-agent** container only.

Gate: agent `/health` returns. **Confirm RT-VLM was not restarted** —
`docker inspect -f '{{.State.StartedAt}}'` on the RT-VLM container must be
unchanged, and `nvidia-smi` must still show ~38 GB held by the same PID. This
check is the enforcement of the one rule above; without it the rule is a
comment.

**5 · Repoint NemoClaw.** The awkward one.
`LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` are baked into the sandbox at
onboard time, so editing `.env` alone does not move a running agent. Use the
documented runtime switch, which does not require a sandbox restart:

```bash
openshell inference set --provider custom --model "${SHARED_LLM_MODEL}"
```

Gate: `openclaw nemoclaw status --json` reports the new model.

**Fallback.** If the runtime switch does not take, re-onboarding
(`init_nemoclaw.sh`, fresh OpenClaw) is the documented reset — but it rebuilds
the sandbox image and resets agent configuration including the skill roster.
Treat it as recovery, not routine. **Verify the runtime-switch path works
before you need it** (O16).

**6 · Run the drift check.**

### Drift check — four probes

`scripts/ops/doctor.sh`, run after every repoint, after every pack switch, and
on a timer.

| Probe | Command | Failure means |
|---|---|---|
| Shim | `GET /v1/models` via :8080 | Shim not re-rendered, or upstream dropped the model |
| RAG | `APP_LLM_MODELNAME` in the running container env | RAG restart missed or reverted |
| VSS | LLM model name in the running vss-agent container env | vss-agent restart missed or reverted |
| NemoClaw | `openclaw nemoclaw status --json` | Sandbox still on the baked-in model |

All four must equal `${SHARED_LLM_MODEL}`. Any mismatch prints the expected
value, the actual value, and the specific step to re-run.

Why four probes and not one: the consumers drift **independently**. NemoClaw
is the one that silently stays behind, because its identity is baked rather
than read. A partial repoint presents as "the agent got worse" while RAG and
VSS look fine — which is an expensive thing to chase under time pressure, and
exactly the failure this check exists to make impossible.

### Pack switch — the same rule

**Resolves D5.** A pack's `knowledge_collection` (§5.1) must become the VSS
agent's `KNOWLEDGE_COLLECTION`, which the agent reads at container start. A
pack switch is therefore a restart of **vss-agent only**, under the same rule
as a repoint.

`scripts/ops/activate-pack.sh <pack_id>`, ordered and gated:

1. **Validate first.** The collection exists in RAG and is non-empty. Fail
   before touching anything.
2. Rewrite `KNOWLEDGE_COLLECTION` in the LVS `.env`.
3. Restart **vss-agent only**. Gate: `/health`, plus the RT-VLM
   `StartedAt`/PID assertion from repoint step 4.
4. Swap the skill-roster symlinks (O14).
5. Call `POST /api/v1/packs/{pack_id}/activate` on the operator port, so mock-wo
   loads the pack's fleet, incidents and parts.
6. Run `doctor.sh`, plus a fifth probe: the agent's `KNOWLEDGE_COLLECTION`
   equals the active pack's.

The container work is host-side, in the script. **mock-wo is never given the
Docker socket.** A socket-mounted mock-wo would be root on the host, one port
away from the sandbox. The activate endpoint only switches mock-wo's own pack
state.

In this build there is one pack (D7), so `activate-pack.sh` runs once, at prep.
It is specified now so the second pack is content work and not a redesign.

### What repoint does not cover

Changing the *endpoint* rather than the model, changing the auth scheme away
from `x-api-key`, or moving to a locally hosted model. The first two are shim
edits with the same procedure minus step 1's assumptions; the third is a GPU
budget change and belongs in a sizing conversation, not a config command.

---

---

## 5. Data model

Extends the existing mock-wo schema. Existing entities are preserved where
possible; changes are marked.

### 5.1 Pack — new, YAML not DB

```yaml
pack_id: manufacturing-motor-drive
display_name: Manufacturing — Motor Drive
knowledge_collection: demo_corpus      # becomes vss-agent KNOWLEDGE_COLLECTION — §4a pack switch

fleet:
  - asset_id: M-3021
    display_name: Motor drive M-3021
    make_model: ABB M3BP 200
    commissioned: 2019-04
    location: Line 3, Hall B
    baseline_clips: [clip-normal-01.mp4, clip-normal-02.mp4]
    service_history:
      - date: 2025-07-14
        summary: Bearing inspected, within tolerance
        technician: J. Moore

incidents:
  - incident_id: M3021-BEARING-THERMAL
    asset_id: M-3021
    clip: clip-anomaly-01.mp4
    outcome_class: work_order            # or monitoring_note
    downtime_cost_per_hour: 4200
    callout_cost: 850
    ambiguous: false                     # authoring/test expectation only — never sent to the agent
    # Precedent is FOUND, not declared — vss-search-archive fusion search
    # over Cosmos Embed1 embeddings + CV attribute matching. These clips are
    # ingested into the archive at prep so the search has something to find.
    archive_seed_clips:
      - { date: 2026-09-02, clip: clip-anomaly-01a.mp4 }
      - { date: 2026-09-09, clip: clip-anomaly-01b.mp4 }

parts:
  - part_number: 6312-2RS
    description: Deep-groove bearing, drive end
    on_hand_local: 0
    on_hand_regional: 2
    oem_lead_days: 6

# ADR-V05 — the installed skill catalog for this pack
skills:
  - vss-manage-alerts
  - vss-generate-video-report-rag
  - vss-search-archive
  - vss-query-analytics
  - vss-manage-video-io-storage
  - vss-ask-video
```

Packs live in `packs/<pack_id>/` with `pack.yaml`, `clips/`, and `corpus/`.
Existing `fixtures/` content migrates into `packs/manufacturing-motor-drive/`
(§11).

**On `ambiguous`.** The flag records what the pack author expects: that the
evidence for this incident genuinely supports two root causes. It is used by
tests and the authoring checklist. It is **never** exposed to the agent through
any agent-port route. An agent told in advance that an incident is ambiguous is
performing uncertainty, not reaching it, which ADR-V03 rules out. If the agent
does not produce two candidates on the flagged incident, that is a finding about
the clip or the corpus, not something to fix by prompting.

**Cost and parts data are agent-readable.** `downtime_cost_per_hour`,
`callout_cost`, `parts` and `service_history` reach the agent through the
read-only agent routes (§6.2). The Propose stage "checks parts" against them.

**On `archive_seed_clips`.** The earlier draft declared prior occurrences as
static YAML, which made the temporal beat a stated fact rather than a finding.
Instead, the clips are ingested into the video archive at prep time and the
agent uses `vss-search-archive` to look for the same signature. The beat is
identical to watch and materially more honest — and it fails visibly if the
signature genuinely isn't there, which is the correct behaviour. The seed clips
named above do not exist yet (O18), and archive search itself is subject to the
O17 footprint check.

### 5.2 Incident — new table

| Field | Type | Notes |
|---|---|---|
| `id` | UUIDv4 | |
| `pack_id` | string | |
| `asset_id` | string | |
| `incident_id` | string | from pack manifest |
| `stage` | enum | `detect \| gather \| propose \| decide \| act \| closed` — no `monitor` (fleet state, §3). `decide` is skipped only for `monitoring_note` |
| `clip` | string | |
| `opened_at` / `closed_at` | ISO-8601 UTC | |

### 5.3 Evidence — new table, supersedes inline citations

The existing `Citation` (`source_type`, `source_id`, `quote`) is a strict
subset. Evidence adds the fields the linking behaviour needs.

| Field | Type | Notes |
|---|---|---|
| `id` | UUIDv4 | |
| `incident_id` | FK | |
| `source_type` | enum `vss \| rag \| agent` | **unchanged from existing** |
| `source_id` | string ≤ 200 | `clip-anomaly-01@00:42`, `manual-01#p12` — **unchanged** |
| `quote` | string ≤ 2000 | **unchanged** |
| `claim` | string ≤ 500 | *new* — what the agent asserts from this |
| `t_start` / `t_end` | float, nullable | *new* — seconds, for `vss` sources |
| `document_anchor` | string, nullable | *new* — section or page for `rag` sources |
| `confidence` | enum `high \| medium \| low` | *new* |

`WorkOrder.citations` is retained and populated from the incident's evidence at
creation, so the existing detail page and its tests keep working.

An assertion rendered without at least one evidence row is a defect, logged as
such. It does not render.

### 5.4 Proposal — new table, the agent's action target

| Field | Type | Notes |
|---|---|---|
| `id` | UUIDv4 | |
| `incident_id` | FK | |
| `kind` | enum `work_order \| monitoring_note` | determines gating |
| `root_cause` | string ≤ 4000 | |
| `alternate_root_cause` | string, nullable | ambiguity beat |
| `confidence_split` | string, nullable | e.g. `"60/40"` |
| `discriminating_test` | string, nullable | |
| `line_items` | JSON array of `LineItem` | independently approvable |
| `draft` | JSON | the WorkOrder or MonitoringNote body |
| `parts_constraint` | string, nullable | the scheduling consequence (§8.5) |
| `impact_if_ignored` / `impact_if_unnecessary` | JSON `{low, high, unit}` | ranges, never point estimates |
| `state` | enum `pending \| approved \| modified \| denied \| auto_filed` | |
| `created_at` | ISO-8601 UTC | |

**Gating rule.** `kind = work_order` → `state = pending`, gate required.
`kind = monitoring_note` → filed immediately, `state = auto_filed`, no gate; the
incident moves `propose → act` and the rail marks Decide *not required* (§3).
This is the proportionality point and it is load-bearing for beat 5.

### 5.5 Decision — new table

| Field | Type | Notes |
|---|---|---|
| `id` / `proposal_id` | UUIDv4 / FK | |
| `action` | enum `approve \| modify \| deny` | |
| `reason` | string ≤ 2000 | required for `deny`, optional otherwise |
| `modifications` | JSON, nullable | field-level diff against `draft` |
| `line_items_approved` | JSON array of IDs | shape of the resulting work order on partial approval is open (O20) |
| `decided_at` | ISO-8601 UTC | |

On `deny`, whether and how the agent is told is open (O21).

The delta between `draft` and `modifications` is the most interesting figure
this system produces over time. Preserve both; never overwrite the draft.

### 5.6 Unchanged

`WorkOrder`, `MonitoringNote`, `Notification` keep their current shape and
constraints. `WorkOrder` gains a nullable `proposal_id` FK.

---

## 6. API

### 6.1 Breaking change — the agent's entry point

| | Before | After |
|---|---|---|
| Agent posts to | `POST /api/v1/work-orders` | `POST /api/v1/proposals` |
| Result | Work order created, `201` | Proposal created, `201`, `state=pending` |
| Work order exists | Immediately | Only after approval |

`POST /api/v1/work-orders` is **removed from the agent-reachable surface**. It
survives as an internal function called by the approval path. Retaining it as a
public route would defeat ADR-V04 — an agent that can still reach it can still
bypass the gate.

The same reasoning moves two more write routes off the agent port:

- `PATCH /api/v1/work-orders/{id}` moves to the operator port. An agent that can
  set a work order's status can close one no human opened.
- `POST /api/v1/notes` is removed from the public surface. Monitoring notes are
  now created only by filing a `monitoring_note` proposal (§5.4), so the agent
  has one write path for outcomes, not two.

`mock-wo/tests/test_api.py` needs rewriting accordingly, including a test that
each removed or moved route returns 404 on 8090.

### 6.2 Routes

Every route belongs to exactly one port (ADR-V08).

```
# ── :8090 AGENT PORT — the only port in the NemoClaw policy ─────────────

# Writes
POST   /api/v1/proposals                 the agent's only outcome write path
POST   /api/v1/evidence                  agent posts evidence as it forms
POST   /api/v1/agent-events              telemetry plugin ingest, display-only (ADR-V09)

# Reads — what the agent investigates with
GET    /api/v1/fleet                     assets, service history
GET    /api/v1/fleet/{asset_id}
GET    /api/v1/parts                     stock and lead times (§8.5)
GET    /api/v1/incidents/{id}            incl. cost model; never `ambiguous`
GET    /api/v1/incidents/{id}/evidence
GET    /api/v1/proposals/{id}            the agent can see its proposal's state
GET    /api/v1/work-orders               list and detail
GET    /api/v1/notes

# Infrastructure
ANY    /ragproxy/v1/*                    transparent forward (ADR-V02)
GET    /health

# ── :8091 OPERATOR PORT — never in the NemoClaw policy ─────────────────

GET    /                                 React SPA (static bundle)
GET    /api/v1/stream                    SSE

GET    /api/v1/packs
POST   /api/v1/packs/{pack_id}/activate  mock-wo pack state only (§4a)
GET    /api/v1/fleet
GET    /api/v1/incidents
GET    /api/v1/incidents/{id}
POST   /api/v1/incidents/inject          { asset_id, incident_id }
GET    /api/v1/incidents/{id}/evidence

GET    /api/v1/proposals/{id}
POST   /api/v1/proposals/{id}/decision   { action, reason?, modifications?, line_items_approved? }
POST   /api/v1/incidents/{id}/ask        operator's vss-ask-video question (§8.6)

GET    /api/v1/work-orders
PATCH  /api/v1/work-orders/{id}          moved from agent surface (§6.1)
GET    /api/v1/notes
GET    /api/v1/notifications
GET    /api/v1/audit
POST   /api/v1/demo/reset                clears incidents, keeps audit
GET    /health
```

Read routes appear on both ports where both sides need them. They are
registered twice, as separate route objects, so a port's route table can be
listed and audited on its own.

Error shapes, the 256 KB body limit, 422-not-500 discipline, and enum
whitelisting all carry over unchanged from the existing contract.

### 6.3 SSE — `/api/v1/stream`

One multiplexed stream, on the operator port. Every event carries `incident_id`, `seq`, `ts`.
`seq` is monotonic per incident so the client detects gaps and re-fetches
rather than silently rendering an incomplete stream.

| Event | Payload |
|---|---|
| `stage.changed` | `{ stage, previous }` |
| `analysis.progress` | `{ chunks_done, chunks_total, eta_seconds }` |
| `analysis.caption` | `{ t_start, t_end, text }` |
| `retrieval.query` | `{ query }` |
| `retrieval.result` | `{ documents[], latency_ms }` |
| `skill.invoked` | `{ skill_name, rationale?, params }` — from the telemetry plugin (ADR-V09) |
| `skill.completed` | `{ skill_name, duration_ms, outcome }` |
| `archive.match` | `{ clip, date, similarity, thumbnail_url }` |
| `agent.token` | `{ text }` — from the telemetry plugin; per-turn text if tokens are not hookable (O24) |
| `evidence.added` | full evidence row |
| `ask.answer` | `{ question, answer, evidence_id }` |
| `proposal.ready` | full proposal |
| `decision.recorded` | `{ action, reason, modifications }` |
| `workorder.created` | `{ work_order_id, notification_id }` |
| `error` | `{ stage, message, recoverable }` |

**Event sources.** State-machine events (`stage.*`, `proposal.ready`,
`decision.recorded`, `workorder.created`) come from mock-wo itself.
`retrieval.*` come from ragproxy. `skill.*` and `agent.token` come from the
telemetry plugin. `analysis.*` come from VSS if it exposes them (O4). Only the
first group can change state.

The auth-shim already sets `proxy_buffering off`; mock-wo's own SSE must not
sit behind any buffering layer either.

---

## 7. Screens

### 7.1 Vertical selector

Entry point. One card per **installed** pack: vertical name, asset class, one
line of scenario. Packs that are not installed do not appear. This build has one
pack (D7), so the selector shows that card and the guide moves straight past it.
Container-side pack switching is a host script, not a button (§4a).

Footer carries the existing disclaimer that this is a technical demonstration,
not a product.

### 7.2 Fleet view

Landing and resting state. Grid of asset tiles from the pack roster: name,
make and model, location, thumbnail, time since last clip, status band. Status
is the only coloured element on a tile.

Two controls above the grid:

- **Inject fault** — clearly labelled, not hidden; the guide's Module 3 tells
  the learner to press it. Where a pack defines more than one
  incident, it opens a short list.
- **Reset demo** — clears incidents, restores assets, **keeps the audit
  trail**. Deliberate: the audit accumulates across a day of demos and becomes
  an artefact worth showing.

Injection posts to `/api/v1/incidents/inject`, which opens the incident,
submits the clip to VSS, and wakes the agent via the OpenClaw webhook — the
same wake-hook pattern proven in `nemoclaw-lab-cl` (`OPENCLAW_HOOK_URL` /
`OPENCLAW_HOOK_TOKEN`). On Linux that pattern needed a host `hook-relay` service
to bridge the gateway onto the Docker network, and OpenClaw silently reassigns
its hook port (default 18789) when it is taken. Both carry over (O2). The learner no longer types a kick-off instruction into
the OpenClaw UI; the HITL moment has moved from kick-off to approval.

### 7.3 Incident workspace

Three fixed columns. No resizing, no collapsing — the learner should not have
to manage a layout while following the guide.

```
┌──────────────────────────────────────────────────────────────────────┐
│  M-3021 · Motor drive · Line 3, Hall B              [ Back to fleet ]│
│  ● Monitor ── ● Detect ── ◐ Gather ── ○ Propose ── ○ Decide ── ○ Act │
├────────────────────┬──────────────────────────┬─────────────────────┤
│  EVIDENCE          │  AGENT ACTIVITY          │  PROPOSAL           │
│  ┌──────────────┐  │  14:02:11                │  Root cause         │
│  │ video        │  │  Analysing clip 3/18     │  ─────────────      │
│  └──────────────┘  │                          │  Draft work order   │
│  ▁▁█▁▁▁█▁▁▁▁▁▁▁▁  │  14:02:44                │  ─────────────      │
│   evidence markers │  "Heat signature on      │  Parts              │
│                    │   bearing housing"       │  ─────────────      │
│  ┌──────────────┐  │   → ev_04                │  Impact             │
│  │ document     │  │                          │  ─────────────      │
│  └──────────────┘  │  14:03:02                │  [Approve]          │
│                    │  Retrieving: bearing     │  [Modify]           │
│                    │  temperature limits      │  [Deny]             │
│                    │   → manual-01 §7.3       │                     │
└────────────────────┴──────────────────────────┴─────────────────────┘
```

The stage rail is the single source of progress truth. It lights on state-machine
transition, never on UI guesswork.

---

## 8. Panels

### 8.1 Video player

Standard controls plus a marker track. Markers are `vss` evidence rows; click
seeks, hover shows the claim. Fully usable during analysis — the learner
watching the 90-second clip is a large part of how four minutes gets absorbed.

### 8.2 Document viewer

Lower half of the evidence column. Empty until the first `rag` evidence
arrives, then shows the cited document scrolled to `document_anchor` with the
passage highlighted. Breadcrumb names document and section; a control steps
through all document citations for the incident.

### 8.3 Evidence linking

Clicking any claim anywhere in the workspace:

1. Seeks the video to `t_start` and pauses on the frame.
2. Scrolls the document viewer to the anchor and highlights the passage.
3. Briefly outlines both panes to show they moved together.

This is the most demonstrable behaviour in the application and should be used
in the first thirty seconds of any walkthrough. **Build it first** (§12).

### 8.4 Agent activity stream

Append-only, timestamped, at the granularity of a competent colleague
narrating their work. Five event classes render distinctly:

| Class | Source | Treatment |
|---|---|---|
| Stage transition | state machine | full-width rule, stage name |
| **Skill invocation** | `skill.invoked` / `skill.completed` | compact chip: skill name, rationale, duration on completion |
| Video observation | VSS caption | quoted, links to timestamp |
| Retrieval | ragproxy | query text, then documents returned |
| Agent reasoning | OpenClaw tokens | the agent's own prose |

Newest at the bottom, auto-scrolling, releasing on manual scroll. Reasoning
collapses to two lines with an expander. **Never a spinner.** More than eight
seconds without an event, the stream states what it is waiting on and for how
long — silence reads as breakage.

### 8.4a Skill trace

A compact horizontal strip pinned below the stage rail, showing the skills
invoked for this incident in order: name, state (running / done / failed),
and elapsed time. Hovering shows the rationale the agent gave for choosing it.

Small, quiet, always visible. It is the sequence that carries the meaning, not
any individual entry — and the sequence differing between beat 4 and beat 5 is
the point.

Failure renders honestly. A skill that errors shows as failed with the upstream
message, and the agent's recovery (retry, different skill, or give up) is
visible in the trace. An agent that visibly recovers is more convincing than
one that never stumbles.

### 8.5 Analysis, uncertainty, parts

**Analysis** populates at the Propose transition: what happened (one sentence,
evidence-linked), root cause, and history. History is where the temporal beat
lands — the same signature on three dates with the interval shortening.

**Uncertainty.** Where `ambiguous: true`, two candidate root causes render side
by side with the confidence split and the discriminating test called out
beneath. Exactly one incident per pack should be ambiguous; an agent that is
always uncertain is as unconvincing as one that never is.

**Parts.** Not a lookup result — a constraint that changes the recommendation.
Each required part shows local stock, regional stock, OEM lead time, and
beneath them the scheduling consequence the agent derived:

> 6312-2RS is not held locally. Two at Regional DC Cork, one day transit.
> Recommend scheduling for 2026-09-15 rather than immediate dispatch, and
> de-rating Line 3 to 60% until then.

**This must be testable.** Change `on_hand_local` to 2 in the pack manifest and
the recommendation must change. It is the clearest available evidence that
reasoning is happening rather than retrieval, and it belongs in the test suite.

### 8.6 Decision

Three actions, all three always visible — plus one affordance that changes what
the gate *is*.

**Ask the footage.** A single input above the decision buttons: "Ask a question
about this clip before deciding." Submitting invokes `vss-ask-video`, which
forwards to the VSS agent's `video_understanding` tool for frame-level VLM
analysis. The answer arrives as an `ask.answer` event, renders in the activity
stream, and creates a new evidence row linked to the timestamps it drew on.

This is the most valuable single addition in this revision. Without it the
operator is passing judgement on someone else's summary. With it, they
investigate: *"is there fluid pooling under the housing?"* — and the answer
changes the decision they then make. In the guide it is the moment the learner
stops watching and starts using the system.

The question is submitted on the operator port and mock-wo invokes the skill
path. The agent does not see or answer it. If routing through the NemoClaw
agent turns out to be the only way to reach `video_understanding`, that is a
change to this section, not a reason to put the operator input on the agent
port.

It is also cheap. Frame-level VLM on a short clip, not a full LVS run, so it
fits comfortably inside the attention the four-minute analysis already bought.

Questions and answers are recorded against the incident and appear in the audit
trail, because "what did the operator check before approving" is exactly the
kind of thing an auditor asks.

**Approve** — mock-wo mints the single-use token server-side, creates the work
order and its notification atomically, marks the token consumed. The agent is
never in this path (ADR-V04).

**Modify** — opens `draft` fields for editing, requires a short note on what
changed. Audit holds both the original draft and the modification.

**Deny** — requires a reason. Free text plus optional pack-defined common
reasons ("already addressed", "wrong root cause", "not urgent", "insufficient
evidence"). Written to audit and echoed into the activity stream as the closing
entry.

**Line items** — where a proposal contains several actions (dispatch, order
parts, de-rate), each is independently approvable. Approving all is one click.

**Replay protection** — a token is single-use and bound to one proposal.
A second decision on the same proposal returns `409 proposal_already_decided`.
Test this explicitly.

### 8.7 Impact

Directly above the decision buttons, because that is what the decision needs.

- **Cost of not acting** — downtime rate × estimated time to failure. Where
  time to failure comes from is open (O19): agent-derived from the corpus,
  pack-declared, or both with the source labelled.
- **Cost of acting unnecessarily** — callout + parts + planned downtime.

Ranges, not point estimates, labelled as derived from pack data. Spurious
precision here is a lie an alert audience will catch.

### 8.8 Audit trail

Separate route from the fleet header. One row per decision: timestamp, asset,
incident, proposed action, decision, modifications, reason, evidence set. Rows
expand to the full incident record. Persists across demo resets and restarts in
the existing SQLite volume.

For a Dell enterprise audience this is frequently the first thing asked about.
It should not look like an afterthought.

---

## 9. Designing for the four-minute wait

VSS video analysis is ~92% of the measured ~250 s end-to-end run; retrieval and
fusion are ~1% each. There is no UI-layer optimisation. The wait must be worth
watching.

**What fills it, in order of reliability:**

1. **Stage progress with honest ETA**, derived from chunk count. If VSS does
   not expose per-chunk progress (**O4**), fall back to elapsed against a
   pack-declared expected duration and say so. "Typically 3–5 minutes for a
   90-second clip" is honest; a progress bar that lies is not.
2. **Chunk captions as they land** — richest content available, contingent on O4.
3. **Skill invocations** — guaranteed by the telemetry plugin (ADR-V09, once
   O24 is verified), and independent of O4. Each
   `skill.invoked` / `skill.completed` pair is a discrete, legible moment, and
   the trace filling out left to right is itself a progress indicator that
   cannot lie. This materially de-risks §9: even in the worst case where VSS
   streams nothing until completion, the skill sequence keeps the screen alive.
4. **Archive matches** — `vss-search-archive` results arriving as thumbnails
   with dates. Visually interesting and narratively the strongest content in
   the wait, because it is where the precedent beat lands.
5. **Retrieval events** — guaranteed via ragproxy.
6. **Agent tokens** — guaranteed from OpenClaw.
7. **The clip itself** — the guide prompts the learner to watch it.

**Forbidden:** indeterminate spinners, fake progress, blocking modals, any
suggestion the application has stalled.

Navigation away and back is allowed; the stream backfills from `seq`.

---

## 10. Visual direction

**Decision (O8, resolved): dark theme, continuous with the Sentinel lab guide.**

Consistency across your demo estate is worth more than a distinctive palette
here. A visitor who sees Infrastructure Sentinel and this dashboard in the same
session should read them as one family.

What carries over from the ISA-101 thinking is the *discipline*, not the
brightness: **colour is reserved almost entirely for abnormal conditions**.
This matters more on dark than on light, because dark themes invite neon
everywhere and that is exactly the generic AI-demo look. A dark field where
every panel glows is a control room where nothing stands out. Hold the line:
the resting state is grey on near-black, and the first coloured thing on screen
should be the fault.

### Tokens

Exact values pending alignment with the Sentinel stylesheet — swap these for
its actual hexes where they exist, and keep the role names. The source is
`nemoclaw-lab-cl/ui/src/index.css` (custom properties), with
`docs/lab-guide.html` for the guide's rendering.

```
--field         #0D1117    page background
--surface       #161B22    panel
--surface-sunk  #090C10    video well, document well
--line          #2A323C    rules and borders
--ink           #E6EAF0    primary text
--ink-muted     #8B95A3    labels, timestamps, metadata

--state-normal  #3FA76B    ONLY to confirm return to normal
--state-warn    #E0A030    degraded
--state-alarm   #E5484D    fault
--agent         #7B8FE8    agent-generated content
```

`--agent` still does the most important job in the palette: it marks the
boundary between what the system knows and what the model asserted. Root cause,
recommendations and `vss-ask-video` answers carry it; asset IDs, inventory
counts, part numbers and timestamps do not. Visitors learn the distinction in
about ten seconds without being told, and it quietly reinforces why the gate
exists. Lifted from `#43508C` to `#7B8FE8` for legibility on the dark field.

Dell blue `#0076CE` and NVIDIA green `#76B900` appear in the header lockup
only. **Do not promote NVIDIA green to `--state-normal`** — a brand colour
doing semantic work means the interface is green whenever nothing is wrong,
which destroys the restraint the palette depends on.

### Contrast on dark

Check every pairing at WCAG AA. `--ink-muted` on `--surface` is the one that
usually fails; if it does, lighten the token rather than enlarging the type —
timestamps and metadata need to stay small. Status is never carried by colour
alone: every tile pairs its band with a text label.

**Type.** IBM Plex Sans for interface text, IBM Plex Mono for identifiers,
timestamps, part numbers and log lines. Drawn for technical and industrial
contexts, and not the default reach for a dashboard. On dark, drop body weight
to 350–400 — regular weights bloom against a dark field and read heavier than
intended.

**Offline constraint — non-negotiable.** mock-wo is deliberately "no CDN, works
offline on the vCD network". The React bundle and **all font files must be
vendored into the image at build time**. No Google Fonts link, no CDN script
tag, no runtime external fetch. Vite builds to static assets served by FastAPI
from the existing container.

This reverses `spec/03`, which rejected an SPA (D6). The Dockerfile becomes
multi-stage: a pinned `node` build stage runs `npm ci` against a committed
lockfile and `vite build`, and the runtime stage stays `python:3.12-slim` and
copies in only `dist/`. Node never ships in the runtime image. Both base images
are multi-arch, so the aarch64-dev / x86-VM property `spec/03` relied on
holds.

**Motion.** One orchestrated moment: the evidence-link response (§8.3).
Everything else static — an activity stream that animates each row becomes
unreadable at the density this one reaches. `prefers-reduced-motion` respected.

**Copy.** Active voice, sentence case. Buttons name their outcome and keep the
name: **Approve** produces "Approved". Empty states direct — "All assets
nominal. Inject a fault to begin.", not "No data".

---

## 11. Packs

| Pack | Status | Detection | Documents | Action |
|---|---|---|---|---|
| `manufacturing-motor-drive` | **This build** | Bearing thermal/vibration anomaly | Manual, log, maintenance schedule | Work order, line de-rate |
| `datacenter-xe9680` | Future | Debris in intake, cable obstructing airflow, panel removed | Dell service manuals, KB articles, prior tickets | Field engineer dispatch, part order |
| `utilities-transmission` | Future | Vegetation encroachment, insulator damage, conductor sag | Clearance standards, outage history, crew rosters | Vegetation crew dispatch, outage risk |
| `rail-track-inspection` | Future | Ballast washout, sleeper cracking, fastener loss | Track standards, inspection history, speed tables | Temporary speed restriction, possession request |

**This build ships manufacturing only (D7).** The other three stay here as the
reason the framework is pack-agnostic, and as the order to add them later.

**Manufacturing is pack one**, revising my earlier recommendation. The repo
already has the fixtures (`clip-normal-01/02`, `clip-anomaly-01`) and a written
corpus (`manual-01`, `log-01`, `schedule-01`), so it migrates at essentially
zero content cost and proves the framework before any filming happens.

**Datacenter is the first future pack**, and remains the one you can shoot yourself in the
CSC lab — tripod, matched healthy/anomalous pairs from an identical angle, no
licensing question. Found footage will never give you the matched pair the
temporal beat needs.

**Rail carries the strongest gate argument.** An agent proposing a temporary
speed restriction is proposing something no operator would let a machine do
unilaterally. The gate stops being a feature and becomes obviously necessary —
which is exactly the point you are now making instead of the autonomy point.

### Migration

`fixtures/video/*` and `fixtures/corpus/*` move to
`packs/manufacturing-motor-drive/{clips,corpus}/`. The existing manifests
become the pack manifest. `fixtures/rag-index/` stays where it is — it is a
prep artefact, not pack content. `scripts/prep/25-ingest-corpus.sh` takes a
pack argument.

### Pack authoring checklist

- [ ] 6–12 assets, one carrying the incident
- [ ] Anomaly clip 30 s – 3 min, fixed camera, no burnt-in text, no faces
- [ ] Matched baseline clip, same angle
- [ ] Two `archive_seed_clips` ingested into the archive so `vss-search-archive`
      has genuine precedent to find
- [ ] Archive search verified to actually return them at usable similarity
- [ ] Corpus ingested, collection name recorded
- [ ] At least one required part **not** in local stock
- [ ] Cost model: downtime rate, callout cost
- [ ] One ambiguous incident with a named discriminating test
- [ ] One `monitoring_note` incident — the ungated, no-action outcome
- [ ] Skill roster declared and installed; selection accuracy spot-checked
- [ ] Three or four `vss-ask-video` questions a learner plausibly asks, tried
      against the clip so none of them embarrass the demo
- [ ] Alert rule authored for `vss-manage-alerts` and confirmed to fire
- [ ] Clips qualified against the VLM with a **neutral** prompt

The last item is a gate, not a suggestion. If `cosmos3-reasoner:1.7` does not
spontaneously describe the anomaly when asked only "describe what you see", the
clip is unusable — the demo fails the first time someone asks a different
question.

---

## 12. Build order

Sequenced so the riskiest and highest-value work is proven first.

**M1 — Data model and state machine.** Incident, Evidence, Proposal, Decision
tables; stage transitions; SSE vocabulary. Testable with a stub emitter, no
GPU, no blueprints. Extends the existing pytest suite.

**M2 — Evidence linking.** Video player, document viewer, and the click
behaviour joining them, against fixture data. The application is judged on
this; if it is awkward, everything else is decoration.

**M3 — ragproxy.** Verify it forwards without buffering, preserves the `/v1`
suffix, emits clean events, and passes failures through. Confirms retrieval
visibility before anything depends on it.

**M4 — Approval gate.** The two-port split (ADR-V08), proposal endpoint, token
minting, server-side work-order creation, replay protection, the three decision
actions, line items. Rewrite `test_api.py`, including the port-isolation tests:
every operator route 404s on 8090, and `40-nemoclaw.sh`'s generated policy has
no 8091. This is the security-relevant milestone; test it hardest.

**M4a — Skill catalog, repoint path, selection bench.** First, the O17
footprint check: confirm what each roster skill needs at v3.2.1 and settle the
roster against the GPU budget. Then install the roster and build
`scripts/ops/repoint-llm.sh`, `activate-pack.sh` and `doctor.sh` to the §4a contract at
the same time — including the RT-VLM-not-restarted assertion, which is the part
that stops being true if nobody tests it. Resolves **O16**. Then measure selection
accuracy against Nano Omni across twenty scripted situations.

This is a **measurement, not a gate** — build proceeds regardless. Its purpose
is to produce a number, so that if the trace looks unreliable at M5 or in front
of an audience you already know whether the cause is the model, and swapping is
a config change rather than an investigation. Cheap remedies first if accuracy
disappoints: narrow the roster further, sharpen the `description` frontmatter
the agent matches against, add explicit skill hints to the standing order. Swap
the model only if those don't move it.

**M5 — Telemetry plugin and activity stream, live.** Verify OpenClaw's hook
points (O24), build the plugin (ADR-V09), then all five event classes against a
real incident.
Resolves **O4** and determines how much of §9 survives contact. Skill events
are independent of O4, so this milestone produces a usable stream even in the
worst case.

**M5a — Archive search.** Contingent on O17 and O18. Seed clips ingested, `vss-search-archive` returning
them, matches rendering as thumbnails. Replaces the seeded-history approach and
closes **O9**.

**M6 — Proposal, parts, impact panels.** Including the inventory-changes-the-
recommendation test and `vss-manage-video-io-storage` clip extraction into
work-order evidence.

**M6a — Ask the footage.** `vss-ask-video` wired into the decision panel, with
answers creating evidence rows and landing in the audit trail.

**M7 — Fleet view and vertical selector.** Deliberately late; simplest screens,
least risk.

**M8 — Audit trail.**

**M9 — Guide and module rewrite** (§2). Cannot start before M4 settles the
beat structure. The guide is the primary consumer of the dashboard (D3), so
this milestone checks every screen against the module that uses it.

**Future — Pack two (datacenter).** Out of this build (D7). It remains the real
test of pack agnosticism: if it requires touching anything outside `packs/`
(plus running `activate-pack.sh`), the abstraction is wrong.

---

## 13. Open items

| # | Item | Resolve |
|---|---|---|
| **O1** | Agent skill / prompt rewrite to post proposals rather than work orders | Before M4 |
| **O2** | Does the wake-hook pattern from `nemoclaw-lab-cl` port cleanly to NemoClaw v0.0.118? Includes the Linux `hook-relay` bridge and OpenClaw's silent hook-port reassignment (default 18789) | Before M7 |
| **O3** | ~~8081 port conflict~~ **Resolved** — ADR-V06: RAG host-published on 8071/8072, container ports unchanged, no 8081 entry in NemoClaw policy. Verify the conflict even applies (it is an `install-vllm` path issue; this build uses a custom provider) | Closed, verify at prep |
| **O4** | Does VSS stream per-chunk captions and progress incrementally? | M5 — de-risked, see below |
| **O5** | `LLM_MODE` remote value; LVS `.env` path at v3.2.1; `config_rag.yml` content | Carried from `spec/08` |
| **O6** | 0.10 `gpu_memory_utilization` floor | Carried from `spec/08` |
| **O7** | Does mock-wo's expanded role exceed its 2 GB compose memory limit? | M1 |
| **O8** | ~~Light vs dark palette~~ **Resolved** — dark, continuous with the Sentinel theme (§10). Align token hexes with the Sentinel stylesheet | Closed |
| **O9** | ~~Prior-occurrence history: seeded or real?~~ **Resolved** — archive search (§5.1), verified at M5a | Closed |
| **O10** | ~~Build doc Docker floors~~ **Closed** — the build doc and `00-host-prep.sh` already carry ≥ 28.3.3, < 29.5.0, Compose ≥ 2.39.1 | Closed |
| **O11** | ~~Skill-selection accuracy gates the build~~ **Resolved** — build on Nano Omni, measure at M4a, swap later if needed. ADR-V07 makes the swap a config change | Closed, measure at M4a |
| **O12** | `VSS_PUBLIC_HTTP_PROTOCOL`, `VSS_PUBLIC_HOST`, `VSS_PUBLIC_PORT` must be set or clip-URL skills fail rather than emitting malformed URLs | Before M6 |
| **O13** | Does `vss-manage-alerts` in CV-verification mode fire reliably on pack clips, or is scripted injection still needed as a fallback? | Before M7 |
| **O14** | Skill roster swapping on pack switch — symlink churn without an agent restart is documented, but untested here. Pack switch restarts vss-agent anyway (§4a), but not the NemoClaw sandbox | Future pack |
| **O15** | Sentinel stylesheet token values — the §10 hexes are proposals pending its actual palette, in `nemoclaw-lab-cl/ui/src/index.css` | Before M2 |
| **O16** | Does `openshell inference set` actually move a running sandbox off its baked-in model, or is re-onboarding the only route? §4a step 5 depends on it | **M4a — verify before you need it** |
| **O17** | Skill footprint (D4): what services and GPU do `vss-search-archive`, `vss-query-analytics` and `vss-manage-alerts` CV verification need at v3.2.1, beyond the LVS profile? Drop or re-size decided then | **Before M4a** |
| **O18** | Content production: `archive_seed_clips` (`clip-anomaly-01a/01b`), the pack's ambiguous incident, and its `monitoring_note` incident. None exist; current fixtures are provisional (ADR-004). Who produces them, and how? | Before M5a |
| **O19** | Source of "estimated time to failure" for impact (§8.7): agent-derived from the corpus, pack-declared, or both labelled | Before M6 |
| **O20** | Partial line-item approval: one work order with the approved subset, one work order per item, or something else? | Before M4 |
| **O21** | On deny, is the agent told (and does anything about its next run change), or does the incident simply close? | Before M4 |
| **O22** | ragproxy reachability: the VSS agent container must resolve `mock-wo` on `demo-net`. Confirm the VSS stack joins it, or use the host path | Before M3 |
| **O23** | Module 1 `vss-deploy-profile`: prep pre-starts the stack under start-order discipline, so the learner cannot redeploy. What does the deployment-side bookend become? | Before M9 |
| **O24** | OpenClaw plugin hook points at NemoClaw v0.0.118: tool-call before/after, skill selection, token streaming. ADR-V09 depends on them | **Start of M5** |

Nothing now blocks the start of work. The remaining items are sequenced within
milestones rather than ahead of them.

O4 has been materially de-risked. Skill events fill the wait independently of
whether VSS streams captions incrementally, so the four-minute design no longer
rests on a single unverified behaviour.

Two items are worth doing before the first line of code: **O17** (it decides
the skill roster, and with it how much of §3 and §9 is real) and **O24** (it
decides whether ADR-V09 is buildable as written). The ADR-V06 check is still
cheap: confirm whether the 8081 policy conflict applies to a custom-provider
onboard at all, one command.
