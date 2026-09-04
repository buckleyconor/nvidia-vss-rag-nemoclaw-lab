---
module_n: 6
slug: triage-a-second-anomaly
title: 'Triage a Second Anomaly'
depends_on: [4, 5]
est_minutes: 20
image_checklist:
  - 'Mock CMMS monitoring note for the second anomaly (the note explains why this anomaly is a note, not a work order)'
  - 'Work-order list unchanged from Module 5 (still exactly one work order)'
success_criteria:
  - 'The agent''s reasoning is visible in the OpenClaw UI for the second run'
  - 'A monitoring note appears in the mock CMMS (equipment, the why-it-is-a-note description, and an anomaly_ref)'
  - 'The work-order list is UNCHANGED from Module 5 — no second work order was filed'
---

## Step outline (numbered; each step: action, expected result, screenshot?)

1. Note the state you are contrasting against: the mock CMMS work-order list holds exactly one work order (Module 5) and the notes list (`http://localhost:8090/notes`) is empty. — expected: the baseline for the contrast. — screenshot: no
2. Trigger the second anomaly of a different kind. Two paths, in order of preference: (a) if the lab's curated second anomaly clip is available at `/data/video` (the fixture manifest marks it `role: anomaly`), play it through the LVS UI; (b) otherwise replay the Module 3 anomaly segment and adjust the trigger in the HITL prompts (e.g. scenario: routine inspection review; knowledge-retrieval query: vibration monitoring criteria for M-3021) so the agent's verdict is the triage path. The exact parameter set that reproduces the note outcome is tuned during the VM e2e dry run (L5 item 6) and recorded in `prep-log.md` — the guide uses the recorded values. — expected: the second anomaly is in the pipeline. — screenshot: no
3. Start a fresh NemoClaw session and paste the same instruction shape (the one-instruction kick-off again). — expected: the skill activates and the four HITL prompts appear. — screenshot: no
4. Answer the four HITL prompts with the adjusted parameters, then hands off. — expected: the agent works — tool calls, retrieval, reasoning visible — and this time the verdict differs. — screenshot: no
5. Verify in the mock CMMS: the notes list shows the monitoring note (equipment, description — why this anomaly is a note and not a work order, anomaly_ref); the work-order list still holds exactly one work order. — expected: the agent triaged — it did not script-follow. One line of why: the same pipeline, the same instruction shape, a different engineering outcome — that contrast is what makes the response trustworthy. — screenshot: yes (image_checklist 1 and 2)

> Checkpoint placement: at step 5, stating the success criteria verbatim.

## Environment delta

Assumes: Modules 1-5 state (the stack, the first work order verified in Module 5, the note-trigger parameters recorded in `prep-log.md`). Leaves behind: the monitoring note in the mock CMMS and an unchanged work-order list. Consumes (does not produce) the work order from Modules 4-5 — the contrast device. Optional module: a session that stops after Module 5 has completed the core lab (the concept marks beat 5 as the optional extension); the module body says so.

## Commands used (full command text, in backtick form)

	`curl -s http://localhost:8090/api/v1/notes`
	`curl -s http://localhost:8090/api/v1/work-orders | jq 'length'`

## Expected outputs (verbatim sample output where known)

- `curl -s http://localhost:8090/api/v1/notes` → an array with the monitoring note (shape from the mock-wo contract, M1/M2):

```
[{"id":"<uuid>","equipment":"M-3021","description":"<why this anomaly is a note, not a work order>","anomaly_ref":"<the second anomaly ref>","created_at":"<iso-8601>"}]
```

  (verbatim sample captured from the build's TestClient run during the VM dry run — the description prose is agent-run-dependent; the guide asserts the shape: one note, equipment present, description non-empty, anomaly_ref present.)
- `curl -s http://localhost:8090/api/v1/work-orders | jq 'length'` → `1` (unchanged from Module 5).
- The second agent run's OpenClaw UI content is agent-run-dependent — the L5 e2e replay (item 6) is where the note outcome is proven on the VM; the module body asserts the observable end states (note present, work-order list unchanged).
