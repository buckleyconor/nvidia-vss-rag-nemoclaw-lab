# 09 — Environment & footprint

This section is what `lab-prep.md` is derived from. The footprint **mirrors
the approved `sizing.md` line-by-line** — the only addition is the mock
work-order service line, which is the sizing's own estimated line (~1–2 GB
RAM / ~1–5 GB disk); **no shortfall was raised** against the sizing. Every
endpoint, credential, artifact path and readiness condition below is
concrete and observable. Where a value is recorded only at prep time, the
pointer is `prep-log.md` (the single "recorded reality" source), never a
guess.

## Per-instance footprint (one learner, one vCD VM)

| Component | GPU / vRAM | vCPU | RAM | Storage |
| --------- | ---------- | ---- | --- | ------- |
| VSS stack: agent :8000, LVS backend :38111, RT-VLM :8018, VST, Redis, Kafka, Elasticsearch | ≈ **34 GB measured** (dry-run 2026-09-10: VLM engine 34134 MiB at the 0.40 pin) — local VLM at `--gpu-memory-utilization 0.40` (the effective knobs are `RTVI_VLLM_*` env, 08 item 39), `--max-num-seqs 4` | 32 (shared, whole VM) | ~160 GB (engine/VST/decode 128 + ES 32; Redis/Kafka in the RAG row) | ~700 GB (`VSS_DATA_DIR`: VST video store, Elastic, Kafka, Redis) |
| RAG stack: server :8081, ingestor :8082 (prep-only), orchestrator, frontend + 6 retriever NIMs | ≈ **34 GB measured** (dry-run 2026-09-10: OCR ~11.1 GB, the rest 2.5–5.6 GB — the ~28 GB estimate undercounted; L5 re-measures on the learner VM) — 6 NIMs (embed-1b-v2, rerank-1b-v2, page-elements-v3, table-structure-v1, graphic-elements-v1, ocr), Triton/TRT, default allocation | — | ~40 GB (CPU-bound ingestion 24 + orchestrator/frontend/Redis/Kafka 16) | ~350 GB (RAG model cache 200 + `~/.cache/nim` NIM weights 150) |
| NemoClaw (OpenClaw sandbox + OpenShell gateway) | — | — | ~6 GB | — |
| auth-shim | — | — | negligible (< 1 GB) | — |
| Mock work-order service (CMMS stand-in; the repo's only app) | — | — | ~1–2 GB (estimate — the sizing's own line) | ~1–5 GB (estimate — the sizing's own line) |
| Host OS, Docker, page cache, container images | — | — | ~16 GB | ~600 GB (`/var/lib/docker`) |
| **Total (committed)** | **~70 GB of ~94 GB (~24 GB headroom), 7 compute processes** | **32** | **~224 GB of 256 GB (+ 32 GB /dev/shm tmpfs)** | **~1650 GB of 2048 GB (~350–400 GB headroom)** |

**Per-instance total:** 1× H100 ~94 GB vGPU partition (~70 GB committed, ~24 GB
headroom), 32 vCPU, 256 GB RAM (~224 GB committed + 32 GB /dev/shm), 2 TB
NVMe (~1650 GB committed).

**Documented minimums and their reality** (sizing): 24 vCPU / 192 GB RAM /
1.5 TB / /dev/shm 16 GB. The 1.5 TB minimum is below the ~1.65 TB of
committed content — **2 TB is the real storage floor**. 192 GB "will run" per
the build document but is untested with the shim and mock-wo service added;
**provision the pool at the recommended 32 vCPU / 256 GB / 2 TB**.

## Concurrency, aggregate, binding constraints

- **Concurrency target:** 10 simultaneous learner instances — one learner per
  VM, 10-VM vCD pool, **hard cap** (user-set: "we will not exceed this").
- **Aggregate at N=10:** 10× H100 ~94 GB (700 GB committed across 10
  cards), 320 vCPU, 2560 GB RAM (2240 GB committed + 320 GB /dev/shm),
  20480 GB storage (~16.5 TB committed).
- **Binding constraints, in order:**
  1. **vRAM on the card** — one instance per card: a second instance
     would need another ~70 GB against ~24 GB of headroom; the card cannot be
     split, so N ≤ number of cards.
  2. **The 10-VM pool cap** — at N=10 the pool is fully consumed (user-set).
  3. **Shared-endpoint capacity (outside the VM)** — unknown and unmeasured
     for 10 concurrent sessions; it serves the VSS LLM role, RAG generation
     and all 10 NemoClaw sessions — **the most likely first failure at N=10**
     (§8 item 20).
- Inside the VM nothing breaks at N=1/VM (single-user by design; the ~24 GB
  headroom absorbs the NIM-floor risk if it materialises).

## Shared vs per-instance

- **Shared, sized once:** the off-VM LLM endpoint
  (`NVIDIA/Nemotron-3.5-Lightning-30B-A3B` at `https://model.delllabs.local/api/nemotron35/v1`,
  pre-provisioned, capacity
  unknown); NGC image and weight sources; the read-only video and document
  corpora (fixtures).
- **Per-instance, multiplied by 10:** all running containers, the full ~70 GB
  vRAM on each card, the nginx auth-shim (tiny, one per VM), writable
  Elasticsearch/Kafka/Redis/VST state, the ingested RAG index and the
  learner's queries against it, and the learner's work orders in the mock CMMS.
- **vCD isolation reality (ADR-005):** per-VM disks are not shared. Unless a
  shared datastore is mounted, the weight caches (~350 GB per VM) are
  per-VM — first build pulls weights per VM (45–70 minutes) or the VM image
  ships weights pre-baked. The spec assumes **no** shared datastore.

## Exact images & versions

The approved sizing's software stack, plus the mock-wo line and the
`prep-log.md` convention. The user's version data (2026-09-02 — the initial
spec-review confirmations, then the GitHub release data for both blueprint
repos the same day) supersedes the sizing's open/unversioned rows for VSS,
RAG and NemoClaw (`sizing.md` is upstream and unedited; §8 items 1, 2, 3, 4,
7, 28):

