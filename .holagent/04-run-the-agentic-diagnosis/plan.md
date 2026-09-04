---
module_n: 4
slug: run-the-agentic-diagnosis
title: 'Run the Agentic Diagnosis'
depends_on: [3]
est_minutes: 20
image_checklist:
  - 'OpenClaw UI — NemoClaw collecting the four HITL parameters (scenario, events of interest, objects to track, knowledge-retrieval query)'
  - 'OpenClaw UI — the visible agent tool calls, including the frag knowledge-retrieval step against the RAG server'
  - 'OpenClaw UI — retrieved corpus documents (manual / log / schedule) inside the agent reasoning'
  - 'The generated video summary report citing RAG-sourced documents'
success_criteria:
  - 'The four HITL parameters are collected (scenario, events of interest, objects to track, knowledge-retrieval query)'
  - 'The agent''s tool calls, retrieved documents, and reasoning are visible in the OpenClaw UI'
  - 'The video summary report is generated and cites RAG-sourced documents (the frag path worked — the corpus was not ignored)'
  - 'No human input occurs after the last HITL answer — from that point the run is autonomous'
---

## Step outline (numbered; each step: action, expected result, screenshot?)

1. From the lab repo checkout on the VM, run the beat-3/4 helper: `bash scripts/demo/03-agent-kickoff.sh` — expected: it verifies NemoClaw shows the custom endpoint + Nano Omni model, prints the OpenClaw UI URL, and prints the ONE instruction to paste. One line of why: HITL is interactive — the script prints, the learner types. — screenshot: no
2. In the OpenClaw UI, start a fresh session (`/new`). — expected: an empty NemoClaw session. — screenshot: no
3. Paste the printed instruction: `I want to generate a video summary report for clip-anomaly-01.` — expected: NemoClaw activates the `vss-generate-video-report-rag` skill and starts collecting parameters. — screenshot: no
4. Answer the four HITL prompts as they appear. Suggested answers (from the Module 3 alert and the equipment context): scenario — industrial motor bearing inspection review; events of interest — the thermal/vibration anomaly in the recorded clip; objects to track — M-3021 bearing housing; knowledge-retrieval query — bearing replacement criteria for M-3021. — expected: all four parameters collected. — screenshot: yes (image_checklist 1)
5. Hands off — watch the agent work (~90 s to ~250 s of visible agent work): VSS analysis, the `frag` knowledge-retrieval tool calls against the RAG server (collection `demo_corpus`), the retrieved documents, and the reasoning, all on screen. — expected: the agent's tool calls + retrieved documents + reasoning visible. — screenshot: yes (image_checklist 2 and 3)
6. Confirm the generated report: it cites RAG-sourced documents (manual / log / schedule), not just video content. — expected: the report is grounded in the retrieved corpus. — screenshot: yes (image_checklist 4)

> Checkpoint placement: at step 6, stating the success criteria verbatim. No checkpoint mid-agent-run — the run is one autonomous stretch; the observable artifact is the finished report.

## Environment delta

Assumes: Module 3 state (the alert raised and its ref recorded — the HITL answers are built from it). Leaves behind: the generated video summary report, and — as the agent's action step completes — the work order filed in the mock CMMS (which Module 5 verifies; this module does not open the CMMS, so the reveal is not spoiled). No double production: the work order is produced here (by the agent), verified in Module 5.

## Commands used (full command text, in backtick form)

	`bash scripts/demo/03-agent-kickoff.sh`

## Expected outputs (verbatim sample output where known)

- `bash scripts/demo/03-agent-kickoff.sh` → sectioned output: `== preconditions ==` / `NemoClaw sandbox: custom endpoint + Nano Omni model active`, then `== beats 3-4 procedure ==` — step 1 carries the OpenClaw UI URL (installer-recorded at prep, else the dashboard port-forward default 18789 — the only variable part), step 2 the exact instruction with the manifest-derived clip id, steps 3-4 the HITL + autonomy procedure, plus the `beat 4 (the aha)` paragraph and the `03-agent-kickoff: ready —` trailer (stable text, M5). The guide shows this verbatim.
- The OpenClaw UI content (tool calls, retrieved documents, report) is agent-run-dependent — capture the screenshots during the VM dry run (L5 item 5: the report cites RAG-sourced documents is the L5 assertion). The module body asserts the observable states (four parameters collected; tool calls + documents + reasoning visible; report generated), not pixel details.
- The exact HITL parameter sets that reproduce the beat-5 note outcome (Module 6) are tuned during the VM e2e dry run (L5 item 6) and recorded in `prep-log.md`; Module 4 uses the work-order path (the default, documented behaviour).
