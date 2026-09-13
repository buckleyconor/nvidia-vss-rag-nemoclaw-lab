# Context-Aware Video AI Agents — Build Document

**Single-VM demo: VSS + Enterprise RAG + NemoClaw**
Docker Compose · Ubuntu 24.04 · 1× H100 ~94 GB (vGPU) · single user, no concurrency

---

## 0. Source of truth

Every command in this document comes from one of the following. Where they disagree
with each other, this doc says so explicitly rather than picking silently.

| Source | Used for |
|---|---|
| [VSS repo](https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization) | Repo layout, system requirements, release tags |
| [VSS docs](https://docs.nvidia.com/vss/latest/index.html) | Hardware profiles, remote LLM/VLM config |
| [RAG repo](https://github.com/NVIDIA-AI-Blueprints/rag) | Components, vector DB defaults, deployment paths |
| [NemoClaw docs](https://nemoclawai.io/docs/get-started/quickstart) | CLI, onboarding, inference switching |
| [Blog: Make Sense of Video Analytics](https://developer.nvidia.com/blog/make-sense-of-video-analytics-by-integrating-nvidia-ai-blueprints/) (Nov 2025) | Background — **integration method superseded** |
| [Blog: Integrating Context-Aware Video AI Agents](https://developer.nvidia.com/blog/integrating-context-aware-video-ai-agents-into-enterprise-workflows/) (Jul 2026) | **Authoritative integration procedure** |

> **The two blogs describe different integration mechanisms.** The Nov 2025 post
> patches the VSS Dockerfile to swap the `context-aware-rag` branch and uses
> `<e>…<e>` prompt tags to route sub-prompts to RAG. That was the VSS 2.x approach
> (it references `src/vss-engine/`, `vila-1.5`, and `kubectl`). The Jul 2026 post
> replaces it entirely with the built-in **frag** knowledge-retrieval tool, enabled
> by pointing `VSS_AGENT_CONFIG_FILE` at `config_rag.yml`. **No source patching is
> required.** This build follows the Jul 2026 method. Read the older post for
> architectural background only.

### Version note — read before cloning

The latest **published release tags** are VSS **v3.1.0** (18 Mar 2026) and RAG
**v2.6.0** (4 Jun 2026). You've confirmed 3.2.1 and 2.6.2 exist; they may be newer
tags, container image versions, or internal builds not reflected in the public
release list. Two distinct things are easy to conflate:

- The **repo tag** — what you `git clone -b`.
- `VSS_AGENT_VERSION` — the **agent container image tag**, set in the `.env` file.
  The Jul 2026 blog uses `VSS_AGENT_VERSION=3.2.0` while the repo's latest release
  is 3.1.0, so these version independently.

Confirm both before Phase 3. If `git clone -b v3.2.1` fails, clone `main` and set
`VSS_AGENT_VERSION` to the image tag you want.

---

## 1. What this builds

Three specialised systems composed through APIs, orchestrated by an agent:

- **VSS** ingests video, chunks it, captions each chunk with a local VLM, and
  exposes agent tools: long video summary (LVS), knowledge retrieval (frag), and
  report generation.
- **Enterprise RAG** indexes the document corpus and answers retrieval queries.
  VSS calls it through the frag tool; RAG handles embedding, reranking and vector
  search internally.
- **NemoClaw** reads the `vss-generate-video-report-rag` skill definition, collects
  intent through human-in-the-loop prompts, drives the pipeline, and turns the
  finished report into downstream action.

Design goal is **minimum footprint**: one GPU, one VM, one user. Everything that
must be local is local; one shared model serves all three components.

### Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ Ubuntu 24.04 VM — 32 vCPU / 256 GB RAM / 2 TB NVMe           │
│                                                               │
│  NemoClaw (OpenClaw sandbox + OpenShell gateway)              │
│    └─ skill: vss-generate-video-report-rag                    │
│         │                                                     │
│         ▼                                                     │
│  VSS agent :8000 ──── frag tool ────► RAG server :8081/v1     │
│    ├─ LVS backend :38111                  ├─ Elasticsearch    │
│    ├─ RT-VLM :8018  ◄── local VLM         ├─ ingestor         │
│    └─ VST / Redis / Kafka / Elastic       └─ 6 local NIMs     │
│                                                               │
│  ┌─────────────────────────────────────────────────┐          │
│  │ H100 ~94 GB — 7 local model containers        │          │
│  └─────────────────────────────────────────────────┘          │
│                                                               │
│  auth-shim :8080  (Authorization: Bearer → x-api-key)         │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
              Shared inference endpoint
              NVIDIA/Nemotron-3.5-Lightning-30B-A3B
              (https://model.delllabs.local/api/nemotron35/v1)
```

### Model placement

| Model | Location | Consumer |
|---|---|---|
| VSS default VLM | **Local GPU** | Per-chunk video captioning |
| `llama-nemotron-embed-1b-v2` | **Local GPU** | RAG embeddings |
| `llama-nemotron-rerank-1b-v2` | **Local GPU** | RAG reranking |
| `nemotron-page-elements-v3` | **Local GPU** | RAG — page layout |
| `nemotron-table-structure-v1` | **Local GPU** | RAG — tables |
| `nemotron-graphic-elements-v1` | **Local GPU** | RAG — charts/diagrams |
| `nemotron-ocr` | **Local GPU** | RAG — text recognition |
| `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` (served id; contract id below) | **Shared endpoint** | VSS LLM + RAG generation + NemoClaw |

This replaces three separate models: `nemotron-3-super-120b-a12b` (RAG default
generation), `nemotron-nano-9b-v2` (VSS default LLM), and NemoClaw's default
provider model.

**The shared model is platform-provisioned (owner correction 2026-09-07).**
The shared off-VM endpoint `https://model.delllabs.local/api/nemotron35/v1`
serves the NVFP4 deployment `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4`
(the owner-confirmed contract id `NVIDIA/Nemotron-3.5-Lightning-30B-A3B`; supersedes the earlier
Nemotron Nano Omni 30B A3B Reasoning expectation from the RAG Blueprint's
optional NIM list). VSS documents
remote OpenAI-compatible endpoints for both LLM and VLM roles.

**2026-09-07 dev-VM correction:** the endpoint actually serves the NVFP4
build as `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` (vLLM behind
the Kong gateway). Gates and env pins now use the served id (recorded
reality — prep-log finding); whether the platform adds the confirmed id
as an alias is open (spec/08).

**VLM identity — confirm at deploy time.** The VSS repo README lists
`Cosmos-Reason2-8B`; the current VSS docs name `nvidia/cosmos3-nano-reasoner` as
the only verified local model. Both are 8B-class Qwen3-VL derivatives, so the
memory budget below is unaffected either way. **Take whichever your version ships
as default** — LVS prompts and alert verification are tuned around it, so
substituting costs pipeline accuracy, not just model quality.

---

## 2. VM specification

| Resource | Recommended | Minimum |
|---|---|---|
| vCPU | 32 | 24 |
| RAM | 256 GB | 192 GB |
| Disk | 2 TB NVMe | 1.5 TB |
| GPU | 1× H100 ~94 GB, **vGPU partition** (SKU H100L-94C — learner SKU, platform-confirmed 2026-09-07) | — |
| `/dev/shm` | 32 GB | 16 GB |

### Software floors (from the VSS repo)

| Component | Version |
|---|---|
| OS | Ubuntu 22.04 or 24.04 (x86) |
| NVIDIA driver | **580.105.08** (Ubuntu 24.04) / 580.65.06 (22.04) |
| NVIDIA Container Toolkit | 1.17.8+ |
| Docker | 27.2.0+ |
| Docker Compose | v2.29.0+ |
| NGC CLI | 4.10.0+ |
| Node.js | 20+ (NemoClaw requirement) |

### Licensing and keys

- **NVIDIA AI Enterprise developer licence** is required to locally host NIMs.
  Confirm this before starting — it gates the entire build.
- NGC API key (`ngc.nvidia.com`)
- NVIDIA Build API key (`build.nvidia.com`)

### RAM allocation

| Consumer | Approx. |
|---|---|
| VSS engine, VST, decode buffers | 128 GB |
| Elasticsearch (RAG + VSS both use it) | 32 GB |
| RAG ingestion pipeline (CPU-bound extraction) | 24 GB |
| RAG orchestrator, frontend, Redis, Kafka | 16 GB |
| NemoClaw sandbox + OpenShell gateway | 6 GB |
| OS, Docker, page cache | 16 GB |
| **Total** | **~222 GB** |

192 GB will run. 256 GB means you debug the demo, not the memory.

### Disk

| Path | Size | Contents |
|---|---|---|
| `/var/lib/docker` | 600 GB | Container images |
| `~/.cache/nim` | 150 GB | NIM model weights |
| `$VSS_DATA_DIR` | 700 GB | VST video store, Elastic, Kafka, Redis |
| RAG model cache | 200 GB | Retriever NIM weights |

Use the vGPU H100 partition (platform-selected 2026-09-07) — the full ~94 GB must be
visible to the VM, and NIM profile selection is verified at prep (L5).

---

## 3. GPU memory budget

### How NIM allocates

```
Requested Budget = total_vram × gpu_memory_utilization    (default 0.9)
  ├── Model weights
  ├── Non-torch overhead (CUDA context, NCCL buffers)
  ├── Peak activations
  └── KV cache  ← fills ALL remaining budget
```

A vLLM/TRT-LLM-backed NIM **consumes its entire fraction** whether it needs it or
not. Left at default, the VLM claims ~86 GB and nothing else starts.

The six retriever NIMs are Triton/TensorRT-based and allocate what they need
rather than claiming a budget, so **only the VLM requires explicit fractioning.**

### Allocation

| Model | Backend | Setting | Est. |
|---|---|---|---|
| VSS VLM | TRT-LLM | `--gpu-memory-utilization 0.40`<br>`--max-model-len 32768`<br>`--max-num-seqs 4` | ~38 GB |
| embed-1b-v2 | Triton/TRT | default | ~5 GB |
| rerank-1b-v2 | Triton/TRT | default | ~5 GB |
| page-elements-v3 | Triton/TRT | default | ~5 GB |
| table-structure-v1 | Triton/TRT | default | ~4 GB |
| graphic-elements-v1 | Triton/TRT | default | ~4 GB |
| ocr | Triton/TRT | default | ~5 GB |
| CUDA contexts × 7 | — | — | ~4 GB |
| **Committed** | | | **~70 GB** |
| **Headroom** | | | **~24 GB** |

### Why these values

- **`--max-model-len 32768`** is the highest-leverage knob. Native context runs to
  256K; VSS chunks are seconds long. KV cache scales with context, so this cuts
  the dominant term by roughly an order of magnitude.
- **`--max-num-seqs 4`** — zero concurrency means no reason to reserve batch slots.
- **`--gpu-memory-utilization 0.40`** — 38 GB leaves comfortable KV headroom for
  long chunks while the retriever stack breathes.

### Applying it

Per your confirmation, VSS accepts `--vlm-env-file`:

```
deploy/docker/scripts/dev-profile.sh up -p base \
  --llm-env-file /path/to/llm.env \
  --vlm-env-file /path/to/vlm.env
```

`vlm.env`:
```bash
NIM_PASSTHROUGH_ARGS=--gpu-memory-utilization 0.40 --max-model-len 32768 --max-num-seqs 4
```

### Start order matters

Bring the **VLM up first on an empty GPU**, then the retriever NIMs. vLLM profiles
free memory at startup, so a greedy container starting second behaves differently
from one starting first.

### Open risk

NIM documents a **minimum floor of 0.10** for `gpu_memory_utilization`. It's
unclear whether that floor applies only to NIM's automatic clamping or also to
user-set values. Phase 2 answers this empirically. If any retriever NIM turns out
to enforce a 9.6 GB floor, revise the budget before co-residency.

---

## 4. Phase 0 — Host preparation

### 4.1 Driver

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y nvidia-driver-580=580.105.08-*
sudo reboot

nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
# Expect: H100 (dev-VM SKU H100L-94C), ~96256 MiB, 580.105.08
```

### 4.2 Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo usermod -aG docker $USER   # log out / back in
```

`/etc/docker/daemon.json`:

```json
{
  "default-runtime": "nvidia",
  "runtimes": {
    "nvidia": { "path": "nvidia-container-runtime", "args": [] }
  },
  "exec-opts": ["native.cgroupdriver=cgroupfs"],
  "default-shm-size": "32G"
}
```

```bash
sudo systemctl restart docker
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi
docker compose version   # must be >= 2.29.0
```

> `native.cgroupdriver=cgroupfs` comes from the VSS prerequisites. It conflicts
> with MicroK8s, which expects systemd cgroups — one of the reasons this build
> uses Compose. VSS ships Compose-only anyway, so Kubernetes would only wrap RAG.

### 4.3 Kernel tuning

```bash
sudo tee /etc/sysctl.d/99-vss.conf <<'EOF'
vm.max_map_count=262144
fs.file-max=2097152
net.core.somaxconn=4096
EOF
sudo sysctl --system
```

Elasticsearch refuses to start without `vm.max_map_count`.

### 4.4 Node.js (NemoClaw)

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node --version   # >= 20
```

### 4.5 Keys and directories

```bash
export NGC_CLI_API_KEY='nvapi-...'
export NVIDIA_API_KEY='nvapi-...'
echo "$NGC_CLI_API_KEY" | docker login nvcr.io --username '$oauthtoken' --password-stdin

export VSS_DATA_DIR=/data/vss-apps-data
sudo mkdir -p /data && sudo chown -R $USER:$USER /data
mkdir -p "$VSS_DATA_DIR"/data_log/{elastic/data,elastic/logs,kafka,redis/data,redis/log}
chmod -R 777 "$VSS_DATA_DIR/data_log"
mkdir -p /data/{corpus,video,nim-cache} ~/.cache/nim
```

### Exit criteria

- [ ] `nvidia-smi` reports ~94 GB, driver 580.105.08
- [ ] `docker run --gpus all` succeeds
- [ ] `docker info | grep -i cgroup` shows `cgroupfs`
- [ ] Docker ≥ 27.2.0, Compose ≥ 2.29.0, Node ≥ 20
- [ ] `docker login nvcr.io` succeeds
- [ ] AI Enterprise developer licence confirmed

---

## 5. Phase 1 — Auth shim

The shared endpoint expects `x-api-key`. VSS (`NVIDIA_API_KEY` +
`LLM_ENDPOINT_URL`), RAG (`APP_LLM_SERVERURL`) and NemoClaw
(`COMPATIBLE_API_KEY` + `NEMOCLAW_ENDPOINT_URL`) all emit OpenAI-style
`Authorization: Bearer`. One translating proxy solves it once for all three.

`auth-shim/nginx.conf.template`:

```nginx
server {
    listen 8080;

    location / {
        proxy_pass          ${UPSTREAM_URL};
        proxy_http_version  1.1;

        proxy_set_header    Authorization "";
        proxy_set_header    x-api-key ${SHARED_API_KEY};
        proxy_set_header    Host ${UPSTREAM_HOST};

        # Required for SSE / streaming completions
        proxy_buffering     off;
        proxy_cache         off;
        proxy_read_timeout  600s;
        proxy_send_timeout  600s;
    }
}
```

`docker-compose.shim.yml`:

```yaml
services:
  auth-shim:
    image: nginx:1.27-alpine
    container_name: auth-shim
    volumes:
      - ./auth-shim/nginx.conf.template:/etc/nginx/templates/default.conf.template:ro
    environment:
      UPSTREAM_URL:   ${SHARED_ENDPOINT_URL}
      UPSTREAM_HOST:  ${SHARED_ENDPOINT_HOST}
      SHARED_API_KEY: ${SHARED_API_KEY}
    ports: ["8080:8080"]
    networks: [demo-net]
    restart: unless-stopped

networks:
  demo-net:
    name: demo-net
```

`nginx:alpine` runs `envsubst` over `/etc/nginx/templates` at startup, so the
variables above are substituted automatically.

### Verify

```bash
docker compose -f docker-compose.shim.yml up -d

curl -s http://localhost:8080/v1/models -H "Authorization: Bearer dummy" | jq '.data[].id'
# Expect nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 (2026-09-07: served NVFP4 id)

# Streaming check — tokens must arrive incrementally, not as one blob
curl -N http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" -H "Authorization: Bearer dummy" \
  -d '{"model":"nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4",
       "messages":[{"role":"user","content":"count to twenty"}],"stream":true}'
```

If either fails, stop. Every later phase depends on this.

---

## 6. Phase 2 — RAG standalone

### 6.1 Clone and configure

```bash
cd /data && git clone https://github.com/NVIDIA-AI-Blueprints/rag.git
cd rag && git checkout v2.6.2   # fall back to v2.6.0 if the tag is absent
```

Edit `variables.env` / export before deploying:

```bash
# Generation LLM → shared endpoint via the shim
export APP_LLM_MODELNAME="nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4"
export APP_LLM_SERVERURL="auth-shim:8080"

# Elasticsearch is the blueprint default — keep it.
# Milvus is the GPU-accelerated alternative and would cost a second GPU budget.
export APP_VECTORSTORE_NAME="elasticsearch"

# Local retriever NIMs
export APP_EMBEDDINGS_MODELNAME="nvidia/llama-nemotron-embed-1b-v2"
export APP_RANKING_MODELNAME="nvidia/llama-nemotron-rerank-1b-v2"

export MODEL_DIRECTORY=/data/nim-cache
export NGC_API_KEY="$NGC_CLI_API_KEY"
```

Leave `ENABLE_AGENTIC_RAG` **off** for now — the LangGraph plan-and-execute
pipeline multiplies calls to the shared endpoint. Turn it on later if the demo
needs multi-hop retrieval.

Follow `docs/deploy-docker-self-hosted.md` for the exact compose invocation for
your tag; the deployment layout has moved between releases and the doc in-tree is
authoritative. **Do not start the LLM NIM profile** — generation is remote.

First run downloads model weights: budget 45–70 minutes.

### 6.2 Measure actual VRAM — the important step

With **only** the RAG NIMs running:

```bash
nvidia-smi --query-compute-apps=pid,used_memory --format=csv
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
docker ps --format 'table {{.Names}}\t{{.Status}}'
```

| Model | Estimated | **Actual** |
|---|---|---|
| embed-1b-v2 | ~5 GB | |
| rerank-1b-v2 | ~5 GB | |
| page-elements-v3 | ~5 GB | |
| table-structure-v1 | ~4 GB | |
| graphic-elements-v1 | ~4 GB | |
| ocr | ~5 GB | |
| **Total** | **~28 GB** | |

**If the total exceeds ~45 GB, reduce the VLM fraction before Phase 4.**

### 6.3 Ingest and validate

```bash
# Ingest corpus (port per your release's ingestor service)
curl -X POST http://localhost:8082/v1/documents \
  -F "documents=@/data/corpus/manual-01.pdf" \
  -F 'data={"collection_name":"demo_corpus"}'

# Query
curl -X POST http://localhost:8081/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"<question your corpus answers>"}],
       "collection_name":"demo_corpus","use_knowledge_base":true}'
```

Record the collection name — Phase 3 needs it.

### Exit criteria

- [ ] Six NIMs healthy; actual VRAM recorded
- [ ] Corpus ingested; `KNOWLEDGE_COLLECTION` value noted
- [ ] `/v1/generate` returns grounded answers with citations
- [ ] Shim access log confirms the shared endpoint served generation

---

## 7. Phase 3 — VSS standalone

**Stop the RAG NIMs first.** The VLM must profile an empty GPU.

### 7.1 Clone

```bash
git clone https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization.git ~/vss-public
cd ~/vss-public
echo "$NGC_CLI_API_KEY" | docker login nvcr.io --username '$oauthtoken' --password-stdin
```

### 7.2 The `.env` file

VSS deployment is `.env`-driven. Edit the LVS profile file — per the Jul 2026 blog,
`deploy/docker/developer-profiles/dev-profile-lvs/.env`.

> **Path check.** The current repo `main` shows a `deployments/developer-workflow/`
> tree rather than `deploy/docker/developer-profiles/`. The layout moved between
> releases. Locate the actual file before editing:
> `find . -name '.env' -path '*lvs*'`

```bash
# Deployment selection
MODE=2d
BP_PROFILE=bp_developer_lvs
HARDWARE_PROFILE=H100

# LLM / VLM placement
# Blog default is local_shared for both. We want the LLM remote.
# Verify the correct remote value for your release — the CLI equivalent is
# `--use-remote-llm` (see VSS "Configure the LLM" docs).
LLM_MODE=remote
VLM_MODE=local_shared
VLM_DEVICE_ID='0'

# Paths — you MUST set these
VSS_APPS_DIR="/home/<user>/vss-public/deploy/docker"
VSS_DATA_DIR="/data/vss-apps-data"
HOST_IP='<your-ip>'

# Agent image + RAG-enabled config
VSS_AGENT_VERSION=3.2.0
VSS_AGENT_CONFIG_FILE=./deploy/docker/developer-profiles/dev-profile-lvs/vss-agent/configs/config_rag.yml

# Credentials
NGC_CLI_API_KEY='nvapi-...'
NVIDIA_API_KEY='nvapi-...'

# Remote LLM → shared endpoint via shim
LLM_ENDPOINT_URL='http://auth-shim:8080'

# RAG Blueprint connection (read by config_rag.yml) — note the /v1 suffix
RAG_SERVER_URL='http://rag-server:8081/v1'
RAG_API_KEY='<your-rag-key>'
KNOWLEDGE_COLLECTION='demo_corpus'
```

Two notes:

- `VSS_AGENT_CONFIG_FILE` pointing at `config_rag.yml` is what enables the frag
  knowledge-retrieval tool. The default `config.yml` has it **off**.
- Those three `RAG_` values are the **only** RAG settings the agent needs. It calls
  the RAG server's search endpoint; RAG handles embedding, reranking and vector
  search internally. Configure the vector DB, embedder and reranker on the RAG
  deployment itself.

### 7.3 Deploy

```bash
cd ~/vss-public/deploy/docker
docker compose \
  --env-file developer-profiles/dev-profile-lvs/.env \
  -f compose.yml \
  up -d
```

The helper script does the same and creates the data directories for you:

```bash
./deploy/docker/scripts/dev-profile.sh up \
  --profile lvs \
  --hardware-profile H100 \
  --vlm-env-file /path/to/vlm.env
```

The compose profile is selected automatically from `COMPOSE_PROFILES` in the
`.env` file. The stack starts VST, Redis, Elasticsearch, LVS, the NIM, and the
agent.

### 7.4 Verify

NIM load takes 5–15 minutes.

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
curl -sS http://localhost:8000/health              # VSS agent
curl -f  http://127.0.0.1:38111/v1/ready           # LVS backend
curl -f  http://127.0.0.1:8018/v1/health/ready     # RT-VLM
# LLM NIM :30081 should NOT be running — the LLM is remote

# Fraction respected? Expect ~38 GB, not ~86 GB
nvidia-smi --query-gpu=memory.used --format=csv
```

If VRAM shows ~86 GB the env file was not applied:

```bash
docker inspect <rt-vlm-container> | jq '.[0].Config.Env'
```

### Exit criteria

- [ ] Agent, LVS and RT-VLM all healthy
- [ ] VLM VRAM ≈ 38 GB
- [ ] Summarisation completes end to end on a short clip
- [ ] Shim log shows VSS aggregation traffic

---

## 8. Phase 4 — Co-residency

```bash
# 1. Shim (running)
# 2. VSS — VLM claims 40% of an empty GPU
cd ~/vss-public/deploy/docker && docker compose --env-file ... up -d

# 3. Gate on RT-VLM before starting RAG
curl --retry 90 --retry-delay 10 --retry-all-errors -sf \
     http://127.0.0.1:8018/v1/health/ready

# 4. RAG stack
cd /data/rag && docker compose ... up -d
```

Steady state: **~70 GB used, ~24 GB free, 7 compute processes.**

```bash
watch -n2 nvidia-smi
```

Run a VSS summarisation and a RAG query concurrently. Watch `docker logs` for OOM.

### If it does not fit

1. `--max-model-len 16384` (halves VLM KV cache)
2. `--gpu-memory-utilization 0.35`
3. `--max-num-seqs 2`
4. Drop unused extraction NIMs — no charts in the corpus means
   `graphic-elements` is dead weight

### Exit criteria

- [ ] Seven processes co-resident, ≤ 80 GB total
- [ ] No OOM under concurrent load
- [ ] Both stacks survive a full VM reboot

---

## 9. Phase 5 — NemoClaw

The NemoClaw installer ships **inside the VSS repo** and does the whole setup in
one command.

### 9.1 Install

For a custom OpenAI-compatible endpoint (our case):

```bash
cd ~/vss-public

NEMOCLAW_PROVIDER=custom \
NEMOCLAW_ENDPOINT_URL='http://auth-shim:8080/v1' \
COMPATIBLE_API_KEY='dummy' \
  bash deploy/docker/scripts/nemoclaw/init_nemoclaw.sh demo
```

This single command:

- onboards NemoClaw and creates the OpenShell gateway
- configures the model provider
- applies the VSS sandbox policy (grants sandbox access to the VSS agent on
  **port 8000**)
- installs the repo skills — including **`vss-generate-video-report-rag`** — into
  the sandbox as an OpenClaw plugin
- prints the OpenClaw UI URL

> NemoClaw requires a **fresh** OpenClaw installation. If OpenClaw is already
> present on the VM, remove it first.

### 9.2 Extend network policy

The default policy grants VSS on :8000 only. Add:

| Target | Port | Purpose |
|---|---|---|
| VSS agent | 8000 | Video analysis (default) |
| RAG server | 8081 | Direct retrieval, if NemoClaw calls it outside VSS |
| auth-shim | 8080 | LLM inference |
| Downstream (Jira/Slack/MCP) | varies | Action |

See the NemoClaw *Customize Network Policy* docs to pre-approve trusted hosts
rather than approving interactively each run.

### 9.3 Verify the active model

```bash
openclaw nemoclaw status --json
```

Output includes the active provider, model and endpoint. Models can also be
switched at runtime **without restarting the sandbox**:

```bash
openshell inference set --provider <provider> --model <model-id>
```

> The `nvidia-nim` provider's registered model table lists
> `nvidia/nemotron-3-nano-30b-a3b` — the text-only Nano 30B, **not** the
> shared lab model (the NVFP4 deployment `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` via the shim).
> That's why we use `NEMOCLAW_PROVIDER=custom` and name the model
> ourselves through the shim.

### 9.4 End-to-end test

```bash
nemoclaw demo connect
openclaw tui
```

Inside the OpenClaw UI (not the shell):

1. `/new` — start a fresh session
2. `I want to generate a video summary report for <VIDEO_NAME>.`

The agent then collects parameters through HITL prompts — scenario, events of
interest, objects to track, and an optional knowledge-retrieval query — then runs
LVS with RAG context and produces the report.

### Exit criteria

- [ ] host `nemoclaw demo status` shows `Provider: compatible-endpoint` + model `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` (and the sandbox-side box via `nemoclaw demo exec -- openclaw nemoclaw status` shows the same model + `NemoClaw registered`)
- [ ] HITL prompts appear and collect all four parameters
- [ ] Report generated with timestamps, citations and recommended actions
- [ ] Report cites RAG-sourced documents, not just video content

---

## 10. Phase 6 — Downstream action

The report becomes the trigger, not the endpoint. NemoClaw can create tickets with
priority and assignment, escalate patterns across runs, bundle evidence for
review, or route gaps to follow-up workflows.

The blog demonstrates Jira. A ticket queue or Slack works equally well and demos
faster. Choose based on what your audience already uses.

---

## 11. Performance expectations

Measured runtime split for the video-analysis-to-ticket pipeline:

| Component | Share of runtime |
|---|---|
| VSS video analysis | ~92% |
| NemoClaw orchestration | ~5.7% |
| Enterprise RAG retrieval | ~1.3% |
| LLM fusion | ~1.0% |

RAG retrieval adds ~1.69 s and LLM fusion ~1.24 s against a ~250 s end-to-end
summarisation. **Integration is essentially free; the VLM is the whole cost.**
This is why the VLM fraction is the one number worth tuning carefully and why
moving the LLM remote costs nothing in latency terms.

HITL is asynchronous — the system stands by while the user answers, so it doesn't
count against pipeline latency.

---

## 12. Agent skills — worth using

Both repos ship agentskills.io-compatible skills that let a coding assistant
operate the blueprints from natural language.

**RAG:**
```bash
cd /data/rag && npx skills add .
```
Installs `rag-blueprint` (deploy, configure, troubleshoot, REST API),
`rag-eval` (RAGAS quality benchmarks), and `rag-perf` (latency/throughput).

**VSS:** `skills/` contains one subdirectory per skill covering deploy and usage
of search, summarisation, alerts, VIOS, RT-VLM and LVS. See `skills/README.md`
for the catalog and install notes.

These are likely to save more time than they cost during Phases 2–5, and
`vss-generate-video-report-rag` is the skill NemoClaw itself reads.

---

## 13. Operations

### Health check

```bash
#!/usr/bin/env bash
set -uo pipefail

echo "=== GPU ==="
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv

echo "=== Endpoints ==="
check() { printf '%-45s' "$1"; curl -sf -o /dev/null "$1" && echo OK || echo FAIL; }
check http://localhost:8080/v1/models
check http://localhost:8000/health
check http://127.0.0.1:38111/v1/ready
check http://127.0.0.1:8018/v1/health/ready
check http://localhost:8081/v1/health

echo "=== Exited containers ==="
docker ps -a --filter status=exited --format '{{.Names}}: {{.Status}}'

echo "=== NemoClaw ==="
openclaw nemoclaw status --json 2>/dev/null | jq -r '.model // "unavailable"'
```

### Cold start order

1. `auth-shim`
2. VSS (VLM must see an empty GPU)
3. Wait for RT-VLM ready
4. RAG stack
5. NemoClaw sandbox

### Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| VLM claims ~86 GB | `--vlm-env-file` not applied | `docker inspect` the env; check path resolution |
| Second NIM OOMs at startup | Wrong start order | Full stop; restart per order above |
| `ValueError: To serve at least one request…` | Fraction too low for `max-model-len` | Raise fraction or lower context |
| Elasticsearch exits immediately | `vm.max_map_count` unset | Re-apply `/etc/sysctl.d/99-vss.conf` |
| 401 from shared endpoint | Shim not stripping `Authorization` | Confirm `proxy_set_header Authorization ""` |
| Streaming arrives as one blob | nginx buffering | Confirm `proxy_buffering off` |
| VSS answers ignore the corpus | frag tool disabled | `VSS_AGENT_CONFIG_FILE` must point at `config_rag.yml` |
| frag returns nothing | Wrong collection or missing `/v1` | Check `KNOWLEDGE_COLLECTION` and `RAG_SERVER_URL` suffix |
| NemoClaw install fails | Existing OpenClaw | Requires a fresh OpenClaw installation |

### Rollback

Each phase is independently reversible via `docker compose down` on the affected
stack. Model weights persist in `/data/nim-cache` and `~/.cache/nim`, so
re-deployment after the first run takes minutes, not an hour.

---

## 14. Open items

| Item | Resolve by |
|---|---|
| Confirm v3.2.1 / v2.6.2 tags vs. `VSS_AGENT_VERSION` image tag | Before cloning |
| Locate the actual LVS `.env` path in your release | Phase 3 |
| Confirm the correct `LLM_MODE` value for remote LLM | Phase 3 |
| Confirm which VLM your version ships as default | Phase 3 |
| Does the 0.10 `gpu_memory_utilization` floor apply to user values? | Phase 2 |
| Record actual per-NIM VRAM; revise if > 45 GB | Phase 2 |
| Select vertical and assemble corpus | Phase 2 |
| Choose downstream action target | Phase 6 |

---

## 15. Future work

**Zero local GPU for VSS.** VSS supports remote VLMs over any OpenAI-compatible
endpoint. If the shared Nemotron-3.5-Lightning endpoint can serve the VLM role, the LVS profile
with remote LLM *and* VLM needs no local GPU, leaving only the RAG retriever stack
on the card. Unverified — only the default VLM is verified for local deployment,
and LVS prompts are tuned around it. Treat as a phase-2 experiment.

**Scale to Charmed Kubernetes.** RAG ships a Helm chart (validated on OpenShift
behind an `openshift.enabled` flag) and ports as-is. VSS is Compose-only, so a
hybrid pattern — VSS on the host, RAG in-cluster — is the lowest-risk path if this
graduates to the shared lab.

**Agentic RAG.** `ENABLE_AGENTIC_RAG` adds a LangGraph plan-and-execute pipeline
with scope discovery, parallel sub-tasks and optional verification. Valuable for
multi-hop questions across manuals, but it multiplies shared-endpoint calls —
enable only after the baseline is stable.

---

## Appendix — vertical selection

The blogs demo a "healthy eating coach". Partner deployments map better onto a
Dell audience:

- **Computacenter** ran the full DETECT → REASON → ACT pipeline on a Run:AI
  cluster for predictive maintenance — drone, borescope and thermal inspection
  footage through VSS, OEM manuals through RAG, NemoClaw auto-drafting Maximo work
  orders. Footage-to-work-order dropped from 30–45 minutes to roughly 19 seconds
  across four asset classes.
- **VAST Data** orchestrates a real-time VSS pipeline on the VAST DataEngine,
  processing live game streams with VAST RAG over VastDB and vectors, running
  end-to-end on NVIDIA DSX AIR.

The inspection-and-manuals pattern reuses the most from work you've already done
and gives the extraction NIMs something real to chew on.
