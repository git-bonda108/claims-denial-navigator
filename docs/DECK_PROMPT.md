# Prompt: Denial Navigator partner deck

Paste everything inside the block below into Claude. Before you run it:
- Replace the four `#HEX` values in **Brand palette** with Alif's exact brand colours, or attach the Alif logo or brand guide and leave them as they are.
- Check the three statistics on slide 3 against their original sources before presenting.

```text
Build a 16:9 PowerPoint deck (.pptx) for a partner walk-through: "Denial Navigator — from denied claim to the right decision, in minutes." The presenter is from Alif Consulting and will talk the audience (hospital revenue-cycle and finance leaders) through it slide by slide. The deck must look premium, visual and confident: infographics over text.

WRITING RULES
- Business-professional, plain English. Short, concrete, active voice.
- Headline on every slide = the takeaway, not a topic label (e.g. "Most denials are recoverable, but only if worked in time").
- Max ~30 words of body text per slide. Bullets ≤ 8 words. No paragraphs.
- Use tables, icons, numbers and diagrams instead of sentences.
- No internal commentary, no references to other vendors' tools, no "we were asked to", no hedging. Speak to the audience's outcomes.
- Put 2–4 sentences of talking points in the SPEAKER NOTES of every slide (that is where detail goes).

TYPOGRAPHY (fonts are installed locally)
- Slide titles: Anthropic Serif Display (fallback: Montserrat SemiBold)
- Section dividers and big numbers: Anthropic Serif Web, bold
- Body, tables, labels: Anthropic Sans Text (fallback: DM Sans)
- Codes and data values (e.g. CO-197, $2,840): Anthropic Mono (fallback: DM Sans)
- Sizes: titles 32–36 pt, big-number infographics 54–72 pt, body 16–20 pt, tables 12–14 pt, footnotes 9 pt.

BRAND PALETTE (Alif Consulting): use the attached brand guide if provided, otherwise these
- Primary (titles, dark backgrounds): #HEX_PRIMARY
- Secondary (headers, key shapes): #HEX_SECONDARY
- Accent 1 (highlights, call-outs): #HEX_ACCENT1
- Accent 2 (charts, icons): #HEX_ACCENT2
Add a semantic colour layer on top of the brand colours and use it consistently, so the colour itself tells the story:
- Revenue lost / pain: coral red #E4572E
- At risk / deadline: amber #F2A541
- Recovered / success: green #2E9E6A
- Solution / AI: the brand accent
- Neutrals: charcoal #1F2933, slate #52606D, light grey #F3F4F6, white
Make it stand out: full-bleed coloured section dividers, a coloured top band or left accent bar on content slides, coloured icon chips, big coloured numbers, gradient-free flat design, generous white space. Alternate light content slides with 3–4 bold dark or brand-coloured slides for rhythm. Keep every chart and table on-palette.

SLIDES (24)
1. Title — "Denial Navigator", subtitle "From denied claim to the right decision, in minutes". Presenter name, date, Alif logo placeholder. Dark brand background.
2. Agenda — 6 numbered coloured chips: The challenge · The solution · How it works · Proof · Investment · Live demo.
3. The denial challenge — three big-number infographic tiles (coral): "$19.7B spent by U.S. hospitals fighting denials (2022)" [Premier Inc., 2024]; "~18% rural vs ~10% urban claim denial rates" [Microsoft Cloud blog, Oct 2025]; "~$330K a year for a small hospital to manage denials" [Microsoft Cloud blog, Oct 2025]. Footnote the sources.
4. Why it hurts more for community and rural hospitals — 6-icon grid: Small billing teams · High staff turnover · Complex, changing payer rules · Missed appeal deadlines · No prioritisation · Cash-flow pressure.
5. The life of a denial today — horizontal process with red pain markers: Remittance arrives → Codes looked up manually → Research payer rules → Decide fix vs appeal → Draft letter → Track deadline. Call-outs: "hours per claim", "knowledge lives in people's heads", "deadlines missed silently".
6. Where denials come from — donut chart (demo dataset mix): Eligibility/registration 25% · Missing info/coding 20% · Prior authorisation 15% · Medical necessity 15% · Bundling 10% · Timely filing 5% · Duplicates 5% · Other 5%. Note "Illustrative mix used in demo dataset". Insight call-out: "Most root causes are preventable or correctable."
7. What good looks like — 4 outcome KPI tiles (green): Every denial triaged same day · Right action first time · Zero missed deadlines · Highest-value claims worked first.
8. Section divider (brand colour): "The solution".
9. Introducing Denial Navigator — one-line value statement plus 4 pillars with icons: Understand (plain-English cause) · Decide (the right next action) · Prioritise (dollars × deadline) · Act (letters, tasks, alerts).
10. How it decides — 4-layer stacked infographic, each layer a different colour: Rules decide what is knowable (codes, edits, deadlines) → Machine learning ranks by recoverable value → AI agent explains, cites policy and drafts appeals → People approve, and every decision teaches the system. Side label: "AI never acts alone."
11. Step-by-step workflow — 8-step numbered chevron flow, colour progressing from coral (problem) to green (resolved): 1 Remittance (835) received · 2 Parsed and matched to claim · 3 Routine adjustments filtered out · 4 Rules check codes, edits, coverage, deadlines · 5 ML scores recovery and urgency · 6 AI explains and drafts · 7 Routed to the right team, with a Teams alert · 8 Approved, resubmitted or appealed; outcome learned.
12. Every denial gets a clear decision — the closed action set as coloured tags: Correct & resubmit · Submit new claim · Appeal · Obtain retro-auth · Bill other payer · Bill patient · Route to credentialing · Write off · No action. Caption: "One action, one owner, one deadline."
13. Anatomy of a decision card — a mock UI card for "Claim PRH-10877 · CO-197 · $2,840" with numbered call-outs: Root cause · Recommended action · Steps · Documents needed · Deadline countdown (amber) · Policy citations · Confidence · Approve / Override buttons.
14. Smart worklist — a scatter or bubble infographic: x = days to deadline, y = expected recovery $, bubble colour = urgency (coral / amber / green). Caption: "Work the right claim first, not the oldest."
15. Works where your team works — two panels: Web app (worklist, claim view, appeal studio, dashboard) and Microsoft Teams (proactive alerts for high-value or near-deadline denials; ask "What are my top 10 by dollars?").
16. Before vs after — two-column table: Research per denial: manual → seconds · Deadline tracking: spreadsheets → automatic · Appeal letter: from scratch → drafted with citations · Prioritisation: first in, first out → dollars × urgency · New-staff ramp-up: months → guided from day one. Use coral for "before" and green for "after".
17. Why this approach — comparison table with ✓ / ✗ / ◐ icons. Columns: Chatbot only · Fine-tuned model only · Denial Navigator (rules + ML + grounded AI). Rows: Accurate on codes and deadlines · Explains with citations · Keeps up with rule changes · Measurable accuracy · Low running cost · Human approval built in. Denial Navigator column highlighted.
18. Secure by design, on Microsoft Azure — simple architecture diagram with 5 coloured blocks: Ingest (835/837) → Decision engine (rules + ML) → AI agent (Azure AI Foundry + Azure AI Search) → Secure data store → Web app and Teams. Badges: Runs in your Azure tenant · Entra ID single sign-on · Managed identities, no shared keys · Full audit trail · No patient data used for model training.
19. Section divider: "Proof".
20. Demo dataset — infographic of the numbers in large type: 300 synthetic patients · 1,200 claims · 6 months · 5 payers · 18% denial rate · 23 denial scenarios. Small source table: Synthetic patients (Synthea-style) · Code sets (CARC/RARC, ICD-10, HCPCS) · Coding edits (CMS NCCI/MUE structure) · Coverage rules (CMS LCD/NCD structure) · Policy library (CMS manuals, payer policies). Badge: "100% synthetic — no real patient data."
21. Tested against known answers — table of 8 example scenarios with columns Denial code · Situation · Expected decision: CO-16 + MA130 | Missing provider ID | Submit new claim · CO-197 | Auth on file, not on claim | Appeal with auth · CO-50 + N115 | Diagnosis not on coverage list | Correct & resubmit · PR-50 (GA) | Signed ABN on file | Bill patient · CO-29 | Proof of timely filing | Appeal · CO-97 + M15 | Separate site documented | Add modifier, resubmit · CO-22 | Other insurance primary | Bill primary, then secondary · CO-45 | Contract adjustment | No action. Plus 4 coloured target gauges: Decision accuracy ≥ 90% · Deadline accuracy 100% · Unsafe actions 0 · Answers grounded in policy ≥ 4/5.
22. Investment — cost matrix table (clean, brand-coloured header row, total rows bold, per-user row highlighted in accent):
   | | Small (1 critical-access hospital) | Mid-size (hospital + clinics) | Network (multi-site) |
   | Billing users | 5 | 15 | 50 |
   | Claims / month | 2,000 | 10,000 | 50,000 |
   | Denied claims / month (~18%) | 360 | 1,800 | 9,000 |
   | AI model usage | $25 | $85 | $400 |
   | Search & knowledge base | $75 | $245 | $490 |
   | Database & storage | $45 | $130 | $370 |
   | App hosting & integration | $35 | $85 | $210 |
   | Monitoring & security | $20 | $45 | $200 |
   | Azure run cost / month | ~$200 | ~$590 | ~$1,670 |
   | Per user / month | ~$40 | ~$39 | ~$33 |
   | Per denied claim | ~$0.56 | ~$0.33 | ~$0.19 |
   Footnote: "Indicative Azure pay-as-you-go list prices (USD), excluding taxes, implementation services and existing Microsoft 365 / Teams licences. Optional: Microsoft 365 Copilot ($30/user/month) only if users want the agent inside Copilot chat." Call-out tile (green): "Recovering a single $200 denial a month covers a small hospital's entire run cost."
23. Roadmap — 3-phase timeline with coloured milestones: Proof of concept (2–3 weeks, synthetic data, live demo) → Pilot (8–10 weeks, your de-identified remittances, accuracy measured on real outcomes) → Scale (clearinghouse and EHR integration, denial prevention before submission, multi-site rollout). Under it, "What we need from you": an executive sponsor · a revenue-cycle lead · sample remittances under BAA · Azure subscription access.
24. Live demo — full-bleed brand-colour divider: "Let's see it work." Subtitle: "Upload a remittance → watch decisions appear → approve an appeal → get the Teams alert."

DESIGN QA BEFORE YOU FINISH
- No slide has more than ~30 words of visible body text; detail is in the speaker notes.
- Every chart, table and icon uses the palette; semantic colours are used consistently (coral = loss, amber = risk, green = recovered).
- Fonts are applied as specified on every text box; numbers and codes use the mono font.
- Tables are readable from the back of the room (≥ 12 pt), with no overflow or clipped text.
- Slide numbers bottom-right, a small Alif logo placeholder bottom-left on content slides, and footnoted sources on slides 3 and 22.
```

**Fonts:** the Anthropic fonts are installed only on your Mac. If the .pptx goes to the partner, either export a PDF, or let the fallbacks (Montserrat / DM Sans) apply on their machine.
