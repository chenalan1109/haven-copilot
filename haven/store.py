"""Local SQLite store for pipeline results, signed notes and an audit log.

Stage II swaps sqlite3 for SQLCipher so the file is encrypted at rest.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS results (session_id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS signed_notes (session_id TEXT PRIMARY KEY, note TEXT NOT NULL, signed_by TEXT NOT NULL, signed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
"""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_FILE)
    conn.executescript(SCHEMA)
    return conn


def audit(action: str, detail: str) -> None:
    with connect() as c:
        c.execute("INSERT INTO audit_log (ts, action, detail) VALUES (?, ?, ?)", (_now(), action, detail))


def save_result(session_id: str, payload: dict) -> None:
    with connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO results VALUES (?, ?, ?)",
            (session_id, json.dumps(payload, ensure_ascii=False), _now()),
        )


def get_result(session_id: str) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT payload FROM results WHERE session_id = ?", (session_id,)).fetchone()
    return json.loads(row[0]) if row else None


def sign_note(session_id: str, note: dict, signed_by: str) -> dict:
    signed_at = _now()
    with connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO signed_notes VALUES (?, ?, ?, ?)",
            (session_id, json.dumps(note, ensure_ascii=False), signed_by, signed_at),
        )
    audit("sign_note", f"{session_id} by {signed_by}")
    return {"session_id": session_id, "signed_by": signed_by, "signed_at": signed_at}


def get_signed_note(session_id: str) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT note FROM signed_notes WHERE session_id = ?", (session_id,)).fetchone()
    return json.loads(row[0]) if row else None


def get_signature(session_id: str) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT signed_by, signed_at FROM signed_notes WHERE session_id = ?", (session_id,)).fetchone()
    return {"signed_by": row[0], "signed_at": row[1]} if row else None


def recent_audit(limit: int = 20) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT ts, action, detail FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{"ts": r[0], "action": r[1], "detail": r[2]} for r in rows]
