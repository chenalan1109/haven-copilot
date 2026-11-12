"""Batch 1 of the 2026-11-12 review: the signing gate is decided by the server.

Each test replays an input from the review reports (finding ids in the names
and comments). The server runs over a throwaway copy of the demo data.
"""

import copy
import sqlite3
import unittest

from helpers import H, ServerCase

from haven import config, signing, store
from haven.agents.verifier import VERIFIER_VERSION, Verifier
from haven.models import Note, NoteSentence
from haven.orchestrator import Orchestrator
from haven.transcript import load_transcript


class ForgedSignTest(ServerCase, unittest.TestCase):
    """ENG-1, SEC-1, CLN-6, UX-I1: a status sent by the browser is not believed."""

    def sign(self, sid, sections, **extra):
        return self.call(f"/api/sessions/{sid}/sign", {"signed_by": "王心理師", "note": {"template": "SOAP", "sections": sections}, **extra})

    def test_forged_supported_suicide_plan_is_refused(self):
        self.draft("C001-S04")
        status, body = self.sign("C001-S04", {"S": [{"text": "個案表示上週買了木炭，打算這週末燒炭。", "evidence": [], "status": "supported"}]})
        self.assertEqual(status, 409)
        self.assertIn("message_zh", body)
        self.assertIsNone(store.get_signature("C001-S04"))

    def test_forged_denial_of_ideation_is_refused(self):
        self.draft("C001-S04")
        for text in ("個案否認自殺意念，無需安全計畫。", "個案否認自殺意念，無風險。"):
            status, _ = self.sign("C001-S04", {"S": [{"text": text, "evidence": [], "status": "supported", "support": 1.0, "must_confirm": False}]})
            self.assertEqual(status, 409, text)

    def test_empty_note_is_refused(self):
        self.draft("C001-S03")
        self.assertEqual(self.sign("C001-S03", {})[0], 409)
        self.assertEqual(self.sign("C001-S03", {"S": []})[0], 409)
        self.assertIsNone(store.get_signature("C001-S03"))

    def test_unknown_session_is_refused(self):
        status, _ = self.sign("ZZZ-NOPE", {})
        self.assertEqual(status, 404)
        self.assertEqual(self.sign("ZZZ-999", {"S": [{"text": "x", "evidence": [], "status": "supported"}]})[0], 404)
        self.assertIsNone(store.get_signature("ZZZ-NOPE"))

    def test_session_never_drafted_is_refused(self):
        self.data.add_session("C001-S71", [("client", "這週睡得比較好。")])
        self.assertEqual(self.sign("C001-S71", {"S": [{"text": "個案表示這週睡得比較好。", "evidence": [1]}]})[0], 409)

    def test_malformed_note_is_a_400_not_a_dropped_connection(self):
        self.draft("C001-S03")
        for note in ([1], {"sections": {"S": "abc"}}, {"sections": None}, {"sections": {"S": [{"text": "a", "evidence": "12"}]}}, {"sections": {"X": []}}):
            self.assertEqual(self.call("/api/sessions/C001-S03/sign", {"signed_by": "王", "note": note})[0], 400, note)
        self.assertEqual(self.call("/api/sessions/C001-S03/sign", {"signed_by": {"a": 1}, "note": {"sections": {}}})[0], 400)


