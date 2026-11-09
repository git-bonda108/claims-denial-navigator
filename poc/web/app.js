/* Denial Navigator web client - plain JS, no build step. */
const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (v) => "$" + Number(v || 0).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
const money2 = (v) => "$" + Number(v || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const title = (s) => String(s || "").replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\*(.+?)\*/g, "<i>$1</i>").replace(/_(Source:.+?)_/g, "<i>$1</i>");
let META = { actions: {}, queues: [], payers: {} };
let lastView = "dashboard";

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}, ...opts });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
function toast(msg, ms = 2600) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), ms); }
/* Run a slow action behind a button: disable it, show progress with elapsed seconds, report errors. */
async function busy(btn, label, fn) {
  if (btn && btn.disabled) return;
  const orig = btn ? btn.innerHTML : "", t0 = Date.now();
  const tick = () => { if (btn) btn.innerHTML = `<span class="spin"></span>${esc(label)} ${Math.round((Date.now() - t0) / 1000)}s`; };
  if (btn) { btn.disabled = true; btn.classList.add("busy"); tick(); }
  const timer = setInterval(tick, 1000);
  try { return await fn(); }
  catch (e) { toast("Something went wrong: " + e.message + ". Please try again.", 6000); throw e; }
  finally { clearInterval(timer); if (btn && btn.isConnected) { btn.disabled = false; btn.classList.remove("busy"); btn.innerHTML = orig; } }
}
window.addEventListener("unhandledrejection", (e) => { console.error(e.reason); e.preventDefault(); });
const actionBadge = (a) => `<span class="badge act-${esc(a)}">${esc(META.actions[a] || a)}</span>`;
const bandBadge = (b, days) => b ? `<span class="badge band-${esc(b)}">${b === "EXPIRED" ? "Expired" : esc(days) + "d"} · ${title(b)}</span>` : `<span class="muted">—</span>`;
const codeLabel = (d) => d.group === "277CA" ? `277CA ${d.carc}` : `${d.group}-${d.carc}`;
const BAND_COLORS = { EXPIRED: "#7b8794", CRITICAL: "#e4572e", HIGH: "#f2a541", MEDIUM: "#f6c97a", LOW: "#2e9e6a", NONE: "#c3ccd5" };

/* ------------------------------------------------------------ routing */
function route() {
  const h = location.hash.slice(1) || "dashboard";
  const [view, arg] = h.split("/");
  if (view === "claim") { openClaim(arg); return; }
  lastView = view;
  $("#drawer").classList.remove("open");
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  ({ dashboard, worklist, assistant, inbox, proof, agent, reporting }[view] || dashboard)(arg);
}
window.addEventListener("hashchange", route);

/* ------------------------------------------------------------ dashboard */
async function dashboard() {
  const el = $("#view-dashboard");
  const s = await api("/api/summary");
  const bands = ["EXPIRED", "CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"];
  const totalBand = bands.reduce((a, b) => a + (s.by_band[b] || 0), 0) || 1;
  const bars = (obj, color) => {
    const max = Math.max(...Object.values(obj), 1);
    return Object.entries(obj).map(([k, v]) => `<div class="bar-row"><div>${esc(k)}</div><div class="bar"><span style="width:${(100 * v) / max}%;background:${color}"></span></div><div class="num">${money(v)}</div></div>`).join("");
  };
  el.innerHTML = `
    <div class="kicker">Overview</div><h1>Denials at a glance</h1>
    <p class="sub">As of ${esc(s.as_of)} · ${s.claims.toLocaleString()} claims with a remittance or rejection · ${(s.denial_rate * 100).toFixed(1)}% denial rate</p>
    <div class="grid kpis">
      <div class="card kpi loss"><div class="label">Open denied dollars</div><div class="value">${money(s.denied_amount)}</div><div class="muted small">${s.open_items} open items</div></div>
      <div class="card kpi risk"><div class="label">At risk ≤ 30 days</div><div class="value">${money(s.at_risk_30d)}</div><div class="muted small">${s.by_band.CRITICAL || 0} critical · ${s.by_band.HIGH || 0} high</div></div>
      <div class="card kpi win"><div class="label">Expected recovery</div><div class="value">${money(s.expected_recovery)}</div><div class="muted small">ML-weighted (synthetic history)</div></div>
      <div class="card kpi"><div class="label">Noise filtered</div><div class="value">${s.noise_filtered.toLocaleString()}</div><div class="muted small">routine adjustments, no work created</div></div>
      <div class="card kpi"><div class="label">Resolved</div><div class="value">${s.completed}</div><div class="muted small">approved or overridden</div></div>
    </div>
    <div class="card" style="margin-bottom:16px">
      <h2>Deadline urgency (open items)</h2>
      <div class="stack">${bands.filter((b) => s.by_band[b]).map((b) => `<div style="flex:${s.by_band[b]};background:${BAND_COLORS[b]}" title="${b}">${s.by_band[b]}</div>`).join("")}</div>
      <div class="legend">${bands.map((b) => `<span><span class="dot" style="background:${BAND_COLORS[b]}"></span>${b === "NONE" ? "No deadline" : title(b)} (${s.by_band[b] || 0})</span>`).join("")}</div>
      <div class="actions"><a href="#worklist/CRITICAL"><button class="warn">Work critical items</button></a></div>
    </div>
    <div class="grid two">
      <div class="card"><h2>Denied dollars by root cause</h2>${bars(s.by_category, "var(--loss)")}</div>
      <div class="card"><h2>Denied dollars by payer</h2>${bars(s.by_payer, "var(--brand-secondary)")}</div>
      <div class="card"><h2>Items by team queue</h2>${Object.entries(s.by_queue).sort((a, b) => b[1] - a[1]).map(([q, n]) => `<div class="bar-row"><div>${title(q)}</div><div class="bar"><span style="width:${(100 * n) / Math.max(...Object.values(s.by_queue))}%;background:var(--brand-accent)"></span></div><div class="num">${n}</div></div>`).join("")}</div>
      <div class="card"><h2>Teams alerts</h2>${s.alerts.length ? s.alerts.map(alertHtml).join("") : `<p class="muted">No alerts yet. Ingest a live remittance from the inbox to trigger one.</p>`}</div>
    </div>`;
}
function alertHtml(a) {
  const c = a.card; const facts = (c.body.find((b) => b.type === "FactSet") || { facts: [] }).facts;
  const urgent = c.body[0].text.includes("Deadline");
  return `<div class="alert-card ${urgent ? "" : "warn"}"><b>${esc(c.body[0].text)}</b> ${a.delivered ? '<span class="chip">sent to Teams</span>' : '<span class="chip">preview · set TEAMS_WEBHOOK_URL to send</span>'}
    <div>${esc(c.body[1].text)}</div><div class="muted small">${facts.map((f) => `${esc(f.title)}: ${esc(f.value)}`).join(" · ")}</div>
    <div class="small"><a href="#claim/${esc(facts[0]?.value.split(" ")[0])}">Open claim →</a></div></div>`;
}

