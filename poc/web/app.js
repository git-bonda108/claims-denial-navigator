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
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 2600); }
const actionBadge = (a) => `<span class="badge act-${esc(a)}">${esc(META.actions[a] || a)}</span>`;
const bandBadge = (b, days) => b ? `<span class="badge band-${esc(b)}">${b === "EXPIRED" ? "Expired" : esc(days) + "d"} · ${title(b)}</span>` : `<span class="muted">—</span>`;
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
  ({ dashboard, worklist, assistant, inbox, proof }[view] || dashboard)(arg);
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
    <h1>Denials at a glance</h1>
    <p class="sub">As of ${esc(s.as_of)} · ${s.claims.toLocaleString()} claims adjudicated · ${(s.denial_rate * 100).toFixed(1)}% denial rate</p>
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
    el.innerHTML = `<h1>Worklist</h1><p class="sub">Ranked by expected recovery × deadline urgency. Routine adjustments are already filtered out.</p>
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
  const q = new URLSearchParams();
  [["queue", "#f-queue"], ["band", "#f-band"], ["action", "#f-action"], ["payer", "#f-payer"], ["status", "#f-status"]].forEach(([k, s]) => q.set(k, $(s).value));
  const { items } = await api("/api/worklist?" + q);
  $("#wl-count").textContent = `${items.length} items · ${money(items.reduce((a, r) => a + r.amount, 0))}`;
  $("#wl").innerHTML = items.map((r) => `<tr class="click" onclick="location.hash='claim/${esc(r.claim_id)}'">
    <td class="score">${r.score}</td><td class="mono">${esc(r.claim_id)}${r.needs_review ? ' <span title="needs human review">⚑</span>' : ""}</td>
    <td>${esc(r.patient)}</td><td>${esc(r.payer.replace(/ \(Demo.*\)/, ""))}</td>
    <td><span class="chip">${esc(r.group)}-${esc(r.carc)}</span>${r.rarcs.map((x) => `<span class="chip">${esc(x)}</span>`).join("")}<div class="muted small">${esc(r.category)}</div></td>
    <td class="mono">${esc(r.code || "")}</td><td class="num">${money2(r.amount)}</td><td>${actionBadge(r.action)}</td><td class="small">${title(r.queue)}</td>
    <td>${bandBadge(r.band, r.days_left)}</td></tr>`).join("") || `<tr><td colspan="10" class="muted">No items match.</td></tr>`;
}

/* ------------------------------------------------------------ claim drawer */
async function openClaim(id, explain = false) {
  const drawer = $("#drawer"); drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false");
  $("#drawer-body").innerHTML = `<p class="muted">Loading ${esc(id)}…</p>`;
  let c;
  try { c = await api(`/api/claims/${encodeURIComponent(id)}${explain ? "?explain=true" : ""}`); } catch (e) { $("#drawer-body").innerHTML = `<p>${esc(e.message)}</p>`; return; }
  const cl = c.claim, rl = c.remit || { lines: [] };
  const work = c.decisions.filter((d) => d.workable), routine = c.decisions.filter((d) => !d.workable);
  const lines = cl.lines.map((ln) => {
    const r = rl.lines.find((x) => x.line_no === ln.line_no) || {};
    return `<tr><td>${ln.line_no}</td><td class="mono">${esc(ln.code)}${ln.modifiers.length ? "-" + ln.modifiers.map(esc).join("-") : ""}</td><td>${esc(c.services[ln.code] || "")}</td>
      <td class="mono">${ln.dx_pointers.map((p) => esc(cl.dx[p - 1])).join(", ")}</td><td class="num">${ln.units}</td><td class="num">${money2(ln.charge)}</td><td class="num">${money2(r.paid)}</td>
      <td>${(r.adjustments || []).map((a) => `<span class="chip">${esc(a.group)}-${esc(a.carc)} ${money2(a.amount)}</span>`).join("")}</td></tr>`;
  }).join("");
  $("#drawer-body").innerHTML = `
    <h1 class="mono" style="font-family:var(--mono)">${esc(cl.claim_id)}</h1>
    <p class="sub">${esc(cl.patient.last)}, ${esc(cl.patient.first)} · ${esc(c.payer)} · DOS ${esc(cl.dos)} · remit ${esc(c.remit_date || "—")} · ICN <span class="mono">${esc(rl.payer_icn || "")}</span></p>
    ${work.map((d) => decisionHtml(d, c)).join("") || `<div class="card">No workable denials on this claim.</div>`}
    <div class="card" style="margin-bottom:16px"><h2>Claim lines (837) and adjudication (835)</h2><div class="table-wrap"><table>
      <thead><tr><th>#</th><th>Code</th><th>Description</th><th>Dx</th><th class="num">Units</th><th class="num">Billed</th><th class="num">Paid</th><th>Adjustments</th></tr></thead><tbody>${lines}</tbody></table></div>
      <div class="small muted" style="margin-top:8px">Diagnoses: ${Object.entries(c.dx).map(([k, v]) => `<span class="chip">${esc(k)}</span>${esc(v || "")}`).join(" · ")}</div>
      ${cl.notes ? `<div class="small" style="margin-top:8px"><b>Claim note (untrusted input):</b> <span class="mono">${esc(cl.notes)}</span></div>` : ""}</div>
    <div class="grid two">
      <div class="card"><h2>EHR facts used (mock EHR)</h2><div class="ehr">${esc(JSON.stringify(c.ehr, null, 2)) || "none"}</div></div>
      <div class="card"><h2>Routine adjustments (no work created)</h2>${routine.map((d) => `<div class="small"><span class="chip">${esc(d.group)}-${esc(d.carc)}</span> ${money2(d.amount)} · ${esc(d.root_cause)} → ${esc(META.actions[d.action])}</div>`).join("") || '<p class="muted">None</p>'}</div>
    </div>`;
}
function decisionHtml(d, c) {
  const ex = d.explanation || {}; const dl = d.deadline; const pr = d.priority || {};
  const fb = (d.feedback || []).map((f) => `<div class="small">✔ ${esc(f.verdict)}${f.action ? " → " + esc(META.actions[f.action]) : ""} by ${esc(f.user)} ${f.note ? "· “" + esc(f.note) + "”" : ""}</div>`).join("");
  const letterable = ["APPEAL_REDETERMINATION", "APPEAL_LEVEL_1", "OBTAIN_RETRO_AUTH", "CORRECT_AND_RESUBMIT", "REOPENING", "MANUAL_REVIEW"].includes(d.action);
  return `<div class="card decision ${d.needs_review ? "review" : ""}">
    <h3><span class="chip">Line ${d.line_no} · ${esc(d.code || "")}</span><span class="chip">${esc(d.group)}-${esc(d.carc)}</span>${d.rarcs.map((r) => `<span class="chip">${esc(r)}</span>`).join("")} ${actionBadge(d.action)}
      <span class="muted small">→ ${title(d.queue)}</span> <span class="badge ${d.status === "DONE" ? "act-CORRECT_AND_RESUBMIT" : ""}" style="${d.status === "DONE" ? "" : "background:#eef2f6;color:#1f2933"}">${esc(d.status)}</span></h3>
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
      <button class="win" onclick="sendFeedback(${d.id}, 'APPROVE', '${esc(d.claim_id)}')" ${d.status === "DONE" ? "disabled" : ""}>Approve plan</button>
      <select id="ov-${d.id}">${Object.entries(META.actions).map(([k, v]) => `<option value="${k}" ${k === d.action ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>
      <input type="text" id="note-${d.id}" placeholder="Reason / note" style="min-width:200px">
      <button class="secondary" onclick="override(${d.id}, '${esc(d.claim_id)}')" ${d.status === "DONE" ? "disabled" : ""}>Override</button>
      ${letterable ? `<button onclick="draftLetter(${d.id})">Draft letter</button>` : ""}
      ${META.agent_mode === "azure" && !(ex.by || "").startsWith("azure") ? `<button class="secondary" onclick="openClaim('${esc(d.claim_id)}', true)">Explain with AI</button>` : ""}
    </div></div>`;
}
async function sendFeedback(id, verdict, claimId, action = null, note = "") {
  await api(`/api/decisions/${id}/feedback`, { method: "POST", body: JSON.stringify({ verdict, action, note }) });
  toast(verdict === "APPROVE" ? "Plan approved - item moved to resolved" : "Override saved - added as a precedent");
  openClaim(claimId);
}
function override(id, claimId) {
  const note = $("#note-" + id).value.trim();
  if (!note) { toast("Add a reason so the override can teach the system"); return; }
  sendFeedback(id, "OVERRIDE", claimId, $("#ov-" + id).value, note);
}
async function draftLetter(id) {
  const m = $("#modal"); m.classList.add("open"); $("#modal-body").innerHTML = '<p class="muted">Drafting…</p>';
  const r = await api(`/api/decisions/${id}/letter`, { method: "POST" });
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
function closeDrawer() { $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); location.hash = lastView; }
$("#drawer-close").onclick = closeDrawer;
$("#drawer").onclick = (e) => { if (e.target.id === "drawer") closeDrawer(); };
$("#modal-close").onclick = () => $("#modal").classList.remove("open");
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { if ($("#modal").classList.contains("open")) $("#modal").classList.remove("open"); else if ($("#drawer").classList.contains("open")) closeDrawer(); } });

