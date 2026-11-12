"""HTTP server for the therapist UI. Standard library only; binds to localhost by default."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import tempfile
import threading
import traceback
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config, files, llm, signing, store
from .agents.verifier import VERIFIER_VERSION, Verifier
from .models import to_dict
from .orchestrator import Orchestrator, get_client, load_clients
from .transcript import ASRError, load_transcript, save_transcript, transcribe_audio

ORCH: Orchestrator | None = None
MAX_UPLOAD = 200 * 1024 * 1024  # a session recording
MAX_JSON = 2 * 1024 * 1024  # a note, a signature, an addendum
# A connection that sends nothing for this long is closed, so half-open
# connections cannot hold threads for ever (slow-loris).
CONNECTION_TIMEOUT = 30
# What the consent box covers, written to the audit log with each upload.
CONSENT_SCOPE = "v1:recording+local-ai-transcription+speaker-guess+transcript-kept"
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".webm"}
SESSION_ID = re.compile(r"^[A-Za-z0-9-]{1,40}$")
CLIENTS_LOCK = threading.Lock()
# Uploads being transcribed: session id -> (client id, session number). Guarded by
# CLIENTS_LOCK. Transcription takes minutes; without the reservation two uploads
# with the same id both pass the "exists" check and the second replaces the first.
UPLOADING: dict[str, tuple[str, int]] = {}
_LOCKS_GUARD = threading.Lock()
_SESSION_LOCKS: dict[str, threading.Lock] = {}
# Sent by the UI on every API request, GET included. A cross-site page cannot
# add a custom header without a CORS preflight, which this server never
# approves, so another website open in the therapist's browser cannot sign,
# upload, start the model or write to the audit log (not even with an <img>).
CSRF_HEADER = "X-Haven"
# On every response. The UI has no inline script or style and loads nothing
# from another origin, so the policy can be strict; the page cannot be framed.
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _allowed_hosts() -> set[str]:
    names = {config.HOST, "localhost", "127.0.0.1", "[::1]"}
    return {f"{n}:{config.PORT}" for n in names} | names


class BadRequest(ValueError):
    pass


class HttpError(Exception):
    """A request answered with a given status and a message for the therapist."""

    def __init__(self, status: HTTPStatus, message: str, zh: str | None = None):
        super().__init__(message)
        self.status, self.zh = status, zh


def _no_session() -> HttpError:
    return HttpError(HTTPStatus.NOT_FOUND, "no such session", "找不到這次會談。")


def _client(client_id: str) -> dict:
    try:
        return get_client(client_id)
    except KeyError:
        raise HttpError(HTTPStatus.NOT_FOUND, "no such client", "找不到這位個案。") from None


def _transcript(sid: str):
    """The stored transcript, or 404. Only "the file is not there" is a 404: a
    damaged file or a transcript naming an unknown client is a server fault (500)."""
    try:
        return load_transcript(sid)
    except FileNotFoundError:
        raise _no_session() from None


def _session_lock(sid: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _SESSION_LOCKS.setdefault(sid, threading.Lock())


def _log_fault(e: BaseException) -> None:
    """Where an unexpected error happened, for the terminal. The exception's
    message is left out: it can quote the request (a KeyError names the key)."""
    frames = "".join(traceback.format_tb(e.__traceback__)[-4:])
    print(f"Haven: unexpected {type(e).__name__}\n{frames}", file=sys.stderr, end="")


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
    transcript = _transcript(sid)
    if store.get_signature(sid):
        raise Refused("this session is already signed; signed notes are not overwritten",
                      "這次會談已經簽核，簽核後的紀錄不能再修改。需要更正時，請新增「補充說明」。")
    result = store.get_result(sid)
    if result is None:
        raise Refused("no draft has been produced for this session yet", "這次會談還沒有產生紀錄草稿，請先開啟會談。")
    client = get_client(transcript.client_id)
    transcript.client_age = client.get("age")
    measures = ORCH.measure_sentences(client, transcript.session_no)
    return result, transcript, measures


def _stale(result: dict) -> bool:
    return result.get("verification", {}).get("verifier_version") != VERIFIER_VERSION


def _open_session(sid: str) -> dict:
    """Drafts the note when the session has none, re-checks a draft made under
    older verifier rules, and returns the session page. This writes, so it is
    reached by POST only."""
    if not (config.SESSIONS_DIR / f"{sid}.json").is_file():
        raise _no_session()
    signed = bool(store.get_signature(sid))
    result = store.get_result(sid)
    if result is None or (not signed and _stale(result)):
        # One pipeline run per session: of several requests opening a session for
        # the first time, one drafts the note and the others wait and read it.
        with _session_lock(sid):
            result = store.get_result(sid)
            if result is None:
                ORCH.process_session(sid)
            elif not signed and _stale(result):
                ORCH.refresh(result)  # a draft checked under older rules
    return _session_view(sid)


def _session_view(sid: str) -> dict:
    """What the session page shows, read from the store and nothing else. Once
    signed, that is the signed note, not the draft."""
    if not (config.SESSIONS_DIR / f"{sid}.json").is_file():
        raise _no_session()
    result = store.get_result(sid)
    if result is None:
        raise Refused("no draft has been produced for this session yet; POST /api/sessions/<id>/open drafts it",
                      "這次會談還沒有產生紀錄草稿。", needs_processing=True)
    signature = store.get_signature(sid)
    store.audit("read_session", f"{sid}{' (signed)' if signature else ''}")
    result["signature"] = signature
    result["signed"] = bool(signature)
    try:  # for the page heading and the signing dialog; the record itself does not depend on it
        client = get_client(result["client_id"])
        result["client_alias"], result["therapist"] = client.get("alias", ""), client.get("therapist", "")
    except KeyError:
        result["client_alias"], result["therapist"] = "", ""
    result["addenda"] = store.get_addenda(sid) if signature else []
    if signature:
        note = store.get_signed_note(sid)
        result["note"] = note
        result["verification"] = signing.summarize(note)
        result["risk_dismissals"] = note.get("risk_dismissals", [])
        result["risk_uncovered"] = []
    else:
        result["needs_refresh"] = _stale(result)
        result.setdefault("risk_uncovered", signing.uncovered_risk(result["risk"], result["note"]))
    return result


def _status() -> dict:
    """What this process is set up to talk to, looked up now. No figure here is a
    constant: the addresses are what the endpoint names resolve to at this moment,
    and the counter is the number of connections Haven's own check refused."""
    asr = None
    if config.ASR_BACKEND == "openai":
        asr = dict(llm.describe(config.ASR_URL), model=config.ASR_MODEL)
    return {
        "engine": ORCH.engine,
        "bind": f"{config.HOST}:{config.PORT}",
        "bind_loopback": config.HOST in ("127.0.0.1", "localhost", "::1"),
        "llm": dict(llm.describe(ORCH.llm.url), model=ORCH.llm.model) if ORCH.llm else None,
        "asr_backend": config.ASR_BACKEND,
        "asr": asr,  # None: Whisper runs inside this process
        "refused_connections": len(llm.REFUSED),
        # Said plainly so nobody reads the page as a measurement of network traffic.
        "note": "addresses are resolved now; refused_connections counts refusals by Haven's endpoint check since start; this is not a packet capture, and it cannot see what the model server itself connects to",
    }


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
    timeout = CONNECTION_TIMEOUT

    def log_message(self, fmt, *args):  # keep transcripts out of console logs
        pass

    def end_headers(self):
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

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

    def _content_length(self, limit: int) -> int:
        raw = self.headers.get("Content-Length")
        if raw is None:
            raise HttpError(HTTPStatus.LENGTH_REQUIRED, "Content-Length is required")
        # int() would accept "-1", "+5" and " 5 "; read(-1) reads until the connection closes.
        if not re.fullmatch(r"[0-9]{1,15}", raw.strip()):
            raise BadRequest("Content-Length must be a non-negative number")
        length = int(raw)
        if length > limit:
            raise HttpError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"the request body is larger than {limit} bytes",
                            "送出的內容太大。")
        return length

    def _body(self) -> bytes:
        length = self._content_length(MAX_JSON)
        body = self.rfile.read(length)
        if len(body) < length:
            raise BadRequest("the request body ended early")
        return body

    def _guard(self, route) -> None:
        """Runs one request. Whatever goes wrong, the client gets a JSON answer:
        an unexpected error is a 500 with no detail, never a dropped connection."""
        try:
            return route()
        except (BadRequest, signing.BadNote) as e:
            self._error(HTTPStatus.BAD_REQUEST, str(e), "送出的資料格式不正確。")
        except HttpError as e:
            self._error(e.status, str(e), e.zh)
        except Refused as e:
            self._error(HTTPStatus.CONFLICT, str(e), e.zh, **e.extra)
        except store.AlreadySignedError:
            self._error(HTTPStatus.CONFLICT, "this session is already signed; signed notes are not overwritten",
                        "這次會談已經簽核，簽核後的紀錄不能再修改。需要更正時，請新增「補充說明」。")
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True  # the browser went away; nobody to answer
        except TimeoutError:
            self.close_connection = True
            self._error(HTTPStatus.REQUEST_TIMEOUT, "the request body did not arrive in time", "上傳逾時，請再試一次。")
        except Exception as e:  # noqa: BLE001 - the last line of defence
            _log_fault(e)
            self.close_connection = True
            try:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal error", "伺服器發生錯誤，這個操作沒有完成。請看終端機的訊息。")
            except OSError:
                pass

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
        self._guard(self._get)

    def _get(self):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        query = parse_qs(url.query)
        if parts[:1] != ["api"]:
            return self._static(url.path)
        # Every API request carries the header, reads included: a read of a clinical
        # record is written to the audit log, and a cross-site <img> must not be
        # able to do that.
        if self.headers.get(CSRF_HEADER) != "1":
            return self._error(HTTPStatus.FORBIDDEN, f"missing {CSRF_HEADER} header")
        # GET only reads. Drafting a note, re-checking one and asking the model are POSTs.
        if parts == ["api", "status"]:
            return self._json(_status())
        if parts == ["api", "clients"]:
            store.audit("list_clients", "")
            return self._json([_client_summary(c) for c in load_clients()])
        if len(parts) == 4 and parts[1] == "clients" and parts[3] == "brief":
            client = _client(parts[2])
            store.audit("read_brief", client["id"])
            return self._json(ORCH.brief(client["id"]))
        if len(parts) == 3 and parts[1] == "sessions":
            return self._json(_session_view(_session_id(parts[2])))
        if parts == ["api", "audit"]:
            store.audit("read_audit", "")
            return self._json(store.recent_audit())
        if parts == ["api", "audit", "verify"]:
            return self._json(store.verify_audit())
        return self._error(HTTPStatus.NOT_FOUND, "unknown endpoint")

    def do_POST(self):
        if not self._host_ok():
            return self._error(HTTPStatus.FORBIDDEN, "unexpected Host header")
        if self.headers.get(CSRF_HEADER) != "1":
            return self._error(HTTPStatus.FORBIDDEN, f"missing {CSRF_HEADER} header")
        # An error may leave part of the body unread; it must not be parsed as the next request.
        self.close_connection = True
        self._guard(self._post)

    def _post(self):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        query = parse_qs(url.query)
        if len(parts) == 4 and parts[1] == "sessions":
            sid = _session_id(parts[2])
            if parts[3] == "open":
                return self._json(_open_session(sid))
            if parts[3] == "process":
                return self._process(sid, query)
            if parts[3] == "verify":
                return self._verify(sid)
            if parts[3] == "sign":
                return self._sign(sid)
            if parts[3] == "addendum":
                return self._addendum(sid)
        if len(parts) == 4 and parts[1] == "clients" and parts[3] == "ask":
            return self._ask(parts[2])
        if parts == ["api", "upload"]:
            return self._upload(query)
        return self._error(HTTPStatus.NOT_FOUND, "unknown endpoint")

    def _payload(self) -> dict:
        try:
            payload = json.loads(self._body() or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
            raise BadRequest("the request body is not JSON") from None
        if not isinstance(payload, dict):
            raise BadRequest("the request body must be a JSON object")
        return payload

    def _ask(self, client_id):
        """The question travels in the body, not the URL: it can name what a client said."""
        q = self._payload().get("q")
        if not isinstance(q, str) or not q.strip() or len(q) > 500:
            raise BadRequest("q is required")
        client = _client(client_id)  # an unknown client is a 404 and leaves no audit row
        store.audit("ask", client["id"])
        return self._json(ORCH.memory.ask(client, q.strip()))

    def _process(self, sid, query):
        template = query.get("template", ["SOAP"])[0]
        if template not in ("SOAP", "DAP"):
            return self._error(HTTPStatus.BAD_REQUEST, "template must be SOAP or DAP")
        if not (config.SESSIONS_DIR / f"{sid}.json").is_file():
            raise _no_session()
        with _session_lock(sid):
            ORCH.process_session(sid, template)  # refuses a signed session
        return self._json(_session_view(sid))

    def _verify(self, sid):
        """Re-checks the note as the therapist has edited it. Only the sentence
        texts, their citations and the confirmations are read from the request."""
        payload = self._payload()
        result, transcript, measures = _draft(sid)
        note, verification, _ = signing.check(sid, transcript, payload, result["note"]["template"], result["note"].get("engine", ""), measures, ORCH.verifier)
        signing.remember(sid, note, verification.get("llm_failed", False))
        store.audit("verify", f"{sid} {verification['supported']}/{verification['total']} supported"
                    + ("; local model did not answer" if verification.get("llm_failed") else ""))
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
        _transcript(sid)
        try:
            return self._json({"addenda": store.add_addendum(sid, text.strip(), author.strip())})
        except store.NotSignedError:
            raise Refused("an addendum can only be added to a signed note", "這次會談還沒有簽核，草稿可以直接修改，不需要補充說明。") from None

    def _upload(self, query):
        client_id = query.get("client", [""])[0]
        session_id = _session_id(query.get("session_id", [""])[0])  # upper case
        if query.get("consent", [""])[0] != "1":
            return self._error(HTTPStatus.BAD_REQUEST, "the client's written consent to recording is required",
                               "需要先取得個案對錄音的書面同意。")
        # Absent means a real client: the safer reading. A recording wrongly marked
        # as simulated would lose the care real data gets (and pass the pre-commit check).
        simulated = query.get("simulated", ["0"])[0] == "1"
        _client(client_id)
        if not session_id.startswith(f"{client_id.upper()}-"):
            raise HttpError(HTTPStatus.BAD_REQUEST, "the session id must start with the client id",
                            f"會談編號要以個案編號開頭，例如 {client_id}-S05。")
        suffix = Path(self.headers.get("X-Filename", "audio.wav")).suffix.lower()
        if suffix not in AUDIO_SUFFIXES:
            suffix = ".wav"
        length = self._content_length(MAX_UPLOAD)
        if length == 0:
            raise HttpError(HTTPStatus.BAD_REQUEST, "the upload is empty", "沒有收到錄音：檔案是空的。請重新選擇錄音檔。")
        session_no = _reserve_upload(session_id, client_id)  # 409 when the id is taken or being uploaded
        # In the data directory (0700), not the shared system temp directory. The
        # file is removed in ``finally``, whatever happens below; what a crash or a
        # power cut leaves behind is removed at the next start (files.clear_temp).
        fd, tmp_name = tempfile.mkstemp(suffix=suffix, prefix="upload-", dir=files.temp_dir())
        try:
            with os.fdopen(fd, "wb") as tmp:
                # Streamed to the temp file in 1 MB pieces, so the upload is not held in memory
                # here. (The faster-whisper backend reads the file from disk; the "openai"
                # backend then loads it whole to send it on: see transcript._openai_server.)
                left = length
                while left > 0:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    tmp.write(chunk)
                    left -= len(chunk)
            if left:
                raise HttpError(HTTPStatus.BAD_REQUEST, "the upload ended before the whole file arrived",
                                "上傳中斷，錄音沒有完整送達。請再上傳一次。")
            try:
                t = transcribe_audio(Path(tmp_name), session_id, client_id, session_no, date.today().isoformat(), simulated)
            except ImportError:
                raise HttpError(HTTPStatus.NOT_IMPLEMENTED, "faster-whisper is not installed",
                                "這台電腦還沒有安裝語音轉寫模組（faster-whisper）。") from None
            except ASRError as e:
                raise HttpError(HTTPStatus.BAD_GATEWAY, f"speech-to-text server at {config.ASR_URL}: {e}",
                                "本機語音轉寫服務沒有回傳可用的逐字稿，請確認錄音檔格式後再試。") from None
            except llm.NonLocalEndpointError:
                raise HttpError(HTTPStatus.BAD_GATEWAY, "the speech-to-text endpoint is not local; nothing was sent",
                                "語音轉寫服務的位址不是本機或診所區域網路，錄音沒有送出。請檢查設定。") from None
            except OSError:
                raise HttpError(HTTPStatus.SERVICE_UNAVAILABLE, f"speech-to-text server not reachable at {config.ASR_URL}",
                                "連不上本機語音轉寫服務，請確認它已經啟動。") from None
            finally:
                _remove(tmp_name)  # Haven keeps no recording, on success or on failure
            if not t.segments:
                raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, "no speech was recognised in the recording",
                                "錄音裡沒有辨識到任何語音，沒有建立會談。請確認錄音檔是否正確、有沒有聲音。")
            labelled = ORCH.speakers.run(t)
            with CLIENTS_LOCK:  # two uploads at once must not drop each other's session
                save_transcript(t)
                clients = load_clients()
                for c in clients:
                    if c["id"] == client_id and session_id not in c.setdefault("sessions", []):
                        c["sessions"].append(session_id)
                files.write_private(config.CLIENTS_FILE, json.dumps(clients, ensure_ascii=False, indent=2) + "\n")
        except BaseException as e:
            # A failed upload is recorded too (the id and the kind of failure, never content).
            kind = f"HTTP {int(e.status)}" if isinstance(e, HttpError) else type(e).__name__
            store.audit("upload_failed", f"{session_id} {kind}; temp audio removed")
            raise
        finally:
            _remove(tmp_name)
            with CLIENTS_LOCK:
                UPLOADING.pop(session_id, None)
        store.audit("transcribe_upload", f"{session_id} consent={CONSENT_SCOPE} simulated={int(simulated)} asr={config.ASR_BACKEND} speakers_guessed={labelled}/{len(t.segments)}; temp audio removed after ASR")
        return self._json(_open_session(session_id))


