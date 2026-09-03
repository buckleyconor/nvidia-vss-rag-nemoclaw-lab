# 08 — Open questions & assumptions

Every assumption made to fill a gap, and every decision a human should confirm
before building. Merged from the "Open items carried to §8" lists of
`01`–`05`, the approved `sizing.md`, and the approved `concept.md`. Each item:
what it is, why it is open, what resolves it, and what changes if the answer
differs.

## A. Version pins to confirm before cloning

1. **VSS repo tag — RESOLVED: v3.2.1** (user's GitHub release data,
   2026-09-02 — `NVIDIA-AI-Blueprints/video-search-and-summarization`,
   release: tag 3.2.1). Two-step provenance: first confirmed as v3.2.0 at
   spec review (2026-09-02), then superseded the same day by the user's
   GitHub release data. This also supersedes the open set v3.1.0 vs v3.2.1
   the sizing carried ("repo tag v3.1.0 (latest public release; v3.2.1
   unconfirmed — open)" — v3.2.1 is now confirmed to exist and is the
   current release); `sizing.md` is upstream and unedited. Because the
   deployment layout moved between VSS releases, the draft's prep-time
   relocation procedure carries over to the v3.2.1 tag: locate the LVS
   `.env` path (item 11), verify `config_rag.yml` content against the M4
   contract (item 10), verify the `LLM_MODE` remote value (item 12), and
   record the resolved facts in `prep-log.md`. Agent image: item 2.
2. **`VSS_AGENT_VERSION=3.2.1`** — the agent **image** tag, which the build
   document explicitly keeps distinct from the repo tag. Assumption: the
   agent image tracks the release tag (the build document's 3.2.0 value
   matched the v3.2.0 tag; the user's release data gives no separate 3.2.1
   agent-image value). Prep check (mandatory): verify the image tag exists
   on nvcr.io and that the v3.2.1 release compose references it; record the
   actual value in `prep-log.md`. A mismatch is a prep finding to surface —
   never a silent substitution.
3. **RAG release — RESOLVED: v2.6.2** (user's GitHub release data,
   2026-09-02 — `NVIDIA-AI-Blueprints/rag`, release: v2.6.2). Supersedes
   both the open v2.6.0-vs-v2.6.2 tag question and the series-level v2.6
   confirmation from spec review (2026-09-02); `sizing.md` (v2.6.0 with
   v2.6.2 fallback) is upstream and unedited. The tag is now fixed — no
   fallback: clone v2.6.2, and the in-tree
   `docs/deploy-docker-self-hosted.md` of v2.6.2 is authoritative (the
   deployment layout moved between releases). The resolved tag and commit
   SHA are recorded in `prep-log.md`.
