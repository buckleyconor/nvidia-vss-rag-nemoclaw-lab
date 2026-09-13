# 01 — Overview

**Lab:** `nvidia-service-bp-vss-rag-nemoclaw` — "NVIDIA Service Blueprint: VSS + RAG + NemoClaw"
**Inputs:** `concept.md` (approved) + `sizing.md` (approved) + the project build document (`spec/context-aware-video-agent-build-doc.md`, which superseded the root-level `NVIDIA-Service-BP-VSS-RAG-NemoClaw-plan.md` on 2026-09-13). Every vendor fact in this spec traces to those three; no company/product research profile was loaded, and no vendor claim goes beyond the build document.

**Version pins (2026-09-02):** VSS repo tag **v3.2.1** (agent image `VSS_AGENT_VERSION=3.2.1` — tracks the release tag; image-tag existence verified at prep → `prep-log.md`), RAG **v2.6.2**, NemoClaw **v0.0.118** (the sizing carried no version). The user's GitHub release data (2026-09-02) supersedes the initial spec-review confirmations (VSS v3.2.0, RAG v2.6.0 with v2.6.2 fallback) and the sizing's open-tag rows; the full version inventory (six NIM image tags, Elasticsearch 9.3.0, VLM `nvcr.io/nim/nvidia/cosmos3-reasoner:1.7`, VSS infra images, host-tool bounds) is recorded with provenance in §8 (items 1, 2, 3, 4, 7, 28, 29, 30). `sizing.md` is upstream and unedited.

## What this lab builds

