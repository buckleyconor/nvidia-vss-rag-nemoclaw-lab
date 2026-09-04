---
module_n: 1
slug: explore-the-stack
title: 'Explore the Running Stack'
depends_on: []
est_minutes: 15
image_checklist:
  - 'Mock CMMS work-order list at http://localhost:8090 — empty list, no unread badge (the baseline reveal surface)'
  - 'OpenClaw UI with the NemoClaw session ready (the beats 3-4 surface)'
success_criteria:
  - 'Every endpoint probe (8080, 8000, 38111, 8018, 8081, 8090) returns 200'
  - 'nvidia-smi shows 7 GPU compute processes (the local VLM + six retriever NIMs) with ~70 GB of 96 GB committed'
  - 'Nothing listens on :30081 (the local LLM NIM must not be running — generation is remote via the shared endpoint)'
  - 'The mock CMMS work-order list is empty and the notification feed has no entries'
  - 'openclaw nemoclaw status reports the shared endpoint model nvidia/nemotron-3-nano-omni-30b-a3b-reasoning'
---

## Step outline (numbered; each step: action, expected result, screenshot?)

1. Open a shell on the learner VM (SSH per the instructor runbook; the guide's commands all run in this shell). — expected: a shell prompt on the VM. — screenshot: no
2. Verify the auth-shim lists the shared model: `curl -s http://localhost:8080/v1/models -H "Authorization: Bearer dummy"` — expected: a JSON model list containing `nemotron-3-nano-omni-30b-a3b-reasoning`. One line of why: the shim translates Bearer to x-api-key for the shared off-VM endpoint — all three LLM roles (VSS LLM, RAG generation, NemoClaw) flow through it. — screenshot: no
3. Verify the VSS agent: `curl -s http://localhost:8000/health` — expected: healthy. — screenshot: no
4. Verify the LVS backend: `curl -s http://127.0.0.1:38111/v1/ready` — expected: 200. One line of why: LVS is the video-analysis backend that raises the beats 1-2 alerts. — screenshot: no
5. Verify the RT-VLM: `curl -s http://127.0.0.1:8018/v1/health/ready` — expected: 200. One line of why: the local 8B-class VLM (40% of the GPU) does the video understanding. — screenshot: no
6. Verify the RAG server: `curl -s http://localhost:8081/v1/health` — expected: healthy. — screenshot: no
7. Verify the mock CMMS: `curl -s http://localhost:8090/health` — expected: `{"status":"ok","db":"ok"}`. — screenshot: no
8. Check GPU residency: `nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader` — expected: exactly 7 rows (the local VLM + six retriever NIMs); then `nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader` — expected: ~70 GB used of ~97871 MiB. One line of why: this is the co-residency budget the whole lab depends on. — screenshot: no
9. Confirm the local LLM NIM is absent: `ss -ltn | grep :30081` — expected: no output. One line of why: a running local LLM NIM is a misconfiguration — the LLM is the shared endpoint, not a local model. — screenshot: no
10. Open the mock CMMS in the browser at `http://localhost:8090`. — expected: the work-order list is EMPTY and the notification badge shows 0. This is the surface Module 5 will fill. — screenshot: yes (image_checklist 1)
11. Open the OpenClaw UI at `http://localhost:18789` (or the port recorded in `prep-log.md` at prep) and run `openclaw nemoclaw status --json | jq -r '.model // "unavailable"'` — expected: `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` (the custom endpoint model, not a local NIM). — screenshot: yes (image_checklist 2)

> Checkpoint placement: after step 2 (the shim serves the shared model — the environment works before the learner invests more time) and at step 11 (module success criteria verbatim).

## Environment delta

Assumes: the full `lab-prep.md` verify state — the stack is up and healthy before the session, the RAG index (collection `demo_corpus`) is built, the clips are at `/data/video`, the corpus at `/data/corpus`, and the mock CMMS is empty. Nothing from an earlier module (this is the first). Leaves behind: nothing — pure orientation. Every vocabulary item this module introduces (auth-shim, shared endpoint, LVS, RT-VLM, mock CMMS, OpenClaw UI, the :30081 invariant) is reused by Modules 2-6.

## Commands used (full command text, in backtick form)

	`curl -s http://localhost:8080/v1/models -H "Authorization: Bearer dummy"`
	`curl -s http://localhost:8000/health`
	`curl -s http://127.0.0.1:38111/v1/ready`
	`curl -s http://127.0.0.1:8018/v1/health/ready`
	`curl -s http://localhost:8081/v1/health`
	`curl -s http://localhost:8090/health`
	`nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader`
	`nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader`
	`ss -ltn | grep :30081`
	`openclaw nemoclaw status --json | jq -r '.model // "unavailable"'`

## Expected outputs (verbatim sample output where known)

- `curl -s http://localhost:8090/health` → `{"status":"ok","db":"ok"}` (verbatim from the mock-wo build, M1/M2 — stable contract).
- `curl -s http://localhost:8080/v1/models -H "Authorization: Bearer dummy"` → a JSON `data` array listing `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` (the exact list depends on the shared endpoint; the lab asserts the model is present).
- `ss -ltn | grep :30081` → (no output — the check passes by silence).
- `openclaw nemoclaw status --json | jq -r '.model // "unavailable"'` → `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`.
- The nvidia-smi outputs: 7 compute-app rows and ~70 GB/97871 MiB — the exact values are the prep-log.md measurements (the guide names the expected shape, not exact MiB).
- The vendor endpoint bodies (:8000, :38111, :8018, :8081) are release-dependent — capture verbatim during the VM dry run (L5) and tighten the wording then.
