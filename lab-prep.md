---
baseline: 'vCD VM: Ubuntu 24.04 x86, 32 vCPU / 256 GB RAM / 2 TB NVMe, 1x RTX PRO 6000 96 GB (full PCIe passthrough, not vGPU), /dev/shm 32 GB'
software:
  - { name: 'NVIDIA driver', version: '580.105.08', where: 'host (nvidia-smi)' }
  - { name: 'Docker Engine', version: '>= 28.3.3 and < 29.5.0 (newer breaks NGC pulls; cgroupfs driver, default-shm-size 32G; exact installed version in prep-log.md)', where: 'host daemon' }
  - { name: 'Docker Compose', version: '>= v2.39.1 (VSS canonical matrix)', where: 'host plugin' }
  - { name: 'NVIDIA Container Toolkit', version: '1.17.8+', where: 'host (nvidia-ctk runtime configure --runtime=docker)' }
  - { name: 'NGC CLI', version: '4.10.0+', where: 'host' }
  - { name: 'Node.js', version: '20.x', where: 'host (NemoClaw requirement)' }
  - { name: 'kernel tuning', version: 'vm.max_map_count=262144, fs.file-max=2097152, net.core.somaxconn=4096', where: '/etc/sysctl.d/99-vss.conf' }
  - { name: 'auth-shim', version: 'nginx:1.27-alpine (resolved digest in prep-log.md)', where: 'compose service on :8080 (Bearer -> x-api-key for the shared endpoint)' }
  - { name: 'mock-wo (mock work-order service)', version: 'python:3.12-slim base, built in-lab (digest in prep-log.md)', where: 'compose service mock-wo on :8090 (API + UI, /health)' }
  - { name: 'VSS stack', version: 'repo v3.2.1 (user GitHub release data 2026-09-02; supersedes the initial v3.2.0 confirmation and the sizing open set v3.1.0 vs v3.2.1), VSS_AGENT_VERSION=3.2.1 (assumed to track the release tag - the build doc 3.2.0 value corresponds to v3.2.0; prep-verified on nvcr.io)', where: 'prep-cloned to vss-public; agent :8000, LVS :38111, RT-VLM :8018' }
  - { name: 'VSS VLM (local)', version: 'nvcr.io/nim/nvidia/cosmos3-reasoner:1.7 (Cosmos3 Nano Reasoner, 8B-class - the VSS 3.2.1 release default)', where: 'local NIM at 0.40/32768/4 (RT-VLM :8018)' }
  - { name: 'Enterprise RAG', version: 'v2.6.2 (user GitHub release data 2026-09-02; supersedes v2.6.0 + v2.6.2 fallback)', where: 'prep-cloned to /data/rag; server :8081, ingestor :8082 (prep-only)' }
  - { name: 'RAG retriever NIMs (6)', version: 'nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:1.13.0, nvcr.io/nim/nvidia/llama-nemotron-rerank-1b-v2:1.10.0, nvcr.io/nim/nvidia/nemotron-page-elements-v3:1.8.0, nvcr.io/nim/nvidia/nemotron-graphic-elements-v1:1.8.0, nvcr.io/nim/nvidia/nemotron-table-structure-v1:1.8.0, nvcr.io/nim/nvidia/nemotron-ocr-v1:1.3.0 (RAG v2.6.2 nims.yaml; actually-pulled values in prep-log.md)', where: 'local NIMs on GPU (embed, rerank, page-elements, graphic-elements, table-structure, ocr)' }
  - { name: 'Elasticsearch (shared)', version: 'docker.elastic.co/elasticsearch/elasticsearch:9.3.0 (shared by VSS and RAG, counted once; actually-pulled value in prep-log.md)', where: 'via the VSS/RAG compose stacks' }
  - { name: 'NemoClaw', version: 'v0.0.118 (user-confirmed at spec review 2026-09-02; sizing carried no version) via the VSS-repo installer (Node 20; fresh OpenClaw required; installer must install/declare v0.0.118 - actual recorded in prep-log.md)', where: 'OpenClaw sandbox + OpenShell gateway (UI URL in prep-log.md)' }
credentials:
  - { user: 'ngc', secret: 'NGC API key — value set by the lab owner at prep (spec 08 item 23; recorded in prep-log.md, never committed)', applies_to: 'nvcr.io login + NIM weight pulls' }
  - { user: 'nvidia-build', secret: 'NVIDIA Build API key — value set by the lab owner at prep (spec 08 item 23)', applies_to: 'build.nvidia.com services' }
  - { user: 'auth-shim', secret: 'SHARED_API_KEY — value set by the lab owner at prep (spec 08 item 23)', applies_to: 'auth-shim :8080 -> shared off-VM inference endpoint' }
  - { user: 'learner-vm', secret: 'SSH access to the 10 vCD VMs — instructor runbook (spec 08 item 23)', applies_to: 'the 10 learner VMs' }
