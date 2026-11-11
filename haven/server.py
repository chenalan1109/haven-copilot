"""HTTP server for the therapist UI. Standard library only; binds to localhost by default."""

from __future__ import annotations

import json
import mimetypes
import re
import tempfile
import threading
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config, signing, store
from .agents.verifier import VERIFIER_VERSION, Verifier
from .models import to_dict
from .orchestrator import Orchestrator, get_client, load_clients
from .transcript import ASRError, load_transcript, save_transcript, transcribe_audio

ORCH: Orchestrator | None = None
MAX_UPLOAD = 200 * 1024 * 1024
# What the consent box covers, written to the audit log with each upload.
CONSENT_SCOPE = "v1:recording+local-ai-transcription+speaker-guess+transcript-kept"
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".webm"}
SESSION_ID = re.compile(r"^[A-Za-z0-9-]{1,40}$")
CLIENTS_LOCK = threading.Lock()
# Sent by the UI on every POST. A cross-site page cannot add a custom header
# without a CORS preflight, which this server never approves, so another
# website open in the therapist's browser cannot sign or upload.
CSRF_HEADER = "X-Haven"


def _allowed_hosts() -> set[str]:
    names = {config.HOST, "localhost", "127.0.0.1", "[::1]"}
    return {f"{n}:{config.PORT}" for n in names} | names


class BadRequest(ValueError):
    pass


def _session_id(value: str) -> str:
    """Session ids are upper case everywhere. On a case-insensitive file system
    (macOS) "c001-s04" opens the same file as "C001-S04", and without this the
    one session could be signed twice under two ids."""
    if not SESSION_ID.match(value):
        raise BadRequest("session_id must be letters, digits or '-'")
    return value.upper()


class Refused(Exception):
    """A request the server understands and will not carry out (409)."""

    def __init__(self, message: str, zh: str, **extra):
        super().__init__(message)
        self.zh, self.extra = zh, extra


def _draft(sid: str) -> tuple[dict, object, list[str]]:
    """The stored draft, the transcript and the server's score lines for a session
    that can still be changed."""
    transcript = load_transcript(sid)  # FileNotFoundError: no such session (404)
    if store.get_signature(sid):
        raise Refused("this session is already signed; signed notes are not overwritten",
                      "這次會談已經簽核，簽核後的紀錄不能再修改。需要更正時，請新增「補充說明」。")
    result = store.get_result(sid)
    if result is None:
        raise Refused("no draft has been produced for this session yet", "這次會談還沒有產生紀錄草稿，請先開啟會談。")
    measures = ORCH.measure_sentences(get_client(transcript.client_id), transcript.session_no)
    return result, transcript, measures


