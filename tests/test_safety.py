"""Clinical-safety and server-hardening checks added after the v1 review."""

import json
import os
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

os.environ["HAVEN_LLM"] = "demo"

from haven import config  # noqa: E402

config.DB_FILE = Path(tempfile.mkdtemp()) / "test.db"

from haven import server, store  # noqa: E402
from haven.agents.outcome import OutcomeAgent, assess  # noqa: E402
from haven.agents.risk import RiskAgent  # noqa: E402
from haven.agents.verifier import Verifier, rule_violation  # noqa: E402
from haven.models import Note, NoteSentence  # noqa: E402
from haven.orchestrator import Orchestrator, get_client  # noqa: E402
from haven.transcript import load_transcript  # noqa: E402


class ClinicalTest(unittest.TestCase):
    def test_checklist_shows_unasked_risk_inquiry_items(self):
        report = RiskAgent().run(load_transcript("C001-S04"))
        items = {c["item"]: c["covered"] for c in report.checklist}
        self.assertIn(11, items["自殺意念"])
        self.assertIn(17, items["安全計畫"])
        # The therapist never asked about means or past attempts.
        self.assertEqual(items["工具或手段可及性"], [])
        self.assertEqual(items["過去自殺或自傷史"], [])

    def test_no_checklist_without_suicide_cues(self):
        self.assertEqual(RiskAgent().run(load_transcript("C002-S05")).checklist, [])

    def test_reversed_negation_in_risk_sentence_is_caught(self):
        source = "有想過，但是沒有真的想要怎麼做"
        self.assertIn("否定", rule_violation("個案表示有具體自殺計畫。", source))
        self.assertEqual(rule_violation("個案曾想過結束生命，但沒有具體計畫。", source), "")

    def test_unknown_speaker_question_is_not_a_disclosure(self):
        t = load_transcript("C001-S04")
        for s in t.segments:
            s.speaker = "unknown"
        flagged = {f.segment_id for f in RiskAgent().run(t).flags}
        self.assertNotIn(11, flagged)  # "你有想過要結束自己的生命嗎？" is the screening question
        self.assertIn(10, flagged)

    def test_recovery_and_phq9_item9(self):
        self.assertEqual(assess("PHQ9", [{"score": 14}, {"score": 6}])["status"], "recovered")
        self.assertEqual(assess("PHQ9", [{"score": 25}, {"score": 18}])["status"], "improved")
        alerts = OutcomeAgent().run(get_client("C001"))["alerts"]
        self.assertTrue(any("第 9 題" in a["name"] for a in alerts))
        self.assertTrue(all(a.get("review") for a in alerts if a["status"] == "not_on_track"))

    def test_scores_fill_the_objective_section(self):
        r = Orchestrator(use_llm=False).process_session("C001-S04")
        objective = r["note"]["sections"]["O"]
        self.assertTrue(any("PHQ-9 18 分" in s["text"] and s["source"] == "measure" for s in objective))
        self.assertTrue(all(s["status"] == "supported" for s in objective if s["source"] == "measure"))

    def test_measure_sentence_needs_no_transcript_evidence(self):
        note = Note("SOAP", {"O": [NoteSentence("PHQ-9 18 分（中重度）。", [], source="measure")]}, "test")
        self.assertTrue(Verifier().run(note, load_transcript("C001-S04"))["ready_to_sign"])


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config.PORT = _free_port()
        server.ORCH = Orchestrator(use_llm=False)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", config.PORT), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{config.PORT}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=headers or {}, method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.load(e)

    def test_foreign_host_header_is_refused(self):
        self.assertEqual(self.call("/api/status", headers={"Host": "evil.example:80"})[0], 403)
        self.assertEqual(self.call("/api/status")[0], 200)

    def test_post_without_csrf_header_is_refused(self):
        status, _ = self.call("/api/sessions/C001-S03/sign", {"signed_by": "x", "note": {"sections": {}}})
        self.assertEqual(status, 403)

    def test_bad_session_id_is_rejected(self):
        self.assertEqual(self.call("/api/sessions/..%2Fclients")[0], 400)

    def test_sign_rules(self):
        h = {"X-Haven": "1", "Content-Type": "application/json"}
        bad = {"S": [{"text": "個案表示與母親關係良好。", "status": "unsupported", "confirmed_by_therapist": False}]}
        self.assertEqual(self.call("/api/sessions/C002-S05/sign", {"signed_by": "王", "note": {"sections": bad}}, h)[0], 409)
        unchecked = {"S": [{"text": "改過的句子。", "status": "unchecked"}]}
        self.assertEqual(self.call("/api/sessions/C002-S05/sign", {"signed_by": "王", "note": {"sections": unchecked}}, h)[0], 409)
        kept = {"S": [dict(bad["S"][0], confirmed_by_therapist=True)]}
        self.assertEqual(self.call("/api/sessions/C002-S05/sign", {"signed_by": "王", "note": {"sections": kept}}, h)[0], 200)
        # A signed note is never overwritten.
        self.assertEqual(self.call("/api/sessions/C002-S05/sign", {"signed_by": "李", "note": {"sections": kept}}, h)[0], 409)
        self.assertEqual(store.get_signature("C002-S05")["signed_by"], "王")
        self.assertIn("1 flagged", store.recent_audit()[0]["detail"])

    def test_upload_requires_consent(self):
        h = {"X-Haven": "1"}
        status, body = self.call("/api/upload?client=C001&session_id=C001-S09", {"x": 1}, h)
        self.assertEqual(status, 400)
        self.assertIn("consent", body["error"])


class ProxyTest(unittest.TestCase):
    def test_llm_requests_ignore_system_proxies(self):
        from haven import llm
        # ProxyHandler({}) replaces the default handler that reads HTTP(S)_PROXY
        # and the system settings; with no proxies it adds no handler at all.
        self.assertFalse([h for h in llm._OPENER.handlers if isinstance(h, urllib.request.ProxyHandler) and h.proxies])


if __name__ == "__main__":
    unittest.main()
