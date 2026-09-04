---
module_n: 2
slug: establish-the-baseline
title: 'Establish the Baseline'
depends_on: [1]
est_minutes: 15
image_checklist:
  - 'LVS UI showing the normal-state clip processed with a healthy pipeline status and no alerts'
  - 'Mock CMMS list still empty after the baseline clips (the contrast the anomaly beat needs)'
success_criteria:
  - 'Both normal-state clips are processed to completion by the VSS pipeline'
  - 'The LVS UI shows a healthy pipeline state with NO alerts for the normal-state clips'
  - 'The mock CMMS work-order list is still empty (nothing has filed anything yet)'
---

## Step outline (numbered; each step: action, expected result, screenshot?)

1. From the lab repo checkout on the VM, run the beat-1 helper: `bash scripts/demo/01-baseline.sh` — expected: it verifies the VSS agent + LVS are healthy, stages the two normal-state clips at `/data/video` (or confirms them), and prints the procedure. One line of why: the helper exists so the learner does not have to remember which clips are the normal-state set (the fixture manifest is the source of truth). — screenshot: no
2. In the LVS UI, play the first normal-state clip through the pipeline (per the procedure the helper printed). — expected: the clip is ingested and processing starts (captioning + summarization). — screenshot: no
3. Wait for processing to complete (a few minutes — the local VLM is the whole cost of the run). — expected: processing completes; the pipeline state is healthy. — screenshot: yes (image_checklist 1)
4. Play the second normal-state clip the same way. — expected: processed to completion, healthy, still no alerts. — screenshot: no
5. Confirm the baseline in two places: the LVS UI shows no alerts, and the mock CMMS list at `http://localhost:8090` is still empty. — expected: a healthy baseline with nothing filed — the contrast beat 2 needs. — screenshot: yes (image_checklist 2)

> Checkpoint placement: at step 5, stating the success criteria verbatim (the module has no long-running API gate — the watch time is in steps 3/4).

## Environment delta

Assumes: Module 1 state (stack verified healthy; every probe 200). Leaves behind: the two processed normal-state clips in the VSS video store (VST) — the pipeline history the anomaly beat reads against — and an explicitly confirmed empty mock CMMS. Produces no artifacts Module 5+ consumes directly; its product is the established contrast.

## Commands used (full command text, in backtick form)

	`bash scripts/demo/01-baseline.sh`

## Expected outputs (verbatim sample output where known)

- `bash scripts/demo/01-baseline.sh` → sectioned output: `== preconditions ==` / `VSS agent + LVS healthy`, `== staging the normal-state clips at /data/video ==` with `staged: <file>` lines, then `== beat 1 procedure (the learner does this in the UI) ==` with the numbered UI procedure — step 1 carries the LVS UI URL read from `prep-log.md` (the only variable part; recorded at prep). Ends with the `01-baseline: ready — next:` trailer. The guide shows this verbatim (M5 stable text).
- The LVS UI state is release-dependent (the LVS UI URL/port is prep-recorded per `lab-prep.md`) — capture the screenshots during the VM dry run (L5); the module body asserts the observable state (processed, healthy, no alerts), not pixel details.
