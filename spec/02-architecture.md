# 02 — Architecture

Components, data flow, data model, and interfaces. The mock work-order service (mock-wo) has **no upstream design** — per the spec authoring rule for this lab, its full contract is pinned here and in `03-build-decisions.md` (build/tooling side). Everything else is the vendor blueprints' documented surface, consumed as contracts from the build document.

## Major components

| # | Component | Kind | Responsibility | Beats served |
| --- | --- | --- | --- | --- |
| 1 | **auth-shim** | `nginx:1.27-alpine` container, :8080 (contract: build doc Phase 1, reused verbatim) | Translates `Authorization: Bearer` → `x-api-key` for the shared endpoint; one tiny container per VM; `proxy_buffering off` for SSE streaming | All LLM traffic (beats 2–4) |
| 2 | **VSS stack** | Vendor blueprint, repo tag **v3.2.1** (user's GitHub release data, 2026-09-02), agent image **`VSS_AGENT_VERSION=3.2.1`** (assumed to track the release tag — the build document's 3.2.0 value corresponds to the v3.2.0 tag; image tag existence verified on nvcr.io at prep → `prep-log.md`), `.env`-driven Compose deploy | Agent :8000 (`/health`), LVS backend :38111 (`/v1/ready`), RT-VLM :8018 (`/v1/health/ready`), VST, Redis `redis:8.6.2-alpine`, Kafka `confluentinc/cp-kafka:8.2.0`, Elasticsearch. The local VLM `nvcr.io/nim/nvidia/cosmos3-reasoner:1.7` (Cosmos3 Nano Reasoner, 8B-class) runs local at `--gpu-memory-utilization 0.40 --max-model-len 32768 --max-num-seqs 4` (~38 GB est.). `VSS_AGENT_CONFIG_FILE` → `config_rag.yml` enables the **frag** tool | 1 (baseline), 2 (alert), 3 (report + retrieval path) |
| 3 | **Enterprise RAG stack** | Vendor blueprint, **v2.6.2** (user's GitHub release data, 2026-09-02) | Server :8081 (`/v1/generate`, `/v1/health`), ingestor :8082 (`/v1/documents`, prep-time only), orchestrator, frontend, 6 retrieval NIMs (Triton/TRT, ~28 GB est. — exact image:tags in Model placement), shared Elasticsearch `docker.elastic.co/elasticsearch/elasticsearch:9.3.0`. `ENABLE_AGENTIC_RAG` **off** | 3 (retrieved documents = the reveal's evidence) |
| 4 | **NemoClaw** | VSS-repo installer `deploy/docker/scripts/nemoclaw/init_nemoclaw.sh` (fresh OpenClaw required; Node 20 host requirement) | OpenClaw sandbox + OpenShell gateway; reads the `vss-generate-video-report-rag` skill; HITL kick-off; drives VSS + RAG; performs the downstream action (POST to mock-wo) | 3 (visible tool calls/reasoning), 4 (work order), 5 (triage) |
| 5 | **mock-wo (mock CMMS)** | **This lab's only real application code.** Python 3.12 / FastAPI, CPU-only Docker image, :8090 (contract below) | Work orders + monitoring notes + in-app notification feed; server-rendered UI the learner watches beat 4 land in | 4 (reveal target), 5 (note reveal) |
| 6 | **Fixtures** | Repo data: pre-recorded clips, document corpus, pre-built RAG index artifact slot | Normal-state clips (beat 1), anomaly segment (beat 2), manuals/logs/schedule corpus (beat 3 retrieval), index ready before the session (indexing is a non-goal) | 1–3 |
| 7 | **Shared off-VM LLM endpoint** | Pre-provisioned, **not on the VM, not in the GPU budget** | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` via auth-shim; serves VSS LLM role + RAG generation + NemoClaw (replaces `nemotron-3-super-120b-a12b`, `nemotron-nano-9b-v2`, and NemoClaw's default model) | All LLM roles |
| 8 | **Per-VM state stores** | Vendor-managed: Elasticsearch, Kafka, Redis, VST (`VSS_DATA_DIR=/data/vss-apps-data`), NIM caches (`~/.cache/nim`, `/data/nim-cache`), mock-wo SQLite volume | Writable per-instance state; wiped on VM reset. Elasticsearch is **shared by VSS and RAG, counted once** in the sizing | steady state |

**Model placement** (build doc §1): local GPU = VSS VLM `nvcr.io/nim/nvidia/cosmos3-reasoner:1.7` (Cosmos3 Nano Reasoner — VSS 3.2.1 release default) + the six retrieval NIMs `nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:1.13.0`, `nvcr.io/nim/nvidia/llama-nemotron-rerank-1b-v2:1.10.0`, `nvcr.io/nim/nvidia/nemotron-page-elements-v3:1.8.0`, `nvcr.io/nim/nvidia/nemotron-graphic-elements-v1:1.8.0`, `nvcr.io/nim/nvidia/nemotron-table-structure-v1:1.8.0`, `nvcr.io/nim/nvidia/nemotron-ocr-v1:1.3.0` (all user-supplied from the blueprint release data, 2026-09-02) = 7 compute processes at steady state, ~70 GB committed / ~26 GB headroom (estimates). Shared endpoint = the 30B Nano Omni serving all three LLM roles. Measured run split (~250 s e2e): VSS video analysis ~92%, NemoClaw ~5.7%, RAG retrieval ~1.3% (~1.69 s), LLM fusion ~1.0% (~1.24 s) — the VLM is the whole cost; the off-VM LLM is latency-neutral.

## Data flow

```
                shared off-VM endpoint (pre-provisioned — NOT on the VM)
                nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
                               ▲ x-api-key (Bearer stripped at the shim)
                               │
