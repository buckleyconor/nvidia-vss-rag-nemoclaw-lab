# HOL-1362-01 NVIDIA Service Blueprint: VSS + RAG + NemoClaw

ℹ️ You can resize or hide the lab guide anytime by sliding it left or right.

## Table of Contents

- [1. Introduction](#introduction)
- [2. Explore the Running Stack](#module-1-explore-the-running-stack)
- [3. Establish the Baseline](#module-2-establish-the-baseline)
- [4. Detect the Anomaly](#module-3-detect-the-anomaly)
- [5. Run the Agentic Diagnosis](#module-4-run-the-agentic-diagnosis)
- [6. Verify the Work Order](#module-5-verify-the-work-order)
- [7. Triage a Second Anomaly](#module-6-triage-a-second-anomaly)
- [8. Summary](#summary)

### Lab Credentials:

- Username/Password: SSH into the learner VM — the credentials and IP arrive with the instructor runbook (there are no local password files in this lab)
- Learner VM endpoints (all local to the VM — the stack is pre-provisioned and already running):
  - http://localhost:8080 — shared LLM endpoint (auth-shim)
  - http://localhost:8000 — VSS agent (UI + API)
  - http://127.0.0.1:38111 — LVS backend (video analysis)
  - http://127.0.0.1:8018 — RT-VLM (the local VLM)
  - http://localhost:8081 — RAG server (Enterprise RAG)
  - http://localhost:8090 — mock CMMS (API + UI)
  - http://localhost:18789 — OpenClaw UI (NemoClaw)
  - http://127.0.0.1:30081 — the local LLM NIM port; nothing should listen here. Its absence is an invariant the lab verifies in Module 1, not a service you use
  - Auth-shim token: any Bearer value works — the shim substitutes the real endpoint key for the shared endpoint. The guide's commands use `Bearer dummy`

### Target Audience

- AI/ML engineers evaluating agentic video pipelines for industrial use cases
- Solution architects and field technical specialists planning video-based predictive maintenance deployments

## Introduction

**Duration:** This guide is designed to be completed in approximately 100 minutes.

**Objective:** The objective of this guide is to run a video clip through a pre-provisioned video-surveillance pipeline, watch the pipeline raise an equipment alert, hand a single natural-language instruction to an AI agent, and verify the work order the agent files — then triage a second anomaly and watch the agent choose a monitoring note instead of another work order.

The problem this lab closes: when a video-surveillance system detects an anomaly on production equipment, the slow part is not the detection — it is what happens after. A human has to watch the clip, understand what happened, look up the equipment manual, check past logs, and decide whether to file a work order. This lab shows the agentic end of that loop: an AI agent that takes one instruction, pulls the alert's clip through the VSS pipeline, retrieves the relevant engineering documents from a RAG index, reasons over both, and files the result into a CMMS the way a dispatcher would.

By the end of this lab you will have:

- Oriented yourself on the running stack (auth-shim, VSS, RT-VLM, RAG, mock CMMS, NemoClaw) and the GPU co-residency it runs on
- Established a healthy baseline: normal-state clips processed, no alerts, nothing filed
- Detected an anomaly: the pipeline raised an alert on equipment M-3021
- Run the agentic diagnosis: one instruction, four human answers, then autonomy
- Verified the agent's work order through the CMMS's own API and notification feed
- Triage a second anomaly and confirm the agent can choose a note over a work order (optional module)

**Note:** The environment is pre-provisioned: every service is already running before this session starts, the RAG index is already built, and the video clips are already on disk. Nothing in this guide installs or starts a service — you operate the pipeline and the agent, and you verify through the systems' own APIs and UIs.

**Note:** Modules 2, 3, and 4 include a few minutes of watch time while the local VLM processes video — that is the whole cost of the video understanding in this architecture, and it is intentional. Module 6 is optional: stopping after Module 5 completes the core lab.

[Back to top](#table-of-contents)

## Module 1: Explore the Running Stack

This module is the orientation pass: ten quick checks around one question — is the whole lab alive, and where does each piece of it run? You verify each endpoint by name, check the GPU budget the architecture depends on, and confirm the one thing that must NOT be running.

1. Open a shell on the learner VM (SSH with the credentials from the instructor runbook). You should see a shell prompt on the learner VM — and note one piece of state now: the lab repo is checked out on this VM (the instructor runbook names the checkout directory). Every `scripts/…` command later in this guide runs from that checkout; the scripts resolve their own repo root, so the checkout location itself does not matter. Every command in this lab runs in this shell, against the local endpoints.

2. Verify the shared LLM endpoint through the auth-shim. The shim sits at `http://localhost:8080`, accepts the standard Bearer token, and translates it to the `x-api-key` header of the shared off-VM endpoint it proxies to — every LLM role in this lab (the VSS agent's LLM, RAG's generation model, and NemoClaw) flows through it:

	`curl -s http://localhost:8080/v1/models -H "Authorization: Bearer dummy"`

   You should see a JSON model list (an `object: list` with a `data` array). The exact list depends on the shared endpoint, but it must include `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`:

   ```
   {"object":"list","data":[{"id":"nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", ...}]}
   ```

   The id `nemotron-3-nano-omni-30b-a3b-reasoning` is the shared endpoint's model — not a local NIM. Remember that: it is the model NemoClaw runs on in Module 4.

3. Verify the VSS agent (the UI + API you work in for Modules 2 and 3):

	`curl -s http://localhost:8000/health`

   You should see a healthy response (200) from the VSS agent.

4. Verify the LVS backend — the video-analysis service that runs the pipeline over the clips and raises the alert in Module 3:

	`curl -s http://127.0.0.1:38111/v1/ready`

   You should see a 200 ready response.

5. Verify the RT-VLM — the local video language model that does the actual video understanding. It runs on this GPU at 40% of it, and it is the reason video processing takes a few minutes per clip:

	`curl -s http://127.0.0.1:8018/v1/health/ready`

   You should see a 200 ready response.

6. Verify the RAG server — Enterprise RAG over the engineering corpus (manuals, logs, schedules). Its retriever NIMs and the shared generation endpoint together produce the citations you will see in Module 5:

	`curl -s http://localhost:8081/v1/health`

   You should see a healthy response (200).

7. Verify the mock CMMS — the work-order system the agent files into. It is a local Python service on `http://localhost:8090` with a small UI:

	`curl -s http://localhost:8090/health`

   You should see exactly:

   ```
   {"status":"ok","db":"ok"}
   ```

8. Check the GPU residency budget. Seven models share this one GPU: the local VLM plus six retriever NIMs (embedding, ranking, page-elements, graphic-elements, table-structure, OCR). List the compute processes:

	`nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader`

   You should see exactly 7 rows. Then check the total footprint:

	`nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader`

   You should see roughly 70 GB used of about 97871 MiB total. These two numbers are the co-residency budget: if you ever see 8 or more compute processes, a local LLM NIM has started — the generation model is the shared endpoint, and it never runs locally.

9. Confirm that invariant directly — nothing should listen on the local LLM NIM port:

	`ss -ltn | grep :30081 || echo 'nothing on :30081 - as expected'`

   You should see:

   ```
   nothing on :30081 - as expected
   ```

10. Open the mock CMMS in the browser at `http://localhost:8090`. The work-order list is empty and the notification badge shows 0 — keep this in mind, because it is the surface Module 5 will fill:

   << INSERT SCREENSHOT: Mock CMMS work-order list at http://localhost:8090 — empty list, no unread badge (the baseline reveal surface) >>

11. Open the OpenClaw UI at `http://localhost:18789` (or the port recorded in the prep log) and confirm NemoClaw's model from the shell:

	`openclaw nemoclaw status --json | jq -r '.model // "unavailable"'`

   You should see:

   ```
   nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
   ```

   That is the shared endpoint's model through the auth-shim — the same id you saw in step 2, which is exactly right: NemoClaw uses the custom endpoint, not a local NIM.

   << INSERT SCREENSHOT: OpenClaw UI with the NemoClaw session ready (the beats 3-4 surface) >>

   > ✅ **Checkpoint:** Every endpoint probe (8080, 8000, 38111, 8018, 8081, 8090) returned 200; `nvidia-smi` shows 7 GPU compute processes with roughly 70 GB of 96 GB committed; nothing listens on `:30081`; the mock CMMS work-order list is empty and the notification feed has no entries; and NemoClaw reports the shared endpoint model `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`.

[Back to top](#table-of-contents)

## Module 2: Establish the Baseline

This module is the first watch: you play two normal-state clips through the pipeline and confirm the system does nothing when nothing is wrong. That "nothing" is load-bearing — it is the contrast that makes the alert in Module 3 mean something.

1. From the lab repo checkout on the VM (if your shell is not in the checkout directory, `cd` there first — the instructor runbook names its path), run the baseline helper. It verifies the VSS agent and LVS backend are healthy, confirms the two normal-state clips are in place at `/data/video`, and prints the procedure for playing them through the LVS UI. The helper exists so you do not have to remember which clips are the normal-state set — the fixture manifest is the source of truth:

	`bash scripts/demo/01-baseline.sh`

   You should see the preconditions pass, the staged clips, and the beat-1 procedure (this is the script's actual output):

   ```
   == preconditions ==
   VSS agent + LVS healthy

   == staging the normal-state clips at /data/video ==
   staged: clip-normal-01.mp4
   staged: clip-normal-02.mp4
   staged: 2 clip(s) at /data/video

   == beat 1 procedure (the learner does this in the UI) ==
   1. Open the LVS UI (LVS UI: <url> — recorded at prep); the stack is up and the work-order list at http://localhost:8090 is EMPTY (baseline).
   2. Play the staged normal-state clip(s) through VSS (the 2 clip(s) at /data/video).
   3. Watch: captioning + summarisation complete, the LVS UI shows a HEALTHY pipeline and NO alerts.

   expected observation (02 beat 1): pipeline running healthy, no alerts — the anomaly (beat 2) is what breaks that picture.
   01-baseline: ready — next: scripts/demo/02-anomaly.sh
   ```

   The one variable part is the LVS UI URL in the printed step 1 — the script reads it from `prep-log.md`, where it was recorded at prep. That line is where the LVS UI lives for the rest of the lab; Modules 2–3 refer to it as the LVS UI.

2. In the LVS UI (the URL the step-1 output printed), do what its printed procedure names — **play the staged normal-state clip(s) through VSS**: the first clip is ingested and processing starts — captioning and summarization, done by the local VLM.

   **Note:** The LVS UI's page and control labels are release-dependent; the printed procedure (step 1) and the prep-recorded URL are the instruction of record. If the on-screen labels differ from anything you expect, follow the recorded procedure.

3. Wait for processing to complete — a few minutes; the local VLM is the whole cost of the video run, and that is the architecture working as designed. When processing completes, the pipeline state is healthy:

   << INSERT SCREENSHOT: LVS UI showing the normal-state clip processed with a healthy pipeline status and no alerts >>

4. Play the second normal-state clip the same way. It processes to completion the same way: healthy, no alerts.

5. Confirm the baseline in both places that matter: the LVS UI shows no alerts, and the mock CMMS list at `http://localhost:8090` is still empty. Nothing was filed, because nothing was wrong:

   << INSERT SCREENSHOT: Mock CMMS list still empty after the baseline clips (the contrast the anomaly beat needs) >>

   > ✅ **Checkpoint:** Both normal-state clips processed to completion; the LVS UI shows a healthy pipeline state with no alerts; and the mock CMMS work-order list is still empty — nothing has filed anything yet.

[Back to top](#table-of-contents)

## Module 3: Detect the Anomaly

This module is the alert. Same pipeline, same UI, one different clip: this segment shows the motor bearing with abnormal thermal and vibration behaviour, and the pipeline notices it, identifies the equipment, and raises the alert.

1. From the lab repo checkout on the VM, run the anomaly helper. It verifies the preconditions, confirms the anomaly segment is staged at `/data/video`, and prints the procedure:

	`bash scripts/demo/02-anomaly.sh`

   You should see the preconditions pass and the anomaly segment named (this is the script's actual output):

   ```
   == preconditions ==
   VSS agent + LVS healthy

   == the anomaly segment ==
   anomaly segment: clip-anomaly-01.mp4 (equipment: M-3021)

   == beat 2 procedure (the learner does this in the UI) ==
   1. With the pipeline healthy from beat 1, play the anomaly segment (clip-anomaly-01.mp4 on M-3021).
   2. Watch the LVS UI: the alert logic FIRES — an alert is raised and the affected equipment is identified.

   expected observation (02 beat 2): alert raised, affected equipment identified.
   note for beat 3: the work order the agent files later cites THIS alert (anomaly_ref) — keep the alert's clip reference + timestamp on screen.
   02-anomaly: ready — next: scripts/demo/03-agent-kickoff.sh
   ```

2. In the LVS UI (same URL as Module 2), do what the printed procedure names — **play the anomaly segment** (`clip-anomaly-01.mp4` on `M-3021`). Processing starts as in Module 2 — the difference is in what the pipeline concludes. As in Module 2, the procedure and the prep-recorded URL are the instruction of record if on-screen labels differ.

3. **Watch** the LVS UI for the alert (a few minutes of VLM time again). The alert logic fires: an alert is raised, and the affected equipment is identified:

   << INSERT SCREENSHOT: LVS UI alert for the anomaly segment — the alert is raised and the affected equipment is identified as M-3021 >>

4. Read the alert and write down two values: the clip reference (for example `clip-anomaly-01`) and the anomaly timestamp (for example `@00:42`). Together they are the alert ref (for example `vss-alert-clip-anomaly-01-00:42`) — it becomes the `anomaly_ref` on the work order in Module 5, tying the whole chain back to this moment.

   **Why this matters:** an alert without an evidence trail is what the engineer on shift has to re-derive by hand — the slow half of the problem this lab closes. The ref you record now is cited on the work order in Module 5.

   > ✅ **Checkpoint:** The alert is raised for the anomaly segment and visible in the LVS UI; it identifies the affected equipment as M-3021; and you have recorded the alert's clip reference and timestamp — the values the Module 5 work order will cite as `anomaly_ref`.

[Back to top](#table-of-contents)

## Module 4: Run the Agentic Diagnosis

This is the heart of the lab. From this module until Module 5, the only human input is four prompt answers — after that, every step is the agent's work, shown on screen as it happens. You can point at the agent's visible tool calls and retrieved documents as the evidence.

1. From the lab repo checkout on the VM, run the agent-kickoff helper. It verifies that NemoClaw is on the custom endpoint with the Nano Omni model, prints the OpenClaw UI URL, and prints the one instruction you will paste. HITL is interactive, so the script prints and you type:

	`bash scripts/demo/03-agent-kickoff.sh`

   You should see the precondition pass, the UI URL, and the instruction to paste (this is the script's actual output):

   ```
   == preconditions ==
   NemoClaw sandbox: custom endpoint + Nano Omni model active

   == beats 3-4 procedure ==
   1. Open the OpenClaw UI:  http://localhost:18789 (dashboard port-forward default — the installer's recorded URL, if different, is in prep-log.md)
   2. Start a fresh session (/new) and paste EXACTLY this one instruction:

        I want to generate a video summary report for clip-anomaly-01.

   3. Answer the HITL prompts as they appear — the agent collects the
      four parameters: scenario, events of interest, objects to track,
      and the (optional) knowledge-retrieval query (02 beat 3; build doc 9.4).
   4. After that: nothing. The agent runs the vss-generate-video-report-rag
      skill — VSS analysis + RAG retrieval over the corpus with the frag
      tool — for ~90 s of visible tool calls, retrieved documents and
      reasoning (02 beat 3: the evidence is on screen, not just the answer).

   beat 4 (the aha): with no human step between the instruction and the
   result, the work order lands in the mock CMMS — open http://localhost:8090
   and watch the list go from empty to the new work order at the TOP, with
   its notification in the feed (http://localhost:8090/notifications).
   the detail page groups the citations by source (rag / vss / agent) —
   that is the diagnosis's evidence (02 beat 4).

   03-agent-kickoff: ready — the learner types the instruction in the OpenClaw UI
   ```

   The one variable part is the OpenClaw UI URL in printed step 1 — the installer records it at prep; when it is recorded, the line shows the recorded URL, otherwise the dashboard port-forward default on `18789`.

2. In the OpenClaw UI, start a fresh session (`/new`). An empty NemoClaw session is open.

3. Paste the printed instruction: `I want to generate a video summary report for clip-anomaly-01.` NemoClaw activates the `vss-generate-video-report-rag` skill and starts collecting parameters.

4. Answer the four HITL prompts as they appear. The suggested answers come from the Module 3 alert and the equipment context:

   - **Scenario:** industrial motor bearing inspection review
   - **Events of interest:** the thermal/vibration anomaly in the recorded clip
   - **Objects to track:** M-3021 bearing housing
   - **Knowledge-retrieval query:** bearing replacement criteria for M-3021

   << INSERT SCREENSHOT: OpenClaw UI — NemoClaw collecting the four HITL parameters (scenario, events of interest, objects to track, knowledge-retrieval query) >>

   **Note:** These four answers are the whole steering surface of the run — they determine which clip is analyzed, what the VLM looks for, and which corpus documents the agent retrieves. From the last answer onward, hands off.

5. Watch the agent work — roughly 90 seconds to 4 minutes of visible agent work. On screen you should be able to follow: the VSS analysis of the clip, the agent's tool calls including the `frag` knowledge-retrieval step against the RAG server (the `demo_corpus` collection), the retrieved documents, and the reasoning that ties them together:

   << INSERT SCREENSHOT: OpenClaw UI — the visible agent tool calls, including the frag knowledge-retrieval step against the RAG server >>

   << INSERT SCREENSHOT: OpenClaw UI — retrieved corpus documents (manual / log / schedule) inside the agent reasoning >>

   **Tip:** The retrieved documents are the frag path working: the agent asked the RAG server a question (your step-4 knowledge-retrieval query), and the answer came back as specific corpus passages — a manual section, a maintenance log entry, a schedule entry — not a generic summary.

6. Confirm the generated report: it cites RAG-sourced documents (manual / log / schedule) alongside the video content — the diagnosis is grounded in the retrieved corpus, not just the clip:

   << INSERT SCREENSHOT: The generated video summary report citing RAG-sourced documents >>

   > ✅ **Checkpoint:** The four HITL parameters were collected; the agent's tool calls, retrieved documents, and reasoning were visible in the OpenClaw UI; the video summary report was generated and cites RAG-sourced documents; and no human input occurred after the last HITL answer.

[Back to top](#table-of-contents)

## Module 5: Verify the Work Order

You have not opened the mock CMMS since Module 1. Open it now.

1. Open the mock CMMS at `http://localhost:8090`. The list that was empty in Modules 1–3 now has a work order at the top: a title (bearing replacement, M-3021), equipment `M-3021`, a priority, status `open`, and a creation timestamp. From the single instruction in Module 4, every step since — analysis, retrieval, reasoning, filing — was the agent's work. This is the aha: the agent did not just produce a report, it closed the loop into the system the maintenance team works from.

   << INSERT SCREENSHOT: Mock CMMS list with the new work order at the TOP (beat 4 — the list was empty in Modules 1-3) >>

2. Click the work order to open the detail page. It shows the diagnosis fields — description, equipment, `anomaly_ref`, priority — and the citations grouped by source: `rag`, `vss`, `agent`. The `anomaly_ref` matches the alert ref you recorded in Module 3 (same clip, same timestamp) — that is the evidence trail you deliberately preserved:

   << INSERT SCREENSHOT: Work-order detail page with the diagnosis fields and citations grouped by source (rag / vss / agent) — the evidence panel >>

3. Open the notification feed at `http://localhost:8090/notifications`. It holds the in-app notification for the work order, delivered atomically with the work order itself — the dispatcher who never watches the agent still gets pinged:

   << INSERT SCREENSHOT: Notification feed with the delivered in-app notification for the work order >>

4. Verify through the same API the agent used to file it. List the work orders:

	`curl -s http://localhost:8090/api/v1/work-orders`

   You should see a JSON array with the new work order first (newest first is the contract). The shape, from this lab's canonical example (your run's id and timestamps differ, and the agent's exact title and wording follow its diagnosis):

   ```
   [{"id":"3eca5d81-6172-4a9b-9a63-bd298563fdd9","title":"Bearing replacement — M-3021 motor drive","description":"Thermal anomaly on motor M-3021 detected at clip-anomaly-01@00:42. Manual-01 p.12: bearing temp above 75°C requires replacement per schedule. Recommend priority-high replacement within 48 h.","equipment":"M-3021","anomaly_ref":"vss-alert-clip-anomaly-01-00:42","priority":"high","assigned_to":"maintenance-team-b","status":"open","citations":[{"source_type":"rag","source_id":"manual-01#p12","quote":"Bearing temperature above 75°C: replace per preventive schedule."},{"source_type":"vss","source_id":"clip-anomaly-01@00:42","quote":"RT-VLM caption: heat signature on bearing housing, vibration audible."}],"created_at":"2026-09-03T17:18:06.708307Z","updated_at":"2026-09-03T17:18:06.708307Z"}]
   ```

   The signals to check, not the exact prose: `equipment` is `M-3021`, the `anomaly_ref` matches Module 3, and `citations` is non-empty with the source types grouped.

5. Verify the entity by id — without retyping the UUID, lift it from the list response:

	`curl -s http://localhost:8090/api/v1/work-orders/"$(curl -s http://localhost:8090/api/v1/work-orders | jq -r '.[0].id')"`

   You should get 200 with the same entity the detail page shows: same id, same fields, same citations, same timestamps. And the notification matches it too:

	`curl -s http://localhost:8090/api/v1/notifications`

   ```
   [{"id":"68d30681-b449-489d-8706-b47fec19ada5","work_order_id":"3eca5d81-6172-4a9b-9a63-bd298563fdd9","channel":"in_app","message":"Work order WO-3eca5d81-6172-4a9b-9a63-bd298563fdd9 filed: Bearing replacement — M-3021 motor drive (priority high, equipment M-3021)","read_at":null}]
   ```

   The notification's `work_order_id` is the work order's id, and its `channel` is `in_app` — the same entity the UI rendered.

   > ✅ **Checkpoint:** The new work order is at the top of the mock CMMS list with equipment `M-3021` and status `open`; the detail page shows citations grouped by source type and an `anomaly_ref` matching the Module 3 alert; the notification feed holds the matching `in_app` notification; and the API returns the same entity the UI shows.

[Back to top](#table-of-contents)

## Module 6: Triage a Second Anomaly

Optional module — stopping here after Module 5 completed the core lab. This module is the trust check: a pipeline that always files a work order is a noise machine. A useful one triages. Same pipeline, same instruction shape, a different engineering outcome.

1. Note the state you are contrasting against: the work-order list holds exactly one work order (Module 5), and the notes list is empty:

	`curl -s http://localhost:8090/api/v1/notes`

   You should see `[]` — no monitoring notes yet.

2. Determine which trigger path applies. The fixture manifest in the repo checkout (`fixtures/video/manifest.yaml`) names the anomaly clips: if a second curated anomaly clip (marked `role: anomaly`) is staged at `/data/video`, use path (a); otherwise use path (b).

3. Trigger the second anomaly of a different kind. Path (a): **play the second curated anomaly clip through the LVS UI** (the URL from Module 2). Path (b): replay the Module 3 anomaly segment and adjust the trigger in the HITL prompts — for example, scenario: *routine inspection review*, and knowledge-retrieval query: *vibration monitoring criteria for M-3021* — so the agent's verdict lands on the triage path. The exact parameter set that reproduces the note outcome is tuned during the lab's e2e dry run and recorded in the prep log; use the recorded values. Expected: the second anomaly segment is in the pipeline — VLM processing starts as in Module 3 (a few minutes of watch time), and the LVS UI shows the alert the agent's verdict will be built on.

4. In the OpenClaw UI (the NemoClaw session surface), start a fresh session (**"/new"** — the same kick-off as Module 4) and paste the same instruction shape (the one-instruction kick-off again). The skill activates and the four HITL prompts appear.

5. Answer the four HITL prompts as they appear in the OpenClaw UI (the same prompt flow as Module 4) with the adjusted parameters — then hands off. The agent works exactly as in Module 4: tool calls, retrieval, reasoning on screen. This time the verdict differs.

6. Verify in the mock CMMS. The notes list now holds the monitoring note — equipment, a description explaining why this anomaly is a note and not a work order, and an `anomaly_ref`:

	`curl -s http://localhost:8090/api/v1/notes`

   ```
   [{"id":"<uuid>","equipment":"M-3021","description":"<why this anomaly is a note, not a work order>","anomaly_ref":"<the second anomaly ref>","created_at":"<iso-8601>"}]
   ```

   And the work-order count is unchanged:

	`curl -s http://localhost:8090/api/v1/work-orders | jq 'length'`

   ```
   1
   ```

   The agent triaged — it did not script-follow. The same pipeline and the same instruction shape produced a different engineering outcome, because the inputs said a different thing:

   << INSERT SCREENSHOT: Mock CMMS monitoring note for the second anomaly (the note explains why this anomaly is a note, not a work order) >>

   << INSERT SCREENSHOT: Work-order list unchanged from Module 5 (still exactly one work order) >>

   > ✅ **Checkpoint:** The second agent run completed with its reasoning visible in the OpenClaw UI; a monitoring note appeared in the mock CMMS (equipment, a why-it-is-a-note description, and an `anomaly_ref`); and the work-order list is unchanged from Module 5 — no second work order was filed.

[Back to top](#table-of-contents)

## Summary

In this lab you ran a video-surveillance pipeline end to end and watched the agentic end of the maintenance loop close itself:

- **Baseline** — normal-state clips processed with no alerts and nothing filed: the pipeline is quiet when nothing is wrong.
- **Detection** — the LVS alert logic raised an alert on equipment M-3021 from the anomaly segment, with a clip reference and timestamp as the evidence trail.
- **Agentic diagnosis** — one instruction and four human answers; after that, the agent analyzed the clip, retrieved engineering documents from the RAG index, reasoned over both, and generated a cited report.
- **Closed loop** — the agent filed the work order into the CMMS (the list that was empty for three modules) and delivered the in-app notification, verifiable through the system's own API.
- **Triage** — in the optional Module 6, the agent chose a monitoring note on the second anomaly, and the work-order list stayed put.

The architecture decisions you saw working: one shared off-VM LLM endpoint (through the auth-shim) serving all three LLM roles so the GPU stays free for video understanding; seven models co-resident on one 96 GB GPU at about 70 GB; a local VLM doing the slow, valuable video work; and retrieval-grounded reasoning that turns an alert into a cited, filed, notified work order.

That is the pattern the service blueprint generalizes: detection is the cheap part; the agentic triage-and-file loop is what takes minutes of human attention per alert off the critical path.

[Back to top](#table-of-contents)
