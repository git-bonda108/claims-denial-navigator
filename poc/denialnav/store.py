"""SQLite persistence for the demo (swap for Azure SQL in a pilot)."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY, name TEXT, kind TEXT, received_at TEXT, status TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS claims (claim_id TEXT PRIMARY KEY, payer_key TEXT, data TEXT, ehr TEXT);
CREATE TABLE IF NOT EXISTS remits (claim_id TEXT PRIMARY KEY, payer_key TEXT, remit_date TEXT, data TEXT, file_id INTEGER);
CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY, claim_id TEXT, line_no INTEGER, carc TEXT, data TEXT,
    status TEXT DEFAULT 'OPEN', UNIQUE(claim_id, line_no, carc));
CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY, decision_id INTEGER, verdict TEXT, action TEXT, note TEXT,
    user TEXT, created_at TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript(SCHEMA)

    def count(self, table: str) -> int:
        return self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def add_file(self, name: str, kind: str, status: str, detail: str = "") -> int:
        with self.lock:
            cur = self.db.execute("INSERT INTO files (name, kind, received_at, status, detail) VALUES (?,?,?,?,?)",
                                  (name, kind, now(), status, detail))
            self.db.commit()
            return cur.lastrowid

    def files(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM files ORDER BY id DESC LIMIT ?", (limit,))]

    def put_claims(self, rows: list[tuple]) -> None:
        with self.lock:
            self.db.executemany("INSERT OR REPLACE INTO claims VALUES (?,?,?,?)",
                                [(c["claim_id"], p, json.dumps(c), json.dumps(e)) for c, p, e in rows])
            self.db.commit()

    def claim(self, claim_id: str) -> dict | None:
        r = self.db.execute("SELECT * FROM claims WHERE claim_id=?", (claim_id,)).fetchone()
        return {"payer_key": r["payer_key"], "claim": json.loads(r["data"]), "ehr": json.loads(r["ehr"])} if r else None

    def put_remit(self, claim_id: str, payer_key: str, remit_date: str, data: dict, file_id: int) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO remits VALUES (?,?,?,?,?)", (claim_id, payer_key, remit_date, json.dumps(data), file_id))

    def remit(self, claim_id: str) -> dict | None:
        r = self.db.execute("SELECT * FROM remits WHERE claim_id=?", (claim_id,)).fetchone()
        return {"payer_key": r["payer_key"], "remit_date": r["remit_date"], "remit": json.loads(r["data"])} if r else None

    def put_decision(self, d: dict) -> int:
        with self.lock:
            self.db.execute(
                "INSERT INTO decisions (claim_id, line_no, carc, data) VALUES (?,?,?,?) "
                "ON CONFLICT(claim_id, line_no, carc) DO UPDATE SET data=excluded.data",
                (d["claim_id"], d["line_no"], d["carc"], json.dumps(d)))
            return self.db.execute("SELECT id FROM decisions WHERE claim_id=? AND line_no=? AND carc=?",
                                   (d["claim_id"], d["line_no"], d["carc"])).fetchone()[0]

    def update_decision(self, did: int, data: dict, status: str | None = None) -> None:
        with self.lock:
            if status:
                self.db.execute("UPDATE decisions SET data=?, status=? WHERE id=?", (json.dumps(data), status, did))
            else:
                self.db.execute("UPDATE decisions SET data=? WHERE id=?", (json.dumps(data), did))
            self.db.commit()

    def commit(self) -> None:
        with self.lock:
            self.db.commit()

    def decisions(self, claim_id: str | None = None, workable_only: bool = False) -> list[dict]:
        sql, args = "SELECT id, status, data FROM decisions", ()
        if claim_id:
            sql, args = sql + " WHERE claim_id=?", (claim_id,)
        out = []
        for r in self.db.execute(sql + " ORDER BY id", args):
            d = json.loads(r["data"])
            if workable_only and not d["workable"]:
                continue
            d["id"], d["status"] = r["id"], r["status"]
            out.append(d)
        return out

    def decision(self, did: int) -> dict | None:
        r = self.db.execute("SELECT id, status, data FROM decisions WHERE id=?", (did,)).fetchone()
        if not r:
            return None
        d = json.loads(r["data"])
        d["id"], d["status"] = r["id"], r["status"]
        return d

    def add_feedback(self, did: int, verdict: str, action: str | None, note: str, user: str) -> int:
        with self.lock:
            cur = self.db.execute("INSERT INTO feedback (decision_id, verdict, action, note, user, created_at) VALUES (?,?,?,?,?,?)",
                                  (did, verdict, action, note, user, now()))
            self.db.commit()
            return cur.lastrowid

    def feedback(self, did: int | None = None) -> list[dict]:
        if did is None:
            return [dict(r) for r in self.db.execute("SELECT * FROM feedback ORDER BY id")]
        return [dict(r) for r in self.db.execute("SELECT * FROM feedback WHERE decision_id=? ORDER BY id", (did,))]
