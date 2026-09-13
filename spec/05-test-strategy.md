# 05 — Test strategy

> **Amendment 2026-09-13 — operator dashboard.** The dev gate
> (`scripts/test/run-dev-tests.sh`) adds the dashboard UI (lockfile install,
> typecheck, Vitest, build) and the OpenClaw telemetry plugin (typecheck,
> Vitest, build). The L2 container smoke now builds both stages, asserts Node
> is absent from the runtime image, checks both ports, runs a gated round-trip
> (inject → evidence → proposal → agent-port decision 404 → operator approve
> → work order → replay 409) with the dev-only fake clients, and checks that
> `docker stop` is not held by an open SSE stream. The L1 UI tests below
> (TC-021..TC-023, Jinja2) are superseded by `mock-wo/tests/test_api.py` SPA
> serving tests and the Vitest suites. The dev-machine vs GPU-VM split per
> milestone is in `operator-dashboard-spec.md` §12.

**Scope reality first:** this spec's buildable code is the mock work-order service plus the repo's contracts (compose/env/config files, deployment scripts, fixture manifests). The VSS/RAG/NemoClaw stacks are vendor blueprints configured at environment prep. Therefore the dev-machine gate covers the mock service end-to-end and the contract files deterministically; **everything GPU- or VM-dependent is deferred to environment prep / QA on the learner VM** (named checklist at the end of this section — it becomes the QA content of `09`/`10` and the guide).

**Dev-machine facts the strategy is built on (already verified):** aarch64 (ARM), 20 cores, 121 GB RAM; python3 3.12.3; node v22.23.2; docker 29.2.1 with a running daemon (inside the lab's < 29.5.0 NGC-pull bound); Compose v5.0.2 (above the lab's v2.39.1 floor); uv 0.11.26; jq 1.7; **shellcheck absent**. No GPU here; the lab's H100 (x86 vCD VM) is unreachable from this machine. Consequently **every test in this section runs CPU-only on the aarch64 dev machine** — no x86 images, no vendor NIMs, no ~94 GB card assumed anywhere in the dev gate.

## Test levels and rough split

| Level | What it proves | Share |
| --- | --- | --- |
| **L0 — unit** | mock-wo internals: DB init (WAL), schema/enum whitelists | ~5% |
| **L1 — API/UI integration** | the full `02` contract against the running app via FastAPI `TestClient` (in-process, temp SQLite): happy paths, error paths, abuse paths, persistence, concurrency | ~55% |
| **L2 — container smoke** | the Dockerfile builds and the image serves the contract on the **host architecture** (multi-arch base ⇒ valid on aarch64 here and x86 on the VM) | ~9% |
| **L3 — config/contract** | the repo's contract files are exactly right: shim files verbatim, LVS/RAG/NemoClaw/vlm env values, no `latest`, exact pins, start-order dry-run, `.gitignore` secret hygiene | ~23% |
| **L4 — fixture verification** | fixture manifests parse and referenced files are present, non-empty, structurally valid (MP4 `ftyp` box, corpus content-type coverage) | ~7% |
| **L5 — GPU/VM end-to-end (deferred)** | co-residency, VRAM budget, beat replay — **not runnable here**; environment prep / QA on the VM | out of the dev gate |

## Runner and how tests run

**One runner: `pytest` (pinned `pytest==8.3.2`).** The testable code in the repo is Python (mock-wo + contract/fixture suites); a node runner is deliberately *not* adopted — Node 20 is a NemoClaw host requirement on the VM, and there is no Node application code in this repo to test. HTTP in tests uses `httpx==0.27.2` via FastAPI's `TestClient` (L1) and stdlib `urllib` (L2 host-side, so the smoke script needs no pip at all).

Commands, **run in the lab repo root**, both non-interactive and self-terminating:

