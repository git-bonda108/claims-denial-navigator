# Denial Navigator: live demo runbook

**Length:** about 10 minutes, plus questions.
**Audience:** hospital revenue-cycle and finance leaders.
**All data is synthetic:** a fictional hospital (Prairie Ridge), with fictional payers and patients.

| Link | Use |
|---|---|
| https://ca-dn-sq5zvttffcgfu.agreeablewater-ff7c59b5.eastus2.azurecontainerapps.io | Live demo |
| https://ca-dn-sq5zvttffcgfu.agreeablewater-ff7c59b5.eastus2.azurecontainerapps.io/explainer | 74-second explainer, with play/pause and step buttons |
| https://ca-dn-sq5zvttffcgfu.agreeablewater-ff7c59b5.eastus2.azurecontainerapps.io/explainer.gif | GIF, for email or Teams |
| https://ca-dn-sq5zvttffcgfu.agreeablewater-ff7c59b5.eastus2.azurecontainerapps.io/explainer.mp4 | MP4, for the deck |

---

## A. 15 minutes before the meeting

1. **Reset the demo.** Open the live demo → **Clearinghouse inbox** → **Reset demo data** → OK. It takes about 10 seconds. The three live files (one 277CA, two 835s) then show a plain **Ingest** button, with no "Ingested ✓" badge.
   - If the app won't open at all, restart it from Azure Cloud Shell (Bash) instead, then wait 2 minutes:
     ```bash
     az containerapp revision restart -n ca-dn-sq5zvttffcgfu -g rg-denial-nav-demo --revision $(az containerapp show -n ca-dn-sq5zvttffcgfu -g rg-denial-nav-demo --query properties.latestRevisionName -o tsv) -o none && echo RESET
     ```
2. **Open two Chrome tabs:** the live demo, and `/explainer`. Use Chrome or Edge on your Mac so the deck fonts show. Press **Cmd + Shift + R** once in the demo tab.
3. **Check the starting state:**
   - The sidebar, bottom left, says **"AI: Azure OpenAI"** and **"Version …"**, matching the version printed by the last deploy. If there's no "Version" line, you're looking at an old cached page: press Cmd + Shift + R.
   - The Clearinghouse inbox has a **Reset demo data** button, and all three live files show a plain **Ingest** button.
   - The Dashboard shows **Resolved 0**.
   - Teams alerts says **"No alerts yet"**.
4. **Close everything else and turn on Do Not Disturb.** Set the browser zoom to 90–100%.

---

## B. The 10-minute flow

| # | Time | Click | Say | You should see |
|---|---|---|---|---|
| 1 | 1:15 | **Explainer** tab → Play (or jump with the step buttons) | "Here's the whole idea in one minute: one denied claim, from a question in Teams to an approved appeal." | The 7 steps: Ask, Secure, Check, Prioritise, Decide, Respond, Learn |
| 2 | 1:00 | Demo tab → **Dashboard** | "This is a 25-bed rural hospital: about 1,200 claims and an 18% denial rate. Over 3,000 routine adjustments were filtered out automatically, so the team sees only real denials." | Open denied dollars, at-risk ≤ 30 days, the urgency bar, root causes, payers, queues |
| 3 | 0:45 | **Clearinghouse inbox** → **Ingest** on `835_LIVE_SMM_…` (**click once**) | "A payer file just arrived. Nobody reads it; it's decided in seconds." | The button shows **Processing… 1s, 2s…**. Within about 5 seconds: "✓ 835 processed · 2 denials decided, 2 Teams alerts", the file gets an **Ingested ✓** badge, and it appears at the top of Recent files |
| 4 | 0:30 | **Dashboard** → Teams alerts card | "The right team gets a Teams alert: one for a high-value denial, one for a deadline in 5 days." | 💲 High-value denial (PRH-10222, $2,840) and ⏰ Deadline alert (PRH-10223) |
| 5 | 1:30 | Click **Open claim** on PRH-10222 (or Worklist → PRH-10222) | "Prior-auth denial, $2,840. It found the authorisation was on file but missing from the claim, so the answer is appeal, not write-off. It cites the payer policy and computes the deadline." | Appeal (level 1) → Utilization Review · cause names AUTH-… · policy citation · 60-day countdown |
| 6 | 0:45 | **Draft letter** → **Approve plan** | "The appeal letter is drafted with the claim and auth numbers. A person approves; nothing goes out on its own." | Letter in about 4 seconds · item moves to Resolved |
| 7 | 1:00 | **Clearinghouse inbox** → **Ingest** on `835_LIVE_MCR_…` (**click once**) → click **PRH-10224** in the result | (while it shows Processing…, about 5 s) "The AI is writing an explanation for each Medicare denial, all at once." Then: "Medical necessity on an echocardiogram. The billed diagnosis isn't on the coverage list, but a covered one is in the chart. So the fix is to correct and resubmit, not write it off." | Correct & resubmit → Coding · ✗ billed diagnosis not covered · ✓ covered diagnosis in chart · reopening deadline |
| 8 | 0:30 | Worklist → **PRH-10227** | "Missing provider ID. There are no appeal rights, so it says: add the NPI and send a new claim. That saves a wasted appeal." | Submit new claim → Billing |
| 9 | 0:45 | **Assistant** → "What is due this week?" → "Why was PRH-10222 denied?" → type "Write me a poem" | "Managers just ask. The same assistant works in Teams. And it stays on topic." | Due list including PRH-10223 · claim explanation · polite decline |
| 10 | 0:45 | Any open item → choose another action, type a reason, **Override** → **Proof & quality** | "People stay in control: an override becomes a precedent the system learns from. Every decision is scored against known answers, with zero unsafe actions." | Override saved · Proof shows decisions correct and **0 unsafe actions** |
| 11 | 0:30 | Back to the deck: data trust and next steps | "It runs in your Azure tenant, and your data never trains public AI. The next step is a pilot on your de-identified remittances." | |

