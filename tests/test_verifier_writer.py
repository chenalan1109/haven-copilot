"""Batch 2 of the 2026-11-12 review: verifier and note writer.

The inputs are the reviewers' own (ENG-2, ENG-4, ENG-6..8, CLN-2, CLN-7, CLN-8,
CLN-13, CLN-17, CLN-21).
"""

import unittest

from helpers import IsolatedData, ServerCase

from haven import signing, store
from haven.agents.risk import RiskAgent
from haven.agents.verifier import MODEL_SILENT, Verifier, rule_violation, unbacked_clause
from haven.agents.writer import CHUNK, FALLBACK_ENGINE, TEMPLATES, NoteWriter, _evidence, _parse
from haven.models import Note, NoteSentence, Segment, Transcript
from haven.orchestrator import Orchestrator
from haven.transcript import load_transcript


def transcript(*lines, speaker="client"):
    """Lines are text, or (speaker, text)."""
    segs = []
    for i, line in enumerate(lines, start=1):
        who, text = line if isinstance(line, tuple) else (speaker, line)
        segs.append(Segment(i, float(i), float(i + 1), who, text))
    return Transcript("T-S01", "C001", 1, "2026-11-12", segs)


class FakeLLM:
    label = "fake:model"
    url = "http://127.0.0.1:1"

    def __init__(self, answer):
        self.answer, self.calls = answer, 0

    def generate_json(self, system, prompt, max_tokens=None):
        self.calls += 1
        return self.answer(prompt) if callable(self.answer) else self.answer


YES = FakeLLM({"results": [{"id": i, "supported": True} for i in range(40)]})
NO = FakeLLM({"results": [{"id": i, "supported": False} for i in range(40)]})


def verify(t, text, evidence, llm=None):
    note = Note("SOAP", {"S": [NoteSentence(text, evidence)]}, "test")
    summary = Verifier(llm).run(note, t)
    return note.sections["S"][0], summary


class ReversedMeaningTest(unittest.TestCase):
    """2.1: ENG-2, CLN-2, CLN-13, CLN-I11."""

    def setUp(self):
        self.s04 = load_transcript("C001-S04")

    def assertBlocked(self, sentence, summary):
        self.assertTrue(sentence.status == "unsupported" or sentence.must_confirm, (sentence.status, sentence.reason))
        self.assertFalse(summary["ready_to_sign"])

    def test_segment_12_rewritten_as_wanting_to_act(self):
        s, summary = verify(self.s04, "個案表示有想過，而且真的想要怎麼做，就是晚上一個人的時候會冒出來。", [12])
        self.assertEqual(s.status, "unsupported")
        self.assertIn("否定", s.reason)
        self.assertFalse(summary["ready_to_sign"])

    def test_segment_10_rewritten_as_denial(self):
        s, _ = verify(self.s04, "個案表示不會覺得活著好累，沒有想說消失算了。", [10])
        self.assertEqual(s.status, "unsupported")

    def test_cutting_denied(self):
        t = transcript("這個月我又割腕了兩次，晚上一個人的時候還好。")
        for llm in (None, YES):
            s, summary = verify(t, "個案表示這個月沒有割腕，晚上一個人的時候還好。", [1], llm)
            self.assertEqual(s.status, "unsupported", llm)
        s, summary = verify(transcript("我昨天又割腕了。"), "個案表示昨天沒有割腕。", [1])
        self.assertBlocked(s, summary)

    def test_stockpiled_pills_denied(self):
        s, summary = verify(transcript("我已經存了很多安眠藥。"), "個案表示沒有存安眠藥。", [1], YES)
        self.assertEqual(s.status, "unsupported")
        self.assertFalse(summary["ready_to_sign"])

    def test_double_negation_is_an_affirmation(self):
        t = transcript("我沒有一天不想死。")
        s, summary = verify(t, "個案表示沒有想死。", [1])
        self.assertEqual(s.status, "unsupported")
        self.assertFalse(summary["ready_to_sign"])
        s, _ = verify(t, "個案表示沒有一天不想死。", [1])
        self.assertEqual(s.status, "supported")
        s, _ = verify(t, "個案表示每天都想死。", [1])
        self.assertNotIn("否定", s.reason)

    def test_negation_in_another_clause_does_not_block_a_true_sentence(self):
        t = transcript("我睡不好，常常想死。")
        s, _ = verify(t, "個案表示常常想死。", [1])
        self.assertEqual(s.status, "supported")
        s, summary = verify(t, "個案否認想死。", [1])
        self.assertBlocked(s, summary)

    def test_earlier_rule_still_holds_for_paraphrased_risk_sentences(self):
        source = "有想過，但是沒有真的想要怎麼做"
        self.assertIn("否定", rule_violation("個案表示有具體自殺計畫。", source))
        self.assertEqual(rule_violation("個案曾想過結束生命，但沒有具體計畫。", source), "")

    def test_risk_agent_does_not_lower_a_double_negation(self):
        for text in ("我沒有一天不想死。", "我沒辦法不去想死這件事。", "我不是不想死。", "我不會不想死。", "不是不想死，是不敢。"):
            flags = RiskAgent().run(transcript(text)).flags
            self.assertTrue(flags, text)
            self.assertEqual((flags[0].level, flags[0].negated), ("high", False), text)
        denied = RiskAgent().run(transcript("我沒有想死。")).flags[0]
        self.assertEqual((denied.level, denied.negated), ("review", True))


