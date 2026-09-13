# 03 — Build decisions

Chosen stack, repo layout, tooling, and pinned dependencies. Depth is scaled to a single-user lab: the "application" is one small CPU-only service; the rest of the system is vendor blueprints configured through repo-carried contract files, not code.

## Technology choices (mock work-order service — the only code we build)

| Choice | Pinned | Rationale (one line) | Alternative noted & rejected |
| --- | --- | --- | --- |
| Runtime | Python **3.12** (base image `python:3.12-slim`) | multi-arch base → the image builds on the aarch64 dev machine *and* the x86 learner VM; pure-Python dependency graph means no per-arch native compilation | Node 20 + Express: `better-sqlite3` is a native module (per-arch rebuilds); Node on the VM is a NemoClaw host requirement, not our stack |
| Framework | **FastAPI 0.115.0** | pydantic validation for free + free OpenAPI docs — the agent's POST contract is self-documenting, which serves beat 4's "visible evidence" story | stdlib `http.server`: no validation layer, no OpenAPI, more hand-rolled error paths |
| ASGI server | **Uvicorn 0.30.6** (single worker) | the standard companion to FastAPI; one worker keeps SQLite access single-process (WAL still allows concurrent readers) | Hypercorn: no added value for one small service |
| Validation | **Pydantic 2.8.2** | the 422/413 error contract in `02` is enforced by the schemas | hand-rolled validation: drift between docs and behaviour |
| UI | **Jinja2 3.1.4** server-rendered, autoescape on, one static CSS file | the UI is a reveal target, not an app; zero JS build toolchain, works offline on the vCD network | JS SPA (React/Vite): a build toolchain and a CDN dependency for no beat-visible benefit |
| Storage | **SQLite via stdlib `sqlite3`** (WAL mode) | stdlib = zero native deps; per-instance state is one file on a named volume, wiped on VM reset | Postgres container: an extra container and RAM/disk rows the sizing did not budget; JSON-file store: no atomic writes |
| Auth-shim | **`nginx:1.27-alpine`** | not a choice — the build document's Phase 1 contract, reused **verbatim** | — |

### mock-wo image (contract — build config, not application code)

```dockerfile
# mock-wo/Dockerfile — contract. Pinned base + pinned deps; arch-neutral by design.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MOCK_WO_DB_PATH=/data/mock-wo/work-orders.db
HEALTHCHECK --interval=10s --timeout=3s --retries=12 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health')"
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
EXPOSE 8090
ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "1"]
```

```
mock-wo/requirements.txt        (runtime)
fastapi==0.115.0
uvicorn==0.30.6
pydantic==2.8.2
jinja2==3.1.4

mock-wo/requirements-dev.txt    (dev/test only — never installed in the image)
-r requirements.txt
httpx==0.27.2
pytest==8.3.2
coverage==7.6.0
ruff==0.8.4
pyyaml==6.0.2                   # M4/M6 L3/L4 suites parse YAML (08 item 35)
```

Transitive dependencies resolve at build time; the first prep build records the resolved set in `prep-log.md` (supply-chain traceability — see `04-security.md`). Direct dependencies are pinned exactly; no `latest`, no range pins.

### mock-wo compose service (contract)

```yaml
# compose/mock-wo.yml — standalone file (also the dev-machine smoke target).
services:
  mock-wo:
    image: mock-wo:lab
    build: ./mock-wo
    container_name: mock-wo
    ports: ["8090:8090"]
    environment:
      MOCK_WO_DB_PATH: /data/mock-wo/work-orders.db
    volumes:
      - mock-wo-data:/data/mock-wo
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health')"]
      interval: 10s
      timeout: 3s
      retries: 12
    networks: [demo-net]   # same network as the auth-shim (build doc contract)
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 2g       # within the sizing's ~1–2 GB estimate; CPU-only, no GPU

volumes:
  mock-wo-data:            # per-instance learner state; wiped on VM reset
```

No `gpus:` key, no nvidia runtime — CPU-only. The image is built **on the VM at prep** (x86) and on the dev machine (aarch64) for the L2 smoke test; the multi-arch base makes both builds valid.

## Project / folder structure (the lab repo)