**Tips**
- In step 3, ingest the **SMM** file first. It fires both alerts.
- Click **Ingest** once and watch the seconds counter. Other buttons are locked until the file finishes, so a double click can't load it twice.
- If you need to re-run a step, use **Reset demo data** rather than "Ingest again".

---

## C. Likely questions

| Question | Answer |
|---|---|
| Does our data train the AI? | No. It's processed in your Azure tenant, and Azure OpenAI doesn't use your prompts or data to train its systems. It learns your patterns only from your own resolved claims, inside your tenant. |
| How accurate is it? | Codes, edits and deadlines are decided by rules, so they're exact. In testing against known answers there were zero unsafe actions. The pilot measures accuracy on your real outcomes. |
| What does it cost to run? | Azure consumption for a hospital this size is about $250–500 a month, billed by Microsoft. The engagement cost is in the proposal, not in the app. |
| Does it need EHR integration? | Not to start. It reads the standard files the clearinghouse already produces: 277CA acknowledgements, 835 remittances and 837 claim copies. Read-only EHR exports (for example from Epic) come later, with the EHR owner's approval. Nothing is written back to the EHR. |
| Is sign-in supported? | Yes. Entra ID single sign-on is a switch; it's off for this demo only. |
| Is this real patient data? | No. Everything here is synthetic. |

---

## D. If something goes wrong

| Symptom | Fix |
|---|---|
| A sign-in page appears, or `401` | In Cloud Shell: `az containerapp auth update -n ca-dn-sq5zvttffcgfu -g rg-denial-nav-demo --enabled false -o none`, then reload in a private window |
| Blank page, or a 503 / "unavailable" page | It's restarting. Wait 1–2 minutes and reload. The page shows "Starting up…" and connects by itself. |
| Ingest shows a red "Could not process" message | Wait 5 seconds and click **Ingest** once more. The message gives the reason. |
| A file was ingested twice, or the numbers look off | Clearinghouse inbox → **Reset demo data**, then start the flow again |
| The page looks old or half-loaded | Hard refresh: **Cmd + Shift + R**, or open a private window |
| The sidebar says "AI: offline templates" | Everything still works with template explanations. Carry on, and check the Azure OpenAI deployment afterwards. |
| The app won't load at all | Play the explainer (`/explainer` or the MP4 in the deck) and walk through the test-case workbook screens |

---

## E. Test cases and validation

- **Workbook:** [`docs/Denial_Navigator_Test_Cases.xlsx`](./Denial_Navigator_Test_Cases.xlsx) holds 19 business test cases (TC-01 to TC-19) plus 60 browser checks. Every case lists how to test it in the web app, the expected result and the automated result. Yellow columns are for your own PASS/FAIL, name, date and notes.
- **To re-run against live Azure**, in Cloud Shell:
  ```bash
  cd ~/claims-denial-navigator/poc && python3 scripts/run_test_cases.py https://ca-dn-sq5zvttffcgfu.agreeablewater-ff7c59b5.eastus2.azurecontainerapps.io
  download Denial_Navigator_Test_Results.xlsx
  ```
  The script prints the exact path of the workbook. `download` sends the file to your browser's Downloads folder. The run starts and ends with a reset, so the app is clean afterwards.

