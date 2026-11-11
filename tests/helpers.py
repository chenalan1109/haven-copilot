"""Shared test set-up: a throwaway copy of the demo data and an in-process server."""

import json
import os
import shutil
import socket
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

os.environ["HAVEN_LLM"] = "demo"

from haven import config, server  # noqa: E402
from haven.orchestrator import Orchestrator  # noqa: E402

REPO_DATA = Path(__file__).resolve().parent.parent / "data"
H = {"X-Haven": "1", "Content-Type": "application/json"}


class IsolatedData:
    """Points config at a temp copy of data/sessions and clients.json, with an empty
    database, so a test can sign, upload or add sessions without touching the repo."""

    def __enter__(self):
        self.saved = (config.DATA_DIR, config.SESSIONS_DIR, config.CLIENTS_FILE, config.DB_FILE)
        self.dir = Path(tempfile.mkdtemp(prefix="haven-test-"))
        shutil.copytree(REPO_DATA / "sessions", self.dir / "sessions")
        shutil.copy(REPO_DATA / "clients.json", self.dir / "clients.json")
        config.DATA_DIR, config.SESSIONS_DIR = self.dir, self.dir / "sessions"
        config.CLIENTS_FILE, config.DB_FILE = self.dir / "clients.json", self.dir / "test.db"
        return self

    def __exit__(self, *exc):
        config.DATA_DIR, config.SESSIONS_DIR, config.CLIENTS_FILE, config.DB_FILE = self.saved
        shutil.rmtree(self.dir, ignore_errors=True)

    def add_session(self, session_id: str, lines: list[tuple[str, str]], client_id: str = "C001", session_no: int = 9, source: str = "script"):
        """Writes a transcript; ``lines`` are (speaker, text)."""
        segments = [{"id": i, "start": float(i), "end": float(i + 1), "speaker": who, "text": text, "speaker_source": source}
                    for i, (who, text) in enumerate(lines, start=1)]
        payload = {"session_id": session_id, "client_id": client_id, "session_no": session_no, "date": "2026-11-12",
                   "simulated": True, "segments": segments}
        (config.SESSIONS_DIR / f"{session_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerCase:
    """Mixin for unittest.TestCase: starts the real Handler on a free port over isolated data."""

    llm = None

    @classmethod
    def setUpClass(cls):
        cls.data = IsolatedData().__enter__()
        cls.saved_port, cls.saved_orch = config.PORT, server.ORCH
        config.PORT = free_port()
        server.ORCH = Orchestrator(llm=cls.llm, use_llm=False)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", config.PORT), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{config.PORT}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        config.PORT, server.ORCH = cls.saved_port, cls.saved_orch
        cls.data.__exit__()

    @classmethod
    def call(self, path, body=None, headers=None, method=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=headers or (H if data is not None else {}),
                                     method=method or ("POST" if data is not None else "GET"))
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.load(e)

    @classmethod
    def draft(self, sid):
        """Opens a session and returns the note as the UI would send it back."""
        status, r = self.call(f"/api/sessions/{sid}")
        assert status == 200, r
        return r, {"template": r["note"]["template"], "sections": {
            k: [{"text": s["text"], "evidence": s["evidence"], "source": s["source"]} for s in v]
            for k, v in r["note"]["sections"].items()}}