4. **Six NIM image tags + Elasticsearch version — RESOLVED with exact
   values** (user-supplied from the RAG v2.6.2 `deploy/compose/nims.yaml`
   and the RAG repo, 2026-09-02): `nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:1.13.0`,
   `nvcr.io/nim/nvidia/llama-nemotron-rerank-1b-v2:1.10.0`,
   `nvcr.io/nim/nvidia/nemotron-page-elements-v3:1.8.0`,
   `nvcr.io/nim/nvidia/nemotron-graphic-elements-v1:1.8.0`,
   `nvcr.io/nim/nvidia/nemotron-table-structure-v1:1.8.0`,
   `nvcr.io/nim/nvidia/nemotron-ocr-v1:1.3.0`; Elasticsearch
   `docker.elastic.co/elasticsearch/elasticsearch:9.3.0` (shared by VSS
   and RAG, counted once). **Correction on record:** the earlier
   user-supplied expected value recorded here ("elasticsearch 0.18.0") is
   superseded by 9.3.0 (the user's GitHub release data, 2026-09-02). The
   exact tags are pinned in `03`/`09` and `lab-prep.md`; prep still records
   the actually pulled values in `prep-log.md` (a mismatch is a prep
   finding). The sub-components nv-ingest 26.3.0, seaweedfs 4.21.0, and
   zipkin 0.4.0 (user-supplied expected values, 2026-09-02) remain
   blueprint-carried `prep-log.md` verification targets without independent
   pinning in the spec.
5. **Python pins chosen without network verification.** The spec stage is
   local-files-only, so `fastapi 0.115.0`, `uvicorn 0.30.6`, `pydantic 2.8.2`,
   `jinja2 3.1.4` (dev: `httpx 0.27.2`, `pytest 8.3.2`, `coverage 7.6.0`,
   `ruff 0.8.4`) are exact but unverified against the index. The first
   `pip install` at build time is the verification point: if a pin is
   unresolvable, substitute the nearest same-series release and record it in
   `prep-log.md`; the M1 tests fail loudly on any incompatibility.
6. **Base-image pinning practice** — `python:3.12-slim` and
   `nginx:1.27-alpine` are series-pinned (never `latest`); repo practice is to
   record the resolved digest in `prep-log.md` at the first prep build, and
   to record the resolved transitive dependency set (direct deps pinned
   exactly). Confirm this practice is acceptable versus full digest-pinning
   of the bases.

## B. Model identity and GPU budget

7. **VLM identity — RESOLVED: `nvcr.io/nim/nvidia/cosmos3-reasoner:1.7`
   (Cosmos3 Nano Reasoner)** (user-supplied from the VSS 3.2.1 release
   `deploy/docker/services/nim/*/compose.yml`, 2026-09-02). The earlier open
   question (Cosmos-Reason2-8B per the repo README vs
   `nvidia/cosmos3-nano-reasoner` per the current VSS docs) resolves to the
   current-docs side: the VSS 3.2.1 release ships `cosmos3-reasoner:1.7` as
   its local VLM NIM image. 8B-class, so the GPU budget (~38 GB at
   0.40/32768/4) is unaffected; LVS prompts and alert verification are
   tuned around this image. The VSS 3.2.1 release also lists
   `nvcr.io/nim/nvidia/nemotron-3-nano:1` (Nemotron-3-Nano) as VSS's local
   LLM NIM — in the lab it is **not run** (the VSS LLM role goes to the
   shared off-VM endpoint; the "LLM NIM :30081 must be absent" check in `02`
   applies to it).
8. **The 0.10 `gpu_memory_utilization` floor risk** — unclear whether the
   documented NIM minimum applies to user-set values. If a 9.6 GB floor is
   enforced per NIM, the ~26 GB headroom is consumed; the remediation is
   cutting the VLM fraction (0.40 → 0.35 / `--max-model-len 16384` /
   `--max-num-seqs 2`, per the sizing reduction row) before co-residency.
   Resolved empirically by the L5 per-NIM VRAM measurement (item 2 of the L5
   checklist in `05`/`09`).
9. **All vRAM figures are the build document's estimates** (VLM ~38 GB at
   0.40/32768/4, six NIMs ~28 GB, CUDA contexts ~4 GB, ~70 GB committed /
   ~26 GB headroom) pending its Phase 2 measurement. L5 records the actuals;
   if the six NIMs measure over ~45 GB total, the VLM fraction is cut before
   co-residency and the `lab-prep.md` steady-state expectations shift —
   flagged, not absorbed.

## C. Integration contract to verify against the cloned release

10. **`config_rag.yml` exact content** — the spec's M4 contract test pins
    what the file must provide at build time (exists, valid YAML, the
    `frag` knowledge-retrieval tool enabled — see 08 item 38); the exact
    shipped content, including the schema and the runtime reads of the
    three `RAG_` values, is verified against the cloned release at prep.
11. **LVS `.env` actual path at the chosen tag** — the layout moved between
    releases (`deploy/docker/developer-profiles/…` vs
    `deployments/developer-workflow/…`); located at prep and recorded in
    `prep-log.md`.
12. **`LLM_MODE` remote value** — the build document flags this as
    "verify the correct remote value for your release" (the CLI equivalent is
    `--use-remote-llm`).
