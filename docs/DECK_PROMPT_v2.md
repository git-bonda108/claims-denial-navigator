# Prompt: revise the Denial Navigator partner deck (v2)

Attach the current deck (`Claims_denail_navigator.pptx`) in Claude, then paste everything inside the block below.

```text
Revise the attached deck "Denial Navigator". Keep the existing design system exactly: layouts, colours, fonts (Anthropic Serif Display titles, Anthropic Sans Text body, Anthropic Mono for codes and numbers), icon style, slide numbering, footers, speaker-note style. Edit in place; do not rebuild the deck. Return the revised .pptx.

GOAL OF THIS REVISION
Hospital leaders often assume their claims data will be used to train someone else's AI. The deck must remove that doubt: their data stays in their Azure tenant, is used only to understand their own denial patterns and prioritise their own work, and is never used to train public or frontier AI. Governance must read as built in, not bolted on.

1. REMOVE "MODEL" LANGUAGE EVERYWHERE (slides AND speaker notes)
Do not use these words anywhere: model, models, ML, machine learning, fine-tuned, fine-tuning, LLM, GPT, training (as in training AI). Replace consistently:
- "Machine learning" / "ML" → "Prioritisation"
- "ML scores recovery and urgency" → "Prioritisation scores recovery and urgency"
- "Rules + ML + grounded AI" → "Rules + prioritisation + grounded AI"
- "Fine-tuned model only" (slide 17 column) → "Custom-trained AI only"
- "AI model usage" (slide 22 cost row) → "AI usage"
- "No patient data used for model training" → "Your data never trains public AI"
- Ranking described as "learns from your own outcomes, inside your tenant"
"Azure AI Foundry" and "Azure AI Search" are product names and stay as they are. Staff training sessions ("training deck") are fine.
After editing, search all slide text and notes for the banned words and fix any that remain.

2. NEW SLIDE — insert directly after slide 18 ("Secure by design…")
Title: "Your data stays yours: it sharpens your decisions, never public AI"
Layout: a two-column Myth vs Fact table, 4 rows. Myth column in coral (#E4572E) with a ✗ chip; Fact column in green (#2E9E6A) with a ✓ chip. A small shield icon in the title area. Keep visible text within ~45 words.
| Myth | Fact |
| "Our claims data trains the AI" | Never. Your data is not used to train public or frontier AI |
| "Data leaves our organisation" | It is processed and stored in your Azure tenant and chosen region |
| "It learns from every hospital" | It learns patterns only from your own outcomes, only for you |
| "Once in, we lose control of it" | You own it: retention, export and deletion on your terms |
Bottom strip (brand accent, one line): "Patterns, not training: your outcomes tune your priorities, inside your walls."
Speaker notes (3–4 sentences): Microsoft commits that prompts and responses sent to Azure OpenAI are not available to other customers or to OpenAI, and are not used to train or improve its AI. Denial Navigator learns which of your denials are most recoverable from your own resolved cases, and that learning lives in your tenant and can be deleted with your data. For regulated workloads, the hospital can apply to Microsoft for modified abuse monitoring so prompts are not retained for review. The proof of concept uses only synthetic data; the pilot uses de-identified remittances under a BAA.

3. REWORK SLIDE 18 INTO THE GOVERNANCE SLIDE
New title: "Governed by design, inside your own Azure tenant"
Keep the 5-block architecture strip (Ingest → Decision engine (Rules + prioritisation) → AI agent (Azure AI Foundry + Azure AI Search) → Secure data store → Web app and Teams). Replace the five badges below it with a 2×4 grid of control tiles, each an icon chip plus a 2–5 word label and a one-line detail in small text:
- Identity: Entra ID single sign-on — MFA and Conditional Access
- Zero standing privilege: least-privilege roles — users see only their team's queue; admin rights just-in-time (Privileged Identity Management)
- No shared secrets: managed identities — no API keys; Key Vault for anything else
- Private by default: private endpoints — no public exposure of data or AI services
- Encrypted: in transit and at rest — customer-managed keys optional
- Audited: every decision logged — who approved what, when; Azure Monitor and Microsoft Purview
- Policy-enforced: Azure Policy and Defender for Cloud — guardrails on every resource
- People decide: human approval — no appeal, write-off or resubmission without sign-off
Speaker notes: explain that these are standard Azure controls the hospital's IT team already knows; the POC runs on synthetic data, and private networking, customer-managed keys and Purview are switched on for the pilot. Mention HIPAA: Azure services used are covered by Microsoft's HIPAA Business Associate Agreement; the hospital confirms scope in its own Microsoft agreement.

4. FIXES FROM REVIEW
- Slide 14 (worklist bubble chart): today every point is green and >35 days out, which contradicts "Work first". Add 4–5 coral bubbles (≤15 days, $1,800–$4,000), 3–4 amber (16–35 days), keep 4–5 green (>35 days, lower $). Make them true bubbles sized by dollars. Top-left must hold the coral bubbles.
- Slide 3: "~$330K" breaks across two lines and overflows the tile. Fit it on one line (reduce to fit, same size as the other two stats).
- Slide 7: "Day 0" wraps and overflows. Replace with "Same day" at a size that fits on one line; keep the other three tiles matching.
- Slide 13: policy citations line → "Payer auth policy §4.2" only (remove the CMS manual reference).
- Add the missing final slide: full-bleed brand-colour divider, title "Let's see it work.", subtitle "Upload a remittance → watch decisions appear → approve an appeal → get the Teams alert." The agenda already promises it.
- Update the agenda only if needed so numbering still matches; renumber slide numbers.
- Leave presenter name, date and logo placeholders as they are (filled in later).

DESIGN QA BEFORE RETURNING
- No banned word (model, ML, machine learning, fine-tuned, LLM, GPT) in any slide text or speaker note — list any you could not remove.
- New and edited slides match the existing layouts, fonts, colours and title position exactly.
- No text overflows or numbers break across lines; tables ≥ 12 pt.
- Total slide count and slide numbers are consistent with the agenda.
- Return a one-line change log per edited slide.
```

**Before presenting, check:** the Microsoft data-privacy wording for Azure OpenAI (*"Data, privacy, and security for Azure OpenAI Service"* on Microsoft Learn), and the BAA scope in the hospital's Microsoft agreement.