---

## F. After the demo

- **Reset for the next one:** Clearinghouse inbox → **Reset demo data**.
- **Stop all costs once the demos are finished:** in the Azure portal, delete the resource group `rg-denial-nav-demo`.

---

## G. Partner demo (partner branding on)

With `PARTNER_NAME` set on the Container App (for example `PARTNER_NAME="Centered Networks"`), the sidebar names the partner. Two pages are worth showing after step 10 of section B:

| # | Time | Click | Say | You should see |
|---|---|---|---|---|
| 10a | 1:00 | **Agent card** | "Six things a production agent needs, live from the system: owner, authority, evaluation, identity, telemetry, runbook." | Six cards marked "In place"; AI calls and response time update after you ingest a file |
| 10b | 1:00 | **Reporting** → hover a month → change *Net patient revenue* | "This is what your Power BI report carries: denial trend, rate by payer, turnaround, recovery and the value side of ROI." | Steady ~18% monthly rate; turnaround in seconds; at the defaults, $758K a year in denial cost and $152K–$202K in annual value. There are no prices in the app: cost belongs in the proposal. |

Turn the branding off again with `az containerapp update -n ca-dn-sq5zvttffcgfu -g rg-denial-nav-demo --remove-env-vars PARTNER_NAME -o none`.

---

## H. Critical access hospital demo (Epic via Community Connect, Experian Health)

Set the context on the Container App once: `SITE_CONTEXT="25-bed critical access hospital · Epic (Community Connect) · Experian Health"` (the deploy block does this). The sidebar then shows it under the hospital name, and the inbox is labelled as Experian Health's file drop. Everything is still synthetic.

| # | Time | Click | Say | You should see |
|---|---|---|---|---|
| 1 | 0:45 | **Dashboard** | "A 25-bed critical access hospital. Experian Health is the clearinghouse; Epic is hosted through Community Connect. We read the clearinghouse files, so nothing changes in Epic." | Open denied dollars, urgency, root causes |
| 2 | 1:00 | **Clearinghouse inbox** → **Ingest** on `277CA_EXPERIAN_…` (**click once**) | "Experian's acknowledgement for yesterday's batch. Most claims were accepted. Three were rejected before they ever reached the payer, so they'll never show up on an 835." | "✓ 277CA processed · Experian Health · 3 payers: 8 claims acknowledged: 5 accepted, 3 rejected → 3 work items, 2 Teams alerts" |
| 3 | 1:15 | Click the **Summit Mutual** claim in the result (the one due in 6 days) | "An ER visit with 6 days left in a 90-day filing window. The member ID was keyed wrong at registration; the 271 has the right one. It's routed to Registration to correct and resubmit. There's nothing to appeal, so no appeal letter is offered." | 277CA A7:33:IL · Correct & resubmit → Registration · ✗ member ID mismatch · 6 days, Critical · no Draft letter button |
| 4 | 0:30 | The other two items | "An invalid rendering NPI goes to Billing; a diagnosis billed without its 5th character goes to Coding. That's a $2,840 CT, so the team gets a high-value alert." | A7:562:82 → Billing (fails the NPI check digit) · A7:255 → Coding (K57.9 billed, K57.92 in the chart) |
| 5 | 1:30 | **Ingest** `835_LIVE_SMM_…` → **PRH-10222** → **Draft letter** → **Approve plan** | "Then the payer denials arrive on the 835. A prior-auth denial where the auth was on file: appeal, with the letter drafted. A person approves." | As steps 3–6 of section B |
| 6 | 1:00 | **Reporting** | "Chris asked for Power BI on denial trends, turnaround, recovery and ROI. These are those measures, live. In the pilot Power BI reads them from Azure SQL; here you can download the same dataset." | Trend, rate by payer, root causes, turnaround (file → worklist in seconds; recommendation → decision in minutes), recovery, value side of ROI · **Download dataset (CSV)** |
| 7 | 0:30 | **Agent card** | "Owner, authority, evaluation, identity, telemetry and runbook, filled live from the system." | Six cards marked "In place" |

**Tips**
- Ingest the **277CA first**, then the 835s.
- Front-end rejections and payer denials are different work: rejections are corrected and resubmitted within timely filing; denials may be appealed. The worklist shows both, ranked together.