class MeasureLineTest(ServerCase, unittest.TestCase):
    """ENG-3, SEC-2, ENG-I2: score lines come from the questionnaire data only."""

    def test_fake_score_line_is_refused_at_signing(self):
        self.draft("C001-S04")
        status, _ = self.call("/api/sessions/C001-S04/sign", {"signed_by": "王", "note": {"sections": {
            "O": [{"source": "measure", "status": "supported", "text": "PHQ-9 3 分（極輕微），無自殺風險。", "evidence": []}]}}})
        self.assertEqual(status, 409)

    def test_edited_score_line_fails_verify_and_cannot_be_signed(self):
        r, note = self.draft("C001-S04")
        real = next(s for s in note["sections"]["O"] if s["source"] == "measure" and "PHQ-9 18 分" in s["text"])
        edited = copy.deepcopy(note)
        for s in edited["sections"]["O"]:
            if s["text"] == real["text"]:
                s.update(text="PHQ-9 3 分（極輕微），第 9 題 0 分，否認自殺意念。", status="unchecked")
        status, v = self.call("/api/sessions/C001-S04/verify", edited)
        self.assertEqual(status, 200)
        changed = next(s for s in v["note"]["sections"]["O"] if "PHQ-9 3 分" in s["text"])
        self.assertEqual(changed["status"], "unsupported")
        self.assertIn("量表", changed["reason"])
        self.assertFalse(v["verification"]["ready_to_sign"])
        # Even "confirmed", an edited score line is not signed as a score line.
        for s in edited["sections"]["O"]:
            s["confirmed_by_therapist"] = True
        status, body = self.call("/api/sessions/C001-S04/sign", {"signed_by": "王", "note": edited})
        self.assertEqual(status, 409)
        self.assertIn("量表", body["message_zh"])

    def test_any_sentence_claiming_to_be_a_score_line_is_checked(self):
        self.draft("C001-S04")
        status, v = self.call("/api/sessions/C001-S04/verify", {"template": "SOAP", "sections": {"S": [
            {"text": "個案表示有具體自殺計畫。", "status": "unchecked", "source": "measure", "evidence": []}]}})
        self.assertEqual(v["note"]["sections"]["S"][0]["status"], "unsupported")
        self.assertFalse(v["verification"]["ready_to_sign"])

    def test_untouched_score_lines_stay_supported(self):
        r, note = self.draft("C001-S04")
        _, v = self.call("/api/sessions/C001-S04/verify", note)
        self.assertTrue(all(s["status"] == "supported" for s in v["note"]["sections"]["O"] if s["source"] == "measure"))


class ModelRejectedTest(unittest.TestCase):
    """ENG-4, ENG-I3: a weak sentence the local model said no to waits for the therapist."""

    def test_model_no_blocks_signing_until_confirmed(self):
        class NoLLM:
            def generate_json(self, system, prompt, max_tokens=None):
                return {"results": [{"id": i, "supported": False} for i in range(10)]}
        t = load_transcript("C001-S04")
        note = Note("SOAP", {"S": [NoteSentence("個案表示被主管當眾責罵後已辭職。", [2])]}, "test")
        summary = Verifier(NoLLM()).run(note, t)
        s = note.sections["S"][0]
        self.assertNotEqual(s.status, "supported")
        self.assertTrue(s.status == "unsupported" or s.must_confirm)
        self.assertFalse(summary["ready_to_sign"])
        self.assertEqual(len(signing.blocking_sentences(note)), 1)
        s.confirmed_by_therapist = True
        self.assertEqual(signing.blocking_sentences(note), [])


class RiskCoverageTest(ServerCase, unittest.TestCase):
    """ENG-5, CLN-F4, ENG-F4: high-level risk cues must be in the note or left out with a reason."""

    def test_s04_cannot_be_signed_with_an_empty_note(self):
        self.draft("C001-S04")
        self.assertEqual(self.call("/api/sessions/C001-S04/sign", {"signed_by": "王", "note": {"template": "SOAP", "sections": {}}})[0], 409)

    def test_s04_without_the_risk_line_needs_a_reason(self):
        r, note = self.draft("C001-S04")
        self.assertEqual(r["risk_uncovered"], [])
        risky = {f["segment_id"] for f in r["risk"]["flags"] if f["level"] in ("high", "critical")}
        self.assertIn(10, risky)
        trimmed = {"template": "SOAP", "sections": {k: [s for s in v if not risky & set(s["evidence"])] for k, v in note["sections"].items()}}
        status, body = self.call("/api/sessions/C001-S04/sign", {"signed_by": "王", "note": trimmed})
        self.assertEqual(status, 409)
        self.assertEqual([u["segment_id"] for u in body["risk_uncovered"]], sorted(risky))
        # A reason is required, not just a tick.
        status, _ = self.call("/api/sessions/C001-S04/sign", {"signed_by": "王", "note": trimmed, "risk_dismissals": [{"segment_id": 10, "reason": ""}]})
        self.assertEqual(status, 400)
        status, _ = self.call("/api/sessions/C001-S04/sign", {"signed_by": "王", "note": trimmed,
                                                             "risk_dismissals": [{"segment_id": s, "reason": "已另記於風險評估表"} for s in risky]})
        self.assertEqual(status, 200)
        actions = [a["action"] for a in store.recent_audit()]
        self.assertIn("risk_cue_left_out", actions)

    def test_upload_with_unknown_speakers_and_a_disclosure_cannot_be_signed_blank(self):
        # ENG-5: the demo engine skips unknown speakers, so the note used to be empty and signable.
        self.data.add_session("C001-S72", [("unknown", "最近還好嗎？"), ("unknown", "我上個月割腕了兩次。"), ("unknown", "嗯。")], source="none")
        r, note = self.draft("C001-S72")
        self.assertEqual(r["risk"]["level"], "high")
        self.assertEqual(self.call("/api/sessions/C001-S72/sign", {"signed_by": "王", "note": {"sections": {}}})[0], 409)


