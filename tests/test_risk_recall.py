"""Batch 3 of the 2026-11-12 review: risk detection.

Recall is reported per category on the reviewer's own sentences
(tests/risk_phrases.py, from review-2026-11-12/clinical.md) and held above a
floor. 待心理師確認: the sentences and the lexicon entries they led to have
not been checked by a licensed psychologist, and the lexicon was written with
these sentences in view, so the figures say "nothing regressed", not "this is
how well it works on real sessions".

    python3 tests/test_risk_recall.py        # prints the recall table
"""

import os
import sys
import unittest
from pathlib import Path

os.environ["HAVEN_LLM"] = "demo"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk_phrases import HELD_OUT_RISK, KNOWN_FALSE_ALARMS, NEGATIVE, POSITIVE  # noqa: E402

from haven.agents import risk as R  # noqa: E402
from haven.agents.risk import RiskAgent  # noqa: E402
from haven.agents.verifier import Verifier  # noqa: E402
from haven.agents.writer import NoteWriter  # noqa: E402
from haven.models import Note, NoteSentence, Segment, Transcript  # noqa: E402
from haven.transcript import load_transcript  # noqa: E402

FLOOR = 0.8  # backlog 3.1; before the change the reviewer measured about 22%
FULL = {"通報義務線索", "物質使用"}  # backlog 3.3 and 3.8: every sentence


def transcript(*lines, source="script", age=None):
    """Lines are text (the client speaking) or (speaker, text)."""
    segs = []
    for i, line in enumerate(lines, start=1):
        who, text = line if isinstance(line, tuple) else ("client", line)
        segs.append(Segment(i, float(i), float(i + 1), who, text, source))
    return Transcript("T-S01", "C001", 1, "2026-11-12", segs, client_age=age)


def flags(*lines, **kw):
    return RiskAgent().run(transcript(*lines, **kw)).flags


def recall_table() -> dict[str, tuple[int, int, list[str]]]:
    table = {}
    for name, (_, categories, sentences) in POSITIVE.items():
        missed = [s for s in sentences if not any(f.category in categories for f in flags(s))]
        table[name] = (len(sentences) - len(missed), len(sentences), missed)
    return table


def format_table(table) -> str:
    rows = ["category                 hit/total  recall"]
    for name, (hit, total, missed) in table.items():
        rows.append(f"{name:<14} {hit:>3}/{total:<3} {hit / total:>6.0%}" + (f"   missed: {' '.join(missed)}" if missed else ""))
    hit, total = sum(v[0] for v in table.values()), sum(v[1] for v in table.values())
    rows.append(f"{'全部（審查員的句子）':<14} {hit:>3}/{total:<3} {hit / total:>6.0%}")
    held = [s for s in HELD_OUT_RISK if flags(s)]
    rows.append(f"未用來建詞表的句子（無門檻，僅報告） {len(held)}/{len(HELD_OUT_RISK)} {len(held) / len(HELD_OUT_RISK):.0%}")
    loud = [s for s in KNOWN_FALSE_ALARMS if any(f.level in ('high', 'critical') for f in flags(s))]
    rows.append(f"已知誤報的日常句（僅報告） {len(loud)}/{len(KNOWN_FALSE_ALARMS)} 仍亮高關注")
    return "\n".join(rows)


class RecallTest(unittest.TestCase):
    """3.1, 3.2, 3.3, 3.4, 3.8: CLN-1, CLN-3, CLN-4, CLN-5, CLN-14."""

    def test_recall_per_category(self):
        table = recall_table()
        print("\n" + format_table(table), file=sys.stderr)
        for name, (hit, total, missed) in table.items():
            floor = 1.0 if name in FULL else FLOOR
            self.assertGreaterEqual(hit / total, floor, f"{name}: missed {missed}")

    def test_no_high_alert_on_everyday_sentences(self):
        for text in NEGATIVE:
            loud = [(f.category, f.cue) for f in flags(text) if f.level in ("high", "critical")]
            self.assertEqual(loud, [], text)

    def test_demo_sessions_are_unchanged(self):
        self.assertEqual(RiskAgent().run(load_transcript("C002-S05")).flags, [])
        self.assertEqual(RiskAgent().run(load_transcript("C001-S03")).flags, [])
        s04 = RiskAgent().run(load_transcript("C001-S04"))
        self.assertEqual(s04.level, "high")
        self.assertEqual({f.segment_id for f in s04.flags if f.level in ("high", "critical")}, {10})


