---
target_platforms:
  - vcd
concurrency_target: 10
deployment_target: 'vCD single Ubuntu 24.04 VM, Docker Compose, 1x RTX PRO 6000 96 GB (full PCIe passthrough), shared off-VM LLM endpoint'
demo_footprint:
  gpu: '1x RTX PRO 6000 96 GB (full PCIe passthrough, not vGPU)'
  vram_gb: 96
  vcpu: 32
  ram_gb: 256
  storage_gb: 2048
---

# Sizing — NVIDIA Service Blueprint: VSS + RAG + NemoClaw

What this lab needs to run, shrunk to the smallest thing that still tells the
story in `concept.md`. Multiple instances run concurrently, so per-instance
footprint is the constraint that matters. Consumed by `/hol-spec`, which
derives `lab-prep.md` from it.

Source of all numbers: the project build document
(`NVIDIA-Service-BP-VSS-RAG-NemoClaw-plan.md`), which cites the vendor
repos/docs. No company or product research profile was loaded for this lab —
no vendor claim here goes beyond that document. Numbers the build document
marks as estimates are estimates here; every one of them is listed in
Open questions & assumptions.

## Production footprint

What a real customer deployment of this blueprint looks like — the honest
number, before any reduction.

| Component | GPU / vRAM | vCPU | RAM | Storage | Notes |
| --------- | ---------- | ---- | --- | ------- | ----- |
| RAG generation — `nemotron-3-super-120b-a12b` (default) | Multi-GPU, cluster scale — not measured | not recorded | not recorded | not recorded | 120B-class generation model; the partner reference deployment (Computacenter) ran the full DETECT→REASON→ACT pipeline on a Run:AI cluster |
| VSS LLM — `nemotron-nano-9b-v2` (default) | Local on the VSS GPU, 9B-class (not measured) | not recorded | not recorded | not recorded | Local by default in production; the demo moves it off-VM |
| VSS VLM (8B-class default) | Local on the VSS GPU | not recorded | not recorded | not recorded | Same model class as the demo |
| NemoClaw default provider model | Not recorded in the build document | not recorded | not recorded | not recorded | Replaced by the shared endpoint in the demo |
| RAG retriever NIMs (6, 1B-class) | ~28 GB (estimate) | — | — | ~350 GB weights | Same six NIMs as the demo |
| VSS/RAG data plane (engine, VST, ES, Kafka, Redis, orchestrator) | — | not recorded | ~222 GB per node (demo-VM baseline, unverified at cluster scale) | ~1.65 TB per node (demo-VM baseline) | Cluster node count and sizing not recorded in the build document |

**How this lab differs from production (misrepresentation check).** The demo
footprint genuinely differs from how this blueprint deploys in production,
and a learner who sizes production from the lab will be wrong: production
runs the 120B-class RAG generation model, the 9B VSS LLM, and NemoClaw's
default model locally at multi-GPU / cluster scale (the partner deployment
cited in the build document ran on a Run:AI cluster). This lab moves all
three LLM roles onto one shared off-VM 30B endpoint and keeps only the
8B-class VLM and the six 1B-class retriever NIMs on a single 96 GB card, in a
single-user single VM. That is a deliberate density decision for the lab, not
a production pattern. The VLM and retriever NIMs are the same models
production runs locally, so the detection and retrieval halves of the lab are
representative; the reasoning/generation half is not.

## Minimal demo footprint

What one learner instance actually needs. One vCD VM: Ubuntu 24.04, Docker
Compose, one full 96 GB GPU. RAM and disk rows are the build document's
per-VM allocations (approximate — see Open questions & assumptions). The
mock work-order service is the only component not named in the build
document; it is estimated and flagged.

