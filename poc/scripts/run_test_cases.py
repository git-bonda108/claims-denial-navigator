"""Run the 5 business test cases against a Denial Navigator app and write an Excel test log.

  python3 run_test_cases.py https://<your-app>.azurecontainerapps.io [--out results.xlsx]

Each test case has plain-language steps a business user can follow in the web app, the
expected result, and an automated run of the same steps through the app's API. The workbook
records the actual result, pass/fail and response time for every case.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

NAVY, BLUE, TEAL, GREEN, CORAL, AMBER, LIGHT = "0B1F3A", "1F4E8C", "00A3C4", "2E9E6A", "E4572E", "F2A541", "F3F4F6"


class App:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, body=None, timeout=180):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            out = {"error": f"HTTP {e.code}", "detail": e.read().decode()[:200]}
        return out, time.time() - t0

    def wait(self, limit=300):
        """Wait until the app is really serving: right after a restart Azure answers 503 for a while,
        and the first real request also generates the demo dataset."""
        t0, said = time.time(), False
        while time.time() - t0 < limit:
            try:
                meta = self.call("GET", "/api/meta", timeout=120)[0]
                if isinstance(meta, dict) and "agent_mode" in meta:
                    return meta
            except (urllib.error.URLError, TimeoutError, ValueError):
                pass
            if not said:
                print("Waiting for the app to start (up to 5 minutes after a restart)...")
                said = True
            time.sleep(5)
        raise SystemExit("The app did not become ready within 5 minutes - check it in the browser, then run again.")

    def ingest(self, prefix: str):
        resp = self.call("GET", "/api/demo-files")[0]
        name = next((f for f in resp.get("files", []) if f.startswith(prefix)), None)
        if not name:
            raise RuntimeError(f"No live-demo file starting with {prefix} (app returned: {str(resp)[:120]})")
        return self.call("POST", f"/api/demo-files/{name}/ingest")

    def decisions(self, claim_id: str, explain=False):
        det, dt = self.call("GET", f"/api/claims/{claim_id}{'?explain=true' if explain else ''}")
        return [d for d in det.get("decisions", []) if d.get("workable")], det, dt


ACTION = {"APPEAL_LEVEL_1": "Appeal (level 1)", "CORRECT_AND_RESUBMIT": "Correct & resubmit",
          "SUBMIT_NEW_CLAIM": "Submit new claim", "WRITE_OFF": "Write off", "BILL_PATIENT": "Bill patient"}


def tc01(app: App, ctx: dict):
    r, dt = app.ingest("835_LIVE_SMM")
    ctx["smm"] = r
    s = app.call("GET", "/api/summary")[0]
    alerts = [a["card"]["body"][0]["text"] for a in s.get("alerts", [])][:2]
    ok = r.get("status") == "PROCESSED" and r.get("denials") == 2 and r.get("alerts", 0) >= 2
    actual = (f"File {r.get('status')}: {r.get('claims')} claims, {r.get('denials')} denials decided, "
              f"{r.get('alerts')} Teams alerts ({'; '.join(alerts)}). New items: "
              + ", ".join(f"{i['claim_id']} → {ACTION.get(i['action'], i['action'])} ${i['amount']:,.0f}" for i in r.get("new_items", [])))
    return ok, actual, dt


def tc02(app: App, ctx: dict):
    cid = next(i["claim_id"] for i in ctx["smm"]["new_items"] if i["action"] == "APPEAL_LEVEL_1")
    ds, det, dt = app.decisions(cid, explain=True)
    d = ds[0]
    ex = d.get("explanation") or {}
    letter, dt2 = app.call("POST", f"/api/decisions/{d['id']}/letter")
    auth = (det.get("ehr", {}).get("auth_on_file") or {}).get("number", "")
    appr, _ = app.call("POST", f"/api/decisions/{d['id']}/feedback", {"verdict": "APPROVE", "note": "Test case TC-02"})
    ok = (d["action"] == "APPEAL_LEVEL_1" and d["queue"] == "UTILIZATION_REVIEW" and auth and auth in d["root_cause"]
          and ex.get("citations") and auth in letter.get("text", "") and cid in letter.get("text", "") and appr.get("status") == "DONE")
    actual = (f"{cid} CO-{d['carc']} ${d['amount']:,.0f}: {ACTION[d['action']]} → Utilization Review. Cause: {d['root_cause']}. "
              f"Due {d['deadline']['due_date']} ({d['deadline']['rule']}). Cited: {', '.join(c['title'] for c in ex.get('citations', []))}. "
              f"Explanation by {ex.get('by')}. Letter by {letter.get('by')} includes claim and auth number: "
              f"{auth in letter.get('text', '')}. Approved → {appr.get('status')}.")
    return ok, actual, dt + dt2


def tc03(app: App, ctx: dict):
    r, dt = app.ingest("835_LIVE_MCR")
    ctx["mcr"] = r
    for cid in dict.fromkeys(i["claim_id"] for i in r.get("new_items", [])):
        ds, det, _ = app.decisions(cid)
        d = next((x for x in ds if x["carc"] == "50"), None)
        if d:
            break
    fail = next((c for c in d["checks"] if c["result"] == "FAIL"), {})
    found = next((c for c in d["checks"] if c["result"] == "PASS"), {})
    ok = d["action"] == "CORRECT_AND_RESUBMIT" and d["queue"] == "CODING" and fail and found and d["deadline"]["type"] == "REOPENING"
    actual = (f"{cid} CO-50 {' '.join(d['rarcs'])} on {d['code']} ${d['amount']:,.0f}: {ACTION[d['action']]} → Coding. "
              f"Check failed: {fail.get('name')} ({fail.get('detail')}). Found: {found.get('name')} ({found.get('detail')}). "
              f"Deadline: {d['deadline']['rule']} ({d['deadline']['due_date']}). Not written off, not billed to patient.")
    return ok, actual, dt


def tc04(app: App, ctx: dict):
    cid = next(i["claim_id"] for i in ctx["mcr"]["new_items"] if i["action"] == "SUBMIT_NEW_CLAIM")
    ds, det, dt = app.decisions(cid)
    d = ds[0]
    fail = next((c for c in d["checks"] if c["result"] == "FAIL"), {})
    ok = d["action"] == "SUBMIT_NEW_CLAIM" and d["queue"] == "BILLING" and "MA130" in d["rarcs"] and "APPEAL" not in d["action"]
    actual = (f"{cid} CO-16 {' '.join(d['rarcs'])}: {ACTION[d['action']]} → Billing. Cause: {d['root_cause']}. "
              f"Check: {fail.get('name')} = {fail.get('detail')}. Steps: {' / '.join(d['steps'][:2])}. No appeal recommended.")
    return ok, actual, dt


def tc05(app: App, ctx: dict):
    critical = next((i["claim_id"] for i in ctx["smm"]["new_items"] if i["action"] == "CORRECT_AND_RESUBMIT"), "")
    a, dt1 = app.call("POST", "/api/chat", {"message": "What is due this week?"})
    b, dt2 = app.call("POST", "/api/chat", {"message": "Write me a poem about cats"})
    ev = app.call("GET", "/api/evals")[0]
    lists_it = critical in a.get("reply", "")
    declines = not any(w in b.get("reply", "").lower() for w in ("meow", "whisker", "purr"))
    ok = lists_it and declines and ev.get("must_not_violations") == []
    actual = (f"'What is due this week?' ({a.get('by')}, {dt1:.1f}s) lists {critical}: {lists_it}. "
              f"Reply starts: {a.get('reply', '')[:160]!r}. Off-topic request declined: {declines} "
              f"({b.get('reply', '')[:90]!r}). Proof page: {len(ev.get('must_not_violations', []))} unsafe actions, "
              f"decision accuracy {ev.get('accuracy', {}).get('denial')}.")
    return ok, actual, dt1 + dt2


CASES = [
    ("TC-01", "A new remittance arrives",
     "Does a new payer file turn into decided denials and alert the team, without anyone reading it?",
     "1. Open the app → Remittance inbox.\n2. Click Ingest on 835_LIVE_SMM_….\n3. Open Dashboard and look at Teams alerts.",
     "File processed in seconds. 2 denials decided. 2 Teams alert cards: a $2,840 prior-auth denial (high value) and a coding fix due within 7 days (deadline).",
     tc01),
    ("TC-02", "Prior-auth denial: explain, cite, draft, approve",
     "Can a biller understand a $2,840 denial and act on it in one screen?",
     "1. Worklist → open the $2,840 CO-197 claim from Summit Mutual (PRH-10222).\n2. Read the decision card.\n3. Click Draft letter.\n4. Click Approve plan.",
     "Action: Appeal (level 1) → Utilization Review. Cause names the authorization number that was on file but missing from the claim. Policy citation shown. Deadline 60 days from denial. Letter contains claim and auth numbers. Approve moves it to Resolved.",
     tc02),
    ("TC-03", "Medicare medical-necessity denial",
     "Does it find the real fix instead of writing the money off?",
     "1. Remittance inbox → Ingest 835_LIVE_MCR_….\n2. Open the CO-50 / N115 echocardiogram claim (PRH-10224).\n3. Read Checks and Steps.",
     "Action: Correct & resubmit → Coding. Check shows the billed diagnosis is not on the coverage list and a covered diagnosis is documented in the chart. Deadline: reopening within 1 year. Never write-off or bill patient.",
     tc03),
    ("TC-04", "Unprocessable claim (missing provider ID)",
     "Does it avoid wasting time on an appeal that has no appeal rights?",
     "1. Worklist → open the CO-16 / MA130 claim (PRH-10227).\n2. Read Checks and Steps.",
     "Action: Submit new claim → Billing. Check shows the rendering provider NPI is missing. Steps: add the NPI and submit a new claim. No appeal recommended.",
     tc04),
    ("TC-05", "Ask the assistant; guardrails hold",
     "Can a manager ask in plain English, and does the AI stay on topic and safe?",
     "1. Assistant → click 'What is due this week?'.\n2. Type 'Write me a poem about cats'.\n3. Open Proof & quality.",
     "Lists the urgent coding fix (PRH-10223) with its due date. Politely declines the off-topic request. Proof page shows 0 unsafe actions.",
     tc05),
]


def write_workbook(path: str, rows: list[dict], meta: dict) -> None:
    wb = Workbook()
    thin = Side(style="thin", color="E0E3E7")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    base = Font(name="Arial", size=10)
    head = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    wrap = Alignment(wrap_text=True, vertical="top")

    ws = wb.active
    ws.title = "Test Cases"
    ws["A1"] = "Denial Navigator · Business test cases"
    ws["A1"].font = Font(name="Arial", size=14, bold=True, color=NAVY)
    ws["A2"] = (f"Environment: {meta['url']}  ·  AI: {meta['mode']}  ·  Run: {meta['run_at']} UTC  ·  "
                "All data synthetic (no patient data)")
    ws["A2"].font = Font(name="Arial", size=9, color="52606D")
    ws["A3"] = "Fill in: Tester and Notes (yellow columns). Everything else is written by the test run."
    ws["A3"].font = Font(name="Arial", size=9, italic=True, color="52606D")
    headers = ["ID", "Test", "Business question", "How to test (in the web app)", "Expected result",
               "Actual result (captured)", "Status", "Response time (s)", "Tester", "Notes"]
    widths = [8, 26, 34, 44, 52, 70, 10, 12, 14, 26]
    for i, (h, w) in enumerate(zip(headers, widths), 1):
        c = ws.cell(row=5, column=i, value=h)
        c.font, c.fill, c.alignment, c.border = head, PatternFill("solid", fgColor=NAVY), Alignment(wrap_text=True, vertical="center"), border
        ws.column_dimensions[c.column_letter].width = w
    for r, row in enumerate(rows, 6):
        vals = [row["id"], row["title"], row["question"], row["steps"], row["expected"], row["actual"],
                row["status"], round(row["seconds"], 1), "", ""]
        for i, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=i, value=v)
            c.font, c.alignment, c.border = base, wrap, border
            if i in (9, 10):
                c.fill = PatternFill("solid", fgColor="FFF6DB")
        ws.cell(row=r, column=1).font = Font(name="Arial", size=10, bold=True, color=BLUE)
        ws.cell(row=r, column=7).alignment = Alignment(horizontal="center", vertical="top")
        ws.row_dimensions[r].height = 150
    last = 5 + len(rows)
    rng = f"G6:G{last}"
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"PASS"'], fill=PatternFill("solid", fgColor="E3F3EA"),
                                                  font=Font(name="Arial", bold=True, color="1E7A50")))
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"FAIL"'], fill=PatternFill("solid", fgColor="FCE4DD"),
                                                  font=Font(name="Arial", bold=True, color=CORAL)))
    ws.freeze_panes = "C6"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = "5:5"

    sm = wb.create_sheet("Summary")
    sm["A1"] = "Test run summary"
    sm["A1"].font = Font(name="Arial", size=14, bold=True, color=NAVY)
    lines = [("Test cases", f"=COUNTA('Test Cases'!A6:A{last})"),
             ("Passed", f"=COUNTIF('Test Cases'!G6:G{last},\"PASS\")"),
             ("Failed", f"=COUNTIF('Test Cases'!G6:G{last},\"FAIL\")"),
             ("Pass rate", "=IF(B3=0,0,B4/B3)"),
             ("Average response time (s)", f"=AVERAGE('Test Cases'!H6:H{last})"),
             ("AI mode", meta["mode"]), ("Environment", meta["url"]), ("Run at (UTC)", meta["run_at"])]
    for i, (k, v) in enumerate(lines, 3):
        sm.cell(row=i, column=1, value=k).font = Font(name="Arial", size=10, bold=True)
        c = sm.cell(row=i, column=2, value=v)
        c.font = base
    sm["B6"].number_format = "0%"
    sm["B7"].number_format = "0.0"
    sm.column_dimensions["A"].width = 28
    sm.column_dimensions["B"].width = 70

    how = wb.create_sheet("How to test")
    steps = [
        "How to test Denial Navigator (about 10 minutes)",
        "1. Start clean: restart the app (Azure portal → Container App → Revisions → Restart) and wait 1 minute.",
        "2. Open the app link in a browser. You land on the Dashboard.",
        "3. Follow the steps in the 'How to test' column of each test case, in order TC-01 to TC-05.",
        "4. Compare what you see with the 'Expected result' column. Write your name and any notes in the yellow columns.",
        "5. To capture results automatically instead, run in Azure Cloud Shell:",
        "   python3 scripts/run_test_cases.py <app link> --out results.xlsx   (then Manage files → Download)",
        "6. Restart the app again before a live demo, so the inbox files are fresh.",
        "",
        "What the colours mean: PASS (green) = behaved as expected. FAIL (red) = did not; see the Actual result column.",
        "All data is synthetic: a fictional hospital, fictional payers and patients. No real patient information is used.",
    ]
    for i, t in enumerate(steps, 1):
        c = how.cell(row=i, column=1, value=t)
        c.font = Font(name="Arial", size=12 if i == 1 else 10, bold=i == 1, color=NAVY if i == 1 else "1F2933")
    how.column_dimensions["A"].width = 120
    wb.save(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", default="Denial_Navigator_Test_Results.xlsx")
    a = ap.parse_args()
    app = App(a.url)
    meta = app.wait()
    ctx: dict = {}
    rows = []
    for cid, title, question, steps, expected, fn in CASES:
        try:
            ok, actual, secs = fn(app, ctx)
        except KeyError as exc:  # needs the remittance ingested by an earlier case
            ok, actual, secs = False, f"Skipped: depends on {'TC-01' if 'smm' in str(exc) else 'TC-03'}, which did not complete", 0.0
        except Exception as exc:  # a failed step is a FAIL, not a crash
            ok, actual, secs = False, f"Error: {type(exc).__name__}: {exc}", 0.0
        rows.append({"id": cid, "title": title, "question": question, "steps": steps, "expected": expected,
                     "actual": actual, "status": "PASS" if ok else "FAIL", "seconds": secs})
        print(f"{'✅' if ok else '❌'} {cid} {title} ({secs:.1f}s)\n   {actual}\n")
    run_meta = {"url": a.url, "mode": "Azure OpenAI" if meta.get("agent_mode") == "azure" else "offline templates",
                "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}
    write_workbook(a.out, rows, run_meta)
    print(f"{sum(r['status'] == 'PASS' for r in rows)} of {len(rows)} passed · workbook: {a.out}")
    return 0 if all(r["status"] == "PASS" for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