```bash
# L0 + L1 + L3 + L4  (the dev gate)
bash scripts/test/run-dev-tests.sh
# 1) python3 -m venv .venv  (recreated if missing)
# 2) .venv/bin/pip install -q -r mock-wo/requirements.txt -r mock-wo/requirements-dev.txt
# 3) .venv/bin/ruff check mock-wo/ tests/
# 4) .venv/bin/pytest mock-wo/tests tests -q --cov=mock-wo.app --cov-report=term-missing --cov-fail-under=90

# L2 (container smoke — needs the local Docker daemon; host-arch build)
bash scripts/test/container-smoke.sh
# 1) docker build -t mock-wo:lab -f mock-wo/Dockerfile mock-wo
# 2) docker run -d --name mock-wo-smoke -p 18090:8090 -e MOCK_WO_DB_PATH=/tmp/smoke.db mock-wo:lab
#    (host port 18090 — never 8090, so it cannot collide with a learner session)
# 3) poll http://127.0.0.1:18090/health (stdlib urllib, 30 s budget)
# 4) POST a work order → GET list → GET / (UI) → assert 201/200/200 + title present
# 5) assert `docker inspect` Health == "healthy"; docker rm -f mock-wo-smoke
```

- **CI:** there is no CI service for this lab repo. The two commands above are the gate: run before commit, and **re-run at environment prep on the VM (x86)** — that re-run doubles as the target-architecture container check (the aarch64 build proves the Dockerfile is arch-neutral; only an x86 run proves the x86 image).
- **Coverage target:** **≥ 90% line coverage on `mock-wo/app`** (enforced by `--cov-fail-under=90`); **100% of the TC table below must be executable** — every row maps to a named test; L3/L4 are binary gates (any failure fails the suite).
- **Abuse/failure cases are first-class** (TC-008/009/010/013/024–027): the agent is the API's main client and will retry, mistype enums, and paste odd text; the contract must fail loudly (422/404/413), never 500.

## Test-case table

