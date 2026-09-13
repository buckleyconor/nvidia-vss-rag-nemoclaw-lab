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
   enforced per NIM, the ~24 GB headroom is consumed; the remediation is
   cutting the VLM fraction (0.40 → 0.35 / `--max-model-len 16384` /
   `--max-num-seqs 2`, per the sizing reduction row) before co-residency.
   Resolved empirically by the L5 per-NIM VRAM measurement (item 2 of the L5
   checklist in `05`/`09`).
9. **All vRAM figures are the build document's estimates** (VLM ~38 GB at
   0.40/32768/4, six NIMs ~28 GB, CUDA contexts ~4 GB, ~70 GB committed /
   ~24 GB headroom) pending its Phase 2 measurement. L5 records the actuals;
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
20. **Shared-endpoint capacity + model** — unknown and unmeasured for
    10 concurrent lab sessions; it serves the VSS LLM role, RAG generation,
    and all 10 NemoClaw sessions, making it the most likely first failure
    at N=10 outside the VM. Confirm throughput/concurrency limits before
    launch. Endpoint and model ID **owner-confirmed 2026-09-07**:
    `https://model.delllabs.local/api/nemotron35/v1` serves model ID
    `NVIDIA/Nemotron-3.5-Lightning-30B-A3B` — supersedes the expected model
    image recorded 2026-09-02 from the RAG v2.6.2 `nims.yaml`
    (`nvcr.io/nim/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:1.7.0-variant`).
    The platform team should confirm the pre-provisioned endpoint serves
    that model ID (platform-side verification target; `10`).
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
31. **Learner-VM GPU — RESOLVED: vGPU H100 (platform-confirmed 2026-09-07)** —
    the platform changed the learner VM GPU from the spec-confirmed RTX PRO
    6000 96 GB full PCIe passthrough to an H100 vGPU partition. All three
    open points confirmed by the platform 2026-09-07: the learner SKU is
    **H100L-94C** (dev-VM observation: `nvidia-smi` reports
    `NVIDIA H100L-94C`, 96256 MiB (~94 GB), driver 580.105.08 — the pin
    unchanged), the **full ~96256 MiB is visible to the VM** (the ~70 GB
    committed co-residency budget holds), and the VSS hardware profile name
    is **`H100`** (`config/lvs.env`; re-verify against the vss-public
    `dev-profile.sh` profile list when the clone lands — cheap re-check).
    The ~70 GB committed estimate was carried from the RTX PRO 6000; NIM
    profile selection is GPU-dependent, so re-measure at prep (L5) — the
    last genuinely open point on this item.

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
    endpoint was pre-provisioned and unrecorded at the time
    (lab-prep: "pre-provisioned; reached via the auth-shim"), and 04
    stated the template carries "`${SHARED_API_KEY}` substitution only".
    M4 adds `${SHARED_ENDPOINT_URL}` (non-secret, full URL incl.
    scheme, instructor-provided alongside the key from lab.env) as the
    only other substitution; 04's row now says so. TC-033's asserted
    strings are unchanged.
    **Correction 2026-09-07 (owner):** the endpoint now carries a path
    prefix — its OpenAI-compatible base URL is
    `https://model.delllabs.local/api/nemotron35/v1`. Because `location /`
    + `proxy_pass <URI>` replaces the matched location prefix (`/`) with
    the proxy_pass URI and appends the rest of the client path, and every
    consumer calls the shim with `/v1/...` paths, the `lab.env` value is
    the prefix *before* `/v1`, trailing slash included:
    `SHARED_ENDPOINT_URL=https://model.delllabs.local/api/nemotron35/`.
    The full base URL would double-map clients' `/v1/models` to upstream
    `/api/nemotron35/v1v1/models` — the prep-time `GET :8080/v1/models`
    gate catches it (09).
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
39. **VLM budget pin: the effective vendor knobs are `RTVI_VLLM_*`, not
    `NIM_PASSTHROUGH_ARGS`** (dry-run, 2026-09-10, VM ubuntu-24). The
    `--vlm-env-file config/vlm.env` mechanism the lab contract (02,
    TC-036) pins is only VALIDATED by this release's `dev-profile.sh`
    (existence check; the path is forwarded as `VLM_ENV_FILE` in its
    generated.env) — the RTVI VLM entrypoint (`start_rtvi_vlm.sh`) reads
    nothing from the file. The effective knobs are the
    `RTVI_VLLM_GPU_MEMORY_UTILIZATION` / `RTVI_VLLM_MAX_NUM_SEQS` shell
    variables that `services/rtvi/rtvi-vlm/rtvi-vlm-docker-compose.yml`
    interpolates into the `vss-rtvi-vlm` container env (defaults: empty
    → entrypoint 0.7 / 256). Observed: the empty default drove the engine
    to a 62.8 GB pool on the ~94 GB H100L-94C and three of the six
    retrieval NIMs OOM-exited at start (co-residency budget, 09). Fix
    (lab-owned, no vendor patch): `20-start.sh` STEP 2 exports
    `RTVI_VLLM_GPU_MEMORY_UTILIZATION=0.40` and `RTVI_VLLM_MAX_NUM_SEQS=4`
    before the `dev-profile.sh` call — compose interpolation precedence
    (process env > `--env-file`) makes the export win over the vendor's
    0.35 default / `get_rtvi_vllm_gpu_memory_utilization` tier values. No
    max-model-len knob exists on this surface, so the 32768 context pin in
    TC-036 is documented intent; the pool cap is the protection that
    guards the budget. `config/vlm.env` is retained as the contract
    artifact (TC-036) and documented intent — see its header note.
