"""Outcome tracking and case memory (backlog batch 7 of the 2026-11-12 review)."""

import unittest

from helpers import IsolatedData, ServerCase

from haven.agents.memory import CaseMemory, expand  # noqa: E402
from haven.agents.outcome import OutcomeAgent, assess  # noqa: E402
from haven.orchestrator import get_client  # noqa: E402


def history(*scores):
    return [{"session": i, "date": "", "score": s} for i, s in enumerate(scores, start=1)]


class NotOnTrackTest(unittest.TestCase):
    """7.1: CLN-16, CLN-I6."""

    def test_small_drop_over_many_sessions_is_not_on_track(self):
        # The reviewer's case: PHQ-9 from 20 to 19 over 8 sessions was "目前無警示".
        r = assess("PHQ9", history(20, 20, 21, 20, 19, 20, 19, 19))
        self.assertEqual(r["status"], "not_on_track")
        self.assertEqual(r["label"], "未達預期改善")
        self.assertIn("改善 1 分", r["message"])

    def test_reliable_improvement_still_in_range_is_not_flagged(self):
        self.assertEqual(assess("PHQ9", history(22, 20, 18, 16))["status"], "improved")
        self.assertEqual(assess("PHQ9", history(16, 14, 12, 9))["status"], "recovered")

    def test_two_scores_are_too_few(self):
        self.assertEqual(assess("PHQ9", history(20, 19))["status"], "on_track")

    def test_below_the_cut_off_is_not_flagged(self):
        self.assertEqual(assess("PHQ9", history(9, 8, 8, 8))["status"], "on_track")

    def test_reliable_worsening_since_the_last_session(self):
        # 20 -> 12 -> 19: worse than last time by 7, though not worse than the first score.
        r = assess("PHQ9", history(20, 12, 19))
        self.assertEqual(r["status"], "deteriorated")
        self.assertIn("比上一次惡化 7 分", r["message"])

    def test_bsrs5_uses_a_provisional_threshold_and_says_so(self):
        r = assess("BSRS5", history(12, 11, 11, 10))
        self.assertEqual(r["status"], "not_on_track")
        self.assertIn("暫定", r["message"])
        self.assertIn("暫以 3 分", r["note"])
        self.assertEqual(assess("BSRS5", history(12, 11, 10, 9))["status"], "on_track")

    def test_gad7_explains_its_cut_off(self):
        r = assess("GAD7", history(15, 12, 8))
        self.assertEqual((r["band"], r["clinical_cutoff"]), ("輕度", 8))
        self.assertIn("IAPT", r["note"])

    def test_demo_clients(self):
        c001 = OutcomeAgent().run(get_client("C001"))
        self.assertEqual([m["status"] for m in c001["measures"]], ["not_on_track"] * 3)
        self.assertEqual(len(c001["alerts"]), 5)
        self.assertEqual(OutcomeAgent().run(get_client("C002"))["alerts"], [])


class SingleItemTest(unittest.TestCase):
    """7.2: CLN-I13, CLN-I6. Both items remind from 1; neither is called "惡化"."""

    def client(self, item9=0, suicide_item=0):
        return {"scores": {"PHQ9": [{"session": 1, "score": 4, "item9": item9}],
                           "BSRS5": [{"session": 1, "score": 3, "suicide_item": suicide_item}]}}

    def test_both_items_remind_from_a_score_of_one(self):
        alerts = OutcomeAgent().run(self.client(item9=1, suicide_item=1))["alerts"]
        self.assertEqual(len(alerts), 2)
        for a in alerts:
            self.assertEqual((a["status"], a["label"]), ("item_alert", "單題提醒"))
            self.assertIn("請於會談中詢問", a["message"])
            self.assertNotIn("惡化", a["label"] + a["message"])

    def test_bsrs5_item_of_two_adds_the_referral_advice(self):
        (alert,) = OutcomeAgent().run(self.client(suicide_item=2))["alerts"]
        self.assertIn("轉介", alert["message"])
        self.assertEqual(alert["status"], "item_alert")

    def test_zero_is_quiet(self):
        self.assertEqual(OutcomeAgent().run(self.client())["alerts"], [])

    def test_ui_has_a_style_for_item_reminders(self):
        from test_ui import CSS
        self.assertIn(".alert.item_alert", CSS)


class CaseMemoryTest(ServerCase, unittest.TestCase):
    """7.3: CLN-18, CLN-I9, CLN-I14, UX-F12."""

    def ask(self, q, client="C001"):
        status, r = self.call(f"/api/clients/{client}/ask", {"q": q})
        self.assertEqual(status, 200)
        return r

    def test_readme_question_returns_both_sessions(self):
        # Before: five hits, all from C001-S03; C001-S04 #4 「跟我爸說的一樣」 was cut off.
        r = self.ask("哪幾次提到父親？")
        self.assertEqual([(s["session_id"], s["count"]) for s in r["sessions"]], [("C001-S03", 5), ("C001-S04", 1)])
        self.assertEqual(r["total"], 6)
        self.assertIn(("C001-S04", 4), [(h["session_id"], h["segment_id"]) for h in r["hits"]])
        self.assertTrue(all("爸" in h["text"] for h in r["hits"]))
        self.assertLessEqual(max(sum(1 for h in r["hits"] if h["session_id"] == s["session_id"]) for s in r["sessions"]), 3)

    def test_risk_topics_are_found(self):
        for q in ("哪幾次提到想死", "有沒有自殺意念", "之前有沒有談過輕生"):
            r = self.ask(q)
            self.assertIn(("C001-S04", 10), [(h["session_id"], h["segment_id"]) for h in r["hits"]], q)
            self.assertIn("消失", r["expanded"])
        self.assertTrue(self.ask("保護因子")["hits"])

    def test_no_match_is_empty_with_the_words_that_were_tried(self):
        r = self.ask("有沒有提到自傷")
        self.assertEqual((r["hits"], r["total"], r["sessions"]), ([], 0, []))
        self.assertIn("自殘", r["expanded"])
        from test_ui import JS
        self.assertIn("這不代表會談中沒有談過", JS)  # what the page says for an empty result

    def test_speaker_is_reported_as_labelled(self):
        self.data.add_session("C001-S71", [("unknown", "我爸昨天又打電話來。"), ("therapist", "你爸爸說了什麼？")], source="none")
        self.data.add_session("C001-S72", [("client", "我爸說我沒用。")], source="model")
        import json
        from haven import config
        clients = json.loads(config.CLIENTS_FILE.read_text(encoding="utf-8"))
        clients[0]["sessions"] += ["C001-S71", "C001-S72"]
        config.CLIENTS_FILE.write_text(json.dumps(clients, ensure_ascii=False), encoding="utf-8")
        hits = {(h["session_id"], h["segment_id"]): h for h in self.ask("父親")["hits"]}
        self.assertEqual(hits[("C001-S71", 1)]["speaker"], "unknown")
        self.assertEqual(hits[("C001-S72", 1)]["speaker_source"], "model")
        from test_ui import JS
        self.assertNotIn('h.speaker === "client" ? "個案" : "心理師"', JS)  # unknown was shown as the therapist
        self.assertIn("說話者未標示", JS)

    def test_missing_session_file_does_not_break_the_search(self):
        with IsolatedData():
            client = dict(get_client("C001"), sessions=["C001-S03", "C001-GONE"])
            self.assertTrue(CaseMemory().ask(client, "父親")["hits"])

    def test_plain_words_still_search_by_overlap(self):
        self.assertEqual(expand("主管"), [])
        self.assertTrue(self.ask("被主管罵")["hits"])


if __name__ == "__main__":
    unittest.main()