```
nvidia-service-bp-vss-rag-nemoclaw/
├── README.md                          # setup/run/config/troubleshooting (content plan: section 06)
├── spec/                              # this spec set (01–10)
├── mock-wo/                           # the only real application code
│   ├── Dockerfile                     # contract above
│   ├── requirements.txt               # pinned runtime deps
│   ├── requirements-dev.txt           # pinned dev deps
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI app: routes, 256 KB body limit, healthcheck
│   │   ├── schemas.py                 # pydantic models = the 02 data model
│   │   ├── db.py                      # sqlite3 init (WAL) + parameterized queries ONLY
│   │   ├── templates/                 # Jinja2 (autoescape): base.html, work_orders.html,
│   │   │                              #   work_order.html, notes.html, notifications.html
│   │   └── static/style.css           # the single static CSS file (03 tech table)
│   └── tests/                         # L0–L1 pytest suites (conftest.py, test_api.py,
│                                       #   test_schemas.py, test_ui.py)
├── compose/
│   ├── docker-compose.shim.yml        # VERBATIM from build doc Phase 1 (nginx:1.27-alpine, :8080, demo-net)
│   ├── nginx.conf.template            # VERBATIM from build doc Phase 1 (envsubst at start)
│   └── mock-wo.yml                    # contract above
├── config/
│   ├── config_rag.yml                 # VSS agent config enabling frag (Jul 2026 blog; verified at prep)
│   ├── vlm.env                        # NIM_PASSTHROUGH_ARGS (0.40 / 32768 / 4)
│   ├── lvs.env.example                # VSS LVS .env overlay — secrets as placeholders (see 04)
│   ├── rag.env                        # RAG APP_* values (02 contract)
│   └── nemoclaw.env                   # NEMOCLAW_PROVIDER=custom etc.
├── scripts/
│   ├── prep/
│   │   ├── 00-host-prep.sh            # driver 580.105.08, Docker+toolkit, daemon.json (cgroupfs,
│   │   │                              #   default-shm-size 32G), sysctl 99-vss.conf, Node 20,
│   │   │                              #   /data dirs, nvcr.io login (password-stdin)
│   │   ├── 10-clone-blueprints.sh     # tag-pinned clones: VSS v3.2.1 (→ ~/vss-public), RAG v2.6.2
│   │   │                              #   (v2.6.2 fallback, → /data/rag); records clone SHAs to prep-log.md
│   │   ├── 20-start.sh                # start order with the RT-VLM gate; --dry-run prints the order
│   │   ├── 25-ingest-corpus.sh        # prep-time corpus ingest via :8082 (index ready before session)
│   │   ├── 30-verify-stack.sh         # health gate table: 8080/8000/38111/8018/8081/8082/8090 +
│   │   │                              #   nvidia-smi VRAM check (LLM NIM :30081 must be absent)
│   │   └── 40-nemoclaw.sh             # init_nemoclaw.sh with config/nemoclaw.env; network-policy
│   │                                  #   extension pre-approving RAG :8081, shim :8080, mock-wo :8090
│   ├── demo/
│   │   ├── 01-baseline.sh             # beat 1: play normal-state clips (fixtures/video)
│   │   ├── 02-anomaly.sh              # beat 2: play the anomaly segment
│   │   └── 03-agent-kickoff.sh        # beats 3–4: nemoclaw connect + print the instruction to paste
│   │                                  #   (HITL is interactive — the script prints, the learner types)
│   └── test/
│       ├── run-dev-tests.sh           # L0–L1, L3, L4 on the dev machine (see 05)
│       └── container-smoke.sh         # L2: docker build + run + HTTP round-trip, host arch
├── fixtures/
│   ├── video/
│   │   ├── manifest.yaml              # clip id, role (normal|anomaly), duration, equipment, source
│   │   └── <clips>.mp4                # pre-recorded — content OPEN (§8)
│   ├── corpus/
│   │   ├── manifest.yaml              # doc id, content_type (manual|log|schedule), file, sha256
│   │   └── <docs>.pdf|md              # curated small corpus — content OPEN (§8)
│   └── rag-index/
│       └── manifest.yaml              # collection_name=demo_corpus, built_from=<corpus sha256>,
│                                       #   artifact format + restore command (defined at prep — §8)
└── tests/                             # repo-level (non-app) suites
    ├── test_config_contracts.py       # L3: env/config file contracts (see 05)
    ├── test_fixtures.py               # L4: fixture manifests + file validity
    └── test_start_order.py            # L3: 20-start.sh --dry-run ordering
```