/* ------------------------------------------------------------ worklist */
async function worklist(band) {
  const el = $("#view-worklist");
  if (!el.dataset.ready) {
    el.innerHTML = `<div class="kicker">Work queue</div><h1>Worklist</h1><p class="sub">Ranked by expected recovery × deadline urgency. Routine adjustments are already filtered out.</p>
      <div class="filters">
        <select id="f-queue"><option value="">All queues</option>${META.queues.map((q) => `<option value="${q}">${title(q)}</option>`).join("")}</select>
        <select id="f-band"><option value="">All urgency</option>${["CRITICAL", "HIGH", "MEDIUM", "LOW", "EXPIRED"].map((b) => `<option value="${b}">${title(b)}</option>`).join("")}</select>
        <select id="f-action"><option value="">All actions</option>${Object.entries(META.actions).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select>
        <select id="f-payer"><option value="">All payers</option>${Object.entries(META.payers).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select>
        <select id="f-status"><option value="OPEN">Open</option><option value="DONE">Resolved</option><option value="">All</option></select>
        <span id="wl-count" class="muted" style="align-self:center"></span>
      </div><div class="card table-wrap" style="padding:0"><table><thead><tr><th>Score</th><th>Claim</th><th>Patient</th><th>Payer</th><th>Denial</th><th>Service</th><th class="num">Amount</th><th>Decision</th><th>Queue</th><th>Due</th></tr></thead><tbody id="wl"></tbody></table></div>`;
    el.querySelectorAll("select").forEach((s) => s.addEventListener("change", loadWorklist));
    el.dataset.ready = 1;
  }
  if (band !== undefined) $("#f-band").value = band;
  loadWorklist();
}
async function loadWorklist() {
  const seq = (loadWorklist.seq = (loadWorklist.seq || 0) + 1);
  const q = new URLSearchParams();
  [["queue", "#f-queue"], ["band", "#f-band"], ["action", "#f-action"], ["payer", "#f-payer"], ["status", "#f-status"]].forEach(([k, s]) => q.set(k, $(s).value));
  $("#wl-count").textContent = "Loading…";
  const { items } = await api("/api/worklist?" + q);
  if (seq !== loadWorklist.seq) return; // a newer filter change is already loading: don't show stale rows
  $("#wl-count").textContent = `${items.length} items · ${money(items.reduce((a, r) => a + r.amount, 0))}`;
  $("#wl").innerHTML = items.map((r) => `<tr class="click" onclick="location.hash='claim/${esc(r.claim_id)}'">
    <td class="score">${r.score}</td><td class="mono">${esc(r.claim_id)}${r.needs_review ? ' <span title="needs human review">⚑</span>' : ""}</td>
    <td>${esc(r.patient)}</td><td>${esc(r.payer.replace(/ \(Demo.*\)/, ""))}</td>
    <td><span class="chip">${esc(codeLabel(r))}</span>${r.rarcs.map((x) => `<span class="chip">${esc(x)}</span>`).join("")}<div class="muted small">${esc(r.category)}</div></td>
    <td class="mono">${esc(r.code || "")}</td><td class="num">${money2(r.amount)}</td><td>${actionBadge(r.action)}</td><td class="small">${title(r.queue)}</td>
    <td>${bandBadge(r.band, r.days_left)}</td></tr>`).join("") || `<tr><td colspan="10" class="muted">No items match.</td></tr>`;
}