def _session_view(sid: str) -> dict:
    """What the session page shows. Once signed, that is the signed note, not the draft."""
    result = store.get_result(sid)
    signature = store.get_signature(sid)
    if result is None:
        result = ORCH.process_session(sid)
    elif not signature and result.get("verification", {}).get("verifier_version") != VERIFIER_VERSION:
        result = ORCH.refresh(result)  # a draft checked under older rules
    result["signature"] = signature
    result["signed"] = bool(signature)
    result["addenda"] = store.get_addenda(sid) if signature else []
    if signature:
        note = store.get_signed_note(sid)
        result["note"] = note
        result["verification"] = signing.summarize(note)
        result["risk_dismissals"] = note.get("risk_dismissals", [])
        result["risk_uncovered"] = []
    else:
        result.setdefault("risk_uncovered", signing.uncovered_risk(result["risk"], result["note"]))
    return result


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

    def _error(self, status, message, zh=None, **extra):
        # "error" is for logs and scripts; "message_zh" is what the UI shows the therapist.
        self._json({"error": message, **({"message_zh": zh} if zh else {}), **extra}, status)

    def _host_ok(self) -> bool:
        # Rejects DNS-rebinding: a hostile domain pointed at 127.0.0.1 still
        # sends its own name in the Host header.
        return self.headers.get("Host", "") in _allowed_hosts()

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
        if not self._host_ok():
            return self._error(HTTPStatus.FORBIDDEN, "unexpected Host header")
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
                    "llm_endpoint": ORCH.llm.url if ORCH.llm else None,
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
                return self._json(_session_view(_session_id(parts[2])))
            if parts == ["api", "audit"]:
                return self._json(store.recent_audit())
            return self._error(HTTPStatus.NOT_FOUND, "unknown endpoint")
        except BadRequest as e:
            return self._error(HTTPStatus.BAD_REQUEST, str(e))
        except (KeyError, FileNotFoundError):
            return self._error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self):
        if not self._host_ok():
            return self._error(HTTPStatus.FORBIDDEN, "unexpected Host header")
        if self.headers.get(CSRF_HEADER) != "1":
            return self._error(HTTPStatus.FORBIDDEN, f"missing {CSRF_HEADER} header")
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        query = parse_qs(url.query)
        try:
            if len(parts) == 4 and parts[1] == "sessions":
                sid = _session_id(parts[2])
                if parts[3] == "process":
                    return self._process(sid, query)
                if parts[3] == "verify":
                    return self._verify(sid)
                if parts[3] == "sign":
                    return self._sign(sid)
                if parts[3] == "addendum":
                    return self._addendum(sid)
            if parts == ["api", "upload"]:
                return self._upload(query)
            return self._error(HTTPStatus.NOT_FOUND, "unknown endpoint")
        except Refused as e:
            return self._error(HTTPStatus.CONFLICT, str(e), e.zh, **e.extra)
        except store.AlreadySignedError:
            return self._error(HTTPStatus.CONFLICT, "this session is already signed; signed notes are not overwritten",
                               "這次會談已經簽核，簽核後的紀錄不能再修改。需要更正時，請新增「補充說明」。")
        except (KeyError, FileNotFoundError):
            return self._error(HTTPStatus.NOT_FOUND, "not found", "找不到這次會談。")
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            return self._error(HTTPStatus.BAD_REQUEST, str(e), "送出的資料格式不正確。")

    def _payload(self) -> dict:
        payload = json.loads(self._body() or b"{}")
        if not isinstance(payload, dict):
            raise BadRequest("the request body must be a JSON object")
        return payload

    def _process(self, sid, query):
        template = query.get("template", ["SOAP"])[0]
        if template not in ("SOAP", "DAP"):
            return self._error(HTTPStatus.BAD_REQUEST, "template must be SOAP or DAP")
        result = ORCH.process_session(sid, template)  # refuses a signed session
        result["signature"], result["signed"], result["addenda"] = None, False, []
        return self._json(result)

    def _verify(self, sid):
        """Re-checks the note as the therapist has edited it. Only the sentence
        texts, their citations and the confirmations are read from the request."""
        payload = self._payload()
        result, transcript, measures = _draft(sid)
        note, verification, _ = signing.check(sid, transcript, payload, result["note"]["template"], result["note"].get("engine", ""), measures, ORCH.verifier)
        signing.remember(sid, note)
        store.audit("verify", f"{sid} {verification['supported']}/{verification['total']} supported")
        return self._json({"note": to_dict(note), "verification": verification,
                           "risk_uncovered": signing.uncovered_risk(result["risk"], note)})

    def _sign(self, sid):
        payload = self._payload()
        signed_by = payload.get("signed_by")
        if not isinstance(signed_by, str) or not signed_by.strip() or len(signed_by) > 80 or "note" not in payload:
            return self._error(HTTPStatus.BAD_REQUEST, "signed_by and note are required", "請填寫簽核心理師姓名。")
        dismissals = signing.parse_dismissals(payload.get("risk_dismissals"))
        result, transcript, measures = _draft(sid)
        # The rule lives here, not in the UI. Sentences the server has not judged
        # before are checked by the rule layers only: fast, and never more lenient
        # than the full check the therapist saw.
        note, verification, forged = signing.check(sid, transcript, payload["note"], result["note"]["template"], result["note"].get("engine", ""), measures, Verifier(None))
        if forged:
            raise Refused(f"{len(forged)} score line(s) do not match the questionnaire data",
                          f"有 {len(forged)} 句量表句和量表資料不一致。量表句由系統依量表資料產生，不能修改；請還原後再簽核。", blocking=forged)
        if verification["total"] == 0:
            raise Refused("the note has no sentences", "紀錄是空的，不能簽核。請至少寫下一句引用逐字稿的紀錄。")
        blocking = signing.blocking_sentences(note)
        if blocking:
            raise Refused(f"{len(blocking)} sentence(s) unverified, unsupported, or held for confirmation; re-verify, edit or confirm them first",
                          f"還有 {len(blocking)} 句沒有通過驗證（無支持證據、與風險有關而支持不足，或被本機模型否決）。請先修改、刪除，或逐句按「確認無誤」，再重新驗證。",
                          blocking=[s.text for s in blocking])
        risk = to_dict(ORCH.risk.run(transcript))
        known = {f["segment_id"] for f in risk["flags"]}
        dismissals = [d for d in dismissals if d["segment_id"] in known]
        uncovered = signing.uncovered_risk(risk, note, dismissals)
        if uncovered:
            where = "、".join(f"#{u['segment_id']}" for u in uncovered)
            raise Refused(f"{len(uncovered)} high-level risk cue(s) are not in the note and not left out with a reason",
                          f"逐字稿 {where} 的風險線索還沒有寫進紀錄。請補寫並引用該段，或在風險面板按「不納入紀錄」並填寫理由。",
                          risk_uncovered=uncovered)
        kept = sum(1 for s in note.sentences() if s.status != "supported" and s.confirmed_by_therapist)
        signed = signing.signed_form(note, dismissals)
        signature = store.sign_note(
            sid, signed, signed_by.strip(), kept,
            transcript_sha256=signing.transcript_sha256(sid), note_sha256=signing.note_sha256(signed), verifier_version=VERIFIER_VERSION,
            audit_rows=[("risk_cue_left_out", f"{sid} #{d['segment_id']}: {d['reason']}") for d in dismissals],
        )
        return self._json(signature)

    def _addendum(self, sid):
        payload = self._payload()
        text, author = payload.get("text"), payload.get("author")
        if not isinstance(text, str) or not text.strip() or len(text) > 4000 or not isinstance(author, str) or not author.strip() or len(author) > 80:
            return self._error(HTTPStatus.BAD_REQUEST, "text and author are required", "請填寫補充說明的內容和姓名。")
        load_transcript(sid)
        try:
            return self._json({"addenda": store.add_addendum(sid, text.strip(), author.strip())})
        except store.NotSignedError:
            raise Refused("an addendum can only be added to a signed note", "這次會談還沒有簽核，草稿可以直接修改，不需要補充說明。") from None

    def _upload(self, query):
        client_id = query.get("client", [""])[0]
        session_id = _session_id(query.get("session_id", [""])[0])  # upper case
        if query.get("consent", [""])[0] != "1":
            return self._error(HTTPStatus.BAD_REQUEST, "the client's written consent to recording is required")
        if (config.SESSIONS_DIR / f"{session_id}.json").exists():
            return self._error(HTTPStatus.CONFLICT, "a session with this id already exists")
        simulated = query.get("simulated", ["1"])[0] == "1"
        client = get_client(client_id)
        suffix = Path(self.headers.get("X-Filename", "audio.wav")).suffix.lower()
        if suffix not in AUDIO_SUFFIXES:
            suffix = ".wav"
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_UPLOAD:
            return self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "upload too large")
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            # Streamed to the temp file, so a long recording is not held in memory.
            while length > 0:
                chunk = self.rfile.read(min(length, 1 << 20))
                if not chunk:
                    break
                tmp.write(chunk)
                length -= len(chunk)
            tmp.flush()
            try:
                t = transcribe_audio(Path(tmp.name), session_id, client_id, len(client.get("sessions", [])) + 1, date.today().isoformat(), simulated)
            except ImportError:
                return self._error(HTTPStatus.NOT_IMPLEMENTED, "faster-whisper is not installed")
            except ASRError as e:
                return self._error(HTTPStatus.BAD_GATEWAY, f"speech-to-text server at {config.ASR_URL}: {e}")
            except OSError:
                return self._error(HTTPStatus.SERVICE_UNAVAILABLE, f"speech-to-text server not reachable at {config.ASR_URL}")
        # The raw audio is never kept: the temp file is deleted on leaving the block.
        labelled = ORCH.speakers.run(t)
        save_transcript(t)
        with CLIENTS_LOCK:  # two uploads at once must not drop each other's session
            clients = load_clients()
            for c in clients:
                if c["id"] == client_id and session_id not in c.setdefault("sessions", []):
                    c["sessions"].append(session_id)
            tmp_file = config.CLIENTS_FILE.with_suffix(".tmp")
            tmp_file.write_text(json.dumps(clients, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tmp_file.replace(config.CLIENTS_FILE)
        store.audit("transcribe_upload", f"{session_id} consent={CONSENT_SCOPE} simulated={int(simulated)} asr={config.ASR_BACKEND} speakers_guessed={labelled}/{len(t.segments)}; audio deleted after ASR")
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