class LockAfterSigningTest(ServerCase, unittest.TestCase):
    """ENG-11, UX-6, UX-I2, ENG-I7, CLN-F11, ENG-F3, ENG-12, SEC-F1, ENG-16."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.r, cls.note = cls.draft("C001-S03")
        first = cls.note["sections"]["S"][0]
        first["text"] = first["text"].rstrip("。") + "。"  # unchanged
        cls.status, cls.signature = cls.call("/api/sessions/C001-S03/sign", {"signed_by": "王心理師", "note": cls.note})

    def test_signing_the_server_draft_works(self):
        self.assertEqual(self.status, 200, self.signature)

    def test_signature_records_hashes_and_verifier_version(self):
        sig = store.get_signature("C001-S03")
        self.assertEqual(sig["transcript_sha256"], signing.transcript_sha256("C001-S03"))
        self.assertEqual(sig["note_sha256"], signing.note_sha256(store.get_signed_note("C001-S03")))
        self.assertEqual(len(sig["note_sha256"]), 64)
        self.assertEqual(sig["verifier_version"], VERIFIER_VERSION)
        self.assertEqual(self.signature["note_sha256"], sig["note_sha256"])

    def test_process_after_signing_is_refused_and_changes_nothing(self):
        before = store.get_result("C001-S03")
        status, body = self.call("/api/sessions/C001-S03/process?template=DAP", {})
        self.assertEqual(status, 409)
        self.assertIn("簽核", body["message_zh"])
        self.assertEqual(store.get_result("C001-S03"), before)
        with self.assertRaises(store.AlreadySignedError):
            Orchestrator(use_llm=False).process_session("C001-S03", "DAP")

    def test_get_returns_the_signed_note(self):
        status, r = self.call("/api/sessions/C001-S03")
        self.assertEqual(status, 200)
        self.assertTrue(r["signed"])
        self.assertEqual(r["signature"]["signed_by"], "王心理師")
        self.assertEqual(set(r["note"]["sections"]), {"S", "O", "A", "P"} | (set(r["note"]["sections"]) - {"S", "O", "A", "P"}))
        self.assertEqual(r["note"], store.get_signed_note("C001-S03"))
        self.assertEqual([s["text"] for s in r["note"]["sections"]["S"]], [s["text"] for s in self.note["sections"]["S"]])

    def test_verify_and_second_signature_are_refused(self):
        self.assertEqual(self.call("/api/sessions/C001-S03/verify", self.note)[0], 409)
        self.assertEqual(self.call("/api/sessions/C001-S03/sign", {"signed_by": "李", "note": self.note})[0], 409)
        self.assertEqual(store.get_signature("C001-S03")["signed_by"], "王心理師")

    def test_lower_case_id_is_the_same_session(self):
        # ENG-12: on macOS "c001-s03" opened the same file and could be signed again.
        status, r = self.call("/api/sessions/c001-s03")
        self.assertEqual((status, r["session_id"], r["signed"]), (200, "C001-S03", True))
        self.assertEqual(self.call("/api/sessions/c001-s03/sign", {"signed_by": "李", "note": self.note})[0], 409)
        self.assertIsNone(store.get_signature("c001-s03"))
        with store.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM signed_notes").fetchone()[0], 1)

    def test_addendum_is_append_only(self):
        self.assertEqual(self.call("/api/sessions/C002-S05/addendum", {"text": "補記", "author": "王"})[0], 409)  # not signed
        status, body = self.call("/api/sessions/C001-S03/addendum", {"text": "會談後個案來電，改約下週三。", "author": "王心理師"})
        self.assertEqual(status, 200)
        self.call("/api/sessions/C001-S03/addendum", {"text": "第二則補充。", "author": "王心理師"})
        _, r = self.call("/api/sessions/C001-S03")
        self.assertEqual([a["text"] for a in r["addenda"]], ["會談後個案來電，改約下週三。", "第二則補充。"])
        self.assertEqual(r["note"], store.get_signed_note("C001-S03"))  # the signed note itself is untouched
        self.assertEqual(self.call("/api/sessions/C001-S03/addendum", {"text": "", "author": "王"})[0], 400)


class SignTransactionTest(unittest.TestCase):
    """ENG-16: the signed note and its audit row are stored together or not at all."""

    def test_audit_failure_rolls_the_signature_back(self):
        from helpers import IsolatedData
        with IsolatedData():
            store.audit("setup", "x")
            with store.connect() as c:
                c.execute("CREATE TRIGGER no_sign_audit BEFORE INSERT ON audit_log WHEN NEW.action = 'sign_note' BEGIN SELECT RAISE(ABORT, 'disk full'); END")
            with self.assertRaises(sqlite3.DatabaseError):
                store.sign_note("C001-S03", {"sections": {}}, "王", note_sha256="a", transcript_sha256="b", verifier_version="v")
            self.assertIsNone(store.get_signature("C001-S03"))

    def test_older_database_gets_the_new_columns(self):
        from helpers import IsolatedData
        with IsolatedData():
            conn = sqlite3.connect(config.DB_FILE)
            conn.execute("CREATE TABLE signed_notes (session_id TEXT PRIMARY KEY, note TEXT NOT NULL, signed_by TEXT NOT NULL, signed_at TEXT NOT NULL)")
            conn.execute("INSERT INTO signed_notes VALUES ('C001-S03', '{\"sections\": {}}', '王', '2026-11-01T10:00:00+08:00')")
            conn.commit()
            conn.close()
            self.assertEqual(store.get_signature("C001-S03")["note_sha256"], "")


class ServerVerdictTest(ServerCase, unittest.TestCase):
    """UX-I1: a paraphrase the local model accepted keeps the server's own verdict at signing."""

    class llm:
        label = "fake:yes"
        url = "http://127.0.0.1:1"

        @staticmethod
        def generate_json(system, prompt, max_tokens=None):
            if "\"sentence\"" in prompt:
                return {"results": [{"id": i, "supported": True} for i in range(40)]}
            return None  # the writer falls back to the rule engine

    def test_model_checked_sentence_signs_without_asking_the_model_again(self):
        r, note = self.draft("C002-S05")
        note["sections"]["S"].append({"text": "個案在分組報告上台發表，起初緊張，後來較為平順。", "evidence": [2]})
        _, v = self.call("/api/sessions/C002-S05/verify", note)
        self.assertEqual(v["note"]["sections"]["S"][-1]["status"], "supported")
        # Not verified by the server: the same kind of sentence sent straight to /sign gets the rule layers only.
        unseen = copy.deepcopy(note)
        unseen["sections"]["S"].append({"text": "個案覺得同學的回饋讓人安心許多。", "evidence": [6], "status": "supported"})
        self.assertEqual(self.call("/api/sessions/C002-S05/sign", {"signed_by": "王", "note": unseen})[0], 409)
        self.assertEqual(self.call("/api/sessions/C002-S05/sign", {"signed_by": "王", "note": note})[0], 200)


if __name__ == "__main__":
    unittest.main()
