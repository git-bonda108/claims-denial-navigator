"""End-to-end check of a running Denial Navigator - every component, the whole workflow.

  python3 verify_deployment.py https://<your-app>.azurecontainerapps.io

Standard library only (runs in Azure Cloud Shell as-is). It ingests the live-demo remittances,
approves one item and overrides another, then resets the demo data so the app is clean for a live demo.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
results: list[tuple[str, str, str, str]] = []  # (area, check, status, detail)


def call(method: str, path: str, body=None, raw: bytes | None = None, ctype: str | None = None, timeout=120):
    data, headers = None, {}
    if body is not None:
        data, headers = json.dumps(body).encode(), {"Content-Type": "application/json"}
    if raw is not None:
        data, headers = raw, {"Content-Type": ctype}
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode("utf-8", "replace")
            status = r.status
    except urllib.error.HTTPError as e:
        text, status = e.read().decode("utf-8", "replace"), e.code
    dt = time.time() - t0
    try:
        return status, json.loads(text), dt
    except ValueError:
        return status, text, dt


def record(area, name, ok, detail="", warn=False):
    results.append((area, name, "PASS" if ok else ("WARN" if warn else "FAIL"), str(detail)[:110]))


def multipart(name: str, content: bytes):
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: text/plain\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def main() -> int:
    print(f"Verifying {BASE}\n")
    # 1. platform - wait up to 3 minutes for a cold start (the first start also generates the dataset)
    t0 = time.time()
    while True:  # after a restart Azure answers 503 for a while; wait for a real 200
        try:
            s, body, _ = call("GET", "/health", timeout=60)
            if s == 200:
                break
        except (urllib.error.URLError, TimeoutError) as exc:
            body = str(exc)
        if time.time() - t0 > 300:
            print(f"App not ready after 5 minutes: {body}")
            return 1
        time.sleep(5)
    dt = time.time() - t0
    record("Platform", "App responds (/health)", s == 200 and body == {"status": "ok"}, f"HTTP {s} in {dt:.1f}s")
    s, html, _ = call("GET", "/")
    record("Platform", "Web UI served", s == 200 and "Denial Navigator" in str(html), f"HTTP {s}")
    s, js, _ = call("GET", "/static/app.js")
    record("Platform", "Front-end assets served", s == 200, f"HTTP {s}")
    s, meta, _ = call("GET", "/api/meta")
    mode = meta.get("agent_mode") if isinstance(meta, dict) else None
    record("AI", "Connected to Azure OpenAI", mode == "azure", f"agent_mode={mode}", warn=mode == "offline")

    # 2. data + dashboard
    s, summ, _ = call("GET", "/api/summary")
    ok = s == 200 and summ.get("claims", 0) >= 1000
    record("Data", "Synthetic dataset loaded", ok, f"{summ.get('claims')} claims, {summ.get('denied_claims')} denied")
    record("Data", "Denial rate realistic (15-21%)", 0.15 <= summ.get("denial_rate", 0) <= 0.21, summ.get("denial_rate"))
    record("Rules", "Routine adjustments filtered", summ.get("noise_filtered", 0) > summ.get("open_items", 0),
           f"{summ.get('noise_filtered')} filtered vs {summ.get('open_items')} work items")
    record("Prioritisation", "Ranking engine trained", (summ.get("model_card") or {}).get("test_auc", 0) > 0.6,
           f"AUC {(summ.get('model_card') or {}).get('test_auc')}")

    # 3. worklist
    s, wl, _ = call("GET", "/api/worklist")
    items = wl.get("items", []) if isinstance(wl, dict) else []
    record("Worklist", "Open items returned", len(items) > 100, f"{len(items)} items")
    scores = [i["score"] for i in items]
    record("Worklist", "Ranked by priority score", scores == sorted(scores, reverse=True), f"top {scores[:3]}")
    record("Worklist", "Every item has action + queue", all(i["action"] and i["queue"] for i in items), "")
    with_deadline = [i for i in items if i.get("due_date")]
    record("Rules", "Deadlines computed", len(with_deadline) > 100, f"{len(with_deadline)} with a due date")

    # 4. claim detail + AI explanation
    top = next((i for i in items if i.get("group") != "277CA"), items[0] if items else {})  # an 835 denial: it has a remittance and a letter
    s, det, _ = call("GET", f"/api/claims/{top.get('claim_id')}")
    work = [d for d in det.get("decisions", []) if d.get("workable")] if isinstance(det, dict) else []
    d0 = work[0] if work else {}
    record("Claim view", "Claim + 837 lines + 835 remit", s == 200 and det.get("remit") and det.get("claim", {}).get("lines"),
           top.get("claim_id"))
    record("Claim view", "Decision has cause, steps, checks", bool(d0.get("root_cause") and d0.get("steps") and d0.get("checks") is not None),
           d0.get("root_cause", "")[:80])
    record("Claim view", "Policy citations attached", bool((d0.get("explanation") or {}).get("citations")),
           ", ".join(c["id"] for c in (d0.get("explanation") or {}).get("citations", [])))
    s, det2, dt = call("GET", f"/api/claims/{top.get('claim_id')}?explain=true", timeout=180)
    ex = next((d.get("explanation") for d in det2.get("decisions", []) if d.get("workable")), {}) if isinstance(det2, dict) else {}
    by = (ex or {}).get("by", "")
    record("AI", "Live AI explanation", by.startswith("azure:"), f"by {by} in {dt:.1f}s; {(ex or {}).get('model_error', '')}",
           warn=mode != "azure")
    record("AI", "Action stays with the rules", all(d.get("action") == w.get("action") for d, w in
           zip([d for d in det2.get("decisions", []) if d.get("workable")], work)), "rule action unchanged after AI")

    # 5. letter
    s, letter, dt = call("POST", f"/api/decisions/{d0.get('id')}/letter", timeout=180)
    record("Appeals", "Letter drafted", s == 200 and top.get("claim_id", "?") in letter.get("text", ""),
           f"by {letter.get('by')} in {dt:.1f}s")

    # 6. live remittance ingestion + Teams alerts
    s, files, _ = call("GET", "/api/demo-files")
    names = files.get("files", []) if isinstance(files, dict) else []
    record("Ingestion", "Clearinghouse files available", len(names) >= 4 and any(n.startswith("277CA") for n in names)
           and any(n.startswith("277_") for n in names), ", ".join(names))
    for n in names:
        s, r, dt = call("POST", f"/api/demo-files/{n}/ingest", timeout=180)
        if not isinstance(r, dict):
            r = {"error": f"HTTP {s}: {str(r)[:60]}"}
        ok = s == 200 and r.get("status") == "PROCESSED" and not r.get("unmatched") and r.get("unbalanced", 0) == 0
        if n.startswith("277CA"):
            ok = ok and r.get("rejected") == 3 and r.get("accepted") == 5 and r.get("denials") == 3
            detail = f"{r.get('claims')} claims: {r.get('accepted')} accepted, {r.get('rejected')} rejected, {r.get('alerts')} alerts in {dt:.1f}s"
        elif n.startswith("277_"):
            ok = ok and r.get("kind") == "277" and (r.get("in_process"), r.get("paid"), r.get("needs_action")) == (3, 1, 2)
            detail = (f"{r.get('claims')} statuses: {r.get('in_process')} in process, {r.get('paid')} paid, "
                      f"{r.get('needs_action')} need action, {r.get('alerts')} alerts in {dt:.1f}s")
        else:
            detail = f"{r.get('claims')} claims, {r.get('denials')} denials, {r.get('alerts')} alerts in {dt:.1f}s"
        record("Ingestion", f"Parse + decide {n[:22]}", ok, detail if ok else f"HTTP {s}: {r.get('error') or r.get('detail') or r}")
        if n.startswith("277CA") and ok:
            dets = [call("GET", f"/api/claims/{i['claim_id']}")[1] for i in r.get("new_items", [])]
            rej = [d for det in dets if isinstance(det, dict) for d in det.get("decisions", []) if d.get("source") == "277CA"]
            record("Rejections", "277CA rejections routed, not appealed",
                   len(rej) == 3 and {d.get("queue") for d in rej} == {"REGISTRATION", "BILLING", "CODING"}
                   and all(d.get("action") == "CORRECT_AND_RESUBMIT" and (d.get("deadline") or {}).get("type") == "TIMELY_FILING" for d in rej),
                   ", ".join(f"{d.get('claim_id')} {d.get('carc')} -> {d.get('queue')} ({(d.get('deadline') or {}).get('days_left')}d)" for d in rej))
            if rej:
                sl, _, _ = call("POST", f"/api/decisions/{rej[0].get('id')}/letter")
                record("Rejections", "No appeal letter for a rejection", sl == 404, f"HTTP {sl}")
    s, summ2, _ = call("GET", "/api/summary")
    record("Teams", "Alert cards generated", len(summ2.get("alerts", [])) >= 2,
           f"{len(summ2.get('alerts', []))} cards; delivered to Teams: {sum(1 for a in summ2.get('alerts', []) if a.get('delivered'))}")
    raw, ctype = multipart("broken.txt", b"this is not an X12 file")
    s, q, _ = call("POST", "/api/ingest", raw=raw, ctype=ctype)
    record("Ingestion", "Bad file quarantined, not crashed", s == 200 and q.get("status") == "QUARANTINED", q.get("error", ""))

    # 7. human in the loop
    s, wl2, _ = call("GET", "/api/worklist")
    it = wl2.get("items", [])
    s, k_before, _ = call("GET", "/api/knowledge")
    s, a, _ = call("POST", f"/api/decisions/{it[0]['id']}/feedback", body={"verdict": "APPROVE"})
    record("Feedback", "Approve moves item to resolved", s == 200 and a.get("status") == "DONE", it[0]["claim_id"])
    s, o, _ = call("POST", f"/api/decisions/{it[1]['id']}/feedback",
                   body={"verdict": "OVERRIDE", "action": "WRITE_OFF", "note": "Verification run override"})
    s, k_after, _ = call("GET", "/api/knowledge")
    record("Feedback", "Override becomes a precedent", o.get("status") == "DONE" and len(k_after["cards"]) == len(k_before["cards"]) + 1,
           f"cards {len(k_before['cards'])} -> {len(k_after['cards'])}")
    s, bad, _ = call("POST", f"/api/decisions/{it[2]['id']}/feedback", body={"verdict": "OVERRIDE", "action": "NOPE"})
    record("Feedback", "Invalid override rejected", s == 400, f"HTTP {s}")

    # 7b. reporting (what the Power BI report carries) and no prices in the app
    s, rep_, _ = call("GET", "/api/report")
    ok = s == 200 and isinstance(rep_, dict) and rep_.get("trend") and rep_.get("turnaround", {}).get("files_timed", 0) >= 1 \
        and rep_.get("recovery", {}).get("approved_items", 0) >= 1
    record("Reporting", "Trend, turnaround, recovery", bool(ok),
           f"{len(rep_.get('trend', []))} months, files timed {rep_.get('turnaround', {}).get('files_timed')}, "
           f"approved {rep_.get('recovery', {}).get('approved_items')}" if isinstance(rep_, dict) else f"HTTP {s}")
    s, csv_text, _ = call("GET", "/api/report/denials.csv")
    csv_text = csv_text if isinstance(csv_text, str) else ""
    record("Reporting", "Power BI dataset (CSV) export", s == 200 and csv_text.startswith("claim_id,") and "277CA" in csv_text,
           f"{max(0, csv_text.count(chr(10)) - 1)} rows")
    s, js, _ = call("GET", "/static/app.js")
    js = js if isinstance(js, str) else ""
    record("Reporting", "No prices in the web app", s == 200 and "TIERS" not in js and "pricing" not in js.lower(), "cost belongs in the proposal")

    # 8. assistant (same agent as Teams)
    for q, must in [("Top 5 by dollars", "PRH-"), ("What is due this week?", ""), (f"Why was {top.get('claim_id')} denied?", top.get("claim_id")),
                    ("What is the Medicare timely filing limit?", "12"), ("Write me a poem about cats", "")]:
        s, r, dt = call("POST", "/api/chat", body={"message": q}, timeout=180)
        reply = r.get("reply", "") if isinstance(r, dict) else ""
        ok = s == 200 and bool(reply) and (must in reply)
        record("Assistant", q[:34], ok, f"by {r.get('by')} in {dt:.1f}s: {reply[:60]!r}")

    # 9. proof
    s, ev, _ = call("GET", "/api/evals")
    acc = ev.get("accuracy", {})
    record("Quality", "Denial decisions vs ground truth", acc.get("denial", 0) >= 0.95, f"{acc.get('denial')}")
    record("Quality", "Zero unsafe actions", ev.get("must_not_violations") == [], f"{len(ev.get('must_not_violations', []))} violations")
    record("Quality", "Noise filter vs ground truth", acc.get("noise", 0) >= 0.99, f"{acc.get('noise')}")

    # 10. leave the demo clean
    s, rs, dt = call("POST", "/api/demo/reset", timeout=300)
    s2, summ3, _ = call("GET", "/api/summary")
    record("Reset", "Demo data reset to a clean start", s == 200 and summ3.get("completed") == 0 and not summ3.get("alerts"),
           f"{rs.get('claims')} claims reloaded in {dt:.1f}s" if isinstance(rs, dict) else f"HTTP {s}")

    # 11. exposure
    record("Security", "Sign-in required", s == 401 or "login" in str(html).lower()[:2000],
           "open to anyone with the URL - enable Entra ID authentication before sharing", warn=True)

    width = max(len(r[1]) for r in results)
    for area, name, status, detail in results:
        mark = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌"}[status]
        print(f"{mark} {area:<14} {name:<{width}}  {detail}")
    p = sum(r[2] == "PASS" for r in results)
    f = sum(r[2] == "FAIL" for r in results)
    w = sum(r[2] == "WARN" for r in results)
    print(f"\n{p} passed, {w} warnings, {f} failed")
    print("The demo data has been reset: the app is ready for a live demo.")
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