/* ------------------------------------------------------------ assistant */
function assistant() {
  const el = $("#view-assistant");
  if (el.dataset.ready) return;
  el.innerHTML = `<h1>Assistant</h1><p class="sub">The same agent is available in Microsoft Teams. It answers from the worklist, the rules and the policy library.</p>
    <div class="chat card"><div class="msgs" id="msgs"></div>
    <div class="suggest">${["Top 10 by dollars", "What is due this week?", "Give me a summary", "What is the Medicare timely filing limit?", "When can I use modifier XS?"].map((s) => `<button onclick="ask('${s}')">${s}</button>`).join("")}</div>
    <form class="composer" onsubmit="event.preventDefault();ask($('#q').value)"><input type="text" id="q" placeholder="Ask about a claim (e.g. why was PRH-10222 denied?)" autocomplete="off"><button>Send</button></form></div>`;
  el.dataset.ready = 1;
}
async function ask(text) {
  if (!text.trim()) return;
  $("#q").value = "";
  const msgs = $("#msgs");
  msgs.insertAdjacentHTML("beforeend", `<div class="msg me">${esc(text)}</div>`);
  msgs.insertAdjacentHTML("beforeend", `<div class="msg bot" id="typing">…</div>`); msgs.scrollTop = msgs.scrollHeight;
  const r = await api("/api/chat", { method: "POST", body: JSON.stringify({ message: text }) }).catch((e) => ({ reply: e.message, by: "error" }));
  $("#typing").remove();
  const html = md(r.reply).replace(/PRH-\d{5}/g, (m) => `<a href="#claim/${m}">${m}</a>`);
  msgs.insertAdjacentHTML("beforeend", `<div class="msg bot">${html}<div class="by">${esc(r.by)}</div></div>`); msgs.scrollTop = msgs.scrollHeight;
}

