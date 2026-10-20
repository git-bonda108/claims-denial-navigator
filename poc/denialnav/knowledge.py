"""Knowledge retrieval over the policy library.

Locally this is tag + keyword scoring over reference/knowledge.yaml. The interface
(`for_decision`, `search`) is what an Azure AI Search adapter would implement.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .refdata import Reference

_WORD = re.compile(r"[a-z0-9]+")
_STOP = set("the a an of to and or for is are be with on in by as at this that it from was were not no".split())


def _tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in _STOP]


class Library:
    def __init__(self, ref: Reference):
        self.ref = ref
        self.cards = {c["id"]: c for c in ref.knowledge}
        self._tf = {cid: Counter(_tokens(c["title"] + " " + c["text"])) for cid, c in self.cards.items()}
        df = Counter(t for tf in self._tf.values() for t in tf)
        n = len(self.cards)
        self._idf = {t: math.log(1 + n / f) for t, f in df.items()}

    def get(self, ids: list[str]) -> list[dict]:
        return [self.cards[i] for i in ids if i in self.cards]

    def for_decision(self, decision: dict, payer_key: str, k: int = 3) -> list[dict]:
        """Cards named by the rule, then the best tag matches for the codes/payer involved."""
        payer = self.ref.payers[payer_key]
        scores: Counter = Counter()
        for cid in decision.get("knowledge", []):
            scores[cid] += 10
        for cid, card in self.cards.items():
            tags = card.get("tags") or {}
            if tags.get("payer") and payer_key not in tags["payer"]:
                scores.pop(cid, None)  # another payer's manual never applies
                continue
            scores[cid] += 3 * (decision["carc"] in tags.get("carc", []))
            scores[cid] += 2 * bool(set(decision.get("rarcs", [])) & set(tags.get("rarc", [])))
            scores[cid] += 3 * (payer_key in tags.get("payer", []))
            scores[cid] += 1 * (payer["type"] in tags.get("payer_type", []))
            scores[cid] += 2 * ((decision.get("code") or "") in tags.get("code", []))
            scores[cid] += 1 * (decision.get("action") in tags.get("action", []))
        return [self.cards[c] for c, s in scores.most_common(k) if s >= 3]

    def search(self, query: str, k: int = 4) -> list[dict]:
        q = _tokens(query)
        scored = []
        for cid, tf in self._tf.items():
            s = sum(self._idf.get(t, 0) * (1 + math.log(tf[t])) for t in q if tf.get(t))
            if s:
                scored.append((s, cid))
        return [self.cards[c] for _, c in sorted(scored, reverse=True)[:k]]


def cite(card: dict) -> dict:
    return {"id": card["id"], "title": card["title"], "source": card["source"],
            "fictional": card["source"].startswith("FICTIONAL")}
