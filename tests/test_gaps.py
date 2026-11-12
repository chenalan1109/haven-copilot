"""Safety-critical paths the 2026-11-12 review found untested (backlog 8.10, ENG-I13)
and that no other test file covers end to end, plus two documentation checks."""

import re
import unittest
from pathlib import Path

from helpers import ServerCase

from haven import config, server, store  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


class WeakRiskSentenceAtTheServerTest(ServerCase, unittest.TestCase):
    """A weak sentence about risk was only tested at the verifier, never through /sign."""

    def test_weak_risk_sentence_blocks_signing_until_confirmed(self):
        _, note = self.draft("C001-S04")
        # A paraphrase of #12 with little word overlap: weak, and about suicide.
        risky = {"text": "個案表示曾出現自殺念頭，目前沒有打算付諸行動。", "evidence": [12]}
        note["sections"]["R"].append(dict(risky))
        status, v = self.call("/api/sessions/C001-S04/verify", note)
        self.assertEqual(status, 200)
        got = v["note"]["sections"]["R"][-1]
        self.assertNotEqual(got["status"], "supported")
        self.assertTrue(got["status"] == "unsupported" or got["must_confirm"])
        status, body = self.call("/api/sessions/C001-S04/sign", {"signed_by": "王", "note": note})
        self.assertEqual(status, 409)
        self.assertIn(risky["text"], body["blocking"])
        note["sections"]["R"][-1]["confirmed_by_therapist"] = True
        self.assertEqual(self.call("/api/sessions/C001-S04/sign", {"signed_by": "王", "note": note})[0], 200)
        self.assertIn("1 flagged", next(a["detail"] for a in store.recent_audit(10) if a["action"] == "sign_note"))


class BrokenModelTest(ServerCase, unittest.TestCase):
    """The model answers, but not in the agreed shape: the session still opens and says so."""

    class llm:  # noqa: N801 - stands in for an LLM client
        label, url, model = "fake:broken", "http://127.0.0.1:1", "broken"

        @staticmethod
        def generate_json(system, prompt, max_tokens=None):
            if '"sentence"' in prompt:
                return {"results": 5}  # crashed the verifier before the fix
            if "speakers" in prompt:
                return {"speakers": "therapist"}
            return {"S": [{"text": "個案最近睡得不好，工作壓力大。", "evidence": 4}], "O": None, "A": "none", "P": [{"text": "", "evidence": None}]}

    def test_session_opens_and_reports_the_missing_model_check(self):
        status, r = self.call("/api/sessions/C001-S03/open", {})
        self.assertEqual(status, 200)
        self.assertTrue(r["verification"]["llm_failed"])
        self.assertTrue(any("本機模型未回應" in w for w in r["warnings"]))
        held = [s for items in r["note"]["sections"].values() for s in items if s["status"] != "supported" and s["source"] != "measure"]
        self.assertTrue(held)
        self.assertTrue(all("模型判斷" not in s["reason"] for s in held))  # no answer is not reported as a judgement
        self.assertIn("local model did not answer", " ".join(a["detail"] for a in store.recent_audit(20)))


class UploadSuccessPathTest(ServerCase, unittest.TestCase):
    def test_upload_registers_the_session_and_drafts_its_note(self):
        from unittest import mock

        from test_server_robust import UploadMixin, fake_transcribe

        class Up(UploadMixin):
            base = self.base
        with mock.patch.object(server, "transcribe_audio", fake_transcribe()):
            status, r = Up().upload("C002-S06", "這週過得怎麼樣？\n好多了，上台報告的時候手沒有那麼抖。", client="C002")
        self.assertEqual(status, 200)
        self.assertEqual((r["session_id"], r["client_id"], r["session_no"]), ("C002-S06", "C002", 6))
        self.assertTrue(all(s["speaker"] == "unknown" for s in r["transcript"]))
        self.assertTrue((config.SESSIONS_DIR / "C002-S06.json").is_file())
        _, brief = self.call("/api/clients/C002/brief")
        self.assertIn("C002-S06", brief["client"]["sessions"])
        self.assertEqual(brief["last_session"]["session_id"], "C002-S06")
        actions = [a["action"] for a in store.recent_audit(20)]
        self.assertIn("transcribe_upload", actions)
        self.assertIn("process_session", actions)


class DocsTest(unittest.TestCase):
    """Claims the review found in the README that the code or docs/ did not back."""

    README = (REPO / "README.md").read_text(encoding="utf-8")

    def test_withdrawn_claims_stay_out(self):
        for claim in ("27B–34B", "room for four rooms", "never leave the room", "performed by actors", "four outcome alerts",
                      "0 cloud", "cloud_calls", "Every processing, query and signing action"):
            self.assertNotIn(claim, self.README, claim)

    def test_every_linked_file_exists(self):
        for target in re.findall(r"\]\((docs/[^)#]+|scripts/[^)#]+)\)", self.README):
            self.assertTrue((REPO / target).exists(), target)
        results = (REPO / "docs" / "RESULTS.md").read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)#:]+\.md)\)", results):
            self.assertTrue((REPO / "docs" / target).exists(), target)

    def test_asr_result_is_marked_as_not_in_the_repository(self):
        self.assertFalse((REPO / "docs" / "asr-eval" / "b70-whisper-turbo-real-voices.md").exists(),
                         "the real result file has arrived: replace the placeholder section in docs/asr-eval/README.md")
        self.assertIn("exist only on the B70", (REPO / "docs" / "asr-eval" / "README.md").read_text(encoding="utf-8"))

    def test_lan_warning(self):
        self.assertEqual(server.lan_warning("127.0.0.1"), "")
        self.assertIn("no login", server.lan_warning("0.0.0.0"))
        self.assertIn("no login", server.lan_warning("192.168.1.5"))

    def test_scripts_named_in_the_readme_exist(self):
        for name in set(re.findall(r"scripts/([a-z0-9_\-]+\.(?:py|sh))", self.README)):
            self.assertTrue((REPO / "scripts" / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