13. **OpenClaw UI URL/port (printed by the installer at prep) and the LVS UI
    port/URL** — both recorded in `prep-log.md`. If the OpenClaw UI ever
    lands on :8090, the mock-wo port is a single constant in one compose
    file (flagged; not a sizing item).
14. **RAG index artifact format** for `fixtures/rag-index/` — the restore
    path is Elasticsearch-version-dependent (item 4), so the **canonical**
    path is ingest-at-prep on the VM; a pre-built artifact is an optional
    fast path. TC-044 gates the manifest, not the artifact format.

## D. Mock work-order service — design confirmations (02/03 decisions)

15. **Confirm or amend before M1 builds** — every item below was open in
    `concept.md` and is pinned by this spec: tech FastAPI/Python 3.12 (over
    Node/Express); storage SQLite WAL (over Postgres/JSON); port 8090;
    in-app notification mechanism (no mailer/webhook); the `MonitoringNote`
    entity for beat 5; deliberately non-idempotent
    `POST /api/v1/work-orders` (retries duplicate — test-pinned); 256 KB body
    cap; single-worker uvicorn; **unauthenticated by design**, with the
    static-token fallback triggering only if learner VMs are exposed beyond
    the learner (confirm the platform network policy before launch — see
    item 23).

## E. Fixtures and corpus

16. **Fixture content** — which pre-recorded clips (normal-state for beat 1;
    an anomaly segment for beat 2) and which corpus (manuals, logs,
    maintenance schedule) is open (carried from `concept.md`). The corpus
    must cover the content types beat 3 retrieves over (manual + log +
    schedule — the sizing reduction row); TC-043 enforces the coverage at
    structure level.
17. **Provisional-fixtures-at-build approach (M6 flag, ADR-004)** —
    structurally valid fixtures at build time; curated content swapped in at
    environment prep. The M6 tests gate structure, not content.
18. **Fixture scrub gate** — confirm the pre-recorded clips contain no
    identifiable personnel (or are released for lab use) before they enter
    the repo. This is the one fixture-derived data path (LLM-fusion text)
    that leaves the VM.

## F. Infrastructure and provisioning

19. **Pre-provisioning ownership** (carried from `concept.md`) — are the
    10-VM vCD pool and the shared off-VM inference endpoint pre-provisioned
    lab infrastructure or in scope for the build? The spec assumes
    pre-provisioned (they appear in `lab-prep.md` as given).
20. **Shared-endpoint capacity + model image** — unknown and unmeasured for
    10 concurrent lab sessions; it serves the VSS LLM role, RAG generation,
    and all 10 NemoClaw sessions, making it the most likely first failure
    at N=10 outside the VM. Confirm throughput/concurrency limits before
    launch. Expected model image (user-supplied from the RAG v2.6.2
    `nims.yaml`, 2026-09-02): `nvcr.io/nim/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:1.7.0-variant`
    — the platform team should confirm the pre-provisioned endpoint serves
    this model/image (platform-side verification target; `10`).
21. **Shared-datastore assumption (ADR-005)** — per-VM weight caches
    (`~/.cache/nim` 150 GB + RAG cache 200 GB ≈ 350 GB each) are assumed with
    no shared datastore mounted. If vCD mounts a shared read-only datastore,
    the per-VM storage budget and the 45–70 minute first-build weight pull
    change.