┌────────────────────────────────────────────────────────────────────────┐
│ vCD VM — Ubuntu 24.04 · 32 vCPU · 256 GB · 2 TB · 1× RTX PRO 6000 96 GB │
│                                                                        │
│  learner ──▶ OpenClaw UI (NemoClaw)        [beat 3 kick-off; 3–4 shown] │
│                    │  skill: vss-generate-video-report-rag             │
│                    ▼                                                   │
│  VSS agent :8000 ──frag──▶ RAG server :8081 ─▶ 6 NIMs (local GPU)      │
│   ├─ LVS :38111                   ├─ Elasticsearch (shared w/ VSS)     │
│   ├─ RT-VLM :8018 ◀─ 8B VLM       ├─ ingestor :8082 (prep only)        │
│   └─ VST / Redis / Kafka          └─ orchestrator / frontend           │
│                                                                        │
│  auth-shim :8080 (nginx:1.27-alpine) ──▶ shared endpoint               │
│   consumers: VSS LLM (LLM_ENDPOINT_URL), RAG generation                │
│   (APP_LLM_SERVERURL), NemoClaw (NEMOCLAW_ENDPOINT_URL)                │
│                                                                        │
│  NemoClaw diagnosis ──POST──▶ mock-wo :8090 (CPU-only, local SQLite)   │
│                                              └─▶ mock CMMS UI ◀── learner │
│                                                   [beat 4 reveal; beat 5 note] │
└────────────────────────────────────────────────────────────────────────┘
```

### Beat-by-beat flow — every beat has something that shows it

| Beat | Learner does | Path through components | What the learner **sees** |
| --- | --- | --- | --- |
| 1 — baseline | Plays pre-recorded **normal-state** clips (fixtures) | VST ingest → RT-VLM captioning → LVS (LLM via shim) | Pipeline running healthy, **no alerts** (LVS UI / stack status) |
| 2 — anomaly | Plays the **anomaly segment** (e.g., motor bearing thermal/vibration) | Same path; LVS alert logic fires | **Alert raised, affected equipment identified** (LVS UI) |
| 3 — diagnosis | One instruction to NemoClaw in the OpenClaw UI (HITL kick-off; the agent collects scenario/events/objects/knowledge-query parameters) | skill → VSS agent (`frag` tool, `config_rag.yml`) → RAG server :8081 → embed/rerank/OCR NIMs → Elasticsearch | **Tool calls + retrieved documents + reasoning visible** in the OpenClaw UI |
| 4 — work order (**aha**) | *Nothing* — autonomous from the single instruction onward | NemoClaw action step → `POST http://mock-wo:8090/api/v1/work-orders` | **Work order appears in the mock CMMS UI + notification delivered** (~90 s of visible agent work) |
| 5 — triage (optional) | Injects a second anomaly of a different kind (or adjusts the trigger) | Same path; agent verdict differs | **Monitoring note appears, no work order** — the agent triaged, it did not script-follow |

