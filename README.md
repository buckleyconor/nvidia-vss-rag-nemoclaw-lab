# NVIDIA Service Blueprint Lab: VSS + RAG + NemoClaw

Single-VM demo of an agentic video-analytics maintenance loop: **NVIDIA VSS**
(video understanding + alerting) + **Enterprise RAG** (retrieval-grounded
diagnosis) + **NemoClaw** (the agentic kick-off), filed into a mock CMMS
(work orders + notifications). One learner, one RTX PRO 6000 96 GB GPU, no
concurrency — the LLM roles run against a shared off-VM endpoint through a
local auth-shim; only the VLM + six retriever NIMs run locally.

## Layout

This repo is the single source for the lab: build code **and** the lab guide.

| Path | What it is |
| --- | --- |
| `spec/` | The ten build documents — source of truth for the build track |
| `mock-wo/` | The mock CMMS service (FastAPI + SQLite; work orders, notifications, notes, small UI) |
| `config/` | Environment contract files (`*.env.example` templates + `rag.env`) |
| `scripts/prep/` | The environment bring-up chain: `00 → 10 → 20 → 25 → 30 → 40` (instructor-run on the build VM) |
| `scripts/demo/` | Session helpers the learner runs: `01-baseline`, `02-anomaly`, `03-agent-kickoff` |
| `scripts/test/` | Dev gate (`run-dev-tests.sh`) + container smoke (`container-smoke.sh`) |
| `fixtures/` | Fixture manifests + provisional fixtures (video, corpus, rag-index) — structure-gated, content curated at prep (ADR-004) |
| `tests/` | pytest suite (L4) — contracts, start order, fixtures |
| `guide.md` | The learner-facing lab guide (HOL-1362-01) — house format |
| `lab-prep.md` | The environment contract the prep chain implements (verify checks, endpoints, artifacts) |
| `.holagent/` | Guide authoring state: plan, module plans, concept, sizing, scored review, build records, validation reports |

## Running it

- **Dev gate** (no GPU needed): `python3 -m venv .venv && .venv/bin/pip install -r mock-wo/requirements-dev.txt && bash scripts/test/run-dev-tests.sh`
- **Environment bring-up** (build VM, GPU): `bash scripts/prep/00-host-prep.sh` … `40-nemoclaw.sh`, per `lab-prep.md`; recorded reality lands in `prep-log.md` (gitignored)
- **Learner session**: follow `guide.md` — the demo scripts in `scripts/demo/` do the staging, the learner operates the UIs

## Pinned versions

VSS **v3.2.1** (tag SHA `7640d917047cf7b0fd3085eefb8282754b56bc94`) · RAG
**v2.6.2** (SHA `f20716d73ae69528244a7b978a64e5c49c48`) · NemoClaw
**v0.0.118**. Mismatches are prep findings, not silent substitutions.
