"""Findings N1, N3, N4 and N8 of the 2026-11-12 project report.

N1: a verdict the rules reached with no model running was reused after a model
was turned on, so the model never got to rule on paraphrases.
N3: the refusal named a button 「確認無誤」 that does not exist.
N4: a one-character topic (貓) found nothing in case memory.
N8: a sentence citing nothing could be signed after one click.
"""

import sqlite3
import unittest

from helpers import ServerCase

from haven import config, server
from haven.agents.memory import CaseMemory, topic
from haven.agents.verifier import Verifier
from haven.orchestrator import get_client

PARAPHRASE = {"text": "個案在分組報告上台發表，起初緊張，後來較為平順。", "evidence": [2]}


class SaysYes:
    label = "fake:yes"
    url = "http://127.0.0.1:1"

    @staticmethod
    def generate_json(system, prompt, max_tokens=None):
        if "\"sentence\"" in prompt:
            return {"results": [{"id": i, "supported": True} for i in range(40)]}
        return None


class VerdictCacheTest(ServerCase, unittest.TestCase):
    """N1"""

    def test_rules_only_verdict_is_rechecked_once_a_model_is_on(self):
        _, note = self.draft("C002-S05")
        note["sections"]["S"].append(dict(PARAPHRASE))
        _, v = self.call("/api/sessions/C002-S05/verify", note)
        self.assertNotEqual(v["note"]["sections"]["S"][-1]["status"], "supported")  # rules alone cannot settle it
        saved = server.ORCH.verifier
        server.ORCH.verifier = Verifier(SaysYes())
        try:
            _, v = self.call("/api/sessions/C002-S05/verify", note)
        finally:
            server.ORCH.verifier = saved
        self.assertEqual(v["note"]["sections"]["S"][-1]["status"], "supported")
        # The model's verdict is the one remembered, so signing (rules only) accepts it.
        self.assertEqual(self.call("/api/sessions/C002-S05/sign", {"signed_by": "王", "note": note})[0], 200)


class UncitedSentenceTest(ServerCase, unittest.TestCase):
    """N8 and N3"""

    def note_with(self, sid, extra):
        _, note = self.draft(sid)
        note["sections"]["S"].append(extra)
        return note

    def test_one_click_is_not_enough_for_a_sentence_citing_nothing(self):
        note = self.note_with("C002-S05", {"text": "個案表示與母親關係良好，最近常一起出遊。", "evidence": [], "confirmed_by_therapist": True})
        status, body = self.call("/api/sessions/C002-S05/sign", {"signed_by": "王", "note": note})
        self.assertEqual(status, 409)
        self.assertIn("保留此句", body["message_zh"])
        self.assertNotIn("確認無誤", body["message_zh"])
        self.assertIn("個案表示與母親關係良好，最近常一起出遊。", body["blocking"])



class UncitedWithBasisTest(UncitedSentenceTest):
    """N8: the written basis lets the sentence through and is kept."""

    test_one_click_is_not_enough_for_a_sentence_citing_nothing = None
    test_basis_is_not_needed_for_a_cited_weak_sentence = None

    def test_kept_with_a_written_basis_signs_and_the_basis_is_recorded(self):
        basis = "會談後個案母親來電告知"
        note = self.note_with("C002-S05", {"text": "個案表示與母親關係良好，最近常一起出遊。", "evidence": [],
                               "confirmed_by_therapist": True, "keep_reason": basis})
        self.assertEqual(self.call("/api/sessions/C002-S05/sign", {"signed_by": "王", "note": note})[0], 200)
        _, signed = self.call("/api/sessions/C002-S05")
        kept = [s for s in signed["note"]["sections"]["S"] if not s["evidence"]]
        self.assertEqual(kept[0]["keep_reason"], basis)
        with sqlite3.connect(config.DB_FILE) as c:
            rows = c.execute("SELECT detail FROM audit_log WHERE action = 'uncited_sentence_kept'").fetchall()
        self.assertTrue(any(basis in r[0] for r in rows))



