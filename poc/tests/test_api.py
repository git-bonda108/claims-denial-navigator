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