class SuicidalBehaviourTest(unittest.TestCase):
    """3.2: CLN-3."""

    def test_recent_attempt_is_critical_with_a_reporting_prompt(self):
        for text in ("我昨天吞了一整罐藥，今天早上才醒來。", "我在浴室燒了炭但是後來我自己把窗戶打開。"):
            f = next(f for f in flags(text) if f.category == R.BEHAVIOUR)
            self.assertEqual(f.level, "critical")
            self.assertIn("自殺防治法", f.note)
            self.assertIn("不會自動通報", f.note)

    def test_past_attempt_is_history_not_a_current_plan(self):
        fl = flags("去年我有試過上吊，但是繩子斷了。")
        self.assertEqual([(f.category, f.level) for f in fl], [(R.PAST, "high")])
        report = RiskAgent().run(transcript("去年我有試過上吊，但是繩子斷了。"))
        self.assertEqual({c["item"]: c["covered"] for c in report.checklist}["過去自殺或自傷史"], [1])

    def test_stockpiled_pills_are_a_means(self):
        self.assertEqual([(f.category, f.level) for f in flags("我已經存了很多安眠藥。")], [(R.PLAN, "critical")])
        self.assertEqual([(f.category, f.level) for f in flags("醫生有開安眠藥給我，我都照醫囑吃。")], [(R.HYPNOTICS, "info")])


class ReportingCueTest(unittest.TestCase):
    """3.3: CLN-4, CLN-F1. A prompt to assess; nothing is sent."""

    def test_every_reporting_flag_names_the_law_and_says_it_is_not_automatic(self):
        _, categories, sentences = POSITIVE["通報義務線索"]
        for text in sentences:
            hits = [f for f in flags(text) if f.category in categories]
            self.assertTrue(hits, text)
            for f in hits:
                self.assertIn("請依法評估是否通報", f.note)
                self.assertIn("不會自動通報", f.note)
                self.assertTrue(f.category.startswith(R.REPORT))

    def test_the_agent_has_no_way_to_send_anything(self):
        import haven.agents.risk as module
        source = Path(module.__file__).read_text(encoding="utf-8")
        for word in ("urllib", "socket", "http", "requests", "smtplib", "subprocess"):
            self.assertNotIn(f"import {word}", source)

    def test_minor_adds_child_protection_and_raises_substance_use(self):
        adult = flags("我爸會用皮帶抽我。")
        minor = flags("我爸會用皮帶抽我。", age=15)
        self.assertNotIn(R.REPORT_CHILD, {f.category for f in adult})
        self.assertIn(R.REPORT_CHILD, {f.category for f in minor})
        f = flags("我最近開始抽大麻。", age=16)[0]
        self.assertEqual(f.level, "high")
        self.assertIn("未滿 18 歲", f.note)

    def test_phone_call_is_not_violence(self):
        self.assertEqual(flags("他昨天一直打我手機。"), [])
        self.assertTrue(flags("我爸喝醉就會打我媽。"))


class HarmToOthersTest(unittest.TestCase):
    """3.4: CLN-5."""

    def test_taking_the_child_along_is_critical_and_the_child_is_not_protective(self):
        for text in ("我想帶孩子一起走。", "如果我走了，孩子也活不下去，不如一起帶走。"):
            report = RiskAgent().run(transcript(text))
            f = next(f for f in report.flags if f.category == R.FILICIDE)
            self.assertEqual(f.level, "critical")
            self.assertIn("兒童及少年", f.note)
            self.assertEqual(report.level, "critical")
            self.assertEqual(report.protective, [], text)

    def test_child_as_a_reason_to_live_still_counts(self):
        report = RiskAgent().run(transcript("我不想讓孩子難過，所以沒有自殺。"))
        self.assertEqual([p.segment_id for p in report.protective], [1])
        report = RiskAgent().run(transcript("週末我會帶孩子去公園。"))
        self.assertEqual([p.cue for p in report.protective], ["孩子"])
        self.assertEqual(report.flags, [])

    def test_weak_note_sentence_about_that_line_waits_for_the_therapist(self):
        # CLN-13: "想帶孩子一起走" written as an outing.
        t = transcript("我想帶孩子一起走。")
        note = Note("SOAP", {"S": [NoteSentence("個案表示想帶孩子出去走走。", [1])]}, "test")
        summary = Verifier().run(note, t)
        s = note.sections["S"][0]
        self.assertTrue(s.status == "unsupported" or s.must_confirm, s.status)
        self.assertFalse(summary["ready_to_sign"])