| Component | Version | Source / image | Licensing |
| --------- | ------- | -------------- | --------- |
| OS | Ubuntu 24.04 LTS (x86) | vCD VM image | none |
| NVIDIA driver | 580.105.08 — the VSS canonical-matrix **exact pin for Ubuntu 24.04** (580.65.06 is the 22.04 variant — not used; user-supplied host matrix, 2026-09-02; the 580.x driver bundle satisfies the RAG blueprint's CUDA ≥ 12.9 host requirement) | `apt nvidia-driver-580` | none |
| NVIDIA Container Toolkit | 1.17.8+ | apt, `nvidia-ctk runtime configure --runtime=docker` | none |
| Docker Engine | ≥ 28.3.3 **and < 29.5.0** — newer Docker breaks NGC pulls (both blueprints' host matrices, user-supplied 2026-09-02); the exact installed version is recorded in `prep-log.md` | get.docker.com | none |
| Docker Compose | ≥ v2.39.1 (VSS canonical matrix; user-supplied 2026-09-02) | Docker plugin | none |
| NGC CLI | 4.10.0+ | nvcr.io | NGC API key |
| Node.js | 20.x (NodeSource `setup_20.x`) | deb.nodesource.com | none (NemoClaw requirement) |
| Kernel tuning | `vm.max_map_count=262144` (+ `fs.file-max=2097152`, `net.core.somaxconn=4096`) | `/etc/sysctl.d/99-vss.conf` | none — Elasticsearch refuses to start without `vm.max_map_count` |
| VSS | repo tag **v3.2.1** (user's GitHub release data, 2026-09-02 — supersedes the initial v3.2.0 confirmation and the sizing's open set v3.1.0 vs v3.2.1; §8 item 1) | github.com/NVIDIA-AI-Blueprints/video-search-and-summarization | none (images below) |
| VSS agent image | `VSS_AGENT_VERSION=3.2.1` (assumed to track the release tag — the build document's 3.2.0 value corresponds to the v3.2.0 tag; image tag existence verified on nvcr.io at prep, a mismatch is a prep finding → `prep-log.md`, §8 item 2) | nvcr.io, via the VSS compose stack | NVIDIA AI Enterprise developer licence |
| VSS local VLM | `nvcr.io/nim/nvidia/cosmos3-reasoner:1.7` (Cosmos3 Nano Reasoner, 8B-class — the VSS 3.2.1 release's local VLM NIM; the earlier open identity question is resolved by the user's GitHub release data, 2026-09-02; §8 item 7) | NIM image from nvcr.io | NVIDIA AI Enterprise developer licence |
| VSS local LLM NIM | `nvcr.io/nim/nvidia/nemotron-3-nano:1` — **not run in the lab** (the VSS LLM role goes to the shared off-VM endpoint; the `:30081`-absent check applies) | listed by the VSS 3.2.1 release's compose (user-supplied, 2026-09-02) | — (not hosted in the lab) |
| RAG | **v2.6.2** (user's GitHub release data, 2026-09-02 — supersedes v2.6.0 (v2.6.2 fallback); §8 item 3) | github.com/NVIDIA-AI-Blueprints/rag | none (NIMs below) |
| NIMs (6) | exact image:tags (user-supplied from the RAG v2.6.2 `deploy/compose/nims.yaml`, 2026-09-02; §8 item 4; actually-pulled values in `prep-log.md`): `nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:1.13.0`, `nvcr.io/nim/nvidia/llama-nemotron-rerank-1b-v2:1.10.0`, `nvcr.io/nim/nvidia/nemotron-page-elements-v3:1.8.0`, `nvcr.io/nim/nvidia/nemotron-graphic-elements-v1:1.8.0`, `nvcr.io/nim/nvidia/nemotron-table-structure-v1:1.8.0`, `nvcr.io/nim/nvidia/nemotron-ocr-v1:1.3.0` | nvcr.io | NVIDIA AI Enterprise developer licence |
| Elasticsearch | `docker.elastic.co/elasticsearch/elasticsearch:9.3.0` (user-supplied from the RAG repo, 2026-09-02 — **corrects the earlier recorded expected value "0.18.0"**; shared by VSS and RAG, counted once; §8 item 4) | via the VSS/RAG compose stacks | open source (Apache-2.0) |
| VSS internal infra | `confluentinc/cp-kafka:8.2.0` (Kafka), `redis:8.6.2-alpine` (Redis), Arize Phoenix `14.15.0` (observability) — exact images user-supplied from the VSS 3.2.1 release's compose, 2026-09-02 | pulled via the VSS compose stack | — |
| auth-shim | nginx:1.27-alpine (resolved digest in `prep-log.md`) | docker.io, `compose/` (verbatim build-doc contract) | none (open source) |
| mock-wo | python:3.12-slim base (resolved digest in `prep-log.md`); FastAPI 0.115.0, Uvicorn 0.30.6, Pydantic 2.8.2, Jinja2 3.1.4, SQLite (stdlib) | built in-lab from `mock-wo/` (arch-neutral) | none |
| NemoClaw | **v0.0.118** (user-confirmed at spec review, 2026-09-02 — the sizing carried no version; §8 item 28) via the VSS-repo installer `deploy/docker/scripts/nemoclaw/init_nemoclaw.sh` (Node.js 20 required; fresh OpenClaw install required; the installer at the pinned VSS v3.2.1 tag must install/declare v0.0.118 — verified at prep, actual recorded in `prep-log.md`) | vss-public repo | — |
| Shared LLM endpoint | `NVIDIA/Nemotron-3.5-Lightning-30B-A3B` at `https://model.delllabs.local/api/nemotron35/v1` (owner-confirmed 2026-09-07 — supersedes the expected nims.yaml image; platform-side verification target — §8 item 20) | off-VM, pre-provisioned — **not on the VM, not in the per-VM GPU budget** | provided by the platform |

Licensing gate: the **NVIDIA AI Enterprise developer licence** is required to
host the NIMs locally and gates the entire build; an NGC API key and an
NVIDIA Build API key are also required.

## Endpoints, credentials, artifacts (what "ready" means)

**Endpoints (VM-local unless noted):**

| Endpoint | Probe | Ready means |
| -------- | ----- | ----------- |
| auth-shim `http://localhost:8080` | `GET /v1/models` | 200 listing `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` (the served id; the owner-confirmed contract id is the platform line above); streaming tokens arrive incrementally (buffering off) |
| VSS agent `http://localhost:8000` | `GET /health` | agent healthy |
| LVS backend `http://127.0.0.1:38111` | `GET /v1/ready` | 200 |
| RT-VLM `http://127.0.0.1:8018` | `GET /v1/health/ready` | 200 — **the gate before the RAG stack starts** |
| RAG server `http://localhost:8081` | `GET /v1/health` | healthy; `/v1/generate` grounded with citations (prep check) |
| RAG ingestor `http://localhost:8082` | `GET /v1/documents` surface | prep-only; corpus ingested, collection `demo_corpus` recorded |
| mock-wo `http://localhost:8090` | `GET /health` | 200 `{"status":"ok","db":"ok"}`; work-order list empty at baseline |
| OpenShell gateway `127.0.0.1:8085` (health :8086, metrics :8087) | `nemoclaw demo status` | gateway `nemoclaw-8085` healthy — standalone host process (vendor default port 8080 collides with the auth-shim; 08 item 40) |
| OpenClaw dashboard `http://127.0.0.1:18789/` | installer host-forward | NemoClaw UI reachable (beats 3–4 surface) |
| sandbox-side registration | `nemoclaw demo exec -- openclaw nemoclaw status` | "NemoClaw registered" box: managed inference route + Nemotron-3.5-Lightning (the endpoint URL itself is not exposed in status output by design — 08 item 43) |
| shared off-VM endpoint | pre-provisioned, reached via the shim | `GET :8080/v1/models` via the shim lists the served model (the lab's LLM path end-to-end) |
| `:30081` (local LLM NIM) | **must be ABSENT** | the LLM is remote — a local LLM NIM running means misconfiguration |

**Credentials (named concretely; values set by the lab owner at prep — never
committed; §8 items 23–24):**

| Credential | Applies to |
| ---------- | ---------- |
| NGC API key | nvcr.io login + NIM weight pulls |
| NVIDIA Build API key | build.nvidia.com services |
| `SHARED_API_KEY` | auth-shim → shared off-VM inference endpoint |
| Learner VM access (SSH) | the 10 vCD VMs (instructor runbook) |

**Artifacts (expected to exist at start):** `/data/vss-apps-data` (VSS data
dir: VST, Elasticsearch, Kafka, Redis), `/data/corpus` (manuals, logs,
maintenance schedule), `/data/video` (pre-recorded normal + anomaly clips),
`/data/nim-cache` (RAG NIM weights, 200 GB), `~/.cache/nim` (VSS NIM weights,
150 GB), the **pre-built RAG index** (collection `demo_corpus` — indexing is a
non-goal; the lab starts from an already-built index), the repo's `fixtures/`
manifests, and `prep-log.md`.

## Deferred (L5) verification — runs on the VM, never on the dev machine

The six-item checklist from `05-test-strategy.md`, restated here as the
environment-prep / QA content (it is also the substance of the
`lab-prep.md` readiness checks):

1. **Shim:** `GET :8080/v1/models` lists `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` (the served id); streaming check — tokens arrive incrementally, not one blob.
2. **RAG Phase 2:** six NIMs healthy; **actual per-NIM VRAM measured and recorded** (resolves the ~28 GB estimate and the 0.10 floor risk; if total > ~45 GB the VLM fraction is cut before co-residency).
3. **VSS Phase 3:** agent :8000, LVS :38111, RT-VLM :8018 healthy; **VLM VRAM ≈ 34 GB** (dry-run measured 34.1 GB — the 0.40 pin via `RTVI_VLLM_*` is effective, 08 item 39), not ~86 GB; LLM NIM :30081 **not** running.
4. **Co-residency Phase 4:** 7 compute processes, ≤ 80 GB total, no OOM under concurrent VSS + RAG load; both stacks survive a full VM reboot.
5. **NemoClaw Phase 5:** the `40-nemoclaw` gate is green — host-side `nemoclaw demo status` (model + `compatible-endpoint` + healthy inference + `Policies: vss`), the sandbox-side `openclaw nemoclaw status` registration box (via `nemoclaw demo exec`), and `GET :8080/v1/models` via the shim lists the model (08 item 43); HITL prompts collect all four parameters; the report cites RAG-sourced documents (the frag path works — corpus not ignored).
6. **End-to-end beat replay 1→4** (the aha) and optional 5 — the full learner walk-through from a clean start.

## Reboot resilience (zero interaction) — 2026-09-10 dry-run

Contract: a rebooted learner VM needs **no human action** to come back to
a green stack (the ~15 min VLM cold-start is headroom, not interaction).
Installed by `scripts/prep/50-resilience.sh` (idempotent; called as the
final `HARDEN` block of `20-start.sh`).

**What comes back on its own (no units of ours):**
- Docker daemon + `nvidia-persistenced` are `enabled`; every long-running
  container is `unless-stopped`/`always` (VSS, RAG, shim, mock-wo, and the
  NemoClaw sandbox container `openshell-default--demo-*`).
- One-shot vendor containers are `on-failure:5` (bounded: a genuinely
  broken one-shot is visible and self-limiting — an unbounded retry loop is
  how the vendor's `vss-kibana-init` reached 272 restarts; its target
  service `kibana` is never started by the lab's compose profile, so it is
  suppressed to `no` and recorded).
- `live-restore: true` in `/etc/docker/daemon.json`: an accidental
  `systemctl restart docker` no longer takes the stack down.

**What is NOT docker-managed, and therefore gets a unit:**
- The host OpenShell **gateway process** (standalone; 08 item 44) and the
  **:18789 dashboard port-forward**. `nemoclaw-recover.service` (boot,
  after docker, 90 s settle) runs the vendor's own repair command
  `nemoclaw demo recover` (repairs a stopped sandbox gateway AND host
  forwards); on an already-healthy stack it declines with a lifecycle-lock
  error — a healthy no-op, not a failure.

**Continuous self-heal:** `lab-health-watch.timer` (5 min; first run 10 min
after boot) → `health-watch.sh`:
| probe | remediation |
| --- | --- |
| docker daemon unresponsive | `systemctl restart docker` |
| container dead/crashed (policy demands running, last exit ≠ 0) | `docker start` |
| container up but its HTTP gate failing after grace | `docker restart` |
| NemoClaw gateway :8086/healthz or dashboard :18789 down | `nemoclaw demo recover` |
| `nvidia-smi` failing (GPU wedge) | **CRIT log only — no action** (a VM reboot is the only fix; that is a human/platform act) |

Discipline (a watchdog that restarts on every blip just manufactures
flapping): exited-0 containers are never restarted (deliberate completion;
one-shots and clean shutdowns); per-target cooldown 10 min; ≥ 3 actions on
one target within an hour escalates (CRIT + hold the target for an hour);
grace windows after (re)start — 20 min for the VLM (its cold start is
real), 5 min for everything else. Log: journal + `/var/log/lab-health.log`.
Verified on the dev VM 2026-09-10: all-green run (zero actions, no false
positives), deliberate stop left alone, `docker kill` (exit 137) self-healed
with the grace window respected.

**Still human acts:** a GPU wedge (watchdog logs CRIT, someone reboots the
VM); a fresh VM (the full `20-start.sh` prep, which now ends by arming this
layer); a failed `nemoclaw demo recover` that the 5-min timer cannot settle.
