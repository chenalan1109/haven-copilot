"""Local SQLite store for pipeline results, signed notes and an audit log.

The file is not encrypted yet; SQLCipher is planned (see README, Stage II).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS results (session_id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS signed_notes (session_id TEXT PRIMARY KEY, note TEXT NOT NULL, signed_by TEXT NOT NULL, signed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS addenda (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, text TEXT NOT NULL, author TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS verdicts (
    session_id TEXT NOT NULL, transcript_sha256 TEXT NOT NULL, verifier_version TEXT NOT NULL,
    text TEXT NOT NULL, evidence TEXT NOT NULL, verdict TEXT NOT NULL,
    PRIMARY KEY (session_id, transcript_sha256, verifier_version, text, evidence));
"""
# Columns added to signed_notes after the first release; older databases get them on first use.
_SIGNED_COLUMNS = ("transcript_sha256", "note_sha256", "verifier_version")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class AlreadySignedError(Exception):
    pass


class NotSignedError(Exception):
    pass


@contextmanager
def connect():
    """One transaction on a fresh connection, closed afterwards (sqlite3's own
    context manager commits but leaves the connection open)."""
    _prepare()
    conn = sqlite3.connect(config.DB_FILE, timeout=30)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


_PREPARE_LOCK = threading.Lock()
_PREPARED: set[str] = set()


def _prepare() -> None:
    """Creates the tables once per database file. Doing it on every connection
    made several first requests at once fail with "database is locked": each
    tried to change the schema while another held the file."""
    key = str(config.DB_FILE)
    if key in _PREPARED and config.DB_FILE.exists():
        return
    with _PREPARE_LOCK:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(config.DB_FILE, timeout=30)
        try:
            conn.executescript(SCHEMA)
            have = {row[1] for row in conn.execute("PRAGMA table_info(signed_notes)")}
            for column in _SIGNED_COLUMNS:
                if column not in have:
                    conn.execute(f"ALTER TABLE signed_notes ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
            conn.commit()
        finally:
            conn.close()
        _PREPARED.add(key)


def _audit(c, action: str, detail: str) -> None:
    c.execute("INSERT INTO audit_log (ts, action, detail) VALUES (?, ?, ?)", (_now(), action, detail))


def audit(action: str, detail: str) -> None:
    with connect() as c:
        _audit(c, action, detail)


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


def sign_note(session_id: str, note: dict, signed_by: str, confirmed: int = 0, *, transcript_sha256: str = "",
              note_sha256: str = "", verifier_version: str = "", audit_rows: list[tuple[str, str]] = ()) -> dict:
    """Files a signed note. A signed note is part of the clinical record and is
    never overwritten; corrections go in an addendum (add_addendum).

    The note and its audit rows are written in one transaction: either both are
    stored or neither is."""
    signed_at = _now()
    try:
        with connect() as c:
            c.execute(
                "INSERT INTO signed_notes (session_id, note, signed_by, signed_at, transcript_sha256, note_sha256, verifier_version)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, json.dumps(note, ensure_ascii=False), signed_by, signed_at, transcript_sha256, note_sha256, verifier_version),
            )
            _audit(c, "sign_note", f"{session_id} by {signed_by}; {confirmed} flagged sentence(s) kept by therapist; "
                                   f"note_sha256={note_sha256[:16]} transcript_sha256={transcript_sha256[:16]} verifier={verifier_version}")
            for action, detail in audit_rows:
                _audit(c, action, detail)
    except sqlite3.IntegrityError as e:
        if "signed_notes.session_id" not in str(e):
            raise  # not the "already signed" case: nothing was stored, and the caller must know
        raise AlreadySignedError(session_id) from None
    return get_signature(session_id)


def get_signed_note(session_id: str) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT note FROM signed_notes WHERE session_id = ?", (session_id,)).fetchone()
    return json.loads(row[0]) if row else None


def get_signature(session_id: str) -> dict | None:
    with connect() as c:
        row = c.execute(
            "SELECT signed_by, signed_at, transcript_sha256, note_sha256, verifier_version FROM signed_notes WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if not row:
        return None
    return {"session_id": session_id, "signed_by": row[0], "signed_at": row[1],
            "transcript_sha256": row[2], "note_sha256": row[3], "verifier_version": row[4]}


def add_addendum(session_id: str, text: str, author: str) -> list[dict]:
    """Appends a correction or later information to a signed note. Append-only:
    there is no update or delete."""
    with connect() as c:
        if not c.execute("SELECT 1 FROM signed_notes WHERE session_id = ?", (session_id,)).fetchone():
            raise NotSignedError(session_id)
        c.execute("INSERT INTO addenda (session_id, text, author, created_at) VALUES (?, ?, ?, ?)", (session_id, text, author, _now()))
        _audit(c, "addendum", f"{session_id} by {author}; {len(text)} characters")
    return get_addenda(session_id)


def get_addenda(session_id: str) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT text, author, created_at FROM addenda WHERE session_id = ? ORDER BY id", (session_id,)).fetchall()
    return [{"text": r[0], "author": r[1], "created_at": r[2]} for r in rows]


def save_verdicts(session_id: str, transcript_sha256: str, verifier_version: str, verdicts: dict[tuple[str, str], dict]) -> None:
    """Remembers what the server's own verifier said about a sentence (text + cited
    segments), so signing can rely on it instead of a status sent by the browser."""
    with connect() as c:
        c.executemany(
            "INSERT OR REPLACE INTO verdicts VALUES (?, ?, ?, ?, ?, ?)",
            [(session_id, transcript_sha256, verifier_version, text, evidence, json.dumps(v, ensure_ascii=False))
             for (text, evidence), v in verdicts.items()],
        )


def get_verdicts(session_id: str, transcript_sha256: str, verifier_version: str) -> dict[tuple[str, str], dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT text, evidence, verdict FROM verdicts WHERE session_id = ? AND transcript_sha256 = ? AND verifier_version = ?",
            (session_id, transcript_sha256, verifier_version),
        ).fetchall()
    return {(r[0], r[1]): json.loads(r[2]) for r in rows}


def recent_audit(limit: int = 20) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT ts, action, detail FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{"ts": r[0], "action": r[1], "detail": r[2]} for r in rows]
