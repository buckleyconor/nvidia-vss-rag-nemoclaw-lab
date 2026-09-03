---
milestones:
  - { n: 1, slug: mock-wo-api, title: "Mock WO REST API + schemas", deliverable: 'mock-wo app implements the full REST contract (work-orders, notes, notifications) over SQLite WAL, with validation, the 422/404/413 error shapes and the /health probe', exit: 'TC-001..TC-020 and TC-024..TC-027 pass; POST work order returns 201 with the notification created atomically; enum/length/oversized-body cases return 422/422/413, never 500', test: 'python3 -m venv .venv && .venv/bin/pip install -q -r mock-wo/requirements.txt -r mock-wo/requirements-dev.txt && .venv/bin/pytest mock-wo/tests/test_api.py mock-wo/tests/test_schemas.py -q', depends_on: [] }
  - { n: 2, slug: mock-wo-ui, title: 'Mock WO UI views', deliverable: 'Jinja2 list/detail/notes/notifications views with autoescape; the work-order list is the beat-4 reveal surface', exit: 'TC-021..TC-023 pass; list is visibly empty at baseline and a new work order appears at the top after POST; detail page groups citations by source; user-supplied text renders escaped', test: 'python3 -m venv .venv && .venv/bin/pip install -q -r mock-wo/requirements.txt -r mock-wo/requirements-dev.txt && .venv/bin/pytest mock-wo/tests/test_ui.py -q', depends_on: [1] }
  - { n: 3, slug: mock-wo-container, title: 'Mock WO container + compose service', deliverable: 'Dockerfile on python:3.12-slim plus compose/mock-wo.yml (demo-net, mem_limit 2g, named volume mock-wo-data, python-urllib healthcheck)', exit: 'TC-028..TC-031 pass; container-smoke.sh builds on the dev machine (aarch64), runs on host port 18090, round-trips a work order, and the docker Health status is "healthy" (app probe: HTTP 200, body {"status":"ok","db":"ok"})', test: 'bash scripts/test/container-smoke.sh', depends_on: [1] }
  - { n: 4, slug: contract-files, title: 'Shim + config contract files', deliverable: 'compose/ auth-shim files verbatim from the build document; config/ overlays (config_rag.yml, vlm.env, lvs.env.example, rag.env, nemoclaw.env); .gitignore with secret hygiene', exit: 'TC-032..TC-038 and TC-041 pass; shim conf strips Authorization and sets x-api-key with buffering off; RAG_SERVER_URL carries the /v1 suffix; no latest anywhere; exact pins only', test: 'python3 -m venv .venv && .venv/bin/pip install -q -r mock-wo/requirements.txt -r mock-wo/requirements-dev.txt && .venv/bin/pytest tests/test_config_contracts.py -q', depends_on: [] }
  - { n: 5, slug: deploy-scripts, title: 'Prep + demo scripts with the start-order gate', deliverable: 'scripts/prep/* (host checks, blueprint clone from pinned tags with SHA logging, 20-start.sh with the RT-VLM ready gate and a --dry-run mode) and scripts/demo/* (beat scripts)', exit: 'TC-039, TC-040 pass; 20-start.sh --dry-run exits 0, prints the ordered plan shim+mock-wo -> VSS -> RT-VLM gate -> RAG -> NemoClaw, and performs no Docker invocation; every script passes bash -n', test: 'bash scripts/prep/20-start.sh --dry-run && for f in scripts/prep/*.sh scripts/demo/*.sh scripts/test/*.sh; do bash -n "$f"; done', depends_on: [4] }
  - { n: 6, slug: fixtures-harness, title: 'Fixture manifests + provisional fixtures', deliverable: 'fixtures/ manifests plus structurally valid provisional fixtures (synthesized ftyp mp4 clips; one manual, one log, one schedule document) and the structure test suite', exit: 'TC-042..TC-044 pass; manifests parse, referenced files exist and are non-empty; corpus content types cover manual + log + schedule; the rag-index manifest names collection demo_corpus', test: 'python3 -m venv .venv && .venv/bin/pip install -q -r mock-wo/requirements.txt -r mock-wo/requirements-dev.txt && .venv/bin/pytest tests/test_fixtures.py -q', depends_on: [] }
---

# 07 — Build sequence

`/hol-build` consumes the frontmatter above one milestone at a time; the
prose explains the plan. Every `test` command is non-interactive,
self-terminating, and runs **at the repo root on the aarch64 dev machine**
(docker daemon available; **no lab GPU** — the RTX PRO 6000 is on the
unreachable vCD VM). GPU/VM-dependent verification is NOT a milestone test:
it is the six-item L5 checklist in `05-test-strategy.md`, run at environment
prep / QA on the VM.

## The plan

| # | Slug | Produces | Why this order |
|---|------|----------|----------------|
| 1 | `mock-wo-api` | the app's REST contract + schemas | the foundation everything else builds on; independently testable via the L1 `TestClient` suite |
| 2 | `mock-wo-ui` | the reveal surface (list/detail/notes/notifications) | needs the API from M1 to render real data |
| 3 | `mock-wo-container` | the arch-neutral image + compose service | needs the app from M1; the container smoke is the L2 gate |
| 4 | `contract-files` | the shim + all `config/` overlays + `.gitignore` | no code dependency — the L3 contract suite proves them; M5 scripts reference these paths |
| 5 | `deploy-scripts` | prep + demo scripts incl. `20-start.sh` with the start-order gate | needs M4's config paths; `--dry-run` makes the gate testable without a GPU |
| 6 | `fixtures-harness` | manifests + provisional fixtures + structure suite | no code dependency; ADR-004 provisional fixtures keep the suite green on the dev machine |

M4 and M6 have no dependencies and may be built in any order relative to M1;
the `n` order is the recommended build order, not a hard constraint beyond
`depends_on`.

**Closing gate (not a milestone):**
`bash scripts/test/run-dev-tests.sh && bash scripts/test/container-smoke.sh`
— the full L0–L4 surface plus the L2 smoke, run before commit and re-run at
environment prep on the VM (x86), where the re-run doubles as the
target-architecture container check.

## What is deliberately NOT a milestone

- **GPU/VM verification** (L5: per-NIM VRAM measurement, VLM ≈ 38 GB not
  ~86 GB, co-residency ≤ 80 GB / 7 processes / reboot survival, NemoClaw
  status, e2e beat replay) — impossible on the dev machine; it is the
  environment-prep / QA checklist owned by `09`/`10` and `lab-prep.md`.
- **Blueprint clone/pull** (VSS v3.2.1, RAG v2.6.2, NIM weight pulls) —
  environment-prep actions on the VM, recorded in `prep-log.md`; they are not
  buildable or testable from this repo.
- **Curated fixture content** (real factory clips + real corpus) — swapped in
  at environment prep (ADR-004); M6 gates structure only.