/* ------------------------------------------------------------ inbox */
async function inbox() {
  const el = $("#view-inbox");
  const [{ files }, s] = await Promise.all([api("/api/demo-files"), api("/api/summary")]);
  el.innerHTML = `<h1>Remittance inbox</h1><p class="sub">Drop an 835 (or 837) file. It is parsed deterministically, matched to the claim, decided, ranked and routed in seconds.</p>
    <div class="grid two">
      <div class="card"><h2>Live demo remittances</h2>${files.map((f) => `<div class="actions" style="margin:6px 0"><span class="mono small" style="flex:1">${esc(f)}</span><a class="small" href="/api/demo-files/${encodeURIComponent(f)}" target="_blank">view raw</a><button onclick="ingestDemo('${esc(f)}')">Ingest</button></div>`).join("") || '<p class="muted">None</p>'}
        <div id="ingest-result" class="result"></div></div>
      <div class="card"><h2>Upload a file</h2><label class="drop" id="drop"><input type="file" id="file" hidden accept=".txt,.835,.837,.edi,.x12">Drag &amp; drop an X12 file here, or click to choose</label></div>
    </div>
    <div class="card" style="margin-top:16px"><h2>Recent files</h2><div class="table-wrap"><table><thead><tr><th>#</th><th>File</th><th>Type</th><th>Status</th><th>Detail</th></tr></thead><tbody>
      ${s.files.map((f) => `<tr><td>${f.id}</td><td class="mono small">${esc(f.name)}</td><td>${esc(f.kind)}</td><td><span class="badge ${f.status === "PROCESSED" ? "act-CORRECT_AND_RESUBMIT" : "band-CRITICAL"}">${esc(f.status)}</span></td><td class="small">${esc(f.detail)}</td></tr>`).join("")}</tbody></table></div></div>`;
  const drop = $("#drop"), input = $("#file");
  drop.onclick = () => input.click();
  input.onchange = () => input.files[0] && upload(input.files[0]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); e.dataTransfer.files[0] && upload(e.dataTransfer.files[0]); };
}
async function ingestDemo(name) { showResult(await api(`/api/demo-files/${encodeURIComponent(name)}/ingest`, { method: "POST" })); }
async function upload(file) { const fd = new FormData(); fd.append("file", file); showResult(await api("/api/ingest", { method: "POST", body: fd })); }
function showResult(r) {
  const el = $("#ingest-result") || $("#view-inbox");
  if (r.status !== "PROCESSED") { el.innerHTML = `<div class="alert-card"><b>Quarantined:</b> ${esc(r.error)}</div>`; return; }
  el.innerHTML = `<div class="alert-card warn" style="border-left-color:var(--win)"><b>${esc(r.kind)} processed${r.payer ? " · " + esc(r.payer) : ""}</b> - ${r.claims} claims${r.denials !== undefined ? `, ${r.denials} denials decided, ${r.alerts} Teams alerts` : ""}${r.unmatched?.length ? `, ${r.unmatched.length} unmatched` : ""}
    ${(r.new_items || []).map((i) => `<div class="small"><a href="#claim/${esc(i.claim_id)}">${esc(i.claim_id)}</a> → ${esc(META.actions[i.action])} · ${money2(i.amount)}</div>`).join("")}</div>`;
  toast(`${r.denials ?? r.claims} items processed`);
}

/* ------------------------------------------------------------ proof */
async function proof() {
  const el = $("#view-proof");
  const [e, s, m] = await Promise.all([api("/api/evals"), api("/api/summary"), api("/api/meta")]);
  const pct = (v) => v === undefined ? "—" : (v * 100).toFixed(1) + "%";
  const scen = Object.entries(e.accuracy).filter(([k]) => k.startsWith("scenario:")).sort();
  el.innerHTML = `<h1>Proof &amp; quality</h1><p class="sub">Every synthetic denial was injected with a known correct answer. This page scores the live decisions against that ground truth.</p>
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

/* ------------------------------------------------------------ boot */
(async function boot() {
  META = await api("/api/meta");
  $("#mode-pill").textContent = META.agent_mode === "azure" ? "AI: Azure OpenAI" : "AI: offline templates";
  $("#asof").textContent = "Demo date " + META.as_of;
  route();
})();
