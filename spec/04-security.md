# 04 — Security

Scaled to a single-user lab demo, as the spec context requires: there is no public surface, no user accounts, and no production data. The honest threat model is small and stated plainly — the real secrets are the API keys and the learner VM access, and the worst case is key exfiltration or fixture leakage, not a breach.

## Threat model

| Asset | Who/what we protect against | Worst case if compromised |
| --- | --- | --- |
| The three API keys: **NGC API key**, **NVIDIA Build API key**, shared-endpoint key (`SHARED_API_KEY` at the shim) | Accidental commit to the GitHub repo; leakage via logs, container env dumps, shell history on the learner VM | Unauthorized NGC pulls / shared-endpoint abuse (cost, rate-limit burn across the 10-VM pool) |
| **Learner VM access** (vCD) | The learner themselves misusing the VM; pool cross-talk between the 10 instances | Cross-tenant state mix-up; demo data from one learner visible to another |
| **Fixture content** — pre-recorded factory clips (assume they may contain identifiable personnel: PII-lite) and the internal-style corpus | Accidental upload/exfiltration off the VM; the RAG service returning fixture text to a wider audience than the learner | PII-ish footage or internal docs leaving the lab boundary |
| **Per-instance learner state** — work orders/notes/notifications in mock-wo SQLite; Elasticsearch/Kafka/Redis/VST state | Cross-instance visibility | One learner seeing another learner's work orders (vCD VMs are isolated; per-VM disks are not shared) |