class CitedWeakTest(ServerCase, unittest.TestCase):
    """N8: a cited sentence needs no written basis."""

    def test_basis_is_not_needed_for_a_cited_weak_sentence(self):
        _, note = self.draft("C002-S05")
        note["sections"]["S"].append(dict(PARAPHRASE, confirmed_by_therapist=True, keep_reason="ignored"))
        self.call("/api/sessions/C002-S05/verify", note)
        self.assertEqual(self.call("/api/sessions/C002-S05/sign", {"signed_by": "王", "note": note})[0], 200)
        _, signed = self.call("/api/sessions/C002-S05")
        self.assertEqual(signed["note"]["sections"]["S"][-1]["keep_reason"], "")  # only kept for uncited sentences


class SingleCharacterTopicTest(ServerCase, unittest.TestCase):
    """N4"""

    def test_topic_strips_question_words(self):
        self.assertEqual(topic("哪幾次提到貓？"), "貓")
        self.assertEqual(topic("個案提過哥哥嗎"), "哥哥")

    def test_cat_is_found(self):
        hits = CaseMemory().search(get_client("C001"), "哪幾次提到貓？")
        self.assertTrue(any(h["session_id"] == "C001-S04" and "貓" in h["text"] for h in hits))
        self.assertTrue(all("貓" in h["text"] for h in hits))


class DraftAutosaveTest(ServerCase, unittest.TestCase):
    """N10: closing the page lost every edit. /verify now saves the working draft."""

    def test_edits_confirmations_and_reasons_come_back_and_restore_discards_them(self):
        _, note = self.draft("C001-S04")
        ai_texts = [s["text"] for s in note["sections"]["P"]]
        for s in note["sections"]["P"]:
            if s["text"] == "安排下週五提前會談。" or "提前" in s["text"]:
                s["text"] = "下次會談提前到這週五。"
        note["sections"]["S"].append({"text": "個案今天比平常早到十分鐘。", "evidence": [],
                                      "confirmed_by_therapist": True, "keep_reason": "心理師觀察"})
        _, r = self.call("/api/sessions/C001-S04")
        flag = next(f for f in r["risk"]["flags"] if f["level"] in ("high", "critical"))
        note["risk_dismissals"] = [{"segment_id": flag["segment_id"], "reason": "已口頭處理，另案記錄"},
                                   {"segment_id": 9999, "reason": "不存在的段落"}]
        status, v = self.call("/api/sessions/C001-S04/verify", note)
        self.assertEqual(status, 200)
        self.assertTrue(v["draft_saved_at"])
        # Reopening (a new page) shows the saved working draft.
        _, again = self.call("/api/sessions/C001-S04/open", {})
        texts = [s["text"] for k in again["note"]["sections"] for s in again["note"]["sections"][k]]
        self.assertIn("下次會談提前到這週五。", texts)
        kept = next(s for s in again["note"]["sections"]["S"] if s["text"] == "個案今天比平常早到十分鐘。")
        self.assertTrue(kept["confirmed_by_therapist"])
        self.assertEqual(kept["keep_reason"], "心理師觀察")
        self.assertEqual(again["draft_dismissals"], [{"segment_id": flag["segment_id"], "reason": "已口頭處理，另案記錄"}])
        # Restore goes back to the AI's note.
        _, back = self.call("/api/sessions/C001-S04/restore", {})
        self.assertEqual([s["text"] for s in back["note"]["sections"]["P"]], ai_texts)
        self.assertNotIn("draft_saved_at", back)
        self.assertNotIn("ai_note", back)

    def test_restore_after_signing_is_refused(self):
        _, note = self.draft("C002-S05")
        self.call("/api/sessions/C002-S05/verify", note)
        self.assertEqual(self.call("/api/sessions/C002-S05/sign", {"signed_by": "王", "note": note})[0], 200)
        self.assertEqual(self.call("/api/sessions/C002-S05/restore", {})[0], 409)


if __name__ == "__main__":
    unittest.main()
