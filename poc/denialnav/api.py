"""FastAPI app: REST API for the web app and Teams, plus the static web UI.

Run locally:  uvicorn denialnav.api:app --reload
"""
from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import teams
from .agent import CHAT_TOOLS
from .rules import ACTIONS, QUEUES
from .service import Service

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data" / "synthetic"))
DB_PATH = os.getenv("DB_PATH", ":memory:")
MAX_UPLOAD = 5 * 1024 * 1024
# Version of the web client: changes whenever app.js or styles.css change, so browsers never run a stale copy
BUILD = hashlib.sha1(b"".join((WEB / f).read_bytes() for f in ("app.js", "styles.css") if (WEB / f).exists())).hexdigest()[:8]
NO_STORE = {"Cache-Control": "no-store, max-age=0"}
STARTED = time.time()
REPO_DOCS = "https://github.com/git-bonda108/claims-denial-navigator/blob/claude/ecstatic-mayer-suc223/docs"


def partner() -> dict:
    """Optional partner branding for a partner-specific demo (e.g. PARTNER_NAME="Centered Networks")."""
    name = os.getenv("PARTNER_NAME", "").strip()
    return {"name": name, "tagline": os.getenv("PARTNER_TAGLINE", "Built on Microsoft Foundry · a person approves every action" if name else "")}


def site() -> dict:
    """Optional hospital context for a customer-specific demo (e.g. SITE_CONTEXT="25-bed critical access hospital · Epic · Experian Health")."""
    return {"name": os.getenv("SITE_NAME", "").strip(), "context": os.getenv("SITE_CONTEXT", "").strip(),
            "clearinghouse": os.getenv("CLEARINGHOUSE", "Experian Health").strip()}


class Feedback(BaseModel):
    verdict: str
    action: str | None = None
    note: str = ""


class Chat(BaseModel):
    message: str


def create_app(service: Service | None = None) -> FastAPI:
    app = FastAPI(title="Denial Navigator", version="0.1.0")
    state = {"svc": service}

    @app.middleware("http")
    async def cache_headers(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/") or path in ("/", "/explainer"):
            response.headers["Cache-Control"] = "no-store, max-age=0"
        elif path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"  # always revalidate (cheap 304 when unchanged)
        return response

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
        return {"actions": ACTIONS, "queues": QUEUES, "agent_mode": s.agent.mode, "as_of": s.as_of.isoformat(), "build": BUILD, "partner": partner(), "site": site(),
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

    @app.post("/api/demo/reset")
    def reset_demo():
        return svc().reset()

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

    @app.get("/api/agent-card")
    def agent_card():
        """The six things a production agent needs, filled from the running system."""
        s = svc()
        ev = s.evaluate()
        fb = s.store.feedback()
        st = dict(s.agent.stats)
        azure = s.agent.mode == "azure"
        keyless = azure and not os.getenv("AZURE_OPENAI_API_KEY")
        return {
            "owner": {"business_owner": os.getenv("AGENT_OWNER", "Revenue-cycle director, [Hospital]"),
                      "technical_owner": os.getenv("AGENT_TECH_OWNER", "Alif Consulting delivery lead"),
                      "operator": os.getenv("AGENT_OPERATOR", (partner()["name"] or "Partner") + " Managed AgentOps")},
            "authority": {"tools": [{"name": t["function"]["name"], "purpose": t["function"]["description"], "access": "read-only"} for t in CHAT_TOOLS],
                          "actions": list(ACTIONS.values()),
                          "decides": "Rules decide the action, owner and deadline; the AI explains and drafts",
                          "may_propose": "Only for items flagged Manual review",
                          "human_approval": ["Every appeal, write-off and resubmission is approved by a person",
                                             "An override needs a reason and becomes a precedent",
                                             "The agent never sends anything to a payer"]},
            "evaluation": {"decision_accuracy": ev.get("accuracy", {}).get("denial"), "noise_accuracy": ev.get("accuracy", {}).get("noise"),
                           "unsafe_actions": len(ev.get("must_not_violations", [])), "labelled_denials": ev.get("counts", {}).get("denial"),
                           "deadlines_computed": ev.get("deadlines_computed"),
                           "suites": "36 automated tests · 19 business test cases · 60 browser checks · 42 deployment checks",
                           "note": "Synthetic data; the pilot re-scores on the hospital's own de-identified remittances"},
            "identity": {"model": f"Azure OpenAI {s.agent.deployment} in Microsoft Foundry" if azure else "Offline templates (no AI service configured)",
                         "guardrail": "Microsoft Foundry default guardrail: content filters, Prompt Shields for prompt attacks, protected material" if azure else "n/a",
                         "service_identity": "Managed identity, no API keys" if keyless else ("API key" if azure else "n/a"),
                         "user_sign_in": "Microsoft Entra ID (switched off for this public demo)",
                         "queue_scoping": "On" if os.getenv("ENFORCE_QUEUES") == "1" else "Available (off in demo)",
                         "data_location": "Inside the hospital's own Azure tenant"},
            "telemetry": {"ai_calls": st["calls"], "ai_errors": st["errors"],
                          "ai_avg_ms": round(st["total_ms"] / st["calls"]) if st["calls"] else None, "last_ai_call": st["last_call"],
                          "files_processed": s.store.count("files"), "decisions": s.store.count("decisions"),
                          "approvals": sum(f["verdict"] == "APPROVE" for f in fb), "overrides": sum(f["verdict"] == "OVERRIDE" for f in fb),
                          "teams_alerts": len(teams.OUTBOX), "uptime_minutes": round((time.time() - STARTED) / 60),
                          "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds")},
            "runbook": [{"title": "Demo runbook", "url": f"{REPO_DOCS}/DEMO_RUNBOOK.md"},
                        {"title": "Test cases and expected outputs", "url": f"{REPO_DOCS}/TEST_CASES.md"},
                        {"title": "Proof of concept plan", "url": f"{REPO_DOCS}/POC_PLAN.md"},
                        {"title": "74-second explainer", "url": "/explainer"}],
        }

    @app.get("/api/report")
    def report():
        return svc().report()

    @app.get("/api/report/denials.csv")
    def report_csv():
        name = f"denial_navigator_dataset_{svc().as_of:%Y%m%d}.csv"
        return Response(svc().report_csv(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}"', **NO_STORE})

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

        @app.api_route("/", response_class=HTMLResponse, methods=["GET", "HEAD"])
        def index():
            html = (WEB / "index.html").read_text()
            html = html.replace('/static/app.js"', f'/static/app.js?v={BUILD}"').replace('/static/styles.css"', f'/static/styles.css?v={BUILD}"')
            return HTMLResponse(html, headers=NO_STORE)

        @app.api_route("/explainer", methods=["GET", "HEAD"])
        def explainer():
            return FileResponse(WEB / "explainer.html")

        @app.api_route("/explainer.gif", methods=["GET", "HEAD"])
        def explainer_gif():
            return FileResponse(WEB / "media" / "Denial_Navigator_Explainer.gif", media_type="image/gif")

        @app.api_route("/explainer.mp4", methods=["GET", "HEAD"])
        def explainer_mp4():
            return FileResponse(WEB / "media" / "Denial_Navigator_Explainer.mp4", media_type="video/mp4")

    return app


app = create_app()
