# NVIDIA Service Blueprint Lab: VSS + RAG + NemoClaw

Single-VM demo of an agentic video-analytics maintenance loop: **NVIDIA VSS**
(video understanding + alerting) + **Enterprise RAG** (retrieval-grounded
diagnosis) + **NemoClaw** (the agentic kick-off), filed into a mock CMMS
(work orders + notifications). One learner, one H100 vGPU partition (~94 GB;
SKU H100L-94C), no
concurrency — the LLM roles run against a shared off-VM endpoint through a
local auth-shim; only the VLM + six retriever NIMs run locally.

## Layout

This repo is the single source for the lab: build code **and** the lab guide.

| Path | What it is |
| --- | --- |
| `spec/` | The ten build documents — source of truth for the build track |
| `mock-wo/` | The mock CMMS and operator dashboard backend (FastAPI + SQLite): agent API on :8090, operator dashboard on :8091 (`operator-dashboard-spec.md`) |
| `mock-wo/ui/` | The operator dashboard UI (React + Vite, fonts vendored; built into the image) |
| `packs/` | Pack manifests — one directory per vertical (manufacturing first) |
| `openclaw/plugins/mock-wo-telemetry/` | OpenClaw plugin forwarding tool-call and model-output hooks to mock-wo (display-only) |
| `config/` | Environment contract files: per-VM `lvs.env` (instructor-injected, gitignored) + lab-owned `rag.env` / `vlm.env` / `nemoclaw.env` (+ `*.env.example` templates) |
| `scripts/prep/` | The environment bring-up chain: `00 → 10 → 20 (finishes by arming 50-resilience.sh) → 25 → 30 → 40` (instructor-run on the build VM) |
| `scripts/demo/` | Session helpers the learner runs: `01-baseline`, `02-anomaly`, `03-agent-kickoff` |
| `scripts/test/` | Dev gate (`run-dev-tests.sh`) + container smoke (`container-smoke.sh`) |
| `scripts/dev/` | Dev-only helpers — `simulate-agent.py` plays the agent's HTTP calls; never part of a learner session |
| `fixtures/` | Fixture manifests + provisional fixtures (video, corpus, rag-index) — structure-gated, content curated at prep (ADR-004) |
| `tests/` | pytest suite (L4) — contracts, start order, fixtures |
| `guide.md` | The learner-facing lab guide (HOL-1362-01) — house format |
| `lab-prep.md` | The environment contract the prep chain implements (verify checks, endpoints, artifacts) |
| `.holagent/` | Guide authoring state: plan, module plans, concept, sizing, scored review, build records, validation reports |

## Running it

- **Dev gate** (no GPU needed; Node 22 for the UI and plugin): `python3 -m venv .venv && .venv/bin/pip install -r mock-wo/requirements-dev.txt && bash scripts/test/run-dev-tests.sh`
- **Dashboard on the dev machine** (no VSS, no NemoClaw): `(cd mock-wo/ui && npm ci && npm run build)`, then `cd mock-wo && MOCK_WO_DB_PATH=../state/dev/mock-wo.db MOCK_WO_PACKS_DIR=../packs MOCK_WO_DEV_FAKE_CLIENTS=1 ../.venv/bin/python -m app.server`; open http://127.0.0.1:8091, inject a fault, then run `scripts/dev/simulate-agent.py`
- **Environment bring-up** (build VM, GPU): `bash scripts/prep/00-host-prep.sh` … `40-nemoclaw.sh`, per `lab-prep.md`; recorded reality lands in `prep-log.md` (gitignored)
- **Learner session**: follow `guide.md` — the demo scripts in `scripts/demo/` do the staging, the learner operates the UIs

## Pinned versions

VSS **v3.2.1** (tag SHA `7640d917047cf7b0fd3085eefb8282754b56bc94`) · RAG
**v2.6.2** (SHA `f20716d73ae69a544ad4a692f38d6178a64e6f36`) · NemoClaw
**v0.0.118**. Mismatches are prep findings, not silent substitutions.