class ThirdPersonTest(unittest.TestCase):
    """3.5: CLN-10."""

    def test_someone_elses_suicide_is_background_not_the_clients_ideation(self):
        for text in ("我朋友上個月自殺了。", "我媽以前自殺過。"):
            report = RiskAgent().run(transcript(text))
            self.assertEqual([(f.category, f.level) for f in report.flags], [(R.EXPOSURE, "info")], text)
            self.assertIn("重大失落", report.flags[0].note)
            self.assertEqual(report.protective, [], text)  # the friend is the loss, not a protective factor
            self.assertEqual(report.checklist, [], text)
            self.assertEqual(report.level, "info")

    def test_the_clients_own_ideation_next_to_a_relative_is_still_the_clients(self):
        for text in ("我怕我媽知道我想死。", "我跟我朋友說我想自殺。", "被他罵完之後我很想死。", "被他罵完很想死。"):
            fl = flags(text)
            self.assertEqual([(f.category, f.level) for f in fl], [(R.IDEATION, "high")], text)

    def test_idiom_and_drug_from_a_friend(self):
        self.assertEqual(flags("我想死你了，好久不見。"), [])
        report = RiskAgent().run(transcript("我朋友給我K他命。"))
        self.assertEqual([f.category for f in report.flags], [R.SUBSTANCE])
        self.assertEqual(report.protective, [])


class AlertFatigueTest(unittest.TestCase):
    """3.6: CLN-11."""

    def test_how_to_do_it_alone_is_not_a_cue(self):
        for text in ("主管問我這個專案要怎麼做。", "我不知道怎麼做報告。", "我不知道要怎麼做才好。"):
            self.assertEqual(flags(text), [], text)

    def test_how_to_do_it_next_to_suicide_talk_is(self):
        fl = flags(("therapist", "你有想過要結束自己的生命嗎？"), "有，我也想過要怎麼做。")
        self.assertEqual([(f.category, f.level, f.segment_id) for f in fl], [(R.PLAN, "critical", 2)])
        s04 = {f.segment_id: f for f in RiskAgent().run(load_transcript("C001-S04")).flags}
        self.assertEqual((s04[12].category, s04[12].level, s04[12].negated), (R.PLAN, "review", True))

    def test_double_negative_answer_to_a_screening_question(self):
        fl = flags(("therapist", "你有想過自殺嗎？"), "我不是沒有想過。")
        self.assertEqual([(f.category, f.level, f.negated) for f in fl], [(R.IDEATION, "high", False)])


class GuessedSpeakerTest(unittest.TestCase):
    """3.7: CLN-12, CLN-I8, CLN-I12."""

    def test_first_person_disclosure_guessed_as_therapist_keeps_its_level(self):
        report = RiskAgent().run(transcript(("therapist", "我想燒炭。"), source="model"))
        f = report.flags[0]
        self.assertEqual((f.level, f.speaker_unconfirmed, f.maybe_therapist), ("critical", True, False))
        self.assertEqual(report.level, "critical")

    def test_only_a_likely_therapist_question_is_lowered(self):
        f = flags(("unknown", "你有想過要結束自己的生命嗎？"), source="none")[0]
        self.assertEqual((f.level, f.maybe_therapist), ("review", True))
        f = flags(("unknown", "我是不是死掉比較好？"), source="none")[0]
        self.assertEqual((f.level, f.maybe_therapist), ("high", False))

    def test_protective_factor_and_checklist_agree_on_a_guessed_line(self):
        report = RiskAgent().run(transcript(("client", "有時候會想死。"), ("therapist", "我妹妹，我不想讓她難過。"), source="model"))
        self.assertEqual([p.segment_id for p in report.protective], [2])
        self.assertTrue(report.protective[0].speaker_unconfirmed)
        self.assertEqual({c["item"]: c["covered"] for c in report.checklist}["保護因子"], [2])

    def test_upload_cannot_say_whether_the_therapist_asked(self):
        report = RiskAgent().run(transcript(("unknown", "我想死。"), source="none"))
        self.assertFalse(report.speakers_confirmed)
        self.assertTrue(RiskAgent().run(load_transcript("C001-S04")).speakers_confirmed)


class TherapistReflectionTest(unittest.TestCase):
    """3.9: CLN-15."""

    def test_restated_disclosure_is_flagged(self):
        for line, category in (("所以你昨天晚上吞了一整罐藥，今天早上才醒來。", R.BEHAVIOUR), ("你剛剛說你爸會用皮帶打你。", R.REPORT_FAMILY),
                               ("你剛說想燒炭。", R.PLAN)):
            fl = flags("嗯。", ("therapist", line))
            self.assertEqual([(f.category, f.segment_id, f.therapist_reflection) for f in fl], [(category, 2, True)], line)
            self.assertIn("心理師複述", fl[0].note)
            self.assertIn(fl[0].level, ("high", "critical"))

    def test_screening_question_and_general_remark_are_not_disclosures(self):
        self.assertEqual(flags(("therapist", "你有想過要結束自己的生命嗎？")), [])
        self.assertEqual(flags(("therapist", "有時候會覺得活著好累，會想說如果消失算了。")), [])
        self.assertEqual(flags(("therapist", "如果情況變得更危險，可以打一九二五安心專線，或是直接去急診。")), [])