**Deliberately out of scope:** defending the mock-wo API from hostile external clients (it is not internet-facing; see exposure below), TLS within the VM (plain HTTP between containers, per the vendor blueprints' documented configuration — not asserted beyond them), and any compliance regime (no production data, no PII collection).

## Authentication & authorization

- **mock-wo: no application auth, by design.** It is reached (a) by NemoClaw over the internal Docker network (`mock-wo:8090`) and (b) by the learner on the VM. **Network exposure:** the port is published on the VM only; vCD network policy should scope learner access to the learner's own VM. **Decision flagged (→ §8):** if the platform later exposes learner VMs to a broader audience than "the learner", a single static bearer token on mock-wo (one env var, checked on all `/api/v1` routes) is the agreed minimal addition — it is not built now.
- **auth-shim:** the shim does not authenticate callers; its job is key *translation* (`Bearer` stripped, `x-api-key` substituted). `COMPATIBLE_API_KEY='dummy'` for NemoClaw is a safe constant because the shim discards the Bearer value.
- **VM access:** the learner is the OS user on their VM; the instructor injects the real keys at prep time. No shared accounts.

## Input validation & output encoding (mock-wo)

- **Validation:** pydantic schemas enforce the `02` contracts — required fields, enum whitelists (`priority`, `status`, `source_type`, `channel`), length caps (title 200, description 8000, citations ≤ 50 × 2000 chars), 256 KB request-body cap → 413. Invalid input is 422, never 500.
- **Injection:** `db.py` uses **parameterized SQLite queries only** — no f-string/concatenated SQL, anywhere. The work-order `id` is a UUIDv4; hostile path segments (`../../etc/passwd`, `'; DROP TABLE…`) are treated as unknown ids → 404 (test-enforced, `05` TC rows).
- **Output encoding (XSS):** Jinja2 **autoescape on** for all UI templates; the UI is server-rendered with no `innerHTML`/`eval` (no JS framework at all). Hostile `title`/`description` content is rendered escaped (test-enforced).
- **Denial of service:** 256 KB body cap; single-worker + SQLite WAL is adequate at lab scale (a handful of calls per beat); `restart: unless-stopped` + healthcheck.

## Secrets management (no hard-coded credentials, ever)

| Secret | Where it lives | Rule |
| --- | --- | --- |
| NGC API key (`NGC_CLI_API_KEY`) | Instructor-injected at prep: `~/.config/vss/lab.env` on the VM (gitignored location); passed to `docker login nvcr.io --password-stdin` and to the VSS `.env` at start | Never in the repo, never in a CLI argument (no key visible in `ps`/history), never in logs |
| NVIDIA Build API key (`NVIDIA_API_KEY`) | Same mechanism, same file | Same rules |
| Shared-endpoint key (`SHARED_API_KEY`) | Same file; consumed by the shim via `envsubst` at container start (the build document's mechanism) | Never in the repo; the repo carries `compose/nginx.conf.template`. envsubst substitutes the key and the **non-secret** upstream address `${SHARED_ENDPOINT_URL}` (instructor-provided — the endpoint is now recorded in `01`/`09`/`10` and `lab-prep.md`; the lab.env value is the prefix before `/v1` per 08 item 36) |
| `RAG_API_KEY` | Same mechanism; injected into the VSS `.env` (`RAG_API_KEY`) | Same rules |
| `COMPATIBLE_API_KEY` | `config/nemoclaw.env` in the repo | `'dummy'` — safe constant, not a credential (shim discards it) |

Repo hygiene: every env file that contains secrets exists only as `*.env.example` with `<PLACEHOLDER>` values; the real files are generated at prep. `.gitignore` covers real env files, `prep-log.md`, and state dirs — and `05` has a test that asserts those patterns exist. No secret is ever printed by any script (no `echo` of key values; `set -u` without `set -x` around credential handling).

## Data handling — what is logged, what must never be logged

**Never logged (hard rule):** key material of any kind (`SHARED_API_KEY`, `NGC_CLI_API_KEY`, `NVIDIA_API_KEY`, `RAG_API_KEY`); any `Authorization` header (the shim keeps nginx's default access log — request line only, no headers — and no header logging is enabled); request bodies.

**What is logged (ops visibility, per-VM, ephemeral):** container start/stop state, health-gate results, the RT-VLM gate outcome, `nvidia-smi` VRAM measurements, corpus ingest counts (document count per collection), mock-wo request logs limited to method + path + status + latency (no body, no query-string content beyond the filter parameters). `prep-log.md` records versions, SHAs, ports, measurements — **never keys**.

**Fixture PII handling:** pre-recorded clips are assumed to potentially contain identifiable personnel. They live in `fixtures/video/` (repo) and, once ingested, inside the per-VM VST. Rules: fixtures are pulled only from the lab's controlled GitHub repo; no fixture file is uploaded to any external service during the lab (RAG ingests locally; VSS analyzes locally); the shared endpoint receives **text queries only** (the LLM fusion step) — this is inherent to the blueprint design and is the one fixture-derived data path that leaves the VM, which is why the corpus and clips are curated/scrubbed before they enter the repo (prep gate, §8). Work-order content (which may quote the corpus/clips) is per-instance and wiped on VM reset.

**At rest / in transit:** at rest — plain files on per-VM disks (vCD default), no production data, so no additional encryption layer is warranted; in transit — plain HTTP within the VM (vendor blueprints' documented configuration); the off-VM endpoint's transport security is the platform's (not asserted here beyond the build document).

## Dependency & supply-chain hygiene

- **Images:** `nginx:1.27-alpine` (fixed series tag) and `python:3.12-slim` (fixed series tag); all NIM/VSS images pulled from `nvcr.io` with the exact tags pinned in `03`/`09` (the user's release data, 2026-09-02) — the actually-pulled values are recorded in `prep-log.md`. No `latest` anywhere in the repo — a repo-wide grep test enforces this.
- **Blueprint repos:** pinned by git tag (VSS v3.2.1, RAG v2.6.2); `10-clone-blueprints.sh` records the resolved commit SHA to `prep-log.md` so a rebuild reproduces the exact tree.
- **Python deps:** direct dependencies pinned exactly (`03` table); the first prep build records the full resolved set (`pip freeze`) in `prep-log.md`.
- **Login:** `docker login nvcr.io --username '$oauthtoken' --password-stdin` — the key never appears on a command line.

## Risk → mitigation map (OWASP Top 10, the categories that apply)

| OWASP category | Applies here? | Mitigation in this design |
| --- | --- | --- |
| A02 Cryptographic failures | Yes — API keys | Secrets table above: prep-injected, gitignored locations, `--password-stdin`, nothing logged |
| A03 Injection | Yes — mock-wo takes agent- and learner-supplied input | Parameterized SQLite only; UUID ids; hostile id → 404 (test-enforced) |
| A04 Insecure design / config | Partially — lab-grade exposure | mock-wo unauthenticated **by design** with the exposure scope stated and the token fallback agreed (§8); vendor-required config (`cgroupfs`, shm 32 GB) kept at the documented values |
| A07 XSS | Yes — work-order text renders in the UI | Jinja2 autoescape on; no JS framework |
| A08 Integrity / supply chain | Yes | Pinned tags/versions, clone-SHA + resolved-set recording, no `latest` (grep test) |
| A09 Logging/monitoring failures | Yes | "Never logged" list enforced; ops logs defined and minimal |

**Known vendor-mandated tolerance (flagged, not fixable here):** the build document requires `chmod -R 777 "$VSS_DATA_DIR/data_log"` for the VSS data directories. Accepted because the VM is single-user and holds only demo data; the compensating control is "no production data on the VM, ever". **→ §8.**

## Open items carried to §8 (from this file)

- **Open (→ §8):** mock-wo unauthenticated by design; the static-token fallback triggers only if learner VMs are exposed beyond the learner (confirm platform network policy before launch).
- **Open (→ §8):** fixture scrubbing gate — confirm the pre-recorded clips contain no identifiable personnel (or are released for lab use) before they enter the repo; this is the one data path (LLM fusion text) that leaves the VM.
- **Open (→ §8):** the `chmod 777` on `VSS_DATA_DIR/data_log` is a vendor requirement accepted as a lab tolerance (single-user VM, demo data only).
- **Open (→ §8):** the three API keys and VM access are the lab's real secrets — confirm the instructor's prep runbook (who holds the keys, how they reach the 10 VMs) before the build.
