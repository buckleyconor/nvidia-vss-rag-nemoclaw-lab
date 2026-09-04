---
module_n: 3
slug: detect-the-anomaly
title: 'Detect the Anomaly'
depends_on: [2]
est_minutes: 15
image_checklist:
  - 'LVS UI alert for the anomaly segment — the alert is raised and the affected equipment is identified as M-3021'
success_criteria:
  - 'The alert is raised for the anomaly segment and is visible in the LVS UI'
  - 'The alert identifies the affected equipment as M-3021'
  - 'The learner has recorded the alert clip reference and timestamp (the value the Module 5 work order will cite as anomaly_ref)'
---

## Step outline (numbered; each step: action, expected result, screenshot?)

1. From the lab repo checkout on the VM, run the beat-2 helper: `bash scripts/demo/02-anomaly.sh` — expected: it verifies the preconditions, stages the anomaly segment (`clip-anomaly-01.mp4`, equipment M-3021), and prints the procedure. — screenshot: no
2. With the baseline healthy (Module 2), play the anomaly segment through the LVS UI. — expected: processing starts; the segment shows the motor bearing with abnormal thermal/vibration behaviour. — screenshot: no
3. Watch for the alert (a few minutes — the VLM is the cost). — expected: the LVS alert logic FIRES — an alert is raised and the affected equipment is identified. — screenshot: yes (image_checklist 1)
4. Read the alert and record two values: the clip reference (e.g. `clip-anomaly-01`) and the anomaly timestamp (e.g. `@00:42`), together the alert ref (e.g. `vss-alert-clip-anomaly-01-00:42`). — expected: the reference is written down — it becomes the work order `anomaly_ref` in Module 5, tying the whole chain back to this beat. One line of why: an alert without this evidence trail is what the engineer on shift has to re-derive by hand — the slow half of the problem this lab closes. — screenshot: no

> Checkpoint placement: at step 4, stating the success criteria verbatim.

## Environment delta

Assumes: Module 2 state (baseline established — healthy pipeline, no alerts, empty CMMS). Leaves behind: the raised M-3021 alert in the LVS state, and the recorded alert ref (clip reference + timestamp) that Module 4's HITL answers and Module 5's work-order verification both consume. No double production: only this module produces the alert ref.

## Commands used (full command text, in backtick form)

	`bash scripts/demo/02-anomaly.sh`

## Expected outputs (verbatim sample output where known)

- `bash scripts/demo/02-anomaly.sh` → sectioned output: `== preconditions ==` / `VSS agent + LVS healthy`, `== the anomaly segment ==` with `anomaly segment: clip-anomaly-01.mp4 (equipment: M-3021)` (manifest-driven — stable text, M5), then `== beat 2 procedure (the learner does this in the UI) ==` with the numbered procedure and the `note for beat 3` line. Ends with the `02-anomaly: ready — next:` trailer. The guide shows this verbatim.
- The LVS alert content is release-dependent — capture the alert screenshot during the VM dry run (L5). The module body asserts the observable state (alert raised, equipment M-3021, ref + timestamp present), not pixel details.
