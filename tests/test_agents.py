import os
import tempfile
import unittest
from pathlib import Path

os.environ["HAVEN_LLM"] = "demo"
_tmp = tempfile.mkdtemp()

from haven import config  # noqa: E402

config.DB_FILE = Path(_tmp) / "test.db"

from haven.agents.outcome import OutcomeAgent, assess  # noqa: E402
from haven.agents.risk import RiskAgent  # noqa: E402
from haven.agents.verifier import Verifier  # noqa: E402
from haven.agents.writer import NoteWriter  # noqa: E402
from haven.llm import NonLocalEndpointError, OllamaLLM, assert_local  # noqa: E402
from haven.models import Note, NoteSentence  # noqa: E402
from haven.orchestrator import Orchestrator, get_client  # noqa: E402
from haven.transcript import load_transcript  # noqa: E402


class VerifierTest(unittest.TestCase):
    def setUp(self):
        self.t = load_transcript("C001-S03")

    def check(self, text, evidence):
        note = Note("SOAP", {"S": [NoteSentence(text, evidence)]}, "test")
        summary = Verifier().run(note, self.t)
        return note.sections["S"][0].status, summary

    def test_quote_backed_sentence_is_supported(self):
        status, summary = self.check("個案表示睡眠很差，半夜三點多常常就醒來。", [4])
        self.assertEqual(status, "supported")
        self.assertTrue(summary["ready_to_sign"])

    def test_invented_sentence_is_unsupported(self):
        status, summary = self.check("個案表示與母親關係良好，最近常一起出遊。", [4])
        self.assertEqual(status, "unsupported")
        self.assertFalse(summary["ready_to_sign"])

    def test_missing_or_unknown_evidence_is_unsupported(self):
        self.assertEqual(self.check("個案睡眠很差。", [])[0], "unsupported")
        self.assertEqual(self.check("個案睡眠很差。", [4, 999])[0], "unsupported")

    def test_rule_based_notes_pass_verification(self):
        for sid in ("C001-S03", "C001-S04", "C002-S05"):
            t = load_transcript(sid)
            note = NoteWriter().run(t)
            self.assertTrue(Verifier().run(note, t)["ready_to_sign"], sid)


class RiskTest(unittest.TestCase):
    def test_suicidal_ideation_session(self):
        report = RiskAgent().run(load_transcript("C001-S04"))
        self.assertEqual(report.level, "high")
        by_seg = {f.segment_id: f for f in report.flags}
        self.assertEqual(by_seg[10].category, "自殺意念")
        # "沒有真的想要怎麼做" is negated: kept for review, not dropped.
        self.assertEqual(by_seg[12].level, "review")
        self.assertIn(11, report.screening_asked)
        self.assertIn(17, report.safety_actions)
        self.assertIn(16, [p.segment_id for p in report.protective])

    def test_routine_session_has_no_flags(self):
        self.assertEqual(RiskAgent().run(load_transcript("C002-S05")).level, "none")


class OutcomeTest(unittest.TestCase):
    def test_deterioration_beyond_reliable_change(self):
        r = assess("PHQ9", [{"score": 10}, {"score": 16}])
        self.assertEqual(r["status"], "deteriorated")

    def test_reliable_improvement(self):
        r = assess("GAD7", [{"score": 15}, {"score": 11}])
        self.assertEqual(r["status"], "improved")

    def test_not_on_track_after_three_sessions(self):
        r = assess("PHQ9", [{"score": 14}, {"score": 15}, {"score": 15}])
        self.assertEqual(r["status"], "not_on_track")

    def test_bsrs_suicide_item_alert(self):
        alerts = OutcomeAgent().run(get_client("C001"))["alerts"]
        self.assertTrue(any("第 6 題" in a["name"] for a in alerts))
        self.assertEqual(OutcomeAgent().run(get_client("C002"))["alerts"], [])


class PrivacyTest(unittest.TestCase):
    def test_cloud_endpoints_are_refused(self):
        for url in ("https://api.openai.com", "http://8.8.8.8:11434", "https://example.com"):
            with self.assertRaises(NonLocalEndpointError):
                OllamaLLM(url=url)

    def test_local_endpoints_are_allowed(self):
        for url in ("http://127.0.0.1:11434", "http://localhost:11434", "http://192.168.1.20:8000", "http://haven-box.local"):
            assert_local(url)


class PipelineTest(unittest.TestCase):
    def test_process_and_case_memory(self):
        o = Orchestrator(use_llm=False)
        r = o.process_session("C001-S04")
        self.assertEqual(r["risk"]["level"], "high")
        self.assertEqual(set(r["timings_ms"]), {"asr", "writer", "verifier", "risk", "outcome"})
        hits = o.memory.ask(get_client("C001"), "哪幾次提到父親")["hits"]
        self.assertTrue(hits and all("爸" in h["text"] for h in hits))


if __name__ == "__main__":
    unittest.main()