def _remove(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _reserve_upload(session_id: str, client_id: str) -> int:
    """Claims ``session_id`` for one upload and gives it the client's next session
    number. Both happen under one lock, so two uploads at once can neither share
    an id (the second is refused) nor a number."""
    with CLIENTS_LOCK:
        client = _client(client_id)
        taken = (config.SESSIONS_DIR / f"{session_id}.json").exists() or session_id in UPLOADING \
            or any(session_id in c.get("sessions", []) for c in load_clients())
        if taken:
            raise Refused("a session with this id already exists or is being uploaded",
                          "這個會談編號已經存在，或正在上傳中。請換一個編號。")
        numbers = [no for cid, no in UPLOADING.values() if cid == client_id]
        for sid in client.get("sessions", []):
            try:
                numbers.append(int(json.loads((config.SESSIONS_DIR / f"{sid}.json").read_text(encoding="utf-8"))["session_no"]))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        session_no = max(numbers, default=0) + 1
        UPLOADING[session_id] = (client_id, session_no)
        return session_no


def lan_warning(host: str) -> str:
    """Haven has no login. On anything but loopback, whoever can reach the port
    can read every transcript and sign notes."""
    if host in ("127.0.0.1", "localhost", "::1"):
        return ""
    return (f"Haven: WARNING: HAVEN_HOST={host} is not loopback. There is no login: anyone who can reach this port can read "
            "every transcript and sign notes. LAN use is not supported yet; set HAVEN_HOST=127.0.0.1.")


def serve() -> None:
    global ORCH
    os.umask(0o077)  # whatever Haven creates is for this account only
    files.secure_data_dir()
    leftover = files.clear_temp()
    if leftover:
        print(f"Haven: removed {leftover} recording(s) left in {files.temp_dir()} by an earlier run that did not finish")
    chain = store.verify_audit()
    if not chain["ok"]:
        print(f"Haven: WARNING: the audit log does not verify (first bad row id {chain['first_bad_id']}). "
              "A row was changed, inserted or removed outside Haven. Run scripts/verify_audit.py.", file=sys.stderr)
    warning = lan_warning(config.HOST)
    if warning:
        print(warning, file=sys.stderr)
    ORCH = Orchestrator()
    httpd = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    print(f"Haven running at http://{config.HOST}:{config.PORT}  (engine: {ORCH.engine})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