class RiskSentenceScopeTest(unittest.TestCase):
    """2.2: CLN-13. Self-harm, harm to others and abuse wording counts as risk too."""

    def test_weak_self_harm_sentence_waits_for_the_therapist(self):
        s, summary = verify(transcript("我昨天又割腕了。"), "個案昨日再度出現割腕行為。", [1], YES)
        self.assertEqual(s.status, "weak")
        self.assertTrue(s.must_confirm)
        self.assertFalse(summary["ready_to_sign"])

    def test_weak_violence_and_substance_sentences_wait_too(self):
        for line, text in (("他喝醉了就會動手，上禮拜又來一次。", "個案表示伴侶酒後曾對其施加暴力。"),
                           ("我最近每天晚上都要喝到睡著。", "個案表示近期每晚飲酒助眠。")):
            s, summary = verify(transcript(line), text, [1], YES)
            self.assertTrue(s.must_confirm, text)

    def test_weak_sentence_citing_a_risk_line_waits_whatever_its_words(self):
        s, summary = verify(load_transcript("C001-S04"), "個案偶爾覺得生活沉重，希望自己不存在。", [10], YES)
        self.assertEqual(s.status, "weak")
        self.assertTrue(s.must_confirm)

    def test_study_plan_is_still_not_a_risk_sentence(self):
        s, _ = verify(load_transcript("C002-S05"), "個案五天中有四天完成每天兩個番茄鐘的讀書計畫。", [7, 8], YES)
        self.assertEqual(s.status, "supported")


class InventedClauseTest(unittest.TestCase):
    """2.3: ENG-4. A clause added to an otherwise matching sentence."""

    def setUp(self):
        self.s04 = load_transcript("C001-S04")

    def test_clause_is_found(self):
        self.assertEqual(unbacked_clause("個案表示對什麼事都提不起勁，已經想放棄工作。", self.s04.by_id()[4].text), "已經想放棄工作")
        self.assertEqual(unbacked_clause("個案表示對什麼事都提不起勁。", self.s04.by_id()[4].text), "")

    def test_sentence_is_held_not_passed(self):
        s, _ = verify(self.s04, "個案表示對什麼事都提不起勁，已經想放棄工作。", [4])
        self.assertEqual(s.status, "weak")
        self.assertIn("已經想放棄工作", s.reason)

    def test_model_no_blocks_it(self):
        s, summary = verify(self.s04, "個案表示對什麼事都提不起勁，已經想放棄工作。", [4], NO)
        self.assertTrue(s.must_confirm)
        self.assertFalse(summary["ready_to_sign"])

    def test_clause_added_to_a_risk_line_blocks_without_a_model(self):
        s, summary = verify(self.s04, "個案表示晚上一個人的時候會冒出想法，希望家人陪伴。", [12])
        self.assertEqual(s.status, "weak")
        self.assertTrue(s.must_confirm)
        self.assertFalse(summary["ready_to_sign"])