class ChecklistTest(unittest.TestCase):
    """3.10: CLN-9, CLN-I3."""

    FALSE_TICKS = [("therapist", "你這週有按時吃藥嗎？"), ("client", "我買了新的鞋子。"), ("client", "有，讀書計畫也有照做，常常讀到很晚。"),
                   ("therapist", "你曾經跟朋友吵架嗎？"), ("therapist", "我們一起想想方法，你週末打算做什麼？")]

    def items(self, *lines):
        return {c["item"]: c["covered"] for c in RiskAgent().run(transcript(*lines)).checklist}

    def test_everyday_words_do_not_tick_items(self):
        filler = [("client", f"這週工作上的第 {n} 件事還算順利。") for n in range(1, 8)]
        items = self.items(("therapist", "你有想過要結束自己的生命嗎？"), ("client", "有時候會想死。"), *filler, *self.FALSE_TICKS)
        self.assertEqual(items["自殺意念"], [1])
        for item in ("頻率或強度", "計畫或方法", "意圖", "工具或手段可及性", "過去自殺或自傷史"):
            self.assertEqual(items[item], [], item)

    def test_medication_and_history_words_need_their_own_question_even_right_after(self):
        items = self.items(("client", "有時候會想死。"), ("therapist", "你這週有按時吃藥嗎？"), ("therapist", "你曾經跟朋友吵架嗎？"), ("client", "我買了新的鞋子。"))
        self.assertEqual(items["工具或手段可及性"], [])
        self.assertEqual(items["過去自殺或自傷史"], [])

    def test_real_questions_do_tick(self):
        items = self.items(("client", "有時候會想死。"), ("therapist", "家裡有拿得到的藥或刀嗎？"), ("therapist", "你以前有沒有試過傷害自己？"),
                           ("therapist", "你有沒有想過怎麼做？"), ("therapist", "這個念頭多常出現？"))
        self.assertEqual((items["工具或手段可及性"], items["過去自殺或自傷史"], items["計畫或方法"], items["頻率或強度"]), ([2], [3], [4], [5]))

    def test_asked_about_suicide_is_one_answer_not_two(self):
        # CLN-I3: "你有沒有想過自殺？" used to show "✗ 未見詢問" beside "✓ 自殺意念".
        report = RiskAgent().run(transcript(("client", "我想死。"), ("therapist", "你有沒有想過自殺？")))
        asked = {c["item"]: c["covered"] for c in report.checklist}["自殺意念"]
        self.assertEqual(report.screening_asked, [2])
        self.assertEqual(asked, report.screening_asked)
        s04 = RiskAgent().run(load_transcript("C001-S04"))
        self.assertEqual({c["item"]: c["covered"] for c in s04.checklist}["自殺意念"], s04.screening_asked)

    def test_s04_checklist_is_what_the_readme_describes(self):
        items = {c["item"]: c["covered"] for c in RiskAgent().run(load_transcript("C001-S04")).checklist}
        self.assertEqual(items["自殺意念"], [11])
        self.assertIn(13, items["頻率或強度"])
        self.assertIn(15, items["保護因子"])
        self.assertEqual(items["安全計畫"], [17])
        self.assertEqual(items["危機資源或轉介"], [19, 20])
        self.assertEqual((items["工具或手段可及性"], items["過去自殺或自傷史"]), ([], []))


class WriterWithNewCuesTest(unittest.TestCase):
    """CLN-7 again, now that abuse is a cue: neither disclosure may be left out of the note."""

    def test_charcoal_and_belt_are_both_written(self):
        t = transcript("我想燒炭。", "我爸會用皮帶抽我。", ("therapist", "你有沒有想過自殺？"), ("therapist", "我們來擬安全計畫，好嗎？"))
        risk_lines = [s.text for s in NoteWriter().run(t).sections["R"]]
        self.assertTrue(any("燒炭" in x for x in risk_lines))
        self.assertTrue(any("皮帶" in x for x in risk_lines))


if __name__ == "__main__":
    print(format_table(recall_table()))
    unittest.main(argv=sys.argv[:1])