| Component | GPU / vRAM | vCPU | RAM | Storage | Notes |
| --------- | ---------- | ---- | --- | ------- | ----- |
| VSS stack: agent :8000, LVS backend :38111, RT-VLM :8018, VST, Redis, Kafka, Elasticsearch | ~38 GB — local VLM at `--gpu-memory-utilization 0.40`, `--max-model-len 32768`, `--max-num-seqs 4` | 32 (shared, whole VM) | ~160 GB (engine/VST/decode 128 + ES 32; Redis/Kafka in the RAG row) | ~700 GB (`VSS_DATA_DIR`: VST video store, Elastic, Kafka, Redis) | Beats 1 (healthy baseline) and 2 (anomaly alert) run through here; Elasticsearch serves both VSS and RAG, counted once |
| RAG stack: server :8081, ingestor :8082, orchestrator, frontend + 6 retriever NIMs | ~28 GB — 6 NIMs (embed-1b-v2, rerank-1b-v2, page-elements-v3, table-structure-v1, graphic-elements-v1, ocr), Triton/TRT, default allocation | — | ~40 GB (CPU-bound ingestion 24 + orchestrator/frontend/Redis/Kafka 16) | ~350 GB (RAG model cache 200 + `~/.cache/nim` NIM weights 150) | Beat 3 (visible RAG hits + reasoning). `ENABLE_AGENTIC_RAG` stays off — it multiplies shared-endpoint calls |
| NemoClaw (OpenClaw sandbox + OpenShell gateway) | — | — | ~6 GB | — | Beats 3 and 4: human-in-the-loop kick-off, then autonomous skill run that files the work order |
| auth-shim | — | — | negligible (<1 GB) | — | `nginx:1.27-alpine` on :8080; translates `Authorization: Bearer` → `x-api-key` for the shared endpoint; one tiny container per VM, sized once per instance |
| Mock work-order service (CMMS stand-in) | — | — | ~1–2 GB (estimate) | ~1–5 GB (estimate) | Beat 4's reveal target: a small CPU-only Docker web app the agent POSTs to; tech, ports, and data model open (plan stage). The learner's work orders are per-instance state |
| Host OS, Docker, page cache, container images | — | — | ~16 GB | ~600 GB (`/var/lib/docker`) | `/dev/shm` 32 GB is RAM-backed tmpfs on top of the RAM budget |
| **Total (committed)** | **~70 GB of 96 GB (~26 GB headroom), 7 compute processes** | **32** | **~224 GB of 256 GB (+32 GB /dev/shm)** | **~1650 GB of 2048 GB (~350–400 GB headroom)** | Steady state after full start sequence |

**Per-instance total:** 1× RTX PRO 6000 96 GB (~70 GB committed, ~26 GB
headroom), 32 vCPU, 256 GB RAM (~224 GB committed + 32 GB /dev/shm), 2 TB
NVMe (~1650 GB committed).

Documented minimum (build document): 24 vCPU / 192 GB RAM / 1.5 TB /
/dev/shm 16 GB. The 1.5 TB minimum is below the ~1.65 TB of committed
content, so 2 TB is the real storage floor; 192 GB "will run" per the build
document but leaves no headroom for the decode buffers plus the 32 GB
/dev/shm once the shim and mock work-order service are added. The learner
pool should be provisioned at the recommended 32 vCPU / 256 GB / 2 TB.

Start order (density-relevant): auth-shim → VSS (the VLM must profile an
empty GPU first) → gate on RT-VLM ready → RAG stack → NemoClaw sandbox. A
greedy container that profiles the GPU before the VLM does breaks the
co-residency budget (build document, failure modes).

## Reduction decisions

Every shrink, and its cost. The last column is the one that matters — it is
what stops the next person shrinking it further and breaking the lab. Rows
marked **aha path** are components the aha moment (beat 4, fed by beat 3)
runs through; they were reduced only in placement, never below the size that
keeps the reveal convincing.