40. **NemoClaw gateway port — RESOLVED: 8085 via `NEMOCLAW_GATEWAY_PORT`**
    (dry-run, 2026-09-10, VM ubuntu-24). NemoClaw's DEFAULT gateway port
    is 8080 (`dist/lib/core/ports.js`) — the auth-shim's port — so the
    onboarding preflight fails with "Gateway port 8080 has multiple
    listeners" (the shim's docker-proxy PIDs are the owners; never stop
    them). The supported knob is `NEMOCLAW_GATEWAY_PORT` (gateway-
    binding.js: a non-default port registers the gateway as
    `nemoclaw-<port>`; the CLI writes `OPENSHELL_SERVER_PORT` into the
    gateway service env itself). 8085 is reserved in 09 (8086/8087 set
    for health/metrics in `~/.config/openshell/gateway.env`; the binary
    disables both by default — port 0 — and binds 127.0.0.1). The
    onboarding session (`~/.nemoclaw/onboard-session.json`) records the
    port; a failed session is discarded (`NEMOCLAW_FRESH=1` / delete the
    file) rather than patched.
41. **NemoClaw onboarding SSRF preflight — RESOLVED: three host-side
    accommodations, all lab-owned** (dry-run, 2026-09-10). The preflight
    probes `NEMOCLAW_ENDPOINT_URL` FROM THE HOST (endpoint-ssrf-
    preflight.js / trusted-private-endpoint.js) and requires the host to
    (a) resolve, (b) resolve to a PUBLIC address OR be on an explicit
    trust allowlist AND resolve to an **operator-trustable** private
    address (RFC1918 yes, loopback NO), (c) then the curl probe (pinned
    to the resolved address) must complete. Observed failures in order:
    "curl exit 6" (auth-shim is a docker-network name, invisible to host
    resolvers); "resolves to private/internal address 127.0.0.1" (the
    trust list was set but loopback is not operator-trustable). Fixes,
    all written/exported by 40-nemoclaw.sh: a host `/etc/hosts` pin of
    `auth-shim` to the VM's management IP (DERIVED — first global
    non-loopback IPv4 via `hostname -I`; the shim's nginx binds all
    interfaces so the real IP serves identically; containers still
    resolve `auth-shim` via docker DNS — runtime contract unchanged);
    `NEMOCLAW_TRUSTED_PRIVATE_INFERENCE_HOSTS=auth-shim` (the documented
    inference-only allowlist, comma-separated). No vendor patch, no proxy
    service; the pin persists across reboots.