**Deliberately absent from the repo:** the VSS/RAG stacks themselves (cloned at prep), model weights (NGC pulls), real credentials (prep-injected), the vCD pool and the shared endpoint (pre-provisioned — §8).

## Tooling

- **Package manager:** pip with exact pins (`requirements.txt` / `requirements-dev.txt`). The dev machine has `uv 0.11.26`; `run-dev-tests.sh` uses plain `python3 -m venv` + pip so the contract runs on any Ubuntu with Python 3.12 (uv is a convenience, not a dependency of the test contract).
- **Linter / formatter:** `ruff 0.8.4` (single tool, `ruff check` + `ruff format` on `mock-wo/`). Alternative noted: flake8 + black — rejected, two tools for one job.
- **Script hygiene:** `bash -n` on every `scripts/**/*.sh` as part of the test gate. `shellcheck` is **absent on the dev machine** (verified fact) — the spec does not require it; scripts are additionally reviewed at build time.
- **CI approach:** no CI service exists for this lab repo. The gate is two non-interactive commands (see `05-test-strategy.md`): `bash scripts/test/run-dev-tests.sh` (L0–L1, L3, L4) and `bash scripts/test/container-smoke.sh` (L2). Run before commit and re-run at environment prep on the VM (x86) — the prep re-run doubles as the target-arch container check.
- **Vendor blueprint handling:** cloned at prep from pinned tags (`10-clone-blueprints.sh`); clone SHAs, the actual LVS `.env` path, the actually-pulled image values (the spec pins exact tags — Elasticsearch 9.3.0, the VLM, the six NIMs — from the user's release data, 2026-09-02, so prep records the actuals and any mismatch is a prep finding), the measured per-NIM VRAM, the OpenClaw UI URL/port, and the NemoClaw installed version (must be v0.0.118 — §8 item 28) are recorded to **`prep-log.md`** (repo root, gitignored) at prep time. `prep-log.md` is the single source of recorded reality that `09` / `lab-prep.md` / the guide reference.

## Pinned dependencies — each earns its place

| Dependency / version | Where | Why it earns its place |
| --- | --- | --- |
| `python:3.12-slim` | mock-wo image base | multi-arch (amd64+arm64) → arch-neutral image for dev (aarch64) and learner VM (x86) |
| `fastapi==0.115.0` | mock-wo runtime | the API contract + free OpenAPI docs for the agent's action step |
| `uvicorn==0.30.6` | mock-wo runtime | ASGI server running the app in the container |
| `pydantic==2.8.2` | mock-wo runtime | enforces the schema/enum/length contracts → the 422 error behaviour |
| `jinja2==3.1.4` | mock-wo runtime | server-rendered UI with autoescaping (XSS mitigation) |
| `nginx:1.27-alpine` | auth-shim | the build document's verbatim contract for Bearer→x-api-key translation |
| `httpx==0.27.2` | dev | FastAPI `TestClient` transport for L1 API tests |
| `pytest==8.3.2` | dev | the single test runner for the whole repo (see `05`) |
| `coverage==7.6.0` | dev | enforces the 90% line-coverage gate on `mock-wo/app` |
| `ruff==0.8.4` | dev | lint/format gate |
| VSS repo **v3.2.1** / agent image **`VSS_AGENT_VERSION=3.2.1`** | cloned at prep | user's GitHub release data, 2026-09-02 — supersedes the initial spec-review confirmation of v3.2.0 and the sizing's open set (v3.2.1 is now confirmed to exist — §8 item 1); the agent image tag is assumed to track the release tag (the build document's 3.2.0 value corresponds to the v3.2.0 tag) — existence on nvcr.io verified at prep, recorded in `prep-log.md` (mismatch = prep finding, §8 item 2) |
| RAG repo **v2.6.2** | cloned at prep | user's GitHub release data, 2026-09-02 — supersedes v2.6.0 (v2.6.2 fallback) and the sizing's open tag question; no fallback remains (— §8 item 3); the in-tree `docs/deploy-docker-self-hosted.md` of v2.6.2 is authoritative |
| NemoClaw **v0.0.118** | installed at prep by the VSS-repo installer `deploy/docker/scripts/nemoclaw/init_nemoclaw.sh` (fresh OpenClaw required; Node 20 host requirement) | the agent that drives beats 3–4 — user-confirmed pin (spec review, 2026-09-02; the sizing carried no version); the installer at the pinned VSS v3.2.1 tag must install/declare v0.0.118 — verified at prep, recorded in `prep-log.md`, a mismatch is a prep finding, never a silent substitution (§8 item 28) |
| NIMs `nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:1.13.0`, `nvcr.io/nim/nvidia/llama-nemotron-rerank-1b-v2:1.10.0`, `nvcr.io/nim/nvidia/nemotron-page-elements-v3:1.8.0`, `nvcr.io/nim/nvidia/nemotron-graphic-elements-v1:1.8.0`, `nvcr.io/nim/nvidia/nemotron-table-structure-v1:1.8.0`, `nvcr.io/nim/nvidia/nemotron-ocr-v1:1.3.0` | pulled at prep | the six local retrieval models — exact image:tags user-supplied from the RAG v2.6.2 `deploy/compose/nims.yaml`, 2026-09-02 (§8 item 4); the actually-pulled values are recorded in `prep-log.md` (mismatch = prep finding) |
| `nvcr.io/nim/nvidia/cosmos3-reasoner:1.7` (VSS local VLM) | pulled at prep | Cosmos3 Nano Reasoner — the VSS 3.2.1 release's local VLM NIM (resolves the open VLM-identity question — §8 item 7); user-supplied from the VSS 3.2.1 release's `deploy/docker/services/nim/*/compose.yml`, 2026-09-02 |
| `nvcr.io/nim/nvidia/nemotron-3-nano:1` (VSS local LLM NIM) | **not run in the lab** | the VSS 3.2.1 release lists it as the local LLM NIM; in the lab the VSS LLM role goes to the shared off-VM endpoint — the ":30081 must be absent" check applies (user-supplied from the VSS 3.2.1 release's compose, 2026-09-02) |
| `docker.elastic.co/elasticsearch/elasticsearch:9.3.0` | pulled at prep | the shared Elasticsearch of both stacks (counted once in the footprint) — user-supplied from the RAG repo, 2026-09-02; **corrects the earlier recorded expected value "0.18.0"** (§8 item 4) |
| VSS infra: `confluentinc/cp-kafka:8.2.0`, `redis:8.6.2-alpine`, Arize Phoenix `14.15.0` | pulled at prep | the VSS 3.2.1 release's internal infrastructure — exact images user-supplied from the release compose, 2026-09-02; recorded for `prep-log.md` verification |
| `NVIDIA/Nemotron-3.5-Lightning-30B-A3B` at `https://model.delllabs.local/api/nemotron35/v1` | shared off-VM endpoint | the one shared LLM for all three LLM roles (sizing decision); model ID and endpoint owner-confirmed 2026-09-07 — supersedes the expected model image recorded 2026-09-02 from the RAG v2.6.2 `nims.yaml` — a platform-side verification target (the endpoint is pre-provisioned — §8 item 20) |

## Start-order script contract

`scripts/prep/20-start.sh` implements the `02` start-order table. Contract: `--dry-run` prints the ordered step list (shim+mock-wo → VSS → RT-VLM gate → RAG → NemoClaw) and exits 0 without touching Docker (this is what the dev-machine test asserts); a real run executes the steps, blocks at the RT-VLM gate (`curl --retry 90 --retry-delay 10 --retry-all-errors`), and exits non-zero on any gate failure. This keeps the non-negotiable ordering in one testable place instead of in prose.

## Open items carried to §8 (from this file)

- **Open (→ §8):** `python:3.12-slim` and `nginx:1.27-alpine` are series-pinned base tags (not `latest`); the repo practice is to record the resolved image digest in `prep-log.md` at the first prep build. Confirm this practice is acceptable vs. digest-pinning the bases.
- **Open (→ §8):** all mock-wo stack choices in the table above (Python/FastAPI over Node/Express, SQLite over Postgres/JSON, port 8090, in-app notification mechanism, monitoring-note entity, non-idempotent POST, 256 KB body limit, 1-worker uvicorn) — recorded as human-confirmation items per the spec's exception rule.
- **Open (→ §8):** transitive dependency resolution at build time (direct deps pinned exactly; resolved set recorded in `prep-log.md`).
- **Open (→ §8):** `config_rag.yml` content verified at prep; LVS `.env` path located at prep (layout moved between releases); `LLM_MODE=remote` value verified.
