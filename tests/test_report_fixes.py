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


if __name__ == "__main__":
    unittest.main()