## Start order (non-negotiable — density-relevant)

The VLM must profile an **empty GPU first**; a greedy container profiling the GPU before it breaks the co-residency budget (build doc failure modes).

| Step | Action | Gate |
| --- | --- | --- |
| 1 | Start **auth-shim** (+ **mock-wo**) | shim: `GET /v1/models` via :8080 lists the model; streaming check incremental. mock-wo: `GET /health` — **mock-wo is CPU-only and touches no GPU; starting it with the shim is safe and deliberate** so the CMMS UI is up and visibly empty before beats 1–2 |
| 2 | Start **VSS** (VLM claims 40% of the empty GPU) | agent :8000 `/health`, LVS :38111 `/v1/ready` |
| 3 | **Gate on RT-VLM ready** before anything else GPU-adjacent | `curl --retry 90 --retry-delay 10 --retry-all-errors -sf http://127.0.0.1:8018/v1/health/ready` (NIM load 5–15 min); VLM VRAM ≈ 38 GB (not ~86 GB) |
| 4 | Start **RAG stack** (ingestor ingests the corpus at prep; index ready before the session) | :8081 `/v1/health`; six NIMs healthy; **actual per-NIM VRAM measured and recorded** (Phase 2 step) |
| 5 | Start **NemoClaw sandbox** (`init_nemoclaw.sh`, fresh OpenClaw) | `openclaw nemoclaw status` shows the custom endpoint + Nano Omni model |

Encoded as `scripts/prep/20-start.sh` (with `--dry-run` — see `03-build-decisions.md`).

## Data model

Only the mock-wo entities are spec-defined; everything else (VST/Elasticsearch/Kafka/Redis state, RAG collections) is vendor-managed per-VM state.

### `WorkOrder` (mock-wo)

| Field | Type / constraint | Required | Notes |
| --- | --- | --- | --- |
| `id` | string, UUIDv4 | — (generated) | surrogate key |
| `title` | string, 1–200 chars | yes | e.g. "Bearing replacement — M-3021 motor drive" |
| `description` | string, ≤ 8000 chars | yes | the diagnosis text the agent composed |
| `equipment` | string, 1–100 chars | yes | asset name/ID the alert identified (ties back to beat 2) |
| `anomaly_ref` | string, 1–200 chars | yes | reference to the VSS alert / clip / report that triggered it (agent-provided) |
| `priority` | enum `low \| medium \| high \| critical` | yes | agent triage output |
| `assigned_to` | string, nullable | no | team/person (agent-provided; nullable — triage may leave it unassigned) |
| `status` | enum `open \| in_progress \| resolved \| cancelled` | no (default `open`) | PATCH-able |
| `citations` | array of `Citation`, 0–50 items | no (default `[]`) | the evidence; rendered on the detail page |
| `created_at` / `updated_at` | ISO-8601 UTC | — (generated) | |

`Citation`: `source_type` enum `vss \| rag \| agent`; `source_id` string ≤ 200 (clip/timestamp, manual doc id, report id); `quote` string ≤ 2000.

### `MonitoringNote` (mock-wo — beat 5)

