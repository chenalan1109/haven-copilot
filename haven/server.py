"""HTTP server for the therapist UI. Standard library only; binds to localhost by default."""

from __future__ import annotations

import json
import mimetypes
import re
import tempfile
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config, store
from .models import Note, NoteSentence, to_dict
from .orchestrator import Orchestrator, get_client, load_clients
from .transcript import load_transcript, save_transcript, transcribe_audio

ORCH: Orchestrator | None = None
MAX_UPLOAD = 200 * 1024 * 1024
SESSION_ID = re.compile(r"^[A-Za-z0-9-]{1,40}$")


def _client_summary(c: dict) -> dict:
    alerts = ORCH.outcome.run(c)["alerts"]
    return {
        "id": c["id"],
        "alias": c["alias"],
        "presenting_concern": c["presenting_concern"],
        "sessions": c.get("sessions", []),
        "alert_count": len(alerts),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "Haven/0.1"

    def log_message(self, fmt, *args):  # keep transcripts out of console logs
        pass

    def _json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, message):
        self._json({"error": message}, status)

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_UPLOAD:
            raise ValueError("upload too large")
        return self.rfile.read(length)

    def _static(self, path: str):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        file = (config.WEB_DIR / rel).resolve()
        if config.WEB_DIR.resolve() not in file.parents or not file.is_file():
            return self._error(HTTPStatus.NOT_FOUND, "not found")
        data = file.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", (mimetypes.guess_type(file.name)[0] or "application/octet-stream") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        query = parse_qs(url.query)
        try:
            if parts[:1] != ["api"]:
                return self._static(url.path)
            if parts == ["api", "status"]:
                return self._json({
                    "engine": ORCH.engine,
                    "bind": f"{config.HOST}:{config.PORT}",
                    "llm_endpoint": config.LLM_URL if ORCH.llm else None,
                    "cloud_calls": 0,
                })
            if parts == ["api", "clients"]:
                return self._json([_client_summary(c) for c in load_clients()])
            if len(parts) == 4 and parts[1] == "clients" and parts[3] == "brief":
                return self._json(ORCH.brief(parts[2]))
            if len(parts) == 4 and parts[1] == "clients" and parts[3] == "ask":
                q = query.get("q", [""])[0].strip()
                if not q:
                    return self._error(HTTPStatus.BAD_REQUEST, "q is required")
                store.audit("ask", f"{parts[2]}")
                return self._json(ORCH.memory.ask(get_client(parts[2]), q))
            if len(parts) == 3 and parts[1] == "sessions":
                sid = parts[2]
                result = store.get_result(sid) or ORCH.process_session(sid)
                result["signature"] = store.get_signature(sid)
                return self._json(result)
            if parts == ["api", "audit"]:
                return self._json(store.recent_audit())
            return self._error(HTTPStatus.NOT_FOUND, "unknown endpoint")
        except (KeyError, FileNotFoundError):
            return self._error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        query = parse_qs(url.query)
        try:
            if len(parts) == 4 and parts[1] == "sessions" and parts[3] == "process":
                template = query.get("template", ["SOAP"])[0]
                if template not in ("SOAP", "DAP"):
                    return self._error(HTTPStatus.BAD_REQUEST, "template must be SOAP or DAP")
                result = ORCH.process_session(parts[2], template)
                result["signature"] = None
                return self._json(result)
            if len(parts) == 4 and parts[1] == "sessions" and parts[3] == "verify":
                # Re-checks the sentences the therapist edited (sent as "unchecked"); the rest keep their result.
                payload = json.loads(self._body() or b"{}")
                note = Note(
                    template=payload["template"],
                    engine=payload.get("engine", ""),
                    sections={k: [NoteSentence(
                        text=s["text"],
                        evidence=[int(e) for e in s.get("evidence", [])],
                        status=s.get("status", "unchecked"),
                        support=float(s.get("support", 0.0)),
                        reason=s.get("reason", ""),
                    ) for s in v] for k, v in payload["sections"].items()},
                )
                verification = ORCH.verifier.run(note, load_transcript(parts[2]))
                return self._json({"note": to_dict(note), "verification": verification})
            if len(parts) == 4 and parts[1] == "sessions" and parts[3] == "sign":
                payload = json.loads(self._body() or b"{}")
                if not payload.get("signed_by") or "note" not in payload:
                    return self._error(HTTPStatus.BAD_REQUEST, "signed_by and note are required")
                return self._json(store.sign_note(parts[2], payload["note"], payload["signed_by"]))
            if parts == ["api", "upload"]:
                return self._upload(query)
            return self._error(HTTPStatus.NOT_FOUND, "unknown endpoint")
        except (KeyError, FileNotFoundError):
            return self._error(HTTPStatus.NOT_FOUND, "not found")
        except (ValueError, json.JSONDecodeError) as e:
            return self._error(HTTPStatus.BAD_REQUEST, str(e))

    def _upload(self, query):
        client_id = query.get("client", [""])[0]
        session_id = query.get("session_id", [""])[0]
        if not SESSION_ID.match(session_id):
            return self._error(HTTPStatus.BAD_REQUEST, "session_id must be letters, digits or '-'")
        client = get_client(client_id)
        suffix = Path(self.headers.get("X-Filename", "audio.wav")).suffix or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            tmp.write(self._body())
            tmp.flush()
            try:
                t = transcribe_audio(Path(tmp.name), session_id, client_id, len(client.get("sessions", [])) + 1, date.today().isoformat())
            except ImportError:
                return self._error(HTTPStatus.NOT_IMPLEMENTED, "faster-whisper is not installed")
        # The raw audio is never kept: the temp file is deleted on leaving the block.
        save_transcript(t)
        clients = load_clients()
        for c in clients:
            if c["id"] == client_id and session_id not in c.setdefault("sessions", []):
                c["sessions"].append(session_id)
        config.CLIENTS_FILE.write_text(json.dumps(clients, ensure_ascii=False, indent=2), encoding="utf-8")
        store.audit("transcribe_upload", f"{session_id} audio deleted after ASR")
        return self._json(ORCH.process_session(session_id))


def serve() -> None:
    global ORCH
    ORCH = Orchestrator()
    httpd = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    print(f"Haven running at http://{config.HOST}:{config.PORT}  (engine: {ORCH.engine})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