A single vCD VM (Ubuntu 24.04 x86, 32 vCPU, 256 GB RAM, 2 TB NVMe, 1× H100 ~94 GB vGPU partition) runs two vendor blueprints — **Video Search & Summarization (VSS)** and **Enterprise RAG** — with the local 8B-class VLM and six 1B-class retrieval NIMs sharing the one GPU, while **all three LLM roles** (VSS LLM, RAG generation, NemoClaw's model) are served from one **pre-provisioned shared off-VM endpoint** (`https://model.delllabs.local/api/nemotron35/v1`, model `NVIDIA/Nemotron-3.5-Lightning-30B-A3B` — owner-confirmed 2026-09-07) through a small **nginx auth-shim** (`nginx:1.27-alpine`, :8080, translates `Authorization: Bearer` → `x-api-key`). **NemoClaw**, kicked off by the learner's single instruction (the blueprint's proven human-in-the-loop path), drives the `vss-generate-video-report-rag` skill, whose VSS agent has the built-in **`frag` knowledge-retrieval tool** enabled via `VSS_AGENT_CONFIG_FILE` → `config_rag.yml` (the authoritative Jul 2026 integration method — no source patching). The agent diagnoses the VSS-flagged video anomaly against a pre-ingested corpus of equipment manuals, logs, and maintenance schedule, then **autonomously files a work order in a small mock CMMS web service** — the mock work-order service is the only real application code in the lab repo (contract pinned in `02-architecture.md` / `03-build-decisions.md`).

The lab is the **agentic glue**: video alert → agent-driven RAG diagnosis → autonomous work order. It deliberately does not teach VSS internals (ingestion, chunking, captioning, summarisation mechanics) or RAG internals (indexing, vector-search mechanics) — both already have their own hands-on labs (concept non-goals).

## Application context

- **What it does:** composes VSS + Enterprise RAG + NemoClaw into one visible alert → diagnosis → work-order chain over pre-recorded factory-equipment video, on one VM with a shared off-VM LLM endpoint.
- **Primary users:** AI/ML engineers and solution architects evaluating agentic video pipelines for industrial use. One learner per VM; zero in-VM concurrency.
- **Core features (priority order):**
  1. **Beat 1 — establish the baseline:** pre-recorded normal-state clips run through VSS; the learner sees the pipeline healthy, no alerts.
  2. **Beat 2 — anomaly detected:** the anomaly segment (e.g., motor bearing with abnormal thermal/vibration behaviour) is played; VSS raises an alert identifying the affected equipment.
  3. **Beat 3 — agentic diagnosis:** the learner instructs NemoClaw (HITL kick-off in the OpenClaw UI); the agent runs RAG retrieval over manuals/logs/schedule with **visible tool calls and reasoning** (which documents were retrieved, what was inferred).
  4. **Beat 4 — work order created (the aha):** with no human step after the single instruction, NemoClaw files a work order in the mock CMMS and the notification is delivered; the learner sees the work order appear in the system.
  5. **Beat 5 — triage (optional extension):** a second anomaly of a different kind produces a different outcome — a monitoring note, not a work order — showing the agent decides rather than script-follows.
- **Out of scope (do NOT build):** VSS internals; RAG internals/indexing (the corpus index is pre-built at environment prep; indexing is a non-goal); real CMMS (Jira/Maximo); cluster/Kubernetes topology; remote VLM (declined in sizing — VLM stays local); live video (pre-recorded clips only); multi-learner-per-VM.
- **Stack / language preferences:** vendor blueprints (Docker Compose, `.env`-driven) plus one small Python 3.12 / FastAPI service (mock work-order service). Chosen and pinned in `03-build-decisions.md`.
- **Runtime & deployment target:** one Ubuntu 24.04 x86 vCD VM per learner, Docker Compose only — **no Kubernetes** (VSS ships Compose-only; its `native.cgroupdriver=cgroupfs` daemon requirement conflicts with MicroK8s). vRAM on the ~94 GB card is the binding constraint: one instance per card; the 10-VM pool (hard cap 10 concurrent learners) bounds N.
- **Data handled & sensitivity:** pre-recorded factory video clips (assume they may contain identifiable personnel — treated as PII-lite, never exfiltrated), an internal-style document corpus (manuals, logs, maintenance schedule), per-instance demo work orders. No production data, no PII collection. See `04-security.md`.
- **Expected scale:** 10 concurrent learner instances (10 VMs, one learner each). Per VM: one user, a handful of API calls per beat, ~250 s measured end-to-end video-analysis run (build document, single measured run).
- **External services / integrations:** the shared off-VM inference endpoint (pre-provisioned, not on the VM, not in the per-VM GPU budget); NGC (images + model weights, `NGC CLI 4.10.0+`); the mock work-order service (local, CPU-only).
- **Hard constraints:** GPU budget ~70 GB committed of ~94 GB (~24 GB headroom — estimates pending the build document's Phase 2 measurement; re-verify on the H100 at prep — NIM profile selection is GPU-dependent); RAM 256 GB (~224 GB committed + 32 GB /dev/shm); disk 2 TB (~1.65 TB committed); the non-negotiable start order (shim → VSS on empty GPU → gate on RT-VLM → RAG → NemoClaw); vendor floors (NVIDIA driver 580.105.08 — the VSS canonical-matrix exact pin for Ubuntu 24.04, Docker ≥ 28.3.3 **and < 29.5.0** — newer Docker breaks NGC pulls, Compose ≥ v2.39.1, `vm.max_map_count=262144`, `/dev/shm` 32 GB, vGPU H100 delivery); exact pinned versions, never `latest`.

## Success criteria (restated from the concept)

The lab has done its job when a learner can:

1. Explain the end-to-end alert → diagnosis → work-order flow and where the RAG context (retrieved manuals, logs, maintenance schedule) enters it.
2. Reproduce the aha moment from a clean start — one instruction to the agent, then the work order appearing in the mock CMMS with its notification, no human step in between.
3. Point at the agent's visible tool calls / retrieved documents on screen as the evidence of the diagnosis, not just the final answer.
4. State why the reasoning LLM is shared/off-VM while the video model and the RAG retrieval models run locally on the GPU — the footprint/density reason: one VM, one ~94 GB GPU, a pool of ten learners.

## What is in the lab repo, and what is not

The lab repo is **deployment code**: the user pulls it from GitHub onto the vCD VM. The VSS and Enterprise RAG stacks are **vendor blueprints, cloned and configured on the VM at environment-prep time** — this repo does not reimplement them.

| In the repo | Not in the repo |
| --- | --- |
| Mock work-order service (the only real application code) + its tests | The VSS and Enterprise RAG stacks — cloned at env-prep from pinned tags (VSS v3.2.1 / agent image `VSS_AGENT_VERSION=3.2.1` — tracks the release tag, prep-verified; RAG v2.6.2 — user-confirmed GitHub releases, 2026-09-02) |
| Compose/env/config contracts: auth-shim compose + `nginx.conf.template` (verbatim from the build document), mock-wo compose, `config_rag.yml`, `vlm.env`, LVS/RAG/NemoClaw env overlays | Model weights and NIM images — pulled from NGC at prep (first run 45–70 min per the build document) |
| Deployment scripts: host prep, tag-pinned blueprint clone with SHA recording, start-order orchestration with the RT-VLM gate, stack verification | The 10-VM vCD pool and the shared off-VM LLM endpoint — assumed pre-provisioned lab infrastructure (open — confirm ownership, **§8**) |
| Fixtures: pre-recorded clips (normal + anomaly), document corpus, pre-built RAG index artifact slot (content **open** — **§8**) | Real CMMS (Jira/Maximo) — explicit non-goal; the mock is the beat |
| This spec set, README, test harness | The learner session itself (guide stage) |

## Non-goals (restated)

- VSS internals — video ingestion, chunking, captioning, summarisation mechanics (own lab).
- Enterprise RAG internals — corpus indexing and vector-search mechanics (own lab).
- Anything beyond the agentic glue this lab is: video alert → agent-driven RAG diagnosis → autonomous work order.
- Topology/cluster deployment; remote VLM; in-VM concurrency.

## Open items carried to §8 (from this file)

- **Resolved by the GitHub release data (2026-09-02, → §8 item 7):** VLM identity — the VSS 3.2.1 release ships `nvcr.io/nim/nvidia/cosmos3-reasoner:1.7` (Cosmos3 Nano Reasoner) as its local VLM NIM image; the earlier open question (Cosmos-Reason2-8B vs `nvidia/cosmos3-nano-reasoner`) resolves to the current-docs side. 8B-class, so the GPU budget is unaffected.
- **Resolved (2026-09-02, → §8):** version tags — VSS repo tag **v3.2.1** (user's GitHub release data — supersedes the initial spec-review confirmation of v3.2.0 and the sizing's open set v3.1.0 vs v3.2.1), agent image `VSS_AGENT_VERSION=3.2.1` (assumed to track the release tag; the build document's 3.2.0 value corresponds to the v3.2.0 tag — prep-verifies against the v3.2.1 release compose, §8 item 2), RAG **v2.6.2** (user's GitHub release data — supersedes v2.6.0 with v2.6.2 fallback), NemoClaw **v0.0.118** (user-confirmed; the sizing carried no version — the installer at the pinned VSS v3.2.1 tag must install/declare it, prep check §8 item 28). Also resolved (→ §8 item 4): the six NIM image tags and Elasticsearch (9.3.0) are now **pinned exactly** from the user's GitHub release data; nv-ingest 26.3.0 / seaweedfs 4.21.0 / zipkin 0.4.0 remain blueprint-carried `prep-log.md` verification targets; **the repo-level pins are VSS v3.2.1 and RAG v2.6.2**.
- **Open (→ §8):** fixture content — which pre-recorded clips and which corpus; the corpus must cover the content types the anomaly beat retrieves over (manual + log + schedule).
- **Open (→ §8):** pre-provisioning ownership — are the 10-VM pool and the shared off-VM endpoint pre-provisioned lab infrastructure or in scope for the build (open in concept.md); shared-datastore assumption (per-VM weight caches, no shared mount).
- **Shortfall check (no shortfall here):** this section adds no resource beyond the sizing's lines. The mock work-order service is the sizing's own estimated line (~1–2 GB RAM / ~1–5 GB disk), and beat 5's monitoring note rides that same line — same service, no new footprint row (see `02-architecture.md`).
