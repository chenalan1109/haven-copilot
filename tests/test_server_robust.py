"""Server robustness and concurrency (backlog batch 4 of the 2026-11-12 review).

Each test uses the reproduction input from the engineering or security report.
"""

import contextlib
import http.client
import io
import json
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from helpers import ServerCase

from haven import config, server, store, transcript  # noqa: E402
from haven.models import Segment, Transcript  # noqa: E402
from haven.orchestrator import get_client  # noqa: E402


def fake_transcribe(delay=0.0):
    """Stands in for Whisper: the "audio" is text, one line per segment."""
    def run(path, session_id, client_id, session_no, date, simulated=True):
        time.sleep(delay)
        lines = [x for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
        segs = [Segment(i, float(i), float(i + 1), "unknown", x, speaker_source="none") for i, x in enumerate(lines, start=1)]
        return Transcript(session_id, client_id, session_no, date, segs, simulated=simulated)
    return run


class UploadMixin:
    def upload(self, session_id, text, client="C001", extra="&simulated=1", headers=None):
        req = urllib.request.Request(f"{self.base}/api/upload?client={client}&session_id={session_id}&consent=1{extra}",
                                     data=text.encode(), headers={"X-Haven": "1", "X-Filename": "a.wav", **(headers or {})}, method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.load(e)


class MalformedRequestTest(ServerCase, unittest.TestCase):
    """ENG-9, SEC-15: every one of these used to drop the connection."""

    def test_malformed_sign_payloads_get_a_json_400(self):
        self.draft("C001-S03")
        for body in ({"signed_by": "王", "note": [1]},
                     {"signed_by": "王", "note": {"sections": {"S": "abc"}}},
                     {"signed_by": "王", "note": {"sections": None}},
                     {"signed_by": {"a": 1}, "note": {"sections": {}}},
                     {"signed_by": "王", "note": {"sections": {"S": [{"text": 5}]}}},
                     [1, 2]):
            status, r = self.call("/api/sessions/C001-S03/sign", body)
            self.assertEqual(status, 400, body)
            self.assertIn("error", r)

    def test_body_that_is_not_json_is_a_400(self):
        conn = http.client.HTTPConnection("127.0.0.1", config.PORT, timeout=4)
        try:
            conn.request("POST", "/api/sessions/C001-S03/verify", body=b"{not json", headers={"X-Haven": "1"})
            r = conn.getresponse()
            self.assertEqual(r.status, 400)
            self.assertIn("error", json.load(r))
        finally:
            conn.close()

    def test_verify_with_missing_fields_is_not_a_404(self):
        self.draft("C001-S03")
        # No template and a sentence without text: 404 "not found" before the fix.
        status, _ = self.call("/api/sessions/C001-S03/verify", {"sections": {"S": [{"evidence": [1]}]}})
        self.assertEqual(status, 200)

    def test_unknown_session_and_client_are_404(self):
        self.assertEqual(self.call("/api/sessions/ZZZ-999")[0], 404)
        self.assertEqual(self.call("/api/sessions/ZZZ-999/process", {})[0], 404)
        self.assertEqual(self.call("/api/clients/NOPE/brief")[0], 404)

    def test_damaged_session_file_is_a_500_without_detail(self):
        (config.SESSIONS_DIR / "C001-S66.json").write_text('{"session_id": "C001-S66", "secret-in-file', encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            status, r = self.call("/api/sessions/C001-S66")
        self.assertEqual(status, 500)
        self.assertEqual(r["error"], "internal error")
        self.assertNotIn("Traceback", json.dumps(r))
        self.assertNotIn("secret-in-file", json.dumps(r))
        # The terminal gets the exception class and where it happened, not its message.
        self.assertIn("JSONDecodeError", err.getvalue())
        self.assertNotIn("secret-in-file", err.getvalue())

    def test_transcript_of_an_unknown_client_is_a_500_not_a_404(self):
        # Inconsistent data must not look like "no such session".
        self.data.add_session("C001-S67", [("client", "最近睡不好。")], client_id="C999")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.call("/api/sessions/C001-S67")[0], 500)

    def test_server_still_answers_after_a_fault(self):
        self.assertEqual(self.call("/api/status")[0], 200)


class ContentLengthTest(ServerCase, unittest.TestCase):
    """ENG-14, SEC-9."""

    def post(self, length, body=b""):
        conn = http.client.HTTPConnection("127.0.0.1", config.PORT, timeout=4)
        try:
            conn.putrequest("POST", "/api/sessions/C001-S03/verify")
            conn.putheader("X-Haven", "1")
            if length is not None:
                conn.putheader("Content-Length", length)
            conn.endheaders()
            if body:
                conn.send(body)
            return conn.getresponse().status
        finally:
            conn.close()

    def test_negative_or_non_numeric_length_is_a_400(self):
        # "-1" made rfile.read(-1) wait for the connection to close; the thread hung.
        for value in ("-1", "abc", "+5", "1e3", ""):
            self.assertEqual(self.post(value), 400, value)

    def test_missing_length_is_a_411(self):
        self.assertEqual(self.post(None), 411)

    def test_json_endpoints_refuse_more_than_2_mb(self):
        self.assertEqual(server.MAX_JSON, 2 * 1024 * 1024)
        self.assertEqual(self.post(str(server.MAX_JSON + 1)), 413)  # refused from the header, nothing is read
        self.assertEqual(self.post(str(150 * 1024 * 1024)), 413)

    def test_body_shorter_than_declared_is_a_400(self):
        conn = http.client.HTTPConnection("127.0.0.1", config.PORT, timeout=4)
        try:
            conn.putrequest("POST", "/api/sessions/C001-S03/verify")
            conn.putheader("X-Haven", "1")
            conn.putheader("Content-Length", "50")
            conn.endheaders()
            conn.send(b'{"sections"')
            conn.sock.shutdown(socket.SHUT_WR)
            self.assertEqual(conn.getresponse().status, 400)
        finally:
            conn.close()


class SlowConnectionTest(ServerCase, unittest.TestCase):
    """SEC-10: a connection that stops sending is closed."""

    def test_default_timeout_is_set(self):
        self.assertEqual(server.CONNECTION_TIMEOUT, 30)
        self.assertEqual(server.Handler.timeout, 30)

    def test_half_sent_request_is_dropped(self):
        with mock.patch.object(server.Handler, "timeout", 0.4):
            for partial in (b"GET /api/sta", f"POST /api/sessions/C001-S03/verify HTTP/1.1\r\nHost: 127.0.0.1:{config.PORT}\r\nX-Haven: 1\r\nContent-Length: 100\r\n\r\n{{".encode()):
                s = socket.create_connection(("127.0.0.1", config.PORT), timeout=5)
                try:
                    s.sendall(partial)
                    t0 = time.monotonic()
                    data = s.recv(4096)
                    while data and b"\r\n\r\n" not in data:
                        data += s.recv(4096) or b""
                        if time.monotonic() - t0 > 4:
                            break
                    # Closed with nothing, or answered 408 and closed; never left hanging.
                    self.assertLess(time.monotonic() - t0, 4)
                    self.assertTrue(data == b"" or b" 408 " in data.split(b"\r\n")[0], data[:60])
                finally:
                    s.close()


class ConcurrentUploadTest(UploadMixin, ServerCase, unittest.TestCase):
    """ENG-10: p7.py, two uploads of C001-S77 at once."""

    def setUp(self):
        patcher = mock.patch.object(server, "transcribe_audio", fake_transcribe(0.4))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_second_upload_of_the_same_id_is_refused_and_the_first_is_kept(self):
        out = {}

        def go(name, text, wait):
            time.sleep(wait)
            out[name] = self.upload("C001-S77", text)

        threads = [threading.Thread(target=go, args=("A", "我想死。\n最近都睡不著。", 0)),
                   threading.Thread(target=go, args=("B", "今天還好。", 0.1))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(out["A"][0], 200, out["A"][1])
        self.assertEqual(out["B"][0], 409)
        self.assertIn("message_zh", out["B"][1])
        # A's disclosure is what is on disk and in the result.
        self.assertIn("我想死", (config.SESSIONS_DIR / "C001-S77.json").read_text(encoding="utf-8"))
        self.assertIn("我想死", out["A"][1]["transcript"][0]["text"])
        self.assertEqual(get_client("C001")["sessions"].count("C001-S77"), 1)
        self.assertEqual(server.UPLOADING, {})

    def test_uploads_at_once_get_different_session_numbers(self):
        out = {}

        def go(sid):
            out[sid] = self.upload(sid, "這週過得怎麼樣？\n不太好，睡不著，白天也提不起勁，工作一直出錯。")

        ids = ["C001-S81", "C001-S82", "C001-S83"]
        threads = [threading.Thread(target=go, args=(sid,)) for sid in ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual([out[s][0] for s in ids], [200, 200, 200])
        numbers = sorted(out[s][1]["session_no"] for s in ids)
        self.assertEqual(len(set(numbers)), 3, numbers)
        # C001's prepared sessions are numbers 3 and 4; an upload never reuses one.
        self.assertGreater(numbers[0], 4)

    def test_failed_upload_releases_the_id(self):
        with mock.patch.object(server, "transcribe_audio", side_effect=transcript.ASRError("HTTP 400")):
            status, r = self.upload("C001-S84", "x")
        self.assertEqual(status, 502)
        self.assertIn("message_zh", r)
        self.assertEqual(server.UPLOADING, {})
        self.assertEqual(self.upload("C001-S84", "這週過得怎麼樣？\n不太好。")[0], 200)


class EmptyUploadTest(UploadMixin, ServerCase, unittest.TestCase):
    """ENG-15 and backlog 4.6."""

    def setUp(self):
        patcher = mock.patch.object(server, "transcribe_audio", fake_transcribe())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_empty_file_is_refused_with_a_clear_message(self):
        status, r = self.upload("C001-S90", "")
        self.assertEqual(status, 400)
        self.assertIn("空", r["message_zh"])
        self.assertFalse((config.SESSIONS_DIR / "C001-S90.json").exists())

    def test_recording_with_no_speech_creates_no_session(self):
        status, r = self.upload("C001-S91", "\n  \n")
        self.assertEqual(status, 422)
        self.assertIn("語音", r["message_zh"])
        self.assertFalse((config.SESSIONS_DIR / "C001-S91.json").exists())
        self.assertNotIn("C001-S91", get_client("C001")["sessions"])
        self.assertEqual(self.upload("C001-S91", "這週過得怎麼樣？")[0], 200)  # the id is free again

    def test_very_short_recording_is_kept_with_a_warning(self):
        status, r = self.upload("C001-S92", "我想死。")
        self.assertEqual(status, 200)  # never thrown away: it may be a disclosure
        self.assertTrue(any("很短" in w for w in r["warnings"]), r["warnings"])
        self.assertEqual(r["risk"]["level"], "high")

    def test_text_without_duration_still_gets_timestamps(self):
        parts = transcript._sentences("最近睡不好。這些想法多常出現？大概每天晚上。", 0.0)
        self.assertGreater(parts[1][0], 0.0)
        self.assertGreater(parts[-1][1], parts[-1][0])


class FirstOpenTest(ServerCase, unittest.TestCase):
    """ENG-13: p8.py, eight GETs for a session nobody has opened yet."""

    def test_pipeline_runs_once(self):
        runs = []
        real = server.ORCH.process_session

        def counted(session_id, template="SOAP"):
            runs.append(session_id)
            time.sleep(0.2)
            return real(session_id, template)

        results = []
        with mock.patch.object(server.ORCH, "process_session", counted):
            threads = [threading.Thread(target=lambda: results.append(self.draft("C001-S03")[0])) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(runs, ["C001-S03"])
        self.assertEqual(len(results), 8)
        self.assertEqual(len({json.dumps(r["note"], sort_keys=True) for r in results}), 1)


class BriefTest(ServerCase, unittest.TestCase):
    """ENG-17: the brief was blank whenever the newest session had no result."""

    def test_brief_uses_the_latest_processed_session(self):
        self.draft("C002-S05")
        self.data.add_session("C002-S06", [("client", "這週好多了。")], client_id="C002", session_no=6)
        clients = json.loads(config.CLIENTS_FILE.read_text(encoding="utf-8"))
        next(c for c in clients if c["id"] == "C002")["sessions"].append("C002-S06")
        config.CLIENTS_FILE.write_text(json.dumps(clients, ensure_ascii=False), encoding="utf-8")
        self.assertIsNone(store.get_result("C002-S06"))
        status, brief = self.call("/api/clients/C002/brief")
        self.assertEqual(status, 200)
        self.assertEqual(brief["last_session"]["session_id"], "C002-S05")
        self.assertEqual(brief["not_processed"], ["C002-S06"])


if __name__ == "__main__":
    unittest.main()