42. **NemoClaw model + policy contracts — RESOLVED with recorded
    deviations** (dry-run, 2026-09-10). (a) Without `--model`, the vendor
    script defaults `NEMOCLAW_MODEL` to NVIDIA's HOSTED model
    (`nvidia/nemotron-3-super-120b-a12b`); the local endpoint 404s on
    unknown models ("The model ... does not exist") and the onboarding
    session records `model: null` → 40-nemoclaw.sh passes `--model` with
    the lab's served MODEL_ID (the onboard probe then passes: "Inference
    smoke passed"). (b) v0.0.118 rejects `allowed_ips` in USER-SUPPLIED
    presets ("not permitted in user-supplied presets") → the generated
    lab policy strips it (recorded deviation: host+port scoping kept,
    hostname→CIDR IP pinning dropped). (c) The vendor VSS preset
    duplicates built-in-baseline host:port entries (clawhub.ai,
    registry.npmjs.org, integrate.api.nvidia.com, openclaw.ai,
    docs.openclaw.ai — all :443) with conflicting metadata → "network
    endpoint ambiguity validation failed". 40-nemoclaw.sh therefore
    dedups the lab file against the live baseline (`nemoclaw demo policy
    get --raw`) before apply, drops sections left empty, and skips
    policy-add when the live policy already covers the whole file
    (idempotent re-run). The vendor call's own final policy step fails
    on that overlap by design on a fresh VM AFTER onboarding completes →
    the script tolerates exactly that failure (vendor failure with no
    sandbox = hard error) and re-applies the deduped file.
43. **02 step-5 gate reality — RESOLVED: host-side gate set** (dry-run,
    2026-09-10). `openclaw` does not exist on the host (it is the
    sandbox-internal agent CLI — the build doc's "openclaw nemoclaw
    status" runs INSIDE the sandbox, via `nemoclaw demo exec`), and the
    status output does not expose the endpoint URL by design
    (credential-safe — the box shows "Managed Inference Route
    (inference.local)"). 40-nemoclaw's gate: host-side `nemoclaw demo
    status` (MODEL_ID + `Provider: compatible-endpoint` + `Inference:
    healthy` + `Policies: vss`) + the sandbox-side registration box
    ("NemoClaw registered" + MODEL_ID; the CLI prints the box then exits
    non-zero with a benign "not a CLI command" note) + a direct
    `curl http://auth-shim:8080/v1/models` (lists the model). Version pin
    v0.0.118 verified via `nemoclaw --version`.
44. **NemoClaw gateway/sandbox lifecycle — recorded** (dry-run,
    2026-09-10). Root has no user D-Bus bus ("Failed to connect to bus:
    No medium found") → the managed systemd USER service is unavailable
    → the OpenShell gateway runs as a STANDALONE host process under
    NemoClaw state (`openshell-gateway[nemoclaw=nemoclaw-8085;port=8085]`;
    gateway authority: nemoclaw-managed, owner: standalone); the
    in-sandbox OpenClaw agent gateway is v2026.7.1 (Harness: OpenClaw
    (gateway)); the dashboard host-forward is :18789 (127.0.0.1; the
    installer prints `http://127.0.0.1:18789/`). Reboot story: the
    documented 20-start → 40-nemoclaw re-run path (vendor script restarts
    the gateway, policy re-apply is idempotent, the gate re-verifies) —
    no user service to keep alive, no `enable-linger` needed.
    **Upgraded 2026-09-10 (item 45): reboot recovery is now
    zero-interaction** — the re-run path remains as the manual fallback,
    but the `nemoclaw-recover.service` boot unit repairs the gateway +
    dashboard forward on its own.
45. **Reboot resilience + self-heal design — recorded** (dry-run,
    2026-09-10). Decision: zero-interaction reboot recovery is achieved
    with (a) restart policies on every container (long-running
    `unless-stopped`/`always`; one-shots `on-failure:5`; the vendor's
    `vss-kibana-init` — crash-looping 272+ times against a `kibana`
    service the lab profile never starts — suppressed to `no` and
    recorded), (b) `live-restore: true` in the docker daemon config,
    (c) the `nemoclaw-recover.service` boot unit running the vendor's own
    `nemoclaw demo recover` (the only two pieces NOT docker-managed: the
    host gateway process and the :18789 dashboard forward), and (d) the
    `lab-health-watch.timer` self-heal (5 min): HTTP-gate probes, docker
    start/restart with per-target cooldown (10 min), grace windows (VLM
    20 min), and escalation (≥3 actions/hour → CRIT + 1 h hold). Deliberate
    limits: a GPU wedge logs CRIT only (a reboot is a human act); the
    watchdog never re-runs 20-start (a full stack re-up is a human
    decision). Exited-0 containers are never restarted (never override a
    deliberate act). Verified live: all-green run, deliberate stop left
    alone, `docker kill` self-healed. The first real reboot is still a
    recorded test item (05 L5 checklist, item 4).
