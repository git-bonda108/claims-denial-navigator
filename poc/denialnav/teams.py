"""Microsoft Teams proactive alerts as Adaptive Cards.

Posts to a Teams Workflows ("When a Teams webhook request is received") URL in TEAMS_WEBHOOK_URL.
Without it, cards are kept in an in-memory outbox that the web app shows, so the demo still works.
"""
from __future__ import annotations

import json
import os
import urllib.request
from collections import deque

from .rules import ACTIONS

OUTBOX: deque = deque(maxlen=50)
ALERT_AMOUNT = float(os.getenv("ALERT_AMOUNT", "2000"))


def should_alert(d: dict) -> bool:
    band = (d.get("deadline") or {}).get("band")
    return d["workable"] and d["action"] not in ("NO_ACTION", "WRITE_OFF") and (band == "CRITICAL" or d["amount"] >= ALERT_AMOUNT)


def card(d: dict, claim: dict, payer_name: str, app_url: str) -> dict:
    dl = d.get("deadline") or {}
    facts = [{"title": "Claim", "value": f"{d['claim_id']} · {claim['patient']['last']}, {claim['patient']['first'][0]}."},
             {"title": "Payer", "value": payer_name},
             {"title": "Denial", "value": " ".join([f"{d['group']}-{d['carc']}", *d.get("rarcs", []), "on", d.get("code") or "claim"])},
             {"title": "Amount", "value": f"${d['amount']:,.2f}"},
             {"title": "Action", "value": f"{ACTIONS[d['action']]} → {(d.get('queue') or '').replace('_', ' ').title()}"}]
    if dl:
        facts.append({"title": "Due", "value": f"{dl['due_date']} ({dl['days_left']} days)"})
    urgent = dl.get("band") == "CRITICAL"
    return {
        "type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "version": "1.5",
        "body": [
            {"type": "TextBlock", "text": "⏰ Deadline alert" if urgent else "💲 High-value denial", "weight": "Bolder",
             "size": "Medium", "color": "Attention" if urgent else "Warning"},
            {"type": "TextBlock", "text": d["root_cause"], "wrap": True},
            {"type": "FactSet", "facts": facts},
        ],
        "actions": [{"type": "Action.OpenUrl", "title": "Open in Denial Navigator", "url": f"{app_url}/#claim/{d['claim_id']}"}],
    }


def send(card_json: dict) -> dict:
    entry = {"card": card_json, "delivered": False}
    url = os.getenv("TEAMS_WEBHOOK_URL")
    if url:
        body = json.dumps({"type": "message", "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "content": card_json}]}).encode()
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                entry["delivered"] = 200 <= r.status < 300
        except Exception as exc:
            entry["error"] = str(exc)[:200]
    OUTBOX.appendleft(entry)
    return entry