class ModelLayerFaultTest(unittest.TestCase):
    """2.4: ENG-7."""

    def test_results_that_are_not_a_list_do_not_crash(self):
        for answer in ({"results": 5}, {"results": None}, {"results": "yes"}, None, [1], {"results": [5, {"id": "x", "supported": True}, {"supported": True}]}):
            s, summary = verify(load_transcript("C001-S04"), "個案表示被主管當眾責罵後已辭職。", [2], FakeLLM(answer))
            self.assertNotEqual(s.status, "supported", answer)

    def test_no_answer_is_not_reported_as_a_model_judgement(self):
        for answer in (None, {"results": 5}):
            s, summary = verify(load_transcript("C001-S04"), "個案表示被主管當眾責罵後請了假休息。", [2], FakeLLM(answer))
            self.assertEqual(s.reason, MODEL_SILENT)
            self.assertNotIn("模型判斷", s.reason)
            self.assertFalse(s.model_rejected)
            self.assertTrue(summary["llm_failed"])
            self.assertTrue(summary["warnings"])

    def test_model_that_raises_is_treated_as_silent(self):
        def boom(prompt):
            raise RuntimeError("context overflow")
        s, summary = verify(load_transcript("C001-S04"), "個案表示被主管當眾責罵後請了假休息。", [2], FakeLLM(boom))
        self.assertEqual(s.reason, MODEL_SILENT)

    def test_an_explicit_no_reads_as_the_models_judgement(self):
        s, _ = verify(load_transcript("C001-S04"), "個案表示被主管當眾責罵後已辭職。", [2], NO)
        self.assertIn("模型判斷", s.reason)
        self.assertTrue(s.model_rejected)

    def test_silent_verdicts_are_not_cached_as_the_servers_verdict(self):
        with IsolatedData():
            note = Note("SOAP", {"S": [NoteSentence("個案表示被主管當眾責罵後請了假休息。", [2])]}, "test")
            summary = Verifier(FakeLLM(None)).run(note, load_transcript("C001-S04"))
            signing.remember("C001-S04", note, summary["llm_failed"])
            self.assertEqual(store.get_verdicts("C001-S04", signing.transcript_sha256("C001-S04"), summary["verifier_version"]), {})


class EvidenceParsingTest(unittest.TestCase):
    """2.5: ENG-8."""

    def test_evidence_forms(self):
        self.assertEqual(_evidence(4), [4])
        self.assertEqual(_evidence("12"), [12])  # was [1, 2]: the wrong lines, unnoticed
        self.assertEqual(_evidence("#4, #12"), [4, 12])
        self.assertEqual(_evidence(["4", 12, None]), [4, 12])
        self.assertEqual(_evidence(None), [])
        self.assertEqual(_evidence(True), [])

    def test_single_number_and_null_evidence_do_not_crash(self):
        parsed = _parse({"S": [{"text": "個案睡眠很差。", "evidence": 4}, {"text": "個案很累。", "evidence": None}]}, "SOAP")
        self.assertEqual([s.evidence for s in parsed["S"]], [[4], []])

    def test_wrong_citation_is_kept_for_the_verifier(self):
        t = load_transcript("C001-S03")
        note = NoteWriter(FakeLLM({"S": [{"text": "個案表示睡眠很差。", "evidence": [4, 999]}]})).run(t)
        self.assertEqual(note.sections["S"][0].evidence, [4, 999])
        Verifier().run(note, t)
        self.assertEqual(note.sections["S"][0].status, "unsupported")
        self.assertIn("不存在", note.sections["S"][0].reason)

    def test_one_bad_field_does_not_discard_the_note(self):
        t = load_transcript("C001-S03")
        llm = FakeLLM({"S": [{"text": "個案表示睡眠很差。", "evidence": [4]}], "O": None, "A": "none", "P": [{"text": "下週同一時間見。", "evidence": "20"}]})
        note = NoteWriter(llm).run(t)
        self.assertEqual(note.engine, "fake:model")
        self.assertEqual(note.warnings, [])
        self.assertEqual(note.sections["P"][0].evidence, [20])
        self.assertEqual(note.sections["O"], [])