| Field | Type / constraint | Required | Notes |
| --- | --- | --- | --- |
| `id` | UUIDv4 | — (generated) | |
| `equipment` | string, 1–100 | yes | |
| `description` | string, ≤ 4000 | yes | why this anomaly is a note, not a work order |
| `anomaly_ref` | string, 1–200 | yes | |
| `created_at` | ISO-8601 UTC | — (generated) | |

### `Notification` (mock-wo — the notification path to the maintenance team)

| Field | Type / constraint | Notes |
| --- | --- | --- |
| `id` | UUIDv4 | |
| `work_order_id` | FK → `WorkOrder.id` | created **atomically with the work order** |
| `channel` | fixed value `"in_app"` | the only channel |
| `message` | string, ≤ 500 | e.g. "Work order WO-… filed: <title> (priority high, equipment M-3021)" |
| `read_at` | ISO-8601 UTC, nullable | set when the learner opens the feed |

**Notification mechanism (named):** an **in-app notification feed** persisted in the same SQLite store and rendered as the "Notifications" pane of the mock CMMS UI. The mock has no mailer, no webhook, no external integration — in this lab the "maintenance team" is the learner in a second role, watching the feed. (External webhooks are a non-goal; see §8.)

**Relationships:** `WorkOrder 1—1 Notification`; `MonitoringNote` is standalone (deliberately *not* linked to a work order — a note is the "no work order" outcome).

## Key interfaces / API contracts

### mock-wo REST API (JSON, under `/api/v1`) — the agent's action target

Base URL inside the VM network: `http://mock-wo:8090`. Error body shape: `{"detail": "..."}` (404/413) or FastAPI validation payload (422). Body limit: request bodies > 256 KB → **413**.

| Method | Path | Request body | Success | Errors |
| --- | --- | --- | --- | --- |
| POST | `/api/v1/work-orders` | `WorkOrder` input (all required fields above; `status`/`created_at`/`id` not accepted) | **201** full entity with generated `id`, `status="open"`, timestamps | 422 (missing/invalid/oversized fields, bad enum, > 50 citations); 413 (body > 256 KB) |
| GET | `/api/v1/work-orders` | — (optional `?status=`, `?equipment=` filters) | **200** array, newest first | 422 (bad `status` filter value) |
| GET | `/api/v1/work-orders/{id}` | — | **200** entity | 404 unknown id |
| PATCH | `/api/v1/work-orders/{id}` | partial: `{"status"?, "assigned_to"?}` | **200** updated entity (new `updated_at`) | 404 unknown id; 422 bad enum / empty patch |
| POST | `/api/v1/notes` | `MonitoringNote` input | **201** full note | 422; 413 |
| GET | `/api/v1/notes` | — | **200** array, newest first | — |
| GET | `/api/v1/notifications` | — (optional `?unread=true`) | **200** array, newest first | 422 (bad filter) |
| GET | `/health` | — | **200** `{"status": "ok", "db": "ok"}` | 503 if DB unreachable |