| ID | Level | Covers | Input | Expected |
| --- | --- | --- | --- | --- |
| TC-001 | L0 | DB init | fresh tmp DB path | 3 tables (`work_orders`, `notes`, `notifications`) created; `PRAGMA journal_mode` = `wal` |
| TC-002 | L0 | schema enums | `priority="urgent"` / `"high"`; `status="open"` / `"yolo"` | bad enums rejected by pydantic; good ones accepted |
| TC-003 | L1 | create work order (happy) | valid POST body (02 example) | 201; UUID id; `status="open"`; `created_at` set; citations echoed |
| TC-004 | L1 | list work orders | two POSTs, then `GET /api/v1/work-orders` | 200; both present; newest first |
| TC-005 | L1 | get by id | `GET /api/v1/work-orders/{id from TC-003}` | 200; fields match the created record |
| TC-006 | L1 | get unknown id | `GET /api/v1/work-orders/00000000-0000-0000-0000-000000000000` | 404 `{"detail": …}` |
| TC-007 | L1 | create, missing required field | POST without `title` | 422 naming `title` |
| TC-008 | L1 | create, bad enum | POST `priority="urgent"` | 422 |
| TC-009 | L1 | create, malformed body | raw body `"{not json"` | 422 (not 500) |
| TC-010 | L1 | create, oversized body | POST with 300 KB `description` | 413 |
| TC-011 | L1 | status update | `PATCH {"status":"in_progress"}` | 200; `status` changed; `updated_at` ≥ `created_at` |
| TC-012 | L1 | patch unknown id | `PATCH /{nonexistent}` | 404 |
| TC-013 | L1 | patch, bad enum | `PATCH {"status":"yolo"}` | 422 |
| TC-014 | L1 | monitoring note (beat 5) | valid POST `/api/v1/notes`; then `GET /api/v1/notes` | 201; note present in list |
| TC-015 | L1 | notification auto-creation | after TC-003, `GET /api/v1/notifications` | 1 entry; `work_order_id` matches; `channel="in_app"` |
| TC-016 | L1 | health | `GET /health` | 200 `{"status":"ok","db":"ok"}` |
| TC-017 | L1 | list filters | `?status=open` (with one `in_progress` present); `?status=bogus` | 200 open-only list; 422 on bad filter |
| TC-018 | L1 | documented non-idempotency | same POST body twice | two 201s, distinct ids (retries duplicate — by design, test-pinned) |
| TC-019 | L1 | persistence across restart | create, then re-open the app on the same DB path | work order still present |
| TC-020 | L1 | concurrency | 10 parallel POSTs | all 201; 10 distinct ids; list count 10 (WAL, single writer) |
| TC-021 | L1 | UI list view (beat 4 reveal surface) | `GET /` after TC-003 | 200 HTML; work-order title visible; unread-notification badge ≥ 1 |
| TC-022 | L1 | UI detail + citations | `GET /work-orders/{id}` | 200 HTML; citation `source_id` and quote rendered, grouped by `source_type` |
| TC-023 | L1 | XSS via title | POST `title="<script>alert(1)</script>"`; `GET /work-orders/{id}` | 201; detail HTML contains escaped `&lt;script&gt;`, **no** raw `<script>` tag |
| TC-024 | L1 | SQL injection in id | `GET /api/v1/work-orders/x'; DROP TABLE work_orders;--` (URL-encoded) | 404; subsequent `GET /api/v1/work-orders` still 200 (table intact) |
| TC-025 | L1 | path traversal in id | `GET /api/v1/work-orders/../../etc/passwd` | 404 (no filesystem access) |
| TC-026 | L1 | oversized citation array | POST with 51 citations | 422 (max 50) |
| TC-027 | L1 | empty patch | `PATCH {}` | 422 |
| TC-028 | L2 | image builds (host arch) | `docker build -t mock-wo:lab -f mock-wo/Dockerfile mock-wo` | build succeeds; image present (multi-arch base ⇒ arch-neutral) |
| TC-029 | L2 | container health | container on host port 18090; poll `/health` | 200 within 30 s |
| TC-030 | L2 | container API round-trip | POST work order → `GET /api/v1/work-orders` → `GET /` through the container | 201 / 200 / 200; title present in UI HTML |
| TC-031 | L2 | healthcheck wiring | `docker inspect mock-wo-smoke` | Health status `"healthy"` |
| TC-032 | L3 | shim compose verbatim contract | parse `compose/docker-compose.shim.yml` | image exactly `nginx:1.27-alpine`; port `8080:8080`; network `demo-net` |
| TC-033 | L3 | shim nginx template | `compose/nginx.conf.template` | contains `proxy_set_header    Authorization "";`, `x-api-key ${SHARED_API_KEY}`, `proxy_buffering off` |
| TC-034 | L3 | LVS env overlay | `config/lvs.env.example` | exact values: `MODE=2d`, `BP_PROFILE=bp_developer_lvs`, `HARDWARE_PROFILE=H100`, `VLM_MODE=local_shared`, `VSS_AGENT_VERSION=3.2.1`, `RAG_SERVER_URL='http://rag-server:8081/v1'` (the `/v1` suffix — load-bearing), `KNOWLEDGE_COLLECTION='demo_corpus'`, `LLM_ENDPOINT_URL='http://auth-shim:8080'`; `LLM_MODE` present non-empty (value verified at prep); secret fields contain **placeholders only** — no `nvapi-…` value anywhere in the repo |
| TC-035 | L3 | RAG env contract | `config/rag.env` | `APP_VECTORSTORE_NAME=elasticsearch`, `APP_LLM_MODELNAME=nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` (the endpoint's served NVFP4 deployment id — the owner-confirmed contract id `NVIDIA/Nemotron-3.5-Lightning-30B-A3B` is tracked in 08), `APP_LLM_SERVERURL=auth-shim:8080`, `APP_EMBEDDINGS_MODELNAME=nvidia/llama-nemotron-embed-1b-v2`, `APP_RANKING_MODELNAME=nvidia/llama-nemotron-rerank-1b-v2`, `MODEL_DIRECTORY=/data/nim-cache`; `ENABLE_AGENTIC_RAG` absent or `off` |
| TC-036 | L3 | VLM budget env | `config/vlm.env` | `NIM_PASSTHROUGH_ARGS` exactly `--gpu-memory-utilization 0.40 --max-model-len 32768 --max-num-seqs 4` |
| TC-037 | L3 | NemoClaw env | `config/nemoclaw.env` | `NEMOCLAW_PROVIDER=custom`, `NEMOCLAW_ENDPOINT_URL=http://auth-shim:8080/v1`, `COMPATIBLE_API_KEY=dummy` |
| TC-038 | L3 | version hygiene | grep across compose/Dockerfile/requirements | no `latest` anywhere; every `requirements*.txt` line is a `name==version` exact pin |
| TC-039 | L3 | script syntax | `bash -n` on every `scripts/**/*.sh` | all pass (shellcheck is absent on the dev machine — not required) |
| TC-040 | L3 | start order | `scripts/prep/20-start.sh --dry-run` | exit 0; printed order contains shim+mock-wo → VSS → RT-VLM gate → RAG → NemoClaw in that relative order; no Docker invocation |
| TC-041 | L3 | secret hygiene in .gitignore | parse `.gitignore` | covers real env files (all `*.env` except `*.env.example`), `prep-log.md`, state dirs |
| TC-042 | L4 | video fixtures | `fixtures/video/manifest.yaml` | parses; every listed clip exists, non-empty, `.mp4`, has an `ftyp` box at offset 4 (pure-Python check, no ffmpeg dependency) |
| TC-043 | L4 | corpus fixtures | `fixtures/corpus/manifest.yaml` | parses; every file exists, non-empty; content types include ≥ 1 `manual`, ≥ 1 `log`, ≥ 1 `schedule` (the corpus must cover the content types beat 3 retrieves over — sizing reduction row) |
| TC-044 | L4 | RAG index artifact slot | `fixtures/rag-index/manifest.yaml` | `collection_name == demo_corpus`; `built_from` sha256 matches the corpus manifest aggregate; if an artifact file is present, it is non-empty (restore format is prep-defined — §8) |

## GPU/VM-dependent verification — deferred, by design

The following **cannot run on the aarch64 dev machine** (no GPU; the ~94 GB card is on the unreachable vCD VM) and are **environment-prep / QA territory on the learner VM**, owned by `09`/`10`, `lab-prep.md`, and the guide (dispatch 2). They are the build document's phase exit criteria, restated as the QA checklist:

1. Shim: `GET :8080/v1/models` lists `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` (the served id); streaming check — tokens arrive incrementally, not one blob (nginx buffering off).
2. RAG Phase 2: six NIMs healthy; **actual per-NIM VRAM measured and recorded** (resolves the ~28 GB estimate and the 0.10 `gpu_memory_utilization` floor risk; if total > ~45 GB the VLM fraction is cut before co-residency).
3. VSS Phase 3: agent :8000, LVS :38111, RT-VLM :8018 healthy; **VLM VRAM ≈ 34 GB, not ~86 GB** (0.40 pin via `RTVI_VLLM_*` — 08 item 39, dry-run measured 34.1 GB); LLM NIM :30081 **not** running.
4. Co-residency Phase 4: 7 compute processes, ≤ 80 GB total, no OOM under concurrent VSS + RAG load; both stacks survive a full VM reboot — **zero interaction** (09 "Reboot resilience": restart policies + `nemoclaw-recover.service` boot repair + the 5-min self-heal timer armed by 50-resilience.sh; the reboot is the live test of that layer).
5. NemoClaw Phase 5: `openclaw nemoclaw status` shows the custom endpoint + Nemotron-3.5-Lightning; HITL prompts collect all four parameters; report cites RAG-sourced documents (the frag path works — corpus not ignored).
6. **End-to-end beat replay 1→4** (the aha) and optional 5 — the full learner walk-through from a clean start.

Until those pass on the VM, "the lab works" is proven only to the extent of L0–L4: the mock service is correct, the contracts are exact, and the fixtures are structurally sound.

## Open items carried to §8 (from this file)

- **Open (→ §8):** all 44 TC rows must be green on the aarch64 dev machine as the dev gate — confirm that deferring GPU/VM verification entirely to env-prep/QA (checklist above) is acceptable to the review process, and that dispatch 2 encodes that checklist into `09`/`10` and `lab-prep.md` readiness checks rather than into §7 milestone tests (which must also run on this machine).
- **Open (→ §8):** the dev-machine L2 smoke proves arch-neutrality but not x86 execution; the prep-time re-run of `container-smoke.sh` on the VM is the arch check — confirm it is part of the prep runbook.
- **Open (→ §8):** fixture content is open (clips/corpus identity) — TC-042/043/044 gate *structure*, not *content*; content suitability (does the corpus actually make beat 3's retrieval legible on screen) is only checkable in the VM-side e2e replay.
- **Shortfall check:** no test requirement exceeds the sizing — the mock-wo test surface lives inside the sized mock-wo line; the dev-machine test environment (venv + one small image) is transient and outside the per-VM budget.