| Component | Production | Demo | Why it still demonstrates the story | What breaks if smaller |
| --------- | ---------- | ---- | ----------------------------------- | ---------------------- |
| RAG generation LLM (aha path) | `nemotron-3-super-120b-a12b`, local, multi-GPU cluster scale | `nemotron-3-nano-omni-30b-a3b-reasoning`, off-VM shared endpoint via `nginx:1.27-alpine` auth-shim | The beats show agent behaviour (visible tool calls, retrieved documents, filed work order), not generation quality; measured LLM fusion is ~1.24 s of a ~250 s run (~1.0%). 30B omni is listed among the RAG blueprint's optional NIMs and VSS documents remote OpenAI-compatible endpoints — the configuration stays inside the product-documented envelope | A model far below 30B-class: multi-step tool-calling reasoning degrades and beats 3–4 lose the visible grounded reasoning that is the evidence for the reveal. Back to local: the multi-GPU budget returns and 1-card / 1-VM density dies |
| VSS LLM (aha path) | `nemotron-nano-9b-v2`, local on the VSS GPU | Same shared 30B endpoint (off-VM) | Latency-neutral (~1.24 s measured fusion share) and a documented VSS remote-LLM configuration | Same quality risk as the row above. Returning to local puts a 9B-class model and its KV budget on a card already ~70 GB committed (estimate — unmeasured) and erodes the 26 GB headroom |
| NemoClaw model (aha path) | Default provider model (size not recorded) | Same shared 30B endpoint (`NEMOCLAW_PROVIDER=custom`) | The agent must reliably drive the `vss-generate-video-report-rag` skill and the HITL kick-off; a 30B-class omni model serves that | A weaker model: the agent fails to complete the skill unaided → beat 4 needs a human nudge, and the aha (nothing between the learner's one instruction and the work order) breaks |
| Cluster → single VM | Run:AI multi-GPU cluster (partner reference) | 1× Ubuntu 24.04 vCD VM, Docker Compose | No beat is about topology or distribution; success criterion 4 makes the footprint itself part of the lesson — one VM, one 96 GB GPU, a pool of ten learners | Nothing breaks below one VM. The risk runs the other way: under-sizing the VM (rows below) |
| Zero local GPU for VLM (build doc "future work") | Local VLM verified | **Declined — VLM stays local** | Not a reduction made; recorded so the next person does not make it | The VLM must profile an empty GPU first; only the default local VLM is verified; LVS prompts and alert verification are tuned around it. Remote VLM is untested → beat 2's alert identity/quality breaks. Aha path: do not reduce |
| VLM budget (aha path) | Default `gpu_memory_utilization` 0.9 (~86 GB) — nothing else would start | 0.40 → ~38 GB, with `--max-model-len 32768` (native 256K) and `--max-num-seqs 4` | Single learner per VM (zero in-VM concurrency), so no batch slots to reserve; VSS chunks are seconds long, so cutting the KV-cache term ~an order of magnitude is free | Below ~0.35 fraction / 16384 context / 2 seqs: long-chunk captioning OOMs or fails with "To serve at least one request"; alert quality on the anomaly clip (beat 2, feeding the aha) degrades. Aha path: do not cut further |
| RAG retriever NIMs (6) (aha path) | 6 local NIMs (same as production) | 6 local NIMs, Triton/TRT, default allocation (~28 GB) | Not reduced — the retrieved documents are the reveal's evidence, and 1B-class NIMs are already the small end of the stack | Dropping an extraction NIM (e.g. `graphic-elements`): retrieval quality degrades for the corpus content types it covers and the "which documents were retrieved" evidence weakens. Open risk: a documented 0.10 `gpu_memory_utilization` floor, if it applies to user-set values, would push a 9.6 GB floor per NIM and eat the 26 GB headroom — must be measured before the budget is trusted |
| Vector DB | GPU-accelerated Milvus alternative exists | Elasticsearch on CPU (blueprint default, kept deliberately) | The reveal is retrieval quality over a small corpus, not vector-search throughput | GPU Milvus costs a second GPU budget and kills 1-card density. Dropping the vector DB entirely kills beat 3 — no RAG hits, no evidence, no aha |
| In-VM concurrency | Production serves many users/streams | 1 learner per VM, zero in-VM concurrency (the build document's own design) | The pool provides concurrency: 10 VMs = 10 learners, with VM-level isolation | 2 learners per VM: vRAM ~70 GB × 2 > 96 GB and decode buffers double → mid-session OOM. The card cannot be shared — one instance per 96 GB card |
| Corpus and footage | Production OEM manuals + drone/borescope/thermal inspection video | Curated small corpus + short pre-recorded clips (normal-state for beat 1, one anomaly segment for beat 2), index pre-built before the session | Indexing is a non-goal (its own lab exists); a small chosen corpus makes the retrieval hits legible on screen | A corpus that does not cover the anomaly's manual/log/schedule entries → RAG retrieval returns nothing relevant → the reveal has no evidence. Clips much longer than the test clip: ~250 s analysis at 92% VLM time multiplied by length blows session time |
| Downstream action target (aha path) | Partner: Maximo work orders (blog: Jira) | Small mock Docker web app the agent POSTs to (tech/ports/data model open) | The concept's aha is "a work order appears in the mock CMMS" — the mock is the beat, and CMMS internals are an explicit non-goal | A mock that does not visibly render a work order plus the notification: success criterion 2 breaks. Real Jira/Maximo: tenant and credentials setup outside lab scope, and the reveal would depend on external uptime |
| RAM | (production per-node sizing not recorded) | 256 GB recommended (documented minimum 192 GB) | "192 GB will run. 256 GB means you debug the demo, not the memory" | Below 192 GB: VSS decode / Elasticsearch OOM. At 192 GB: ~224 GB committed + 32 GB /dev/shm exceeds RAM unless decode buffers come in lighter (untested). Provision the pool at 256 GB |
| Disk | (production sizing not recorded) | 2 TB NVMe recommended (documented minimum 1.5 TB) | Committed content is ~1.65 TB (images 600 + NIM weights 150 + `VSS_DATA_DIR` 700 + RAG cache 200) | At 1.5 TB (1.536 TB) the committed content exceeds capacity on day one — the documented minimum is below the documented content. Below 2 TB: learner session artifacts have nowhere to go; 2 TB leaves ~350–400 GB |
| /dev/shm | — | 32 GB (documented minimum 16 GB) | Docker `default-shm-size: 32G` for decode / shared-memory paths | Below 16 GB: shared-memory OOM in the VSS decode / Docker paths |
| vCPU | — | 32 (documented minimum 24) | CPU-bound work: RAG ingestion extraction, video decode | Below 24: ingest and decode slow down and the ~250 s analysis plus session time balloon |

## Density

- **Per-instance footprint:** 1× RTX PRO 6000 96 GB (~70 GB committed,
  ~26 GB headroom), 32 vCPU, 256 GB RAM (~224 GB committed + 32 GB /dev/shm),
  2048 GB storage (~1650 GB committed).
- **Concurrency target:** 10 simultaneous learner instances — one learner per
  VM, 10-VM vCD pool, hard cap ("we will not exceed this").
- **Aggregate at N=10:** 10× RTX PRO 6000 96 GB (700 GB committed across 10
  cards), 320 vCPU, 2560 GB RAM (2240 GB committed + 320 GB /dev/shm),
  20480 GB storage (~16.5 TB committed).
- **Shared vs per-tenant:**
  - Shared, sized once: the off-VM LLM endpoint
    (`nemotron-3-nano-omni-30b-a3b-reasoning`, pre-provisioned, capacity
    unknown — see Open questions); NGC image and weight sources; the
    read-only video and document corpora.
  - Per-instance, multiplied by 10: all running containers, the full
    ~70 GB vRAM on each card, the nginx auth-shim (tiny, one per VM),
    writable Elasticsearch/Kafka/Redis/VST state, the ingested RAG index and
    the learner's queries against it, and the learner's work orders in the
    mock CMMS.
  - vCD isolation reality: per-VM disks are not shared. Unless a shared
    datastore is mounted, the weight caches (`~/.cache/nim` 150 GB + RAG
    cache 200 GB ≈ 350 GB per VM) are per-VM — first build pulls weights
    per VM (45–70 minutes per the build document) or the VM image ships
    weights pre-baked. Flagged assumption: this file assumes no shared
    datastore; if one is mounted, the 2 TB per-VM budget drops accordingly.
- **Headroom / limits:** vRAM on the card is the binding constraint on
  co-residency — one instance per 96 GB card: a second instance would need
  another ~70 GB but only ~26 GB of headroom exists, so the card cannot be
  split and N ≤ number of cards. The 10-VM pool (user-set hard cap) is the
  binding constraint on N: at N=10 the pool is fully consumed. What runs out
  first at N=10: outside the VM, the shared endpoint's capacity for 10
  concurrent lab sessions is unknown and unmeasured — it serves the VSS LLM
  role, RAG generation, and all 10 NemoClaw sessions, making it the most
  likely first failure outside the VM. Inside the VM nothing breaks at
  N=1/VM (single-user by design; the ~26 GB headroom absorbs the NIM-floor
  risk if it materialises).

## Software stack

| Component | Version | Source / image | Licensing |
| --------- | ------- | -------------- | --------- |
| OS | Ubuntu 24.04 LTS (x86) | vCD VM image | none |
| NVIDIA driver | 580.105.08 (Ubuntu 24.04 build) | `apt nvidia-driver-580` | none |
| NVIDIA Container Toolkit | 1.17.8+ | apt, `nvidia-ctk runtime configure --runtime=docker` | none |
| Docker Engine | 27.2.0+ | get.docker.com | none |
| Docker Compose | v2.29.0+ | Docker plugin | none |
| NGC CLI | 4.10.0+ | nvcr.io | NGC API key |
| Node.js | 20.x (NodeSource `setup_20.x`) | deb.nodesource.com | none (NemoClaw requirement) |
| Kernel tuning | `vm.max_map_count=262144` (plus `fs.file-max=2097152`, `net.core.somaxconn=4096`) | `/etc/sysctl.d/99-vss.conf` | none — Elasticsearch refuses to start without `vm.max_map_count` |
| VSS | repo tag v3.1.0 (latest public release; v3.2.1 unconfirmed — open) | github.com/NVIDIA-AI-Blueprints/video-search-and-summarization | none (images below) |
| VSS agent image | `VSS_AGENT_VERSION=3.2.0` (confirm before cloning) | nvcr.io, via the VSS compose stack | NVIDIA AI Enterprise developer licence |
| VSS default VLM | version default — Cosmos-Reason2-8B (repo README) vs `nvidia/cosmos3-nano-reasoner` (current docs); both 8B-class; identity open | NIM image from nvcr.io | NVIDIA AI Enterprise developer licence |
| RAG | v2.6.0 (v2.6.2 unconfirmed — fall back to v2.6.0) | github.com/NVIDIA-AI-Blueprints/rag | none (NIMs below) |
| NIM `nvidia/llama-nemotron-embed-1b-v2` | per the release's compose file (tag not recorded in the build document) | nvcr.io | NVIDIA AI Enterprise developer licence |
| NIM `nvidia/llama-nemotron-rerank-1b-v2` | per the release's compose file (tag not recorded) | nvcr.io | NVIDIA AI Enterprise developer licence |
| NIM `nemotron-page-elements-v3` | per the release's compose file (tag not recorded) | nvcr.io | NVIDIA AI Enterprise developer licence |
| NIM `nemotron-table-structure-v1` | per the release's compose file (tag not recorded) | nvcr.io | NVIDIA AI Enterprise developer licence |
| NIM `nemotron-graphic-elements-v1` | per the release's compose file (tag not recorded) | nvcr.io | NVIDIA AI Enterprise developer licence |
| NIM `nemotron-ocr` | per the release's compose file (tag not recorded) | nvcr.io | NVIDIA AI Enterprise developer licence |
| Elasticsearch | version not recorded in the build document (VSS/RAG compose default) | via the VSS/RAG compose stacks | per compose default (open) |
| auth-shim | nginx:1.27-alpine | docker.io, local `docker-compose.shim.yml` | none (open source) |
| NemoClaw | via the VSS-repo installer `deploy/docker/scripts/nemoclaw/init_nemoclaw.sh` (Node.js 20 required; fresh OpenClaw install required) | vss-public repo | — |
| Shared LLM endpoint | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | off-VM, pre-provisioned — not on the VM, not in the per-VM GPU budget | provided by the platform |
| Mock work-order service | TBD — small Docker web app (tech, ports, data model open) | built in-lab at the plan stage | none |

Licensing gate: the **NVIDIA AI Enterprise developer licence** is required to
host the NIMs locally and gates the entire build (build document). An NGC API
key and an NVIDIA Build API key are also required.

## Deployment target

vCD — one Ubuntu 24.04 VM per learner, Docker Compose only, **no
Kubernetes**. Why: VSS ships Compose-only, and its
`native.cgroupdriver=cgroupfs` daemon requirement conflicts with MicroK8s
(which expects systemd cgroups); a K8s hybrid (RAG's Helm chart, validated on
OpenShift) is the documented future graduation path, not this lab. Platform
requirements already known to be a problem, for `/hol-platform-check`:

1. Full PCIe passthrough of the RTX PRO 6000 96 GB, **not vGPU** — NIM probes
   the device directly for profile selection.
2. `/dev/shm` 32 GB (Docker `default-shm-size: 32G`).
3. `vm.max_map_count=262144` — Elasticsearch refuses to start without it.
4. 10-VM pool with a hard cap of 10 concurrent learners.

This is the first guess — `/hol-platform-check` is the real gate.

## Open questions & assumptions

Every estimated number, and anything a human should confirm before
`/hol-spec` runs. No company/product research profile was loaded; all vendor
facts come from the local build document.

**Estimates (not measured):**

- All vRAM figures are the build document's estimates, pending its Phase 2
  measurement: VLM ~38 GB (at 0.40 / 32768 / 4), six NIMs ~28 GB
  (5+5+5+4+4+5 GB), CUDA contexts ~4 GB, ~70 GB committed / ~26 GB headroom.
  If the six NIMs measure over ~45 GB total, the VLM fraction must be cut
  before co-residency and this budget shifts.
- The NIM 0.10 floor risk: whether the documented 0.10 minimum
  `gpu_memory_utilization` applies to user-set values is untested; if a
  9.6 GB floor is enforced per NIM, the 26 GB headroom is consumed. Must be
  resolved at build Phase 2.
- RAM rows (128 + 32 + 24 + 16 + 6 + 16 ≈ 222 GB) are the build document's
  approximate per-VM allocations; +~2 GB mock work-order service (estimate)
  ≈ 224 GB; +32 GB /dev/shm (RAM-backed tmpfs) ≈ 256 GB — the recommended
  RAM sits at the top of the commitment. The 192 GB minimum "will run" per
  the document but is untested with the shim and mock service added.
- Disk rows (600 + 150 + 700 + 200 = 1650 GB) are the build document's
  allocations; the conclusion that the documented 1.5 TB minimum (1.536 TB)
  is below the committed content is arithmetic on those estimates.
- Mock work-order service footprint is an estimate: CPU-only, ~1–2 GB RAM,
  ~1–5 GB disk, small image. Tech, ports, and data model are open
  (concept.md); size it concretely at the plan stage. The auth-shim's
  "<1 GB" (nginx:1.27-alpine) and the Reduction-table note that a local
  9B-class VSS LLM would add unquantified vRAM to the card are estimates as
  well.
- Shared-endpoint capacity: unknown and unmeasured for 10 concurrent lab
  sessions — it serves the VSS LLM role, RAG generation, and 10 NemoClaw
  sessions. Likely the first constraint to break at N=10 outside the VM.
  Confirm throughput / concurrency limits before launch.
- The "moving the LLM off-VM costs nothing in latency" claim rests on the
  build document's measured split of one run (~250 s end-to-end: 92% VSS
  video analysis, 5.7% NemoClaw orchestration, 1.3% RAG retrieval ≈ 1.69 s,
  1.0% LLM fusion ≈ 1.24 s). Whether the fusion share holds under 10×
  concurrent load against the shared 30B endpoint is unmeasured.

**Open tags (kept open per build document §14 and concept.md — not resolved
here):**

- VLM identity: Cosmos-Reason2-8B (repo README) vs
  `nvidia/cosmos3-nano-reasoner` (current VSS docs). Both are 8B-class so the
  GPU budget is unaffected, but LVS prompts and alert verification are tuned
  around the version default. Confirm before building.
- Version tags: VSS v3.1.0 vs v3.2.1 (unconfirmed); agent image
  `VSS_AGENT_VERSION=3.2.0`; RAG v2.6.0 vs v2.6.2 (unconfirmed, fall back to
  v2.6.0). NIM image tags and the Elasticsearch version are not recorded in
  the build document.
- Pre-provisioning: whether the 10-VM vCD pool and the shared off-VM
  inference endpoint are pre-provisioned lab infrastructure or in scope for
  the build (open question in concept.md).
- Shared datastore: per-VM weight caches (~350 GB each) are assumed per-VM —
  no shared datastore mounted. If vCD mounts a shared read-only datastore,
  the per-VM storage budget and the 45–70 minute first-build weight pull
  change.
- Footage and corpus: which pre-recorded clips (normal-state + anomaly) and
  which corpus (manuals, logs, maintenance schedule) — open. The corpus must
  cover the content types the anomaly beat retrieves over (see Reduction
  decisions).

**Derived figures:**

- All density aggregates (10 cards, 700 GB committed vRAM, 320 vCPU,
  2560 GB RAM, 20480 GB storage) are 10 × the per-instance figures above.
- Production-footprint figures (Run:AI cluster, 120B-class scale) come from
  the build document's partner-deployment citation; they are context for the
  honesty baseline, not measured sizing inputs.