Create request example (what NemoClaw's action step sends):

```json
{
  "title": "Bearing replacement — M-3021 motor drive",
  "description": "Thermal anomaly on motor M-3021 detected at clip-anomaly-01@00:42. Manual-01 p.12: bearing temp above 75°C requires replacement per schedule. Recommend priority-high replacement within 48 h.",
  "equipment": "M-3021",
  "anomaly_ref": "vss-alert-clip-anomaly-01-00:42",
  "priority": "high",
  "assigned_to": "maintenance-team-b",
  "citations": [
    {"source_type": "rag", "source_id": "manual-01#p12", "quote": "Bearing temperature above 75°C: replace per preventive schedule."},
    {"source_type": "vss", "source_id": "clip-anomaly-01@00:42", "quote": "RT-VLM caption: heat signature on bearing housing, vibration audible."}
  ]
}
```

201 response: the full entity with `"id": "6f1c…"` (UUID), `"status": "open"`, `created_at`/`updated_at` set.
404: `{"detail": "work order 'nope' not found"}`.

**Documented behaviours (test-enforced):** POST is **not idempotent** — a retried agent action creates a second work order; the UI shows both (known lab behaviour, §8). `PATCH` with an empty body → 422. Unknown enum values → 422, never 500.

**How the agent reaches it:** the NemoClaw network-policy extension pre-approves `mock-wo:8090` alongside the build document's list (RAG :8081, auth-shim :8080; VSS :8000 is the policy default). The agent's action step is a plain HTTP POST to the contract above — no SDK.

### mock-wo UI surface (server-rendered, Jinja2 autoescape on)

| Route | What it shows | Beat it serves |
| --- | --- | --- |
| `GET /` | Work-order list (short id, title, equipment, priority, status, created_at) + unread-notification badge + notes count | 4 (the learner sees the list empty at baseline, then the work order **appear at the top**) |
| `GET /work-orders/{id}` | Detail: all fields + citations grouped by `source_type` (the evidence panel) | 4 (success criterion 3 — evidence on screen) |
| `GET /notes` | Monitoring notes list | 5 |
| `GET /notifications` | Notification feed (message, work-order link, read-state) | 4 (the delivered notification) |

Single HTML/CSS (no JS framework, no CDN — works offline on the vCD network). No port other than :8090.

### Cross-component endpoint contracts (consumed, not built)

| Component | Port | Endpoint(s) | Called by | Contract notes |
| --- | --- | --- | --- | --- |
| auth-shim | 8080 | `GET /v1/models` (shim check); full OpenAI-compatible surface proxied | VSS LLM (`LLM_ENDPOINT_URL=http://auth-shim:8080`), RAG generation (`APP_LLM_SERVERURL=auth-shim:8080`), NemoClaw (`NEMOCLAW_ENDPOINT_URL=http://auth-shim:8080/v1`) | strips `Authorization`, sets `x-api-key`; `proxy_buffering off` (SSE) |
| VSS agent | 8000 | `/health` | NemoClaw skill (network-policy default), learner verification | `VSS_AGENT_CONFIG_FILE` → `config_rag.yml` enables frag; agent needs only `RAG_SERVER_URL` (WITH `/v1`), `RAG_API_KEY`, `KNOWLEDGE_COLLECTION` |
| LVS backend | 38111 | `/v1/ready` | start gate, learner verification | LVS mode: `MODE=2d`, `BP_PROFILE=bp_developer_lvs`, `HARDWARE_PROFILE=RTXPRO6000BW`, `LLM_MODE=remote`, `VLM_MODE=local_shared`. **LVS UI port/URL not recorded in the build document — release-dependent, recorded at prep (§8)** |
| RT-VLM | 8018 | `/v1/health/ready` | start gate (step 3) | the 8B-class local VLM; VRAM ≈ 38 GB check |
| RAG server | 8081 | `/v1/generate`, `/v1/health` | VSS agent frag tool; (optionally) NemoClaw directly | `RAG_SERVER_URL='http://rag-server:8081/v1'` — the `/v1` suffix is load-bearing (frag returns nothing without it) |
| RAG ingestor | 8082 | `POST /v1/documents` (multipart: `documents=@file`, `data={"collection_name":"demo_corpus"}`) | **prep-time only** — the learner never runs ingestion | collection name `demo_corpus` = `KNOWLEDGE_COLLECTION` |
| mock-wo | 8090 | full contract above | NemoClaw (policy-pre-approved), learner | |
| **LLM NIM :30081** | — | must **NOT** be running | — | `nvcr.io/nim/nvidia/nemotron-3-nano:1` (the VSS 3.2.1 local LLM NIM) — generation is remote via the shared endpoint; its running is a misconfiguration signal (build doc Phase 3) |

### Config contracts (repo-carried, applied on the cloned blueprints at prep)

- `config/vlm.env`: `NIM_PASSTHROUGH_ARGS=--gpu-memory-utilization 0.40 --max-model-len 32768 --max-num-seqs 4` (applied via `dev-profile.sh up … --vlm-env-file`).
- `config/lvs.env`: the VSS LVS `.env` overlay — `MODE=2d`, `BP_PROFILE=bp_developer_lvs`, `HARDWARE_PROFILE=RTXPRO6000BW`, `LLM_MODE=remote` (**value to verify at prep — CLI equivalent `--use-remote-llm`**), `VLM_MODE=local_shared`, `VLM_DEVICE_ID='0'`, `VSS_AGENT_VERSION=3.2.1`, `VSS_AGENT_CONFIG_FILE` → the repo's `config_rag.yml`, `LLM_ENDPOINT_URL='http://auth-shim:8080'`, `RAG_SERVER_URL='http://rag-server:8081/v1'`, `KNOWLEDGE_COLLECTION='demo_corpus'`, `VSS_DATA_DIR=/data/vss-apps-data`; `VSS_APPS_DIR`, `HOST_IP`, and the three API keys (`NGC_CLI_API_KEY`, `NVIDIA_API_KEY`, `RAG_API_KEY`) injected at prep — **never in the repo** (see `04-security.md`). The LVS `.env` path **moves between releases** — the prep script locates it (`find . -name '.env' -path '*lvs*'`) and overlays these values (repo layout at tag v3.2.1 may differ from the doc's `deploy/docker/developer-profiles/dev-profile-lvs/` path — §8).
- `config/rag.env`: `APP_LLM_MODELNAME=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`, `APP_LLM_SERVERURL=auth-shim:8080`, `APP_VECTORSTORE_NAME=elasticsearch` (deliberate — Milvus costs a second GPU budget), `APP_EMBEDDINGS_MODELNAME=nvidia/llama-nemotron-embed-1b-v2`, `APP_RANKING_MODELNAME=nvidia/llama-nemotron-rerank-1b-v2`, `MODEL_DIRECTORY=/data/nim-cache`; `ENABLE_AGENTIC_RAG` **off** (it multiplies shared-endpoint calls).
- `config/config_rag.yml`: the VSS agent config that enables the built-in `frag` tool — content per the authoritative Jul 2026 blog; the repo carries the copy and prep verifies it against the cloned release's defaults (§8).
- `config/nemoclaw.env`: `NEMOCLAW_PROVIDER=custom`, `NEMOCLAW_ENDPOINT_URL='http://auth-shim:8080/v1'`, `COMPATIBLE_API_KEY='dummy'` (safe constant — the shim discards the Bearer value and substitutes the real `x-api-key`).

## Open items carried to §8 (from this file)

- **Open (→ §8):** mock-wo design decisions pinned by this spec (tech FastAPI/Python 3.12, port 8090, in-app notification mechanism, monitoring-note entity, non-idempotent POST) — every one is a human-confirmation item; the mock's shape was open in concept.md.
- **Open (→ §8):** LVS UI port/URL (not recorded in the build document) and the OpenClaw UI URL/port (printed by the installer at prep) — both recorded at prep; if the OpenClaw UI ever lands on :8090 the mock-wo port is a single constant in one compose file (flagged, not a sizing item).
- **Open (→ §8):** `config_rag.yml` exact content (verify against the cloned release at prep); LVS `.env` actual path at tag v3.2.1; the correct `LLM_MODE` remote value.
- **Open (→ §8):** RAG index artifact format for `fixtures/rag-index/` (restore path is Elasticsearch-version-dependent; ES is `docker.elastic.co/elasticsearch/elasticsearch:9.3.0` per the RAG v2.6.2 release data) — canonical path is ingest-at-prep; the pre-built artifact is an optional fast path (§8).
- **Shortfall check:** beat 5's `MonitoringNote` adds an endpoint to the **same** mock-wo service already sized at ~1–2 GB RAM / ~1–5 GB disk — no new sizing row, no shortfall.
