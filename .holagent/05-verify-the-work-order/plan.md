---
module_n: 5
slug: verify-the-work-order
title: 'Verify the Work Order'
depends_on: [4]
est_minutes: 10
image_checklist:
  - 'Mock CMMS list with the new work order at the TOP (beat 4 — the list was empty in Modules 1-3)'
  - 'Work-order detail page with the diagnosis fields and citations grouped by source (rag / vss / agent) — the evidence panel'
  - 'Notification feed with the delivered in-app notification for the work order'
success_criteria:
  - 'The new work order appears at the top of the mock CMMS list, with equipment M-3021, status open, and a generated id'
  - 'The detail page shows the diagnosis fields and citations grouped by source_type (rag / vss / agent), and the anomaly_ref matches the alert recorded in Module 3'
  - 'The notification feed holds the matching in-app notification (channel in_app, work-order id linked)'
  - 'The API GETs return the same entity the UI shows'
  - 'No human step occurred between the Module 4 instruction and this work order (the learner only verified)'
---

## Step outline (numbered; each step: action, expected result, screenshot?)

1. Open the mock CMMS at `http://localhost:8090`. — expected: the work order appears at the TOP of the list that was empty in Modules 1-3: title (bearing replacement, M-3021), equipment M-3021, priority, status `open`, created_at. One line of why: from the single instruction in Module 4, every step since is the agent's work — this is the aha the lab exists to show. — screenshot: yes (image_checklist 1)
2. Click the work order to open the detail page. — expected: all fields plus the citations GROUPED BY SOURCE (rag / vss / agent) — the evidence panel; the `anomaly_ref` matches the alert ref recorded in Module 3 (same clip, same timestamp). — screenshot: yes (image_checklist 2)
3. Open the notification feed at `http://localhost:8090/notifications`. — expected: the in-app notification for the work order — "Work order WO-… filed: <title> (priority high, equipment M-3021)" — delivered atomically with the work order. — screenshot: yes (image_checklist 3)
4. Verify through the API the agent used: `curl -s http://localhost:8090/api/v1/work-orders` — expected: a JSON array with the new work order first (newest first is the contract). — screenshot: no
5. Verify the entity by id without retyping the UUID: `curl -s http://localhost:8090/api/v1/work-orders/$(curl -s http://localhost:8090/api/v1/work-orders | jq -r '.[0].id')` — expected: 200 with the same entity (id, fields, citations, timestamps) as the UI detail page. — screenshot: no

> Checkpoint placement: at step 5, stating the success criteria verbatim.

## Environment delta

Assumes: Module 4 state (the agent run completed; the work order is filed — the learner has not looked at the CMMS since Module 1, so the reveal is intact). Leaves behind: the verified work order + notification in the mock CMMS — the artifact Module 6 contrasts against (its work-order list must not grow). No double production: the work order was produced by the agent in Module 4; this module only verifies.

## Commands used (full command text, in backtick form)

	`curl -s http://localhost:8090/api/v1/work-orders`
	`curl -s http://localhost:8090/api/v1/work-orders/"$(curl -s http://localhost:8090/api/v1/work-orders | jq -r '.[0].id')"`

## Expected outputs (verbatim sample output where known)

VERBATIM from the mock-wo build (M1/M2) — stable contract; ids/timestamps vary per run:

- `curl -s http://localhost:8090/health` → `{"status":"ok","db":"ok"}`
- `curl -s http://localhost:8090/api/v1/work-orders` (after the agent run) →

```
[{"id":"3eca5d81-6172-4a9b-9a63-bd298563fdd9","title":"Bearing replacement — M-3021 motor drive","description":"Thermal anomaly on motor M-3021 detected at clip-anomaly-01@00:42. Manual-01 p.12: bearing temp above 75°C requires replacement per schedule. Recommend priority-high replacement within 48 h.","equipment":"M-3021","anomaly_ref":"vss-alert-clip-anomaly-01-00:42","priority":"high","assigned_to":"maintenance-team-b","status":"open","citations":[{"source_type":"rag","source_id":"manual-01#p12","quote":"Bearing temperature above 75°C: replace per preventive schedule."},{"source_type":"vss","source_id":"clip-anomaly-01@00:42","quote":"RT-VLM caption: heat signature on bearing housing, vibration audible."}],"created_at":"2026-09-03T17:18:06.708307Z","updated_at":"2026-09-03T17:18:06.708307Z"}]
```

- `GET /api/v1/work-orders/{id}` → the same object (200).
- `curl -s http://localhost:8090/api/v1/notifications` →

```
[{"id":"68d30681-b449-489d-8706-b47fec19ada5","work_order_id":"3eca5d81-6172-4a9b-9a63-bd298563fdd9","channel":"in_app","message":"Work order WO-3eca5d81-6172-4a9b-9a63-bd298563fdd9 filed: Bearing replacement — M-3021 motor drive (priority high, equipment M-3021)","read_at":null}]
```

The actual run's title/description/priority follow the agent's diagnosis (the sample above is the spec's canonical example); the guide asserts the SHAPE (array, newest first, grouped citations, linked notification), not the exact prose. **Note for the body:** the agent's exact fields depend on its run — the guide names the signals (equipment M-3021, an anomaly_ref matching Module 3, citations present), not the exact title.