22. **RAM/disk floors** — 192 GB "will run" per the build document but is
    untested with the shim + mock-wo service added; provision the pool at
    256 GB. The documented 1.5 TB disk minimum is **below** the ~1.65 TB of
    committed content, so 2 TB is the real storage floor (sizing arithmetic
    on the document's estimates).
29. **RAG blueprint host docs vs the lab OS baseline** — the RAG v2.6.2 host
    requirements name Ubuntu 22.04 (the VSS 3.2.1 canonical matrix supports
    Ubuntu 22.04 **or** 24.04); the lab baseline is the approved sizing's
    Ubuntu 24.04 (upstream and unedited; the VSS matrix explicitly supports
    24.04 with driver 580.105.08). Prep must verify the RAG stack (server,
    ingestor, orchestrator, frontend, the six NIMs, Elasticsearch 9.3.0)
    starts cleanly on Ubuntu 24.04; if RAG requires 22.04, that is a
    sizing-level finding to surface — not absorbed.
30. **Docker Engine < 29.5.0 upper bound (NGC pulls)** — both blueprints'
    host matrices (user-supplied, 2026-09-02) bound Docker Engine at
    **≥ 28.3.3 and < 29.5.0** (newer Docker breaks NGC pulls). Prep must
    install Docker inside that window and record the exact installed
    version in `prep-log.md`; `lab-prep.md` gates it with executable
    version checks (Docker Engine server version; Docker Compose ≥
    v2.39.1). The aarch64 dev machine's docker 29.2.1 is inside the bound
    (dev gate only — not the VM).

## G. Security

23. **Instructor key-injection runbook** — the three API keys (NGC, NVIDIA
    Build, `SHARED_API_KEY` for the shim) and the learner VM access are the
    lab's real secrets. Confirm who holds them and how they reach the 10 VMs
    at prep, before the build (see also item 15's exposure question).
24. **`chmod 777` on `VSS_DATA_DIR/data_log`** — a vendor requirement
    accepted as a lab tolerance (single-user VM, demo data only).

## H. Verification deferrals and milestone flags

25. **Confirm the deferral split** — GPU/VM verification is fully deferred to
    environment prep / QA (the six-item L5 checklist in `05`, restated in
    `09`), and stays out of §7 milestone tests (which must run on the
    aarch64 dev machine). Until L5 passes on the VM, "the lab works" is
    proven only to the extent of L0–L4.
26. **M5 flag** — `deploy-scripts` depends on the `20-start.sh --dry-run`
    contract being implemented exactly as specced in `03` (prints the
    ordered plan, exits 0, performs no Docker invocation).
27. **x86 arch check** — the dev-machine L2 smoke proves arch-neutrality but
    not x86 execution; the prep-time re-run of `container-smoke.sh` on the VM
    is the arch check. Confirm it is part of the prep runbook.

## I. Version resolution recorded at spec review (2026-09-02)

28. **NemoClaw — RESOLVED: v0.0.118** (user-confirmed at spec review,
    2026-09-02). The sizing carried no version for NemoClaw (installed
    "via the VSS-repo installer
    `deploy/docker/scripts/nemoclaw/init_nemoclaw.sh`"), so this pin adds a
    version where none was recorded. Prep obligation: the installer at the
    pinned VSS v3.2.1 tag must install/declare v0.0.118 — verify at prep and
    record the actual installed version in `prep-log.md`; a mismatch is a
    prep finding to surface, never a silent substitution.

## J. Spec alignments applied at build stage (2026-09-02, M1)

31. **mock-wo `/health` body wording — RESOLVED: `200 {"status":"ok","db":"ok"}`.**
    `09`'s endpoint table, the `lab-prep.md` verify entry, and the M3 exit
    wording restated the probe as `Health == "healthy"` while §2's interface
    table and TC-016 pin the body to `{"status":"ok","db":"ok"}`. M1 (built
    2026-09-02) implements §2/TC-016, and the three restatements were aligned
    to it (09 endpoint table, lab-prep expect text, 07 M3 exit). The Docker
    healthcheck status is still `healthy` — the compose healthcheck passes on
    HTTP 200, so TC-031 and the lab-prep check are unaffected.
32. **Test-suite layout and TC-024..TC-027 ownership — RESOLVED.**
    §3's layout listed `tests/` as (conftest.py, test_api.py, test_ui.py,
    test_persistence.py), but M1's declared test command runs
    `test_api.py` + `test_schemas.py`, and `test_persistence.py` appeared in
    no milestone's test command. M1 established `tests/` = (conftest.py,
    test_schemas.py, test_api.py, test_ui.py [M2]): L0 units (TC-001/002) sit
    in `test_schemas.py`; persistence (TC-019), concurrency (TC-020) and the
    abuse rows TC-024..TC-027 — which no milestone exit claimed before this
    fix — sit in `test_api.py`, and M1's exit now reads
    "TC-001..TC-020 and TC-024..TC-027 pass". The closing gate's full
    `pytest mock-wo/tests tests` run covers every TC row regardless.
33. **mock-wo CSS delivery — RESOLVED: one static CSS file.** `02`'s UI
    section says "Single HTML/CSS" and `03`'s tech table pins the UI as
    "Jinja2 3.1.4 server-rendered, autoescape on, **one static CSS file**",
    but `03`'s layout tree listed no static directory (internal
    inconsistency, surfaced by the M2 scorer, 2026-09-02). M2 extracts the
    stylesheet to `mock-wo/app/static/style.css` (served at
    `/static/style.css` via a `StaticFiles` mount; linked from
    `base.html`), and the `03` layout tree now carries the file.