def long_transcript(n=240):
    lines = []
    for i in range(n):
        lines.append(("therapist", f"第 {i} 段，這週的狀況怎麼樣？") if i % 2 == 0 else ("client", f"我覺得很累，這是第 {i} 件事。"))
    return transcript(*lines)


class FallbackTest(ServerCase, unittest.TestCase):
    """2.6: ENG-6, ENG-F5, JDG-I6. The model does not answer."""

    llm = FakeLLM(None)

    def test_result_ui_fields_and_audit_say_rule_engine(self):
        status, r = self.call("/api/sessions/C002-S05/open", {})
        self.assertEqual(status, 200)
        self.assertEqual(r["engine"], FALLBACK_ENGINE)
        self.assertEqual(r["note"]["engine"], FALLBACK_ENGINE)
        self.assertNotIn("fake:model", r["engine"])
        self.assertTrue(any("本機模型" in w and "規則引擎" in w for w in r["warnings"]))
        detail = next(a["detail"] for a in store.recent_audit() if a["action"] == "process_session")
        self.assertIn(FALLBACK_ENGINE, detail)

    def test_long_session_is_written_in_parts_to_the_end(self):
        t = long_transcript()
        llm = FakeLLM(None)
        note = NoteWriter(llm).run(t)
        self.assertEqual(llm.calls, len(t.segments) // CHUNK)
        cited = {e for s in note.sentences() for e in s.evidence}
        self.assertGreater(max(cited), len(t.segments) - CHUNK)  # not just the opening minutes
        self.assertEqual(note.engine, FALLBACK_ENGINE)

    def test_partial_failure_names_the_part(self):
        def first_part_only(prompt):
            return {"S": [{"text": "個案表示覺得很累。", "evidence": [2]}]} if "這是第 1 段" in prompt else None
        note = NoteWriter(FakeLLM(first_part_only)).run(long_transcript())
        self.assertIn("fake:model", note.engine)
        self.assertIn("第 2、3、4 段", note.engine)
        self.assertTrue(note.warnings)

    def test_rule_engine_alone_also_covers_a_long_session(self):
        t = long_transcript()
        cited = {e for s in NoteWriter().run(t).sentences() for e in s.evidence}
        self.assertGreater(max(cited), len(t.segments) - CHUNK)


class RuleEngineRiskTest(unittest.TestCase):
    """2.7, 2.8: CLN-7, CLN-8, CLN-17, CLN-21, CLN-I4."""

    def texts(self, note, key):
        return [s.text for s in note.sections[key]]

    def test_disclosure_is_written_and_a_proposal_is_not_a_finished_plan(self):
        t = transcript(("client", "我想燒炭。"), ("client", "我爸會用皮帶抽我。"), ("therapist", "你有沒有想過自殺？"), ("therapist", "我們來擬安全計畫，好嗎？"))
        note = NoteWriter().run(t)
        self.assertTrue(any("燒炭" in x for x in self.texts(note, "R")))
        plan = self.texts(note, "P")
        self.assertNotIn("我們來擬安全計畫。", plan)
        self.assertTrue(any(x.startswith("心理師提議") and "安全計畫" in x for x in plan), plan)

    def test_sentence_limit_cannot_push_a_disclosure_out(self):
        lines = [f"我覺得很累，第 {n} 件事。" for n in range(1, 9)] + ["我昨天晚上又割腕了，覺得活著沒意義。"]
        note = NoteWriter().run(transcript(*lines))
        self.assertEqual(len(note.sections["S"]), 6)
        self.assertTrue(any("割腕" in x for x in self.texts(note, "R")))

    def test_s04_keeps_the_protective_factor_and_writes_the_safety_plan_as_proposed(self):
        t = load_transcript("C001-S04")
        note = NoteWriter().run(t)
        cited = {e for s in note.sections["R"] for e in s.evidence}
        self.assertTrue({10, 12, 16} <= cited)
        plan = self.texts(note, "P")
        self.assertNotIn("我們今天一起來擬一個安全計畫。", plan)
        proposal = next(s for s in note.sections["P"] if "安全計畫" in s.text)
        self.assertTrue(proposal.text.startswith("心理師提議"))
        self.assertIn("個案回應：好", proposal.text)
        self.assertEqual(proposal.evidence, [17, 18])
        self.assertFalse(any(x.startswith("我") or "我會建議" in x for x in plan), plan)
        self.assertTrue(Verifier().run(note, t)["ready_to_sign"])

    def test_dap_has_the_risk_section_too(self):
        self.assertIn("R", TEMPLATES["SOAP"])
        self.assertIn("R", TEMPLATES["DAP"])
        note = NoteWriter().run(load_transcript("C001-S04"), "DAP")
        self.assertEqual(list(note.sections), ["D", "A", "P", "R"])
        self.assertTrue(note.sections["R"])

    def test_model_note_that_skips_the_disclosure_gets_it_added(self):
        t = load_transcript("C001-S04")
        note = NoteWriter(FakeLLM({"S": [{"text": "個案表示上週被主管責罵後請假。", "evidence": [2]}]})).run(t)
        self.assertIn(10, {e for s in note.sections["R"] for e in s.evidence})
        self.assertEqual(signing.uncovered_risk({"flags": [{"segment_id": f.segment_id, "level": f.level, "category": f.category, "quote": f.quote}
                                                           for f in RiskAgent().run(t).flags]}, note), [])

    def test_unknown_speaker_disclosure_is_written_and_held(self):
        t = transcript(("unknown", "最近還好嗎？"), ("unknown", "我上個月割腕了兩次。"), ("unknown", "嗯。"))
        for s in t.segments:
            s.speaker_source = "none"
        note = NoteWriter().run(t)
        self.assertTrue(any("割腕" in x for x in self.texts(note, "R")))
        summary = Verifier().run(note, t)
        self.assertFalse(summary["ready_to_sign"])  # who said it is not confirmed

    def test_self_criticism_written_as_fact_is_caught(self):
        t = load_transcript("C001-S03")
        s, summary = verify(t, "個案確實什麼都做不好。", [8])
        self.assertEqual(s.status, "unsupported")
        self.assertIn("主觀感受", s.reason)
        s, _ = verify(t, "個案表示覺得自己好像真的什麼都做不好。", [8])
        self.assertEqual(s.status, "supported")

    def test_rule_engine_reports_self_criticism_as_said(self):
        note = NoteWriter().run(load_transcript("C001-S03"))
        line = next(s for s in note.sections["S"] if "做不好" in s.text)
        self.assertTrue(line.text.startswith("個案表示"))


class PromptTest(unittest.TestCase):
    """2.9: CLN-I15. O is observed behaviour, still cited. Batch 9: only what the
    transcript text shows; tone, pace, expression and inferred affect are the therapist's to add."""

    def test_objective_section_definition(self):
        o = TEMPLATES["SOAP"]["O"]
        self.assertIn("行為", o)
        self.assertIn("引用", o)
        for word in ("語氣", "語速", "神情", "語氣中透露出"):
            self.assertIn(word, o.split("一律不要寫")[0])  # listed among what not to write
        self.assertIn("語速", TEMPLATES["DAP"]["D"].split("不要寫")[0])

    def test_prompt_tells_the_model_about_proposals_and_risk_section(self):
        from haven.agents.writer import SYSTEM_PROMPT, _prompt
        self.assertIn("心理師提議", SYSTEM_PROMPT)
        self.assertIn('"R"', _prompt(load_transcript("C001-S04"), "SOAP"))


class DemoNotesTest(unittest.TestCase):
    def test_demo_notes_still_pass_and_s05_stays_quiet(self):
        orch = Orchestrator(use_llm=False)
        with IsolatedData():
            for sid in ("C001-S03", "C001-S04", "C002-S05"):
                r = orch.process_session(sid)
                self.assertTrue(r["verification"]["ready_to_sign"], sid)
                self.assertEqual(r["risk_uncovered"], [], sid)
                self.assertEqual(r["warnings"], [], sid)
                self.assertEqual(r["engine"], "rule-based demo")
            self.assertEqual(RiskAgent().run(load_transcript("C002-S05")).flags, [])


if __name__ == "__main__":
    unittest.main()
