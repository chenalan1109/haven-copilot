"""Local SQLite store for pipeline results, signed notes and an audit log.

The file is NOT encrypted. It is created with mode 0600 (this account only);
SQLCipher is planned and not built (README, Limitations). Use full-disk
encryption on the machine.

The audit log is a hash chain: each row stores the hash of the row before it,
so changing or deleting a row in the middle is detected by ``verify_audit``.
It is not tamper-proof: someone who can write the file can rebuild the whole
chain, or cut rows off the end. Comparing the head hash with a copy kept
elsewhere detects that.
"""

from __future__ import annotations

import hashlib
import json
import os
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
_AUDIT_COLUMNS = ("prev_hash", "hash")
GENESIS = "0" * 64


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def now() -> str:
    return _now()


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
            have = {row[1] for row in conn.execute("PRAGMA table_info(audit_log)")}
            for column in _AUDIT_COLUMNS:
                if column not in have:
                    conn.execute(f"ALTER TABLE audit_log ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
            # Rows written before the chain existed join it now, in order.
            prev = GENESIS
            for row_id, ts, action, detail, stored in conn.execute("SELECT id, ts, action, detail, hash FROM audit_log ORDER BY id").fetchall():
                if not stored:
                    stored = _row_hash(prev, ts, action, detail)
                    conn.execute("UPDATE audit_log SET prev_hash = ?, hash = ? WHERE id = ?", (prev, stored, row_id))
                prev = stored
            conn.commit()
        finally:
            conn.close()
        os.chmod(config.DB_FILE, 0o600)
        _PREPARED.add(key)


def _row_hash(prev: str, ts: str, action: str, detail: str) -> str:
    return hashlib.sha256(json.dumps([prev, ts, action, detail], ensure_ascii=False).encode()).hexdigest()


def _audit(c, action: str, detail: str) -> None:
    if not c.in_transaction:
        # Take the write lock before reading the last hash, so two writers
        # cannot both chain onto the same row.
        c.execute("BEGIN IMMEDIATE")
    last = c.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    prev, ts = (last[0] if last else GENESIS), _now()
    c.execute("INSERT INTO audit_log (ts, action, detail, prev_hash, hash) VALUES (?, ?, ?, ?, ?)",
              (ts, action, detail, prev, _row_hash(prev, ts, action, detail)))


def verify_audit() -> dict:
    """Walks the chain. ``ok`` is False at the first row whose content no longer
    matches its hash, or whose link to the row before it is broken (a row was
    changed, inserted or deleted). ``head`` is the last hash: keep a copy
    outside this machine to detect a rebuilt chain or rows cut off the end."""
    with connect() as c:
        rows = c.execute("SELECT id, ts, action, detail, prev_hash, hash FROM audit_log ORDER BY id").fetchall()
    prev, last_id = GENESIS, 0
    for row_id, ts, action, detail, prev_hash, stored in rows:
        if prev_hash != prev or stored != _row_hash(prev, ts, action, detail) or (last_id and row_id != last_id + 1):
            return {"ok": False, "rows": len(rows), "first_bad_id": row_id, "head": None}
        prev, last_id = stored, row_id
    return {"ok": True, "rows": len(rows), "first_bad_id": None, "head": prev if rows else None}


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
        rows = c.execute("SELECT ts, action, detail, id, hash FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{"ts": r[0], "action": r[1], "detail": r[2], "id": r[3], "hash": r[4]} for r in rows]
