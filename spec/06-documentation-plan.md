# 06 — Documentation plan

Scaled to what this repo is: **deployment code for a single-user lab demo** —
one small application (the mock work-order service), pinned contract files, and
scripts. It is not a public product; the reader is the instructor/prep engineer
and the next maintainer. That is why this section is deliberately thin on API
portals and release documentation and specific about the README, the pitfalls,
and the five ADRs.

## What the README must contain

1. **What this repo is.** Deployment code for the VSS + RAG + NemoClaw lab —
   the glue that the instructor pulls from GitHub onto the vCD VM. The VSS and
   Enterprise RAG stacks are vendor blueprints cloned at prep time from pinned
   tags; this repo does not contain or patch them (the one exception: the
   auth-shim compose/nginx files, vendored verbatim from the project build
   document under `compose/`).
2. **Repo layout** (mirrors `03-build-decisions.md`): `mock-wo/`, `compose/`,
   `config/`, `scripts/{prep,demo,test}/`, `fixtures/{video,corpus,rag-index}/`,
   `docs/adr/`, and the gitignored `prep-log.md`.
3. **Prep sequence and start order** — the most important thing in this repo.
   The order is non-negotiable:
   `auth-shim + mock-wo → VSS (VLM profiles an EMPTY GPU at 0.40) → gate on
   RT-VLM ready → RAG stack → NemoClaw sandbox`. One-command entry:
   `scripts/prep/20-start.sh` (testable with `--dry-run`). Host prerequisites
   before that: driver 580.105.08, Docker Engine (≥ 28.3.3 and < 29.5.0 —
   newer breaks NGC pulls) with the `cgroupfs` driver +
   `default-shm-size: 32G`, `vm.max_map_count=262144`, NGC login.
4. **Dev gates** (run anywhere, no GPU): `bash scripts/test/run-dev-tests.sh`
   (ruff + pytest, ≥ 90% line coverage on `mock-wo/app`) and
   `bash scripts/test/container-smoke.sh` (build the mock-wo image, round-trip
   a work order on host port 18090, `Health == "healthy"`).
5. **Deferred-verification pointer:** the six-item L5 checklist in
   `05-test-strategy.md` runs on the VM at environment prep / QA — it is not a
   dev-machine gate and not a build milestone.
6. **The `prep-log.md` convention** — the single "recorded reality" source:
   clone SHAs, resolved image digests, the actually-pulled image values (the
   exact Elasticsearch / VLM / NIM tags are pinned in `03`/`09` — a mismatch
   is a prep finding), measured per-NIM VRAM, the OpenClaw UI URL, the LVS UI
   port, and the NemoClaw installed version (must be v0.0.118 — §8 item 28).
   `09-environment-footprint.md`, `10-platform-target-constraints.md` and
   `lab-prep.md` point at it instead of guessing.
7. **Pitfalls** (build-document failure modes, each as symptom → cause → fix):
   VLM claims ~86 GB (`--vlm-env-file` not applied); second NIM OOMs at
   startup (wrong start order); `ValueError: To serve at least one request`
   (fraction too low for `--max-model-len`); Elasticsearch exits immediately
   (`vm.max_map_count` unset); 401 from the shared endpoint (shim not stripping
   `Authorization`); streaming arrives as one blob (nginx buffering left on);
   VSS answers ignore the corpus (`frag` tool disabled / wrong
   `VSS_AGENT_CONFIG_FILE`); frag returns nothing (wrong collection or missing
   `/v1` on `RAG_SERVER_URL`); NemoClaw install fails (a pre-existing OpenClaw
   is present); NGC pulls fail at the first prep (Docker Engine outside the
   28.3.3–<29.5.0 window — newer Docker breaks NGC pulls); the fix for the
   last: install inside the window and record the exact version in
   `prep-log.md`.

## Interface documentation

- **mock-wo REST contract** — canonical home: `02-architecture.md`. Every app
  endpoint carries a docstring with request/response examples and the exact
  error shapes (422 enum/length/missing, 404, 413 > 256 KB; JSON
  `{"detail"}`).
- **Config files** — `config/` overlays carry comments where non-obvious:
  `vlm.env`'s `NIM_PASSTHROUGH_ARGS` (why exactly
  `--gpu-memory-utilization 0.40 --max-model-len 32768 --max-num-seqs 4`) and
  the RAG triple in `lvs.env.example` (`RAG_SERVER_URL` **with the `/v1`
  suffix**, `RAG_API_KEY`, `KNOWLEDGE_COLLECTION`).
- **Scripts** — a header comment per script: purpose, preconditions, what it
  records in `prep-log.md`, and how to roll back (`docker compose down` per
  stack).

## Docstring / comment expectations

- App code (`mock-wo/app`): module docstring; per-endpoint docstrings; schema
  fields documented at their definition (limits, enums).
- Scripts: bash header comment; inline comments only at non-obvious gates (the
  RT-VLM ready gate, the `--dry-run` branch).
- No doc-rot tolerance: if a config value moves between blueprint tags, the
  README pitfalls section and the config comments change in the same commit.

## ADRs worth keeping (`docs/adr/`, one short file each)

1. **ADR-001 — auth-shim: `Bearer` → `x-api-key`.** The shared endpoint
   expects `x-api-key`; VSS, RAG and NemoClaw all emit OpenAI-style
   `Authorization: Bearer`. One nginx (`nginx:1.27-alpine`, `envsubst` at
   startup) translates once for all three and keeps the sandbox-facing URL
   stable so the endpoint can move later.
2. **ADR-002 — Start-order gate.** The VLM must profile an **empty GPU** first
   (vLLM profiles free memory at startup; a greedy container started second
   behaves differently). The RT-VLM ready gate blocks the RAG stack; encoded
   in `20-start.sh`, testable via `--dry-run`.
3. **ADR-003 — Mock work-order service tech.** FastAPI on Python 3.12 with
   SQLite (WAL) over Node/Express (native `better-sqlite3` needs per-arch
   rebuilds; the image must be arch-neutral) and over Postgres (an unsized
   extra container) or JSON files (no atomicity). In-app notification feed —
   no mailer/webhook; the "maintenance team" is the learner's second role.
   `POST /api/v1/work-orders` is deliberately non-idempotent (retries
   duplicate — pinned by test).
4. **ADR-004 — Provisional fixtures at build time.** Build milestones need
   **structurally valid** fixtures (a synthesized `ftyp` mp4; one
   manual/log/schedule document) so the dev-machine suite passes without
   GPU/VM access; curated content swaps in at environment prep. Content
   suitability (does retrieval read legibly on screen) is only checkable in
   the VM-side e2e replay.
5. **ADR-005 — Per-VM weight caches.** No shared datastore is assumed:
   `~/.cache/nim` (150 GB) + RAG cache (200 GB) are per-VM (≈ 350 GB of the
   2 TB budget). If vCD mounts a shared read-only datastore the per-VM storage
   budget drops — a decision to record, not to silently assume.

## What is deliberately NOT documented here

- Vendor blueprint documentation (VSS/RAG docs) — referenced, not duplicated.
- Learner-facing documentation — that is the guide (`/hol-plan` stage), not
  this repo's README.
