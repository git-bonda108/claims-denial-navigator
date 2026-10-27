from fastapi.testclient import TestClient

from denialnav.api import create_app


def test_api_end_to_end(svc, monkeypatch):
    c = TestClient(create_app(svc))
    assert c.get("/health").json() == {"status": "ok"}
    items = c.get("/api/worklist").json()["items"]
    assert items and items[0]["score"] >= items[-1]["score"]
    det = c.get(f"/api/claims/{items[0]['claim_id']}").json()
    did = next(d["id"] for d in det["decisions"] if d["workable"])
    assert "RE:" in c.post(f"/api/decisions/{did}/letter").json()["text"]
    assert c.post(f"/api/decisions/{did}/feedback", json={"verdict": "APPROVE"}).json()["status"] == "DONE"
    files = c.get("/api/demo-files").json()["files"]
    assert c.post(f"/api/demo-files/{files[0]}/ingest").json()["status"] == "PROCESSED"
    up = c.post("/api/ingest", files={"file": ("x.txt", b"not x12")}).json()
    assert up["status"] == "QUARANTINED"
    assert c.post("/api/chat", json={"message": "summary"}).json()["reply"]
    assert c.get("/api/evals").json()["must_not_violations"] == []
    assert c.get("/").status_code == 200
    assert c.get("/api/claims/PRH-00000").status_code == 404


def test_queue_scoping_s05(svc, monkeypatch):
    monkeypatch.setenv("ENFORCE_QUEUES", "1")
    c = TestClient(create_app(svc))
    rows = c.get("/api/worklist", headers={"X-User-Queue": "CODING"}).json()["items"]
    assert rows and {r["queue"] for r in rows} == {"CODING"}
    other = next(r for r in svc.worklist() if r["queue"] == "UTILIZATION_REVIEW")
    assert c.get(f"/api/claims/{other['claim_id']}", headers={"X-User-Queue": "CODING"}).status_code == 403


def test_live_ingest_runs_ai_in_parallel_and_reset(svc):
    """A live Medicare file has 6 denials; with a 0.5 s AI call each it must finish well under the sequential 3 s."""
    import json
    import threading
    import time
    import types

    calls = []

    class Completions:
        def create(self, model, messages, temperature=0, response_format=None, tools=None):
            calls.append(threading.get_ident())
            time.sleep(0.5)
            p = json.loads(messages[1]["content"].split("\n<untrusted>")[0])
            out = {"narrative": "AI", "steps": [], "documents": [], "citation_ids": [], "proposed_action": None, "confidence": 0.9}
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=json.dumps(out), tool_calls=None))])

    svc.agent.client, svc.agent.mode = types.SimpleNamespace(chat=types.SimpleNamespace(completions=Completions())), "azure"
    c = TestClient(create_app(svc))
    name = next(f for f in c.get("/api/demo-files").json()["files"] if "MCR" in f)
    t0 = time.time()
    r = c.post(f"/api/demo-files/{name}/ingest").json()
    assert r["status"] == "PROCESSED" and r["denials"] == len(calls) > 1
    assert time.time() - t0 < 0.5 * len(calls) - 0.5
    assert all(d["explanation"]["by"].startswith("azure") for d in svc.store.decisions(workable_only=True) if d["claim_id"] in {i["claim_id"] for i in r["new_items"]})

    did = svc.worklist()[0]["id"]
    c.post(f"/api/decisions/{did}/feedback", json={"verdict": "OVERRIDE", "action": "WRITE_OFF", "note": "test"})
    assert c.get("/api/summary").json()["completed"] == 1
    out = c.post("/api/demo/reset").json()
    assert out["claims"] > 0
    s = c.get("/api/summary").json()
    assert s["completed"] == 0 and s["alerts"] == [] and not any(f["name"] == name for f in s["files"])
    assert not any(k["id"].startswith("P") for k in c.get("/api/knowledge").json()["cards"])


def test_browsers_always_get_latest_client(svc):
    from denialnav.api import BUILD
    c = TestClient(create_app(svc))
    r = c.get("/")
    assert "no-store" in r.headers["cache-control"] and f"/static/app.js?v={BUILD}" in r.text and f"/static/styles.css?v={BUILD}" in r.text
    assert c.get("/api/meta").json()["build"] == BUILD
    assert c.get(f"/static/app.js?v={BUILD}").headers["cache-control"] == "no-cache"
    for path in ("/", "/explainer", "/explainer.gif", "/explainer.mp4"):
        assert c.head(path).status_code == 200, path
