"""FastAPI app: REST API for the web app and Teams, plus the static web UI.

Run locally:  uvicorn denialnav.api:app --reload
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .rules import ACTIONS, QUEUES
from .service import Service

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data" / "synthetic"))
DB_PATH = os.getenv("DB_PATH", ":memory:")
MAX_UPLOAD = 5 * 1024 * 1024


class Feedback(BaseModel):
    verdict: str
    action: str | None = None
    note: str = ""


class Chat(BaseModel):
    message: str


def create_app(service: Service | None = None) -> FastAPI:
    app = FastAPI(title="Denial Navigator", version="0.1.0")
    state = {"svc": service}

    def svc() -> Service:
        if state["svc"] is None:
            state["svc"] = Service(DATA_DIR, DB_PATH)
            state["svc"].bootstrap()
        return state["svc"]

    def user(principal: str | None) -> str:
        return principal or "demo.user"

    def check_queue(row_queue: str | None, user_queue: str | None) -> None:
        """Optional queue-based access: when a user is scoped to a queue (header set by the identity layer),
        they may only open items routed to it."""
        if os.getenv("ENFORCE_QUEUES") == "1" and user_queue and row_queue and row_queue != user_queue:
            raise HTTPException(403, f"Your role is limited to the {user_queue} queue")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/meta")
    def meta():
        s = svc()
        return {"actions": ACTIONS, "queues": QUEUES, "agent_mode": s.agent.mode, "as_of": s.as_of.isoformat(),
                "manifest": {k: v for k, v in s.manifest.items() if k != "providers"},
                "payers": {k: v["name"] for k, v in s.ref.payers.items()}}

    @app.get("/api/summary")
    def summary():
        return svc().summary()

    @app.get("/api/worklist")
    def worklist(queue: str | None = None, band: str | None = None, action: str | None = None, payer: str | None = None,
                 status: str = "OPEN", x_user_queue: str | None = Header(default=None)):
        if os.getenv("ENFORCE_QUEUES") == "1" and x_user_queue:
            queue = x_user_queue
        return {"items": svc().worklist(queue, band, action, payer, status or None)}

    @app.get("/api/claims/{claim_id}")
    def claim(claim_id: str, explain: bool = False, x_user_queue: str | None = Header(default=None)):
        det = svc().claim_detail(claim_id.upper(), explain=explain)
        if not det:
            raise HTTPException(404, "Claim not found")
        for d in det["decisions"]:
            if d["workable"]:
                check_queue(d["queue"], x_user_queue)
        return det

    @app.post("/api/decisions/{decision_id}/feedback")
    def feedback(decision_id: int, body: Feedback, x_ms_client_principal_name: str | None = Header(default=None)):
        r = svc().feedback(decision_id, body.verdict.upper(), body.action, body.note, user(x_ms_client_principal_name))
        if "error" in r:
            raise HTTPException(400, r["error"])
        return r

    @app.post("/api/decisions/{decision_id}/letter")
    def letter(decision_id: int):
        r = svc().letter(decision_id)
        if "error" in r:
            raise HTTPException(404, r["error"])
        return r

    @app.post("/api/ingest")
    async def ingest(file: UploadFile = File(...)):
        raw = await file.read(MAX_UPLOAD + 1)
        if len(raw) > MAX_UPLOAD:
            raise HTTPException(413, "File too large for the demo (5 MB)")
        return svc().ingest(file.filename or "upload.txt", raw.decode("utf-8", errors="replace"))

    @app.get("/api/demo-files")
    def demo_files():
        inbox = svc().data_dir / "demo_inbox"
        return {"files": sorted(p.name for p in inbox.glob("*.txt"))} if inbox.exists() else {"files": []}

    @app.post("/api/demo-files/{name}/ingest")
    def ingest_demo(name: str):
        p = svc().data_dir / "demo_inbox" / Path(name).name
        if not p.exists():
            raise HTTPException(404, "Demo file not found")
        return svc().ingest(p.name, p.read_text())

    @app.get("/api/demo-files/{name}", response_class=PlainTextResponse)
    def demo_file(name: str):
        p = svc().data_dir / "demo_inbox" / Path(name).name
        if not p.exists():
            raise HTTPException(404, "Demo file not found")
        return p.read_text()

    @app.post("/api/chat")
    def chat(body: Chat):
        s = svc()
        return s.agent.chat(body.message[:2000], s)

    @app.get("/api/evals")
    def evals():
        return svc().evaluate()

    @app.get("/api/knowledge")
    def knowledge(q: str = ""):
        s = svc()
        cards = s.library.search(q) if q else list(s.library.cards.values())
        return {"cards": cards}

    if WEB.exists():
        app.mount("/static", StaticFiles(directory=WEB), name="static")

        @app.get("/")
        def index():
            return FileResponse(WEB / "index.html")

        @app.get("/explainer")
        def explainer():
            return FileResponse(WEB / "explainer.html")

        @app.get("/explainer.gif")
        def explainer_gif():
            return FileResponse(WEB / "media" / "Denial_Navigator_Explainer.gif", media_type="image/gif")

        @app.get("/explainer.mp4")
        def explainer_mp4():
            return FileResponse(WEB / "media" / "Denial_Navigator_Explainer.mp4", media_type="video/mp4")

    return app


app = create_app()