/* ------------------------------------------------------------ claim drawer */
async function openClaim(id, explain = false) {
  const drawer = $("#drawer"); drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false");
  if (!explain) $("#drawer-body").innerHTML = `<p class="muted"><span class="spin"></span>Loading ${esc(id)}…</p>`;
  let c;
  try { c = await api(`/api/claims/${encodeURIComponent(id)}${explain ? "?explain=true" : ""}`); }
  catch (e) { if (explain) throw e; $("#drawer-body").innerHTML = `<p>Could not load ${esc(id)}: ${esc(e.message)}</p><button onclick="openClaim('${esc(id)}')">Try again</button>`; return; }
  const cl = c.claim, rl = c.remit || { lines: [] };
  const work = c.decisions.filter((d) => d.workable), routine = c.decisions.filter((d) => !d.workable);
  const ack = (work.find((d) => d.source === "277CA") || {}).ack;
  const lines = cl.lines.map((ln) => {
    const r = rl.lines.find((x) => x.line_no === ln.line_no) || {};
    return `<tr><td>${ln.line_no}</td><td class="mono">${esc(ln.code)}${ln.modifiers.length ? "-" + ln.modifiers.map(esc).join("-") : ""}</td><td>${esc(c.services[ln.code] || "")}</td>
      <td class="mono">${ln.dx_pointers.map((p) => esc(cl.dx[p - 1])).join(", ")}</td><td class="num">${ln.units}</td><td class="num">${money2(ln.charge)}</td><td class="num">${c.remit ? money2(r.paid) : "—"}</td>
      <td>${(r.adjustments || []).map((a) => `<span class="chip">${esc(a.group)}-${esc(a.carc)} ${money2(a.amount)}</span>`).join("")}</td></tr>`;
  }).join("");
  $("#drawer-body").innerHTML = `
    <h1 class="mono" style="font-family:var(--mono)">${esc(cl.claim_id)}</h1>
    <p class="sub">${esc(cl.patient.last)}, ${esc(cl.patient.first)} · ${esc(c.payer)} · DOS ${esc(cl.dos)} · ${ack ? `submitted ${esc(cl.submitted)} · rejected by 277CA on ${esc(ack.date)}` : `remit ${esc(c.remit_date || "—")} · ICN <span class="mono">${esc(rl.payer_icn || "")}</span>`}</p>
    ${work.map((d) => decisionHtml(d, c)).join("") || `<div class="card">No workable denials on this claim.</div>`}
    <div class="card" style="margin-bottom:16px"><h2>${c.remit ? "Claim lines (837) and adjudication (835)" : ack ? "Claim lines (837) · no 835: rejected before adjudication" : "Claim lines (837) · no 835 yet"}</h2><div class="table-wrap"><table>
      <thead><tr><th>#</th><th>Code</th><th>Description</th><th>Dx</th><th class="num">Units</th><th class="num">Billed</th><th class="num">Paid</th><th>Adjustments</th></tr></thead><tbody>${lines}</tbody></table></div>
      <div class="small muted" style="margin-top:8px">Diagnoses: ${Object.entries(c.dx).map(([k, v]) => `<span class="chip">${esc(k)}</span>${esc(v || "")}`).join(" · ")}</div>
      ${cl.notes ? `<div class="small" style="margin-top:8px"><b>Claim note (untrusted input):</b> <span class="mono">${esc(cl.notes)}</span></div>` : ""}</div>
    <div class="grid two">
      <div class="card"><h2>EHR facts used (mock EHR)</h2><div class="ehr">${esc(JSON.stringify(c.ehr, null, 2)) || "none"}</div></div>
      <div class="card"><h2>${ack ? "Claim acknowledgement (277CA)" : "Routine adjustments (no work created)"}</h2>${ack ? `<div class="small"><span class="chip">${esc(work[0].carc)}</span> ${esc(work[0].carc_definition)}</div><div class="small muted" style="margin-top:6px">From the clearinghouse claim acknowledgement dated ${esc(ack.date)}. A rejected claim is corrected and resubmitted; there is nothing to appeal.</div>` : ""}${routine.map((d) => `<div class="small"><span class="chip">${esc(d.group)}-${esc(d.carc)}</span> ${money2(d.amount)} · ${esc(d.root_cause)} → ${esc(META.actions[d.action])}</div>`).join("") || (ack ? "" : '<p class="muted">None</p>')}</div>
    </div>`;
}
function decisionHtml(d, c) {
  const ex = d.explanation || {}; const dl = d.deadline; const pr = d.priority || {};
  const fb = (d.feedback || []).map((f) => `<div class="small">✔ ${esc(f.verdict)}${f.action ? " → " + esc(META.actions[f.action]) : ""} by ${esc(f.user)} ${f.note ? "· “" + esc(f.note) + "”" : ""}</div>`).join("");
  const letterable = d.source !== "277CA" && ["APPEAL_REDETERMINATION", "APPEAL_LEVEL_1", "OBTAIN_RETRO_AUTH", "CORRECT_AND_RESUBMIT", "REOPENING", "MANUAL_REVIEW"].includes(d.action);
  return `<div class="card decision ${d.needs_review ? "review" : ""}">
    <h3><span class="chip">${d.source === "277CA" ? "Whole claim · front-end rejection" : `Line ${d.line_no} · ${esc(d.code || "")}`}</span><span class="chip">${esc(codeLabel(d))}</span>${d.rarcs.map((r) => `<span class="chip">${esc(r)}</span>`).join("")} ${actionBadge(d.action)}
      <span class="muted small">→ ${title(d.queue)}</span> <span class="badge ${d.status === "DONE" ? "act-CORRECT_AND_RESUBMIT" : ""}" style="${d.status === "DONE" ? "" : "background:#f2f4f7;color:#1b2a3a"}">${esc(d.status)}</span></h3>
    <div class="cause"><b>${esc(d.root_cause)}.</b></div>
    <div class="narrative">${esc(ex.narrative || "")}<div class="muted small" style="margin-top:6px">Explanation by <span class="mono">${esc(ex.by || "rules")}</span>${ex.proposed_action ? " · model proposes " + actionBadge(ex.proposed_action) : ""}${ex.model_error ? " · model unavailable: " + esc(ex.model_error) : ""}</div></div>
    <div class="cols">
      <div><h2>Checks</h2><ul class="checks">${d.checks.map((k) => `<li class="${k.result}">${esc(k.name)} <span class="muted small">${esc(k.detail)}</span></li>`).join("") || '<li class="INFO">Code lookup</li>'}</ul>
        <h2 style="margin-top:14px">Steps</h2><ol class="steps">${(ex.steps || d.steps).map((s) => `<li>${esc(s)}</li>`).join("")}</ol></div>
      <div>${dl ? `<h2>Deadline</h2><div class="countdown" style="color:${BAND_COLORS[dl.band]}">${dl.days_left < 0 ? "Expired" : dl.days_left + " days"}</div><div class="small">${esc(dl.due_date)} · ${esc(dl.rule)}</div>` : `<h2>Deadline</h2><div class="muted">No filing deadline</div>`}
        <h2 style="margin-top:14px">Documents</h2>${(ex.documents || d.documents).map((x) => `<div class="small">📎 ${esc(x)}</div>`).join("") || '<div class="muted small">None needed</div>'}
        <h2 style="margin-top:14px">Priority</h2><div class="small">Score <b>${pr.score ?? "—"}</b> · P(recover) ${pr.p_recover ?? "—"} · expected ${money2(pr.expected_recovery)} · rule confidence ${d.confidence}</div></div>
      <div><h2>Policy citations</h2>${(ex.citations || []).map((ct) => `<div class="cite"><b>${esc(ct.id)}</b> ${esc(ct.title)}<div class="muted">${esc(ct.source)}</div>${ct.fictional ? '<div class="fiction">Fictional demo policy</div>' : ""}</div>`).join("") || '<div class="muted small">—</div>'}</div>
    </div>
    ${fb}
    <div class="actions">
      <button class="win" onclick="sendFeedback(this, ${d.id}, 'APPROVE', '${esc(d.claim_id)}')" ${d.status === "DONE" ? "disabled" : ""}>Approve plan</button>
      <select id="ov-${d.id}">${Object.entries(META.actions).map(([k, v]) => `<option value="${k}" ${k === d.action ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>
      <input type="text" id="note-${d.id}" placeholder="Reason / note" style="min-width:200px">
      <button class="secondary" onclick="override(this, ${d.id}, '${esc(d.claim_id)}')" ${d.status === "DONE" ? "disabled" : ""}>Override</button>
      ${letterable ? `<button onclick="draftLetter(this, ${d.id})">Draft letter</button>` : ""}
      ${META.agent_mode === "azure" && !(ex.by || "").startsWith("azure") ? `<button class="secondary" onclick="explainAI(this, '${esc(d.claim_id)}')">Explain with AI</button>` : ""}
    </div></div>`;
}
async function sendFeedback(btn, id, verdict, claimId, action = null, note = "") {
  await busy(btn, "Saving…", () => api(`/api/decisions/${id}/feedback`, { method: "POST", body: JSON.stringify({ verdict, action, note }) }));
  toast(verdict === "APPROVE" ? "Plan approved - item moved to resolved" : "Override saved - added as a precedent");
  openClaim(claimId);
}
function override(btn, id, claimId) {
  const note = $("#note-" + id).value.trim();
  if (!note) { toast("Add a reason so the override can teach the system"); $("#note-" + id).focus(); return; }
  sendFeedback(btn, id, "OVERRIDE", claimId, $("#ov-" + id).value, note);
}
async function draftLetter(btn, id) {
  const m = $("#modal"); m.classList.add("open"); $("#modal-body").innerHTML = '<p class="muted"><span class="spin"></span>Drafting the letter…</p>';
  let r;
  try { r = await busy(btn, "Drafting…", () => api(`/api/decisions/${id}/letter`, { method: "POST" })); }
  catch (e) { $("#modal-body").innerHTML = `<h1>Draft letter</h1><p>Could not draft the letter: ${esc(e.message)}. Close this and click Draft letter again.</p>`; return; }
  $("#modal-body").innerHTML = `<h1>Draft letter</h1><p class="sub">Generated by <span class="mono">${esc(r.by)}</span>. Review and edit before sending.</p>
    <textarea class="letter" id="letter-text">${esc(r.text)}</textarea>
    <div class="actions"><button onclick="navigator.clipboard.writeText($('#letter-text').value);toast('Copied')">Copy</button>
    <button class="secondary" onclick="downloadLetter()">Download .txt</button>
    <button class="secondary" onclick="printLetter()">Print / save as PDF</button></div>`;
}
function downloadLetter() {
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([$("#letter-text").value], { type: "text/plain" })); a.download = "appeal-letter.txt"; a.click();
}
function printLetter() {
  const w = window.open("", "_blank"); w.document.write(`<pre style="font:13px/1.5 monospace;white-space:pre-wrap">${esc($("#letter-text").value)}</pre>`); w.document.close(); w.print();
}
async function explainAI(btn, claimId) { await busy(btn, "AI is writing…", () => openClaim(claimId, true)); }
function closeDrawer() { $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); location.hash = lastView; }
$("#drawer-close").onclick = closeDrawer;
$("#drawer").onclick = (e) => { if (e.target.id === "drawer") closeDrawer(); };
$("#modal-close").onclick = () => $("#modal").classList.remove("open");
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { if ($("#modal").classList.contains("open")) $("#modal").classList.remove("open"); else if ($("#drawer").classList.contains("open")) closeDrawer(); } });

/* ------------------------------------------------------------ assistant */
function assistant() {
  const el = $("#view-assistant");
  if (el.dataset.ready) return;
  el.innerHTML = `<div class="kicker">Assistant · also in Microsoft Teams</div><h1>Assistant</h1><p class="sub">The same agent is available in Microsoft Teams. It answers from the worklist, the rules and the policy library.</p>
    <div class="chat card"><div class="msgs" id="msgs"></div>
    <div class="suggest">${["Top 10 by dollars", "What is due this week?", "Give me a summary", "What is the Medicare timely filing limit?", "When can I use modifier XS?"].map((s) => `<button onclick="ask('${s}')">${s}</button>`).join("")}</div>
    <form class="composer" onsubmit="event.preventDefault();ask($('#q').value)"><input type="text" id="q" placeholder="Ask about a claim (e.g. why was PRH-10222 denied?)" autocomplete="off"><button>Send</button></form></div>`;
  el.dataset.ready = 1;
}
async function ask(text) {
  if (!text.trim() || ask.busy) return;
  ask.busy = true; const send = $(".composer button"); send.disabled = true;
  $("#q").value = "";
  const msgs = $("#msgs");
  msgs.insertAdjacentHTML("beforeend", `<div class="msg me">${esc(text)}</div>`);
  msgs.insertAdjacentHTML("beforeend", `<div class="msg bot" id="typing"><span class="spin"></span>Thinking…</div>`); msgs.scrollTop = msgs.scrollHeight;
  const r = await api("/api/chat", { method: "POST", body: JSON.stringify({ message: text }) }).catch((e) => ({ reply: e.message, by: "error" }));
  $("#typing").remove(); ask.busy = false; send.disabled = false; $("#q").focus();
  const html = md(r.reply).replace(/PRH-\d{5}/g, (m) => `<a href="#claim/${m}">${m}</a>`);
  msgs.insertAdjacentHTML("beforeend", `<div class="msg bot">${html}<div class="by">${esc(r.by)}</div></div>`); msgs.scrollTop = msgs.scrollHeight;
}

/* ------------------------------------------------------------ inbox */
let INBOX_BUSY = false;
async function inbox() {
  const el = $("#view-inbox");
  if (INBOX_BUSY) return; // a file is processing: keep the current screen (and its progress) until it finishes
  const [{ files }, s] = await Promise.all([api("/api/demo-files"), api("/api/summary")]);
  if (INBOX_BUSY) return;
  const keep = $("#ingest-result")?.innerHTML || "";
  const done = (f) => s.files.find((x) => x.name === f && x.status === "PROCESSED");
  const ch = (META.site && META.site.clearinghouse) || "the clearinghouse";
  const kindOf = (f) => f.startsWith("277") ? "Claim acknowledgement (277CA)" : f.startsWith("835") ? "Remittance (835)" : "X12 file";
  el.innerHTML = `<div class="kicker">Experian Health · file intake</div><h1>Clearinghouse inbox</h1><p class="sub">Files from ${esc(ch)}: 277CA claim acknowledgements (front-end rejections) and 835 remittances (payer denials). Each file is parsed deterministically, matched to the claim, decided, ranked and routed in seconds.</p>
    <div class="grid two">
      <div class="card"><h2>Today's drop from ${esc(ch)}</h2><div class="muted small">Simulated secure file drop. In the pilot an Azure job collects these from ${esc(ch)} on a schedule.</div>${files.map((f) => { const d = done(f); return `<div class="actions inbox-row" style="margin:6px 0"><span class="small" style="flex:1"><span class="mono">${esc(f)}</span>${d ? ` <span class="badge act-CORRECT_AND_RESUBMIT">Ingested ✓</span>` : ""}<br><span class="muted">${kindOf(f)}</span></span><a class="small" href="/api/demo-files/${encodeURIComponent(f)}" target="_blank">view raw</a><button class="${d ? "secondary" : ""}" data-file="${esc(f)}" onclick="ingestDemo(this)">${d ? "Ingest again" : "Ingest"}</button></div>`; }).join("") || '<p class="muted">None</p>'}
        <div id="ingest-result" class="result">${keep}</div>
        <div class="small muted" style="margin-top:10px">Ingest each file once, 277CA first. A file takes about 5–15 seconds while the AI writes an explanation for every item.</div></div>
      <div class="card"><h2>Upload a file</h2><label class="drop" id="drop"><input type="file" id="file" hidden accept=".txt,.835,.837,.edi,.x12">Drag &amp; drop an X12 file here, or click to choose</label>
        <h2 style="margin-top:18px">Reset the demo</h2><p class="small muted">Reloads the starting data and clears alerts, approvals and overrides.</p><button class="secondary" id="reset-btn" onclick="resetDemo(this)">Reset demo data</button></div>
    </div>
    <div class="card" style="margin-top:16px"><h2>Recent files</h2><div class="table-wrap"><table><thead><tr><th>#</th><th>File</th><th>Type</th><th>Received (UTC)</th><th>Status</th><th>Detail</th></tr></thead><tbody>
      ${s.files.map((f) => `<tr><td>${f.id}</td><td class="mono small">${esc(f.name)}</td><td>${esc(f.kind)}</td><td class="small">${esc((f.received_at || "").replace("T", " ").replace("+00:00", ""))}</td><td><span class="badge ${f.status === "PROCESSED" ? "act-CORRECT_AND_RESUBMIT" : "band-CRITICAL"}">${esc(f.status)}</span></td><td class="small">${esc(f.detail)}</td></tr>`).join("")}</tbody></table></div></div>`;
  const drop = $("#drop"), input = $("#file");
  input.onchange = () => { input.files[0] && upload(input.files[0]); input.value = ""; };
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); e.dataTransfer.files[0] && upload(e.dataTransfer.files[0]); };
}
async function runIngest(btn, label, call) {
  if (INBOX_BUSY) { toast("Still processing the previous file - one moment"); return; }
  INBOX_BUSY = true;
  const others = [...document.querySelectorAll("#view-inbox button[data-file], #reset-btn")].filter((b) => b !== btn);
  others.forEach((b) => (b.disabled = true));
  $("#ingest-result").innerHTML = `<div class="alert-card warn"><span class="spin"></span><b>${esc(label)}</b> - reading the file, matching claims, deciding each denial and writing explanations…</div>`;
  try {
    const r = await busy(btn, "Processing…", call);
    INBOX_BUSY = false;
    showResult(r);
    if (lastView === "inbox") await inbox().catch(() => {});
  } catch (e) {
    $("#ingest-result").innerHTML = `<div class="alert-card"><b>Could not process ${esc(label)}:</b> ${esc(e.message)}. Wait a few seconds and click Ingest again.</div>`;
  } finally { INBOX_BUSY = false; others.forEach((b) => b.isConnected && (b.disabled = false)); }
}
function ingestDemo(btn) { const name = btn.dataset.file; return runIngest(btn, name, () => api(`/api/demo-files/${encodeURIComponent(name)}/ingest`, { method: "POST" })); }
function upload(file) { const fd = new FormData(); fd.append("file", file); return runIngest(null, file.name, () => api("/api/ingest", { method: "POST", body: fd })); }
async function resetDemo(btn) {
  if (!confirm("Reset the demo to its starting data? Alerts, approvals and overrides will be cleared.")) return;
  if (INBOX_BUSY) return;
  INBOX_BUSY = true;
  try { await busy(btn, "Resetting…", () => api("/api/demo/reset", { method: "POST" })); INBOX_BUSY = false; $("#ingest-result").innerHTML = ""; toast("Demo reset to its starting data"); await inbox(); }
  catch (e) { /* busy() already showed the error */ }
  finally { INBOX_BUSY = false; }
}
function showResult(r) {
  const el = $("#ingest-result");
  if (r.status !== "PROCESSED") { el.innerHTML = `<div class="alert-card"><b>Quarantined:</b> ${esc(r.error)}</div>`; toast("File quarantined - see the reason in the inbox"); return; }
  const counts = r.kind === "277CA" ? `${r.claims} claims acknowledged: ${r.accepted} accepted, ${r.rejected} rejected → ${r.denials} work items, ${r.alerts} Teams alerts`
    : `${r.claims} claims${r.denials !== undefined ? `, ${r.denials} denials decided, ${r.alerts} Teams alerts` : ""}`;
  el.innerHTML = `<div class="alert-card warn" style="border-left-color:var(--win)"><b>✓ ${esc(r.kind)} processed${r.payer ? " · " + esc(r.payer) : ""}</b> - ${counts}${r.unmatched?.length ? `, ${r.unmatched.length} unmatched` : ""}
    ${(r.new_items || []).map((i) => `<div class="small"><a href="#claim/${esc(i.claim_id)}">${esc(i.claim_id)}</a> → ${esc(META.actions[i.action])} · ${money2(i.amount)}</div>`).join("")}
    ${r.alerts ? `<div class="small" style="margin-top:6px"><a href="#dashboard">See the Teams alerts on the Dashboard →</a></div>` : ""}</div>`;
  toast(r.kind === "277CA" ? `Done: ${r.rejected} rejections routed, ${r.alerts} Teams alerts` : r.denials !== undefined ? `Done: ${r.denials} denials decided, ${r.alerts} Teams alerts` : `Done: ${r.claims} claims loaded`);
}

/* ------------------------------------------------------------ proof */
async function proof() {
  const el = $("#view-proof");
  const [e, s, m] = await Promise.all([api("/api/evals"), api("/api/summary"), api("/api/meta")]);
  const pct = (v) => v === undefined ? "—" : (v * 100).toFixed(1) + "%";
  const scen = Object.entries(e.accuracy).filter(([k]) => k.startsWith("scenario:")).sort();
  el.innerHTML = `<div class="kicker">Quality</div><h1>Proof &amp; quality</h1><p class="sub">Every synthetic denial was injected with a known correct answer. This page scores the live decisions against that ground truth.</p>
    <div class="grid kpis">
      <div class="card kpi win"><div class="label">Denial decisions correct</div><div class="value">${pct(e.accuracy.denial)}</div><div class="muted small">${e.counts.denial} labelled denials</div></div>
      <div class="card kpi win"><div class="label">Noise correctly filtered</div><div class="value">${pct(e.accuracy.noise)}</div><div class="muted small">${e.counts.noise} routine adjustments</div></div>
      <div class="card kpi ${e.must_not_violations.length ? "loss" : "win"}"><div class="label">Unsafe actions</div><div class="value">${e.must_not_violations.length}</div><div class="muted small">e.g. billing a patient on CO</div></div>
      <div class="card kpi"><div class="label">Deadlines computed</div><div class="value">${e.deadlines_computed}</div><div class="muted small">deterministic engine</div></div>
      <div class="card kpi"><div class="label">Ranking model AUC</div><div class="value">${s.model_card.test_auc}</div><div class="muted small">${esc(s.model_card.data)}</div></div>
    </div>
    <div class="grid two">
      <div class="card"><h2>Accuracy by scenario</h2><div class="table-wrap"><table><thead><tr><th>Scenario</th><th class="num">Items</th><th class="num">Correct</th></tr></thead><tbody>
        ${scen.map(([k, v]) => `<tr><td class="mono">${esc(k.replace("scenario:", ""))}</td><td class="num">${e.counts[k]}</td><td class="num">${pct(v)}</td></tr>`).join("")}</tbody></table></div></div>
      <div class="card"><h2>Dataset</h2><div class="small">${Object.entries(m.manifest).filter(([k]) => k !== "scenarios").map(([k, v]) => `<div><b>${esc(title(k))}:</b> ${esc(v)}</div>`).join("")}</div>
        <h2 style="margin-top:16px">How to read this</h2><p class="small">${esc(e.note)}</p>
        <h2 style="margin-top:16px">Guardrails</h2><ul class="small"><li>Rules own action, queue and deadline; AI explains and drafts.</li><li>AI may only propose an action for items flagged for manual review.</li><li>Citations are limited to retrieved policy cards.</li><li>Claim free text is treated as untrusted data (see scenario S01).</li><li>Every appeal and write-off requires human approval.</li></ul></div>
    </div>`;
}

/* ------------------------------------------------------------ agent card */
async function agent() {
  const el = $("#view-agent");
  el.innerHTML = '<p class="muted"><span class="spin"></span>Loading the agent card…</p>';
  const c = await api("/api/agent-card");
  const pct = (v) => (v === undefined || v === null ? "—" : (v * 100).toFixed(1) + "%");
  const row = (k, v) => `<div class="kv"><div>${esc(k)}</div><div>${v}</div></div>`;
  const t = c.telemetry, e = c.evaluation, id = c.identity;
  const card = (n, title, sub, body) => `<div class="card agent-item"><div class="agent-head"><span class="agent-num">${n}</span><div><h2>${esc(title)}</h2><div class="muted small">${esc(sub)}</div></div><span class="badge act-CORRECT_AND_RESUBMIT">In place</span></div>${body}</div>`;
  el.innerHTML = `<div class="kicker">Governance</div><h1>Agent card</h1>
    <p class="sub">The six things a production agent needs: who owns it, what it may do, how it is tested, how it is governed, what it is doing right now, and how to run it. Filled live from this system.</p>
    <div class="grid two">
      ${card(1, "Named owner", "Accountable people", row("Business owner", esc(c.owner.business_owner)) + row("Technical owner", esc(c.owner.technical_owner)) + row("Operator", esc(c.owner.operator)))}
      ${card(2, "Defined authority", "What it may and may not do",
        row("Decisions", esc(c.authority.decides)) + row("May propose an action", esc(c.authority.may_propose)) +
        row("Tools (all read-only)", c.authority.tools.map((x) => `<span class="chip mono">${esc(x.name)}</span>`).join(" ")) +
        row("Closed action set", `${c.authority.actions.length} actions`) +
        row("Human approval", `<ul class="tight">${c.authority.human_approval.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`))}
      ${card(3, "Evaluation", "Tested against known answers",
        row("Decisions correct", `<b>${pct(e.decision_accuracy)}</b> of ${e.labelled_denials} labelled denials`) + row("Noise filtered correctly", pct(e.noise_accuracy)) +
        row("Unsafe actions", `<b>${e.unsafe_actions}</b>`) + row("Deadlines computed", esc(e.deadlines_computed)) + row("Test suites", esc(e.suites)) + row("Note", `<span class="muted">${esc(e.note)}</span>`))}
      ${card(4, "Identity and governance", "Who it runs as, and the guardrails around it",
        row("Model", esc(id.model)) + row("Guardrail", esc(id.guardrail)) + row("Service identity", esc(id.service_identity)) +
        row("User sign-in", esc(id.user_sign_in)) + row("Queue scoping", esc(id.queue_scoping)) + row("Data location", esc(id.data_location)))}
      ${card(5, "Telemetry", "Live since the last restart",
        row("AI calls", `<b>${t.ai_calls}</b>${t.ai_errors ? ` · ${t.ai_errors} errors` : " · no errors"}`) +
        row("Average AI response", t.ai_avg_ms ? (t.ai_avg_ms / 1000).toFixed(1) + " s" : "—") +
        row("Files processed", t.files_processed) + row("Decisions on record", t.decisions.toLocaleString()) +
        row("Approvals / overrides", `${t.approvals} / ${t.overrides}`) + row("Teams alerts", t.teams_alerts) + row("Uptime", `${t.uptime_minutes} min`))}
      ${card(6, "Runbook", "How to run, test and hand it over",
        `<ul class="tight">${c.runbook.map((r) => `<li><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a></li>`).join("")}</ul>`)}
    </div>`;
}

/* ------------------------------------------------------------ reporting */
/* The measures the hospital's Power BI report carries, computed live from the same tables.
   No vendor prices here: the value side of ROI only. The cost side belongs to the proposal. */
const monthName = (m) => new Date(m + "-15").toLocaleString("en-US", { month: "short" });
const pctTxt = (v, d = 1) => (v === null || v === undefined ? "—" : (v * 100).toFixed(d) + "%");
const kmoney = (v) => (Math.abs(v) >= 1e6 ? "$" + (v / 1e6).toFixed(2).replace(/\.?0+$/, "") + "M" : Math.abs(v) >= 1e4 ? "$" + Math.round(v / 1e3).toLocaleString() + "K" : money(v));
let REPORT = null;
async function reporting() {
  const el = $("#view-reporting");
  el.innerHTML = '<p class="muted"><span class="spin"></span>Loading the report…</p>';
  const r = (REPORT = await api("/api/report"));
  const t = r.trend;
  const adj = t.reduce((a, x) => a + x.claims, 0), den = t.reduce((a, x) => a + x.denied_claims, 0);
  const topRate = Math.max(...t.map((x) => x.denial_rate || 0), 0.01);
  const axis = Math.max(0.1, Math.ceil((topRate * 1.25) / 0.05) * 0.05); // fixed headroom so a steady rate reads as steady
  const cols = t.map((x, i) => {
    const tip = `${monthName(x.month)} ${x.month.slice(0, 4)}: ${x.denied_claims} of ${x.claims} claims denied (${pctTxt(x.denial_rate)}), ${money(x.denied_amount)}${x.rejections ? ` · ${x.rejections} front-end rejections (${money(x.rejected_amount)})` : ""}`;
    return `<div class="col" data-tip="${esc(tip)}" tabindex="0" aria-label="${esc(tip)}">
      <div class="col-val">${i === t.length - 1 || x.denial_rate === topRate ? pctTxt(x.denial_rate) : ""}</div>
      <div class="col-bar" style="height:${Math.max(2, (100 * (x.denial_rate || 0)) / axis)}%"></div>
      <div class="col-lbl">${monthName(x.month)}</div><div class="col-sub">${kmoney(x.denied_amount)}</div></div>`;
  }).join("");
  const maxRate = Math.max(...r.payers.map((p) => p.denial_rate), 0.01);
  const maxAge = Math.max(...r.aging.map((a) => a.amount), 1);
  const ta = r.turnaround, rc = r.recovery;
  const secs = ta.file_to_worklist_seconds === null ? "—" : ta.file_to_worklist_seconds < 1 ? "< 1 s" : ta.file_to_worklist_seconds.toFixed(0) + " s";
  const mins = ta.median_minutes_to_decision === null ? "—" : ta.median_minutes_to_decision < 1 ? "< 1 min" : ta.median_minutes_to_decision.toFixed(0) + " min";
  el.innerHTML = `<div class="kicker">Power BI preview</div><h1>Reporting</h1>
    <p class="sub">What the hospital's Power BI report shows: denial trends, turnaround, recovery and the value side of ROI. Computed live from the same tables as the worklist. In the pilot, Power BI reads them from Azure SQL.</p>
    <div class="grid kpis">
      <div class="card kpi"><div class="label">Denial rate · ${t.length} months</div><div class="value">${pctTxt(adj ? den / adj : null)}</div><div class="muted small">${den.toLocaleString()} of ${adj.toLocaleString()} adjudicated claims</div></div>
      <div class="card kpi loss"><div class="label">Open denied dollars</div><div class="value">${kmoney(rc.denied_open)}</div><div class="muted small">${ta.open_items} open items</div></div>
      <div class="card kpi risk"><div class="label">Front-end rejections (277CA)</div><div class="value">${r.rejections.open}</div><div class="muted small">${money(r.rejections.amount)} not yet at the payer</div></div>
      <div class="card kpi"><div class="label">Median age, open items</div><div class="value">${ta.median_open_age_days ?? "—"} days</div><div class="muted small">since the 835 or 277CA</div></div>
      <div class="card kpi win"><div class="label">Expected recovery</div><div class="value">${kmoney(rc.expected_open)}</div><div class="muted small">${pctTxt(rc.expected_rate)} of open dollars (ML)</div></div>
    </div>
    <div class="grid two">
      <div class="card"><h2>Denial trend: denial rate by month</h2>
        <div class="colchart" role="img" aria-label="Denial rate by remittance month">${cols}</div>
        <div class="muted small">Denied claims ÷ claims adjudicated, by month of the 835 (scale 0–${pctTxt(axis, 0)}). Under each month: denied dollars. Complete months only. Hover a bar for the detail.</div>
        <details class="small"><summary>Show as table</summary><div class="table-wrap"><table><thead><tr><th>Month</th><th class="num">Claims</th><th class="num">Denied</th><th class="num">Rate</th><th class="num">Denied $</th><th class="num">277CA rejections</th></tr></thead><tbody>
          ${t.map((x) => `<tr><td>${esc(x.month)}</td><td class="num">${x.claims}</td><td class="num">${x.denied_claims}</td><td class="num">${pctTxt(x.denial_rate)}</td><td class="num">${money(x.denied_amount)}</td><td class="num">${x.rejections}</td></tr>`).join("")}</tbody></table></div></details></div>
      <div class="card"><h2>Denial rate by payer</h2>
        ${r.payers.map((p) => `<div class="bar-row" title="${esc(p.payer)}: ${p.denied_claims} of ${p.claims} claims denied"><div>${esc(p.payer.replace(/ \(Demo.*\)/, ""))}</div><div class="bar"><span style="width:${(100 * p.denial_rate) / maxRate}%;background:var(--brand-secondary)"></span></div><div class="num">${pctTxt(p.denial_rate)}</div></div>`).join("")}
        <div class="muted small">Denied claims ÷ claims adjudicated on an 835, per payer.</div></div>
      <div class="card"><h2>Where the dollars are</h2><div class="table-wrap"><table><thead><tr><th>Root cause</th><th class="num">Items</th><th class="num">Denied</th><th class="num">Expected recovery</th></tr></thead><tbody>
        ${r.categories.map((c) => `<tr><td>${esc(c.category)}</td><td class="num">${c.items}</td><td class="num" title="${pctTxt(c.share, 0)} of denied dollars">${money(c.amount)}</td><td class="num">${money(c.expected_recovery)}</td></tr>`).join("")}</tbody></table></div></div>
      <div class="card"><h2>Turnaround</h2>
        <div class="kv"><div>File received → ranked worklist</div><div><b>${secs}</b> <span class="muted small">${ta.files_timed ? `average of ${ta.files_timed} live file${ta.files_timed > 1 ? "s" : ""}` : "ingest a file from the inbox to time it"}</span></div></div>
        <div class="kv"><div>Recommendation → biller decision</div><div><b>${mins}</b> <span class="muted small">${ta.decisions_timed ? `median of ${ta.decisions_timed} approval${ta.decisions_timed > 1 ? "s" : ""} or override${ta.decisions_timed > 1 ? "s" : ""}` : "timed from the first approval"}</span></div></div>
        <h2 style="margin-top:14px">Open denied dollars by age</h2>
        ${r.aging.map((a) => `<div class="bar-row" title="${a.items} open items, ${money(a.amount)}"><div>${esc(a.bucket)}</div><div class="bar"><span style="width:${(100 * a.amount) / maxAge}%;background:var(--risk)"></span></div><div class="num">${kmoney(a.amount)}</div></div>`).join("")}</div>
      <div class="card"><h2>Recovery</h2>
        <div class="kv"><div>Open denied dollars</div><div><b>${money(rc.denied_open)}</b></div></div>
        <div class="kv"><div>Expected recovery (ML, before work)</div><div><b>${money(rc.expected_open)}</b> · ${pctTxt(rc.expected_rate)}</div></div>
        <div class="kv"><div>Approved for rework by billers</div><div><b>${rc.approved_items}</b> items · ${money(rc.approved_amount)}</div></div>
        <div class="kv"><div>Confirmed recovered</div><div><span class="muted">Pilot: matched from the follow-up 835 once the corrected claim or appeal is paid (typically 30–60+ days)</span></div></div></div>
      <div class="card"><h2>Value side of ROI</h2>
        <p class="muted small" style="margin-top:0">What denials cost a hospital this size each year, and what comes back. ROI is this value divided by the agreed cost of the engagement, which sits in the proposal. The pilot replaces these benchmarks with measured figures.</p>
        <div class="roi-in">
          <label class="field">Net patient revenue ($M a year)<input type="number" id="r-npr" value="25" min="0" step="1"></label>
          <label class="field">Denial write-offs (% of net revenue)<input type="number" id="r-wo" value="2" min="0" step="0.1"></label>
          <label class="field">Denials a year<input type="number" id="r-den" value="4500" min="0" step="100"></label>
          <label class="field">Cost to work one denial ($)<input type="number" id="r-cpd" value="57.23" min="0" step="0.01"></label>
          <label class="field">Handling effort saved (%)<input type="number" id="r-eff" value="30" min="0" max="100" step="1"></label>
          <label class="field">Write-offs recovered, low–high (%)<span class="pair"><input type="number" id="r-lo" value="15" min="0" max="100" step="1"><input type="number" id="r-hi" value="25" min="0" max="100" step="1"></span></label>
        </div>
        <div id="r-out"></div>
        <div class="muted small">Defaults: a 25-bed critical access hospital. Benchmarks: HFMA (denial write-offs ≈2% of net patient revenue); Premier 2024 ($57.23 to work a denial).</div></div>
      <div class="card"><h2>Power BI dataset</h2>
        <p class="small" style="margin-top:0">One row per denial or rejection: payer, codes, root cause, amount, action, queue, deadline, urgency, ML priority, expected recovery and the biller's decision. Power BI builds the trend, turnaround, recovery and ROI pages from it.</p>
        <div class="actions"><a href="/api/report/denials.csv" download><button>Download dataset (CSV)</button></a></div>
        <ul class="tight small"><li><b>Pilot:</b> Power BI connects to Azure SQL with the same columns, refreshed daily</li><li><b>Report pages:</b> denial trends · turnaround · recovery · ROI · drill-through to the claim</li><li>Synthetic data only, no PHI</li></ul></div>
    </div>`;
  el.querySelectorAll(".roi-in input").forEach((x) => x.addEventListener("input", calcRoi));
  calcRoi();
}
function calcRoi() {
  const v = (id) => Math.max(0, +$(id).value || 0);
  const writeOff = v("#r-npr") * 1e6 * (v("#r-wo") / 100), staff = v("#r-den") * v("#r-cpd");
  const saved = staff * Math.min(v("#r-eff"), 100) / 100;
  const lo = Math.min(v("#r-lo"), 100) / 100, hi = Math.max(lo, Math.min(v("#r-hi"), 100) / 100);
  const range = (a, b) => (Math.round(a) === Math.round(b) ? kmoney(a) : `${kmoney(a)}–${kmoney(b)}`);
  $("#r-out").innerHTML = `<div class="roi-out">
    <div><div class="label">Denials cost a year</div><div class="big">${kmoney(writeOff + staff)}</div><div class="muted small">${kmoney(writeOff)} written off + ${kmoney(staff)} to work them</div></div>
    <div><div class="label">Revenue recovered</div><div class="big">${range(writeOff * lo, writeOff * hi)}</div><div class="muted small">a year</div></div>
    <div><div class="label">Staff effort saved</div><div class="big">${kmoney(saved)}</div><div class="muted small">a year</div></div>
    <div class="total"><div class="label">Annual value</div><div class="big">${range(writeOff * lo + saved, writeOff * hi + saved)}</div><div class="muted small">recovered + effort saved</div></div></div>`;
}

/* ------------------------------------------------------------ boot */
(async function boot() {
  for (let i = 0; ; i++) {
    try { META = await api("/api/meta"); break; }
    catch (e) { if (i > 40) throw e; $("#view-dashboard").innerHTML = `<p class="muted"><span class="spin"></span>Starting up and loading the demo data… (${i * 3}s)</p>`; await new Promise((r) => setTimeout(r, 3000)); }
  }
  $("#mode-pill").textContent = META.agent_mode === "azure" ? "AI: Azure OpenAI" : "AI: offline templates";
  $("#asof").textContent = "Demo date " + META.as_of;
  $("#build").textContent = "Version " + (META.build || "-");
  if (META.partner && META.partner.name) {
    const pn = $("#partner"); pn.textContent = "by " + META.partner.name; pn.hidden = false;
    const pt = $("#partner-tag"); pt.textContent = META.partner.tagline; pt.hidden = false;
    document.title = "Denial Navigator · " + META.partner.name;
  }
  if (META.site && META.site.name) { const sn = $("#site-name"); sn.textContent = "Prepared for " + META.site.name; sn.hidden = false; document.title = "Denial Navigator · " + META.site.name; }
  if (META.site && META.site.context) { const sc = $("#site-context"); sc.textContent = META.site.context; sc.hidden = false; }
  route();
})();
