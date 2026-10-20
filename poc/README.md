# Denial Navigator: working POC

A working, end-to-end demo of the design in [`../docs/POC_PLAN.md`](../docs/POC_PLAN.md). Remittances (835) are parsed deterministically and matched to claims (837). Each denial is then decided by rules, ranked by ML, explained by the AI agent and routed to the right team, with Teams alerts, appeal letters and an accuracy report.

**All data is synthetic.** Prairie Ridge Community Hospital, its payers, patients and NPIs are fictional, and payer policies marked *FICTIONAL* were written for this demo.

## Run it locally (2 minutes)

```bash
cd poc
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn denialnav.api:app --port 8000          # first start generates the dataset (~5 s)
# open http://localhost:8000
```

Optional: switch on the AI model by pointing at an Azure OpenAI / Microsoft Foundry deployment before starting.

```bash
az login                                       # keyless: uses your Entra ID
export AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
export AZURE_OPENAI_DEPLOYMENT=gpt-4.1-mini
export TEAMS_WEBHOOK_URL=<optional Teams Workflows webhook URL>
```

Without these settings, the app runs in **offline mode**. It uses deterministic templates for explanations, letters and chat, and labels that output `rules-template` / `rules-router` in the UI.

| Command | What it does |
|---|---|
| `python -m denialnav.datafactory --out data/synthetic` | Regenerates the dataset (1,200 claims, ~18% denials, 23 scenarios, ground-truth labels) |
| `python -m denialnav.evals` | Scores decisions against ground truth and writes `data/eval_report.md` |
| `python -m denialnav.evals --llm-only --n 80` | AI-only baseline vs. hybrid (needs the Azure model) |
| `pytest -q tests` | 28 tests: X12, rules, deadlines, service, agent guardrails, API, access scoping |

## Demo script (8–10 min)

1. **Dashboard**: open denied dollars, at-risk dollars, deadline urgency bar, root causes, payers and queues.
2. **Remittance inbox**: click **Ingest** on `835_LIVE_SMM_…`. Two denials are decided in under a second, and two **Teams alerts** fire: a $2,840 CT prior-auth denial and a correction due in 5 days.
3. **Claim PRH-10222** (CO-197): checks show the auth was on file, so the decision is to appeal. Click **Draft letter**: the letter cites the payer policy.
4. Ingest `835_LIVE_MCR_…` and open the **CO-50 / N115 echo**. The LCD check fails on the billed diagnosis, and a covered diagnosis is found in the chart, so the decision is to correct and resubmit (reopening), with the deadline computed.
5. **Override** any item with a reason. It becomes a precedent card that future explanations cite.
6. **Assistant**: try *Top 10 by dollars*, *What is due this week?*, and *Why was PRH-10224 denied?*
7. **Proof & quality**: accuracy by scenario, zero unsafe actions, the model card, and the guardrails.

## What is real and what is simulated

| Area | Status |
|---|---|
| X12 835 / 837P parsing and writing | Real, deterministic, with balancing checks. Not a full implementation-guide validator. |
| Rules, deadlines, noise filter | Real logic. Medicare windows follow CMS rules; other payers come from config in `reference/payers.yaml`. |
| Code sets | CARC/RARC: full list (1,485 codes, MIT-licensed from the RHAIL reference). ICD-10 / HCPCS: demo subsets with our own short descriptions. |
| NCCI / MUE / LCD | **Illustrative subsets** in CMS file format. Replace them with the quarterly CMS files and the Medicare Coverage Database for a pilot. |
| ML prioritization | Real model (gradient boosting), trained on **synthetic** outcome history. Retrain on real outcomes in a pilot. |
| AI agent | Real Azure OpenAI calls (structured output, tool calling, keyless auth) when configured; deterministic templates otherwise. |
| EHR facts (auth on file, ABN, chart diagnoses…) | Mock EHR (`ehr_context.json`), standing in for EHR/clearinghouse integration. |
| Knowledge retrieval | Local tag and keyword search over `reference/knowledge.yaml`. The Azure AI Search adapter is the next step. |
| Storage | SQLite (single replica). Azure SQL for a pilot. |
| Teams | Adaptive Card alerts through a Workflows webhook, plus a Teams app (tabs) in `teams/`. Publishing the Foundry agent to Teams is the next step. |

## Deploy to Azure (`azd`)

Prerequisites: [Azure Developer CLI](https://aka.ms/azd) and a subscription with Azure OpenAI quota for `gpt-4.1-mini` (GlobalStandard) in your region.

```bash
cd poc
azd auth login                 # sign in with the account that owns the subscription
azd env new denial-nav-demo
azd env set AZURE_LOCATION eastus2
azd env set TEAMS_WEBHOOK_URL "<optional>"
azd up                         # provisions infra/, builds the image in Azure and deploys (~10 min)
```

This creates a resource group with Container Apps (1 replica), Container Registry, Azure OpenAI with a model deployment (API keys disabled), a user-assigned managed identity with *Cognitive Services OpenAI User* and *AcrPull* roles, and Log Analytics. No secrets are stored in the app. To restrict access to your tenant, enable built-in authentication (Microsoft Entra ID) on the Container App.

**Teams:** add a *Workflows → "When a Teams webhook request is received" → post card in channel* flow, and set its URL as `TEAMS_WEBHOOK_URL`. Then run `python teams/package.py <app url>` and upload the zip in Teams (*Apps → Manage your apps → Upload an app*).

## Layout

```
denialnav/
  x12.py          835/837P reader + writer
  datafactory.py  synthetic world + denial injector + labels
  rules.py        Layer 1: decisions, checks, deadlines
  ml.py           Layer 2: recovery-probability model + ranking
  knowledge.py    policy retrieval
  agent.py        Layer 3: explanations, letters, chat (Azure OpenAI or offline)
  service.py      pipeline, worklist, feedback -> precedents, evaluation
  api.py          FastAPI + static web app
  teams.py        Adaptive Card alerts
  reference/      code sets, payers, edits, coverage, knowledge cards
web/              single-page app (no build step)
infra/            Bicep for azd
teams/            Teams app manifest + packager
tests/            pytest suite
```