endpoints:
  - { url: 'http://localhost:8080', purpose: 'auth-shim (Bearer -> x-api-key to the shared endpoint; /v1/models)' }
  - { url: 'http://localhost:8000', purpose: 'VSS agent (/health)' }
  - { url: 'http://127.0.0.1:38111', purpose: 'VSS LVS backend (/v1/ready)' }
  - { url: 'http://127.0.0.1:8018', purpose: 'RT-VLM local VLM (/v1/health/ready) — the gate before the RAG stack starts' }
  - { url: 'http://localhost:8081', purpose: 'RAG server (/v1/generate, /v1/health)' }
  - { url: 'http://localhost:8082', purpose: 'RAG ingestor (prep-only: /v1/documents)' }
  - { url: 'http://localhost:8090', purpose: 'mock work-order service (API + UI, /health) — beat 4 reveal surface' }
  - { url: 'OpenClaw UI URL recorded at prep (prep-log.md)', purpose: 'NemoClaw / OpenClaw UI (beats 3-4 surface)' }
  - { url: 'shared off-VM inference endpoint (pre-provisioned; reached via the auth-shim)', purpose: 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning serving all LLM roles (VSS LLM, RAG generation, NemoClaw)' }
artifacts:
  - { path: '/data/vss-apps-data', purpose: 'VSS data dir (VST video store, Elasticsearch, Kafka, Redis)' }
  - { path: '/data/corpus', purpose: 'document corpus (manuals, logs, maintenance schedule)' }
  - { path: '/data/video', purpose: 'pre-recorded clips (normal-state for beat 1, anomaly segment for beat 2)' }
  - { path: '/data/nim-cache', purpose: 'RAG NIM weights (~200 GB)' }
  - { path: '~/.cache/nim', purpose: 'VSS NIM weights (~150 GB)' }
  - { path: 'RAG index: Elasticsearch collection demo_corpus', purpose: 'pre-built before the learner session (indexing is a non-goal)' }
  - { path: 'repo fixtures/ manifests (video, corpus, rag-index)', purpose: 'fixture manifests + provisional fixtures (curated content swapped at prep)' }
  - { path: 'repo prep-log.md (gitignored)', purpose: 'recorded reality: clone SHAs, resolved digests, actually-pulled image values (mismatch vs the pinned tags = prep finding), measured VRAM, OpenClaw UI URL, NemoClaw installed version (must be v0.0.118)' }
network: 'pre-wired at prep: nvcr.io pulls complete; outbound from the auth-shim to the shared inference endpoint allowed; no learner network configuration'
verify:
  - { check: 'nvidia-smi --query-gpu=name,memory.total --format=csv,noheader', expect: 'RTX PRO 6000, ~97871 MiB (full passthrough, not vGPU)' }
  - { check: 'nvidia-smi --query-gpu=driver_version --format=csv,noheader', expect: '580.105.08' }
  - { check: 'docker info --format "{{.CgroupDriver}}"', expect: 'cgroupfs' }
  - { check: 'sysctl vm.max_map_count', expect: 'vm.max_map_count = 262144' }
  - { check: 'curl -sf http://localhost:8080/v1/models', expect: 'HTTP 200 listing nemotron-3-nano-omni-30b-a3b-reasoning' }
  - { check: 'curl -sf http://localhost:8000/health', expect: 'VSS agent healthy' }
  - { check: 'curl -sf http://127.0.0.1:38111/v1/ready', expect: 'HTTP 200' }
  - { check: 'curl -sf http://127.0.0.1:8018/v1/health/ready', expect: 'HTTP 200 (RT-VLM ready gate)' }
  - { check: 'curl -sf http://localhost:8081/v1/health', expect: 'RAG server healthy' }
  - { check: 'curl -sf http://localhost:8090/health', expect: 'HTTP 200, body {"status":"ok","db":"ok"}' }
  - { check: 'nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader | wc -l', expect: '7 compute processes (VLM + 6 NIMs)' }
  - { check: 'nvidia-smi --query-gpu=memory.used --format=csv,noheader', expect: 'steady state <= 80 GB (committed ~70 GB; VLM ~38 GB, not ~86 GB)' }
  - { check: 'ss -ltn | grep :30081', expect: 'no output (the local LLM NIM must NOT be running — the LLM is remote)' }
  - { check: 'openclaw nemoclaw status --json | jq -r .model', expect: 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning (shared endpoint)' }
  - { check: 'docker version --format "{{.Server.Version}}"', expect: '>= 28.3.3 and < 29.5.0 (newer Docker breaks NGC pulls)' }
  - { check: 'docker compose version --short', expect: '>= v2.39.1' }
---

# Lab prep — NVIDIA Service Blueprint: VSS + RAG + NemoClaw

The environment contract. Everything below is provisioned **before** the
learner starts; the guide never installs, provisions, or mutates the
environment. Derived from `spec/09-environment-footprint.md`, which mirrors
the approved `sizing.md` (no shortfall raised).

**The frontmatter above is the source of truth** — it is machine-readable,
and `hol_parity` executes the `verify` checks against the dev environment to
prove the running lab matches this file (ADR-011/ADR-012). The tables below
restate it for human readers; keep the two in step.

Frontmatter rules (guide-scaffolds, "Frontmatter subset rule"): one-line flow
map per list entry, quote anything with special characters, numbers bare.

> **Registration note:** this lab currently has **no registered `dev`
> environment** (the vCD VM is not reachable from the dev machine), so
> `verify` cannot be executed by `/hol-qa` yet — the checks are declared for
> when a `dev` entry is added to `.holagent/lab-ref.json`. Until then they
> are the environment-prep / QA checklist (spec `09`, L5).

## Baseline

- Image / OS: vCD VM — Ubuntu 24.04 x86, 32 vCPU / 256 GB RAM / 2 TB NVMe, 1× RTX PRO 6000 96 GB (full PCIe passthrough, **not** vGPU), /dev/shm 32 GB.
- Kernel / runtime notes: `vm.max_map_count=262144`, `fs.file-max=2097152`, `net.core.somaxconn=4096` via `/etc/sysctl.d/99-vss.conf` (Elasticsearch refuses to start without `vm.max_map_count`); Docker daemon `native.cgroupdriver=cgroupfs`, `default-shm-size: 32G`; Docker Engine inside the ≥ 28.3.3 / < 29.5.0 window (newer breaks NGC pulls) with Compose ≥ v2.39.1.

## Preloaded software

| Component | Version | Where |
| --------- | ------- | ----- |
| NVIDIA driver | 580.105.08 | host (`nvidia-smi`) |
| Docker Engine | ≥ 28.3.3 and < 29.5.0 (newer breaks NGC pulls; cgroupfs driver, `default-shm-size: 32G`; exact version in `prep-log.md`) | host daemon |
| Docker Compose | ≥ v2.39.1 (VSS canonical matrix) | host plugin |
| NVIDIA Container Toolkit | 1.17.8+ | host (`nvidia-ctk runtime configure --runtime=docker`) |
| NGC CLI | 4.10.0+ | host |
| Node.js | 20.x | host (NemoClaw requirement) |
| kernel tuning | `vm.max_map_count=262144` (+ `fs.file-max`, `net.core.somaxconn`) | `/etc/sysctl.d/99-vss.conf` |
| auth-shim | nginx:1.27-alpine (digest in `prep-log.md`) | compose service on :8080 |
| mock-wo | python:3.12-slim base, built in-lab (digest in `prep-log.md`) | compose service `mock-wo` on :8090 |
| VSS stack | repo **v3.2.1** (user's GitHub release data, 2026-09-02 — supersedes the initial v3.2.0 confirmation and the sizing's open set v3.1.0 vs v3.2.1), `VSS_AGENT_VERSION=3.2.1` (assumed to track the release tag — the build document's 3.2.0 value corresponds to v3.2.0; prep-verified on nvcr.io) | prep-cloned to `vss-public`; agent :8000, LVS :38111, RT-VLM :8018 |
| VSS VLM (local) | `nvcr.io/nim/nvidia/cosmos3-reasoner:1.7` (Cosmos3 Nano Reasoner, 8B-class — the VSS 3.2.1 release default) | local NIM at 0.40/32768/4 (RT-VLM :8018) |
| Enterprise RAG | **v2.6.2** (user's GitHub release data, 2026-09-02 — supersedes v2.6.0 + v2.6.2 fallback) | prep-cloned to `/data/rag`; server :8081, ingestor :8082 |
| RAG retriever NIMs (6) | exact image:tags from the RAG v2.6.2 `nims.yaml` (user-supplied 2026-09-02): `nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:1.13.0`, `nvcr.io/nim/nvidia/llama-nemotron-rerank-1b-v2:1.10.0`, `nvcr.io/nim/nvidia/nemotron-page-elements-v3:1.8.0`, `nvcr.io/nim/nvidia/nemotron-graphic-elements-v1:1.8.0`, `nvcr.io/nim/nvidia/nemotron-table-structure-v1:1.8.0`, `nvcr.io/nim/nvidia/nemotron-ocr-v1:1.3.0` (actually-pulled values in `prep-log.md`) | local NIMs on GPU |
| Elasticsearch (shared) | `docker.elastic.co/elasticsearch/elasticsearch:9.3.0` (shared by VSS and RAG, counted once; actually-pulled value in `prep-log.md`) | via the VSS/RAG compose stacks |
| NemoClaw | **v0.0.118** (user-confirmed at spec review, 2026-09-02; the sizing carried no version) via the VSS-repo installer (Node 20; fresh OpenClaw required; the installer must install/declare v0.0.118 — actual recorded in `prep-log.md`) | OpenClaw sandbox + OpenShell gateway (UI URL in `prep-log.md`) |

## Credentials

| User | Password | Applies to |
| ---- | -------- | ---------- |
| ngc | NGC API key — set by the lab owner at prep (spec 08 item 23; never committed) | nvcr.io login + NIM weight pulls |
| nvidia-build | NVIDIA Build API key — set by the lab owner at prep (spec 08 item 23) | build.nvidia.com services |
| auth-shim | `SHARED_API_KEY` — set by the lab owner at prep (spec 08 item 23) | auth-shim :8080 → shared off-VM inference endpoint |
| learner-vm | SSH access to the 10 vCD VMs — instructor runbook (spec 08 item 23) | the 10 learner VMs |

## URLs, hosts & ports

| URL / host:port | Purpose |
| --------------- | ------- |
| `http://localhost:8080` | auth-shim (Bearer → x-api-key to the shared endpoint; `/v1/models`) |
| `http://localhost:8000` | VSS agent (`/health`) |
| `http://127.0.0.1:38111` | VSS LVS backend (`/v1/ready`) |
| `http://127.0.0.1:8018` | RT-VLM local VLM (`/v1/health/ready`) — the gate before the RAG stack starts |
| `http://localhost:8081` | RAG server (`/v1/generate`, `/v1/health`) |
| `http://localhost:8082` | RAG ingestor (prep-only: `/v1/documents`) |
| `http://localhost:8090` | mock work-order service (API + UI, `/health`) — beat 4 reveal surface |
| OpenClaw UI URL (recorded at prep in `prep-log.md`) | NemoClaw / OpenClaw UI (beats 3–4 surface) |
| shared off-VM inference endpoint (pre-provisioned, via the auth-shim) | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` serving all LLM roles |
| `:30081` | **must be absent** — the local LLM NIM must not be running (the LLM is remote) |

## Network access

- Pre-wired at prep: nvcr.io pulls complete; outbound from the auth-shim to the shared inference endpoint allowed; no learner network configuration.

## Expected starting artifacts

- `/data/vss-apps-data` — VSS data dir (VST video store, Elasticsearch, Kafka, Redis).
- `/data/corpus` — document corpus (manuals, logs, maintenance schedule).
- `/data/video` — pre-recorded clips (normal-state for beat 1, anomaly segment for beat 2).
- `/data/nim-cache` — RAG NIM weights (~200 GB).
- `~/.cache/nim` — VSS NIM weights (~150 GB).
- RAG index — Elasticsearch collection `demo_corpus`, pre-built before the learner session (indexing is a non-goal).
- Repo `fixtures/` manifests (+ provisional fixtures; curated content swapped at prep) and `prep-log.md`.

## Verification

The environment is ready when every `verify` check in the frontmatter passes:

1. `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader` → RTX PRO 6000, ~97871 MiB (full passthrough, not vGPU)
2. `nvidia-smi --query-gpu=driver_version --format=csv,noheader` → `580.105.08`
3. `docker info --format "{{.CgroupDriver}}"` → `cgroupfs`
4. `sysctl vm.max_map_count` → `vm.max_map_count = 262144`
5. `curl -sf http://localhost:8080/v1/models` → HTTP 200 listing `nemotron-3-nano-omni-30b-a3b-reasoning`
6. `curl -sf http://localhost:8000/health` → VSS agent healthy
7. `curl -sf http://127.0.0.1:38111/v1/ready` → HTTP 200
8. `curl -sf http://127.0.0.1:8018/v1/health/ready` → HTTP 200 (RT-VLM ready gate)
9. `curl -sf http://localhost:8081/v1/health` → RAG server healthy
10. `curl -sf http://localhost:8090/health` → HTTP 200, body `{"status":"ok","db":"ok"}`
11. `nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader | wc -l` → 7 compute processes (VLM + 6 NIMs)
12. `nvidia-smi --query-gpu=memory.used --format=csv,noheader` → steady state ≤ 80 GB (committed ~70 GB; VLM ~38 GB, not ~86 GB)
13. `ss -ltn | grep :30081` → no output (the local LLM NIM must NOT be running)
14. `openclaw nemoclaw status --json | jq -r .model` → `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` (shared endpoint)
15. `docker version --format "{{.Server.Version}}"` → ≥ 28.3.3 and < 29.5.0 (newer Docker breaks NGC pulls)
16. `docker compose version --short` → ≥ v2.39.1

Run them with `/hol-qa --env <dev-environment>` once a `dev` environment is
registered; production is verified by the script `/hol-qa-prod` emits, never
by an agent.