34. **mock-wo Dockerfile HEALTHCHECK — RESOLVED: image-level HEALTHCHECK**
    (03, M3, 2026-09-02). `05`'s TC-031 and the container-smoke pseudocode
    (step 2 raw `docker run`, step 5 `docker inspect` Health == "healthy")
    can only pass if the IMAGE carries a healthcheck — the `03` Dockerfile
    contract had none (the compose contract's healthcheck only applies to
    compose-managed containers). M3 adds the `HEALTHCHECK` instruction to
    the Dockerfile with the compose healthcheck's exact parameters (same
    python-urllib command, interval 10s, timeout 3s, retries 12), and the
    `03` Dockerfile block now carries the line.
35. **Dev dependency `pyyaml==6.0.2` — RESOLVED: added to the pinned dev
    set** (03, M4, 2026-09-02). The M4/M6 L3/L4 suites
    (`tests/test_config_contracts.py`, `tests/test_fixtures.py`) parse
    YAML — the shim compose and the fixture manifests — but the 03 dev
    pin list carried no YAML parser and the pinned `.venv` test command
    cannot see the system python's. `pyyaml==6.0.2` was added to
    `mock-wo/requirements-dev.txt` and the 03 dev table (exact pin per
    the supply-chain rules; dev-only, never in the image).
36. **Shim upstream address — RESOLVED: second, non-secret envsubst
    variable** (04, M4, 2026-09-02). `compose/nginx.conf.template` needs
    an upstream for `proxy_pass`, but the shared off-VM inference
    endpoint is pre-provisioned and recorded nowhere in the repo
    (lab-prep: "pre-provisioned; reached via the auth-shim"), and 04
    stated the template carries "`${SHARED_API_KEY}` substitution only".
    M4 adds `${SHARED_ENDPOINT_URL}` (non-secret, full URL incl.
    scheme, instructor-provided alongside the key from lab.env) as the
    only other substitution; 04's row now says so. TC-033's asserted
    strings are unchanged.
37. **Shim files "verbatim from build doc" — handled as pinned-property
    contracts** (M4, 2026-09-02). 03's layout comments call
    `compose/docker-compose.shim.yml` and `nginx.conf.template`
    "VERBATIM from build doc Phase 1", but the build document is outside
    the repo (local-files-only rule), so verbatim text cannot be carried
    or checked here. The repo files implement the pinned properties
    (nginx:1.27-alpine, 8080:8080, demo-net, envsubst at start,
    Authorization-strip + x-api-key + `proxy_buffering off`) test-asserted
    by TC-032/033; a prep-time cross-check against the build doc's
    Phase 1 text is a prep-log item, not a build gate.
38. **08 item 10 wording aligned to the M4 test suite** (M4, 2026-09-02,
    post-scoring fix). Item 10 originally claimed the M4 contract test
    pins "the `frag` knowledge-retrieval tool enabled, reading the three
    `RAG_` values", but the suite had no `config_rag.yml` assertion and
    the RAG_ reads are runtime VSS behavior (prep/L5), not build-time.
    M4 added `test_config_rag_yaml_frag_enabled` (exists + valid YAML +
    `frag` enabled, schema unpinned) and item 10 now says exactly that.
    M4 gate re-run: 10 passed.
