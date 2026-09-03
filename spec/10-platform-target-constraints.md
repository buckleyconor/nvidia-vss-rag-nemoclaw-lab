# 10 — Platform-target constraints

**First pass — no platform requirements file exists yet.**
`~/.holagent/platforms/vcd/requirements.md` is absent, so this section is
derived from the approved sizing's Deployment target and the build document.
`/hol-platform-check` is the real gate; this section is what the platform
team is asked to review, and the known non-compliances are called out here
rather than deferred.

## Target

**vCD** — one Ubuntu 24.04 VM per learner, Docker Compose only, **no
Kubernetes**.

Why vCD single VM and not K8s:

- VSS ships **Compose-only** (its deployment is `.env`-driven Docker Compose).
- VSS's `native.cgroupdriver=cgroupfs` Docker daemon requirement **conflicts
  with MicroK8s**, which expects systemd cgroups — one of the documented
  reasons the project build document uses Compose.
- A K8s hybrid (RAG ships a Helm chart, validated on OpenShift behind an
  `openshift.enabled` flag; VSS on the host, RAG in-cluster) is the
  **documented future graduation path** for this blueprint — not this lab.
- The density story is per-VM by design (one learner per VM, pool provides
  concurrency) — a cluster adds nothing the beats need and breaks the
  start-order gate (the VLM must profile an empty GPU first).

## Known constraints the platform team must satisfy (first pass)

Each row: the constraint, why it is hard (mechanism), the evidence, and how
it is verified.

| # | Constraint | Why it is hard | Evidence | Verified by |
|---| ---------- | -------------- | -------- | ----------- |
| 1 | **Full PCIe passthrough of the RTX PRO 6000 96 GB — NOT vGPU** | NIM probes the GPU device directly for profile selection; a vGPU partition changes what it sees | build document §2 (VM specification) | L5 item 2/3 (NIMs profile at prep; `nvidia-smi` shows ~97871 MiB to the VM); `lab-prep.md` verify checks |
| 2 | **`/dev/shm` 32 GB** (Docker `default-shm-size: 32G`) | VSS decode / Docker shared-memory paths OOM below 16 GB; 32 GB is the recommended value | sizing reduction row (/dev/shm); build document daemon.json | `lab-prep.md` verify check on the Docker daemon config |
| 3 | **`vm.max_map_count=262144`** (plus `fs.file-max=2097152`, `net.core.somaxconn=4096`) | Elasticsearch **refuses to start** without it | build document failure modes (ES exits immediately) | `lab-prep.md` verify check: `sysctl vm.max_map_count` |
| 4 | **NVIDIA driver 580.105.08 exact** (Ubuntu 24.04 build — the VSS canonical-matrix exact pin for 24.04; 580.65.06 is the 22.04 variant, not used) | exact driver pin per the VSS host matrix (not just a floor) | VSS 3.2.1 host requirements (user-supplied, 2026-09-02); sizing software stack; build document §4.1 | `lab-prep.md` verify check: `nvidia-smi` driver version |
| 5 | **10-VM pool with a hard cap of 10 concurrent learners** | user-set ceiling ("we will not exceed this"); one learner per VM, no in-VM concurrency | sizing density section | pool inventory (platform side); the cap is a policy, not a probe |
| 6 | **Docker daemon: `native.cgroupdriver=cgroupfs`** | VSS prerequisite; conflicts with systemd-cgroup managers (e.g. MicroK8s) — the same fact that rules K8s out | build document §4.2 | `lab-prep.md` verify check on the Docker daemon |
| 7 | **Shared off-VM inference endpoint, pre-provisioned, capacity unknown for 10 concurrent sessions** | it serves the VSS LLM role, RAG generation and all 10 NemoClaw sessions; the per-VM design depends on it, but its throughput/concurrency limits were never measured | sizing open questions; §8 item 20 | **platform team must confirm before launch** — the most likely first failure at N=10 outside the VM |
| 8 | **Docker Engine inside the window ≥ 28.3.3 and < 29.5.0** (Docker Compose ≥ v2.39.1) | newer Docker breaks NGC pulls; below the VSS floor the stack won't start | both blueprints' host matrices (user-supplied, 2026-09-02) | `lab-prep.md` verify checks: Docker Engine server version; Docker Compose version |

## What the platform team should confirm before pool provisioning

1. Pool size/capacity: 10 VMs at 32 vCPU / 256 GB RAM / 2 TB NVMe each
   (the documented 192 GB / 1.5 TB minimums are under-provisioned — see §9).
2. GPU delivery: full PCIe passthrough (constraint 1), driver **580.105.08 exact**
   pre-baked in the VM template (constraint 4).
3. VM template pre-baking: Docker Engine inside the ≥ 28.3.3 / < 29.5.0 window
   with Compose ≥ v2.39.1 (constraint 8), Docker `cgroupfs` + `default-shm-size: 32G`
   (constraints 2, 6) and the sysctl file (constraint 3) — so a learner VM is
   ready out of the template.
4. Shared-endpoint capacity for 10 concurrent sessions (constraint 7) — that
   the endpoint serves the expected model image
   `nvcr.io/nim/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:1.7.0-variant`
   (§8 item 20) — and how the `SHARED_API_KEY` / endpoint location reach each
   VM (instructor runbook, §8 item 23).
5. Shared datastore: whether vCD can mount a shared read-only datastore for
   the weight caches (~350 GB per VM otherwise — ADR-005, §8 item 21).
6. Network policy: NVCR/NGC pulls pre-completed at prep; outbound from the
   auth-shim to the shared endpoint; learner-VM exposure model (mock-wo is
   unauthenticated by design — §8 items 15, 23).
