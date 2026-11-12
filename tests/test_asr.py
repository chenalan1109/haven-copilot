"""Uploaded-audio path: local transcription server, speaker labels, and how guessed labels are used."""

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("HAVEN_LLM", "demo")

from haven import config, transcript  # noqa: E402
from haven.agents.risk import RiskAgent  # noqa: E402
from haven.agents.speakers import SpeakerAgent  # noqa: E402
from haven.llm import NonLocalEndpointError  # noqa: E402
from haven.models import Segment, Transcript  # noqa: E402


def _transcript(*texts):
    segs = [Segment(i, i * 5.0, i * 5.0 + 4, "unknown", t, speaker_source="none") for i, t in enumerate(texts, start=1)]
    return Transcript("T-S01", "C001", 1, "2026-11-08", segs)


GOOD = {"text": "…", "segments": [
    {"start": 0.0, "end": 4.2, "text": "有時候會覺得活著好累。"},
    {"start": 4.2, "end": 7.0, "text": "  "},
    {"start": 7.0, "end": 9.5, "text": "這些想法多常出現？"},
]}


class FakeWhisper(BaseHTTPRequestHandler):
    seen = {}
    reply = (200, GOOD)

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        FakeWhisper.seen = {"path": self.path, "ctype": self.headers["Content-Type"], "body": body}
        status, out = FakeWhisper.reply
        data = out if isinstance(out, bytes) else json.dumps(out, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


class OpenAITranscriptionTest(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeWhisper)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.saved = (config.ASR_BACKEND, config.ASR_URL)
        config.ASR_BACKEND, config.ASR_URL = "openai", f"http://127.0.0.1:{self.srv.server_port}"
        self.audio = Path(tempfile.mkdtemp()) / "a.wav"
        self.audio.write_bytes(b"RIFF-fake-audio")

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        FakeWhisper.reply = (200, GOOD)
        config.ASR_BACKEND, config.ASR_URL = self.saved

    def test_bad_replies_are_asr_errors(self):
        for reply in ((400, {"error": "file too large"}), (200, b"<html>"), (200, {"segments": [{"end": 1, "text": "x"}]}),
                      (200, {"text": None}), (200, [])):
            FakeWhisper.reply = reply
            with self.assertRaises(transcript.ASRError, msg=str(reply)):
                transcript.transcribe_audio(self.audio, "T-S01", "C001", 1, "2026-11-08")

    def test_text_without_timestamps_is_split_into_sentences(self):
        FakeWhisper.reply = (200, {"text": "最近睡不好。這些想法多常出現？大概每天晚上。", "duration": 12.0})
        t = transcript.transcribe_audio(self.audio, "T-S01", "C001", 1, "2026-11-08")
        self.assertEqual([s.text for s in t.segments], ["最近睡不好。", "這些想法多常出現？", "大概每天晚上。"])
        self.assertAlmostEqual(t.segments[-1].end, 12.0, places=0)

    def test_segments_from_local_server(self):
        t = transcript.transcribe_audio(self.audio, "T-S01", "C001", 1, "2026-11-08")
        self.assertEqual([s.text for s in t.segments], ["有時候會覺得活著好累。", "這些想法多常出現？"])
        self.assertEqual([s.id for s in t.segments], [1, 2])
        self.assertTrue(all(s.speaker == "unknown" and s.speaker_source == "none" for s in t.segments))
        self.assertEqual(FakeWhisper.seen["path"], "/v1/audio/transcriptions")
        self.assertIn(b"RIFF-fake-audio", FakeWhisper.seen["body"])
        self.assertIn(b'name="language"\r\n\r\nzh', FakeWhisper.seen["body"])

    def test_no_prompt_for_the_local_server_by_default(self):
        # Measured on the B70: a prompt made whisper-large-v3-turbo drop the last utterance.
        transcript.transcribe_audio(self.audio, "T-S01", "C001", 1, "2026-11-08")
        self.assertNotIn(b'name="prompt"', FakeWhisper.seen["body"])

    def test_half_width_punctuation_is_normalised(self):
        FakeWhisper.reply = (200, {"segments": [{"start": 0, "end": 3, "text": "有想過,但是沒有真的想要怎麼做?大概3,000元"}]})
        t = transcript.transcribe_audio(self.audio, "T-S01", "C001", 1, "2026-11-08")
        self.assertEqual(t.segments[0].text, "有想過，但是沒有真的想要怎麼做？大概3,000元")

    def test_refuses_cloud_transcription(self):
        config.ASR_URL = "https://api.openai.com"
        with self.assertRaises(NonLocalEndpointError):
            transcript.transcribe_audio(self.audio, "T-S01", "C001", 1, "2026-11-08")


class SpeakerAgentTest(unittest.TestCase):
    def test_labels_unknown_segments_as_guesses(self):
        class LLM:
            def generate_json(self, system, prompt, max_tokens=None):
                return {"speakers": [{"id": 1, "speaker": "therapist"}, {"id": 2, "speaker": "client"}, {"id": 3, "speaker": "narrator"}]}
        t = _transcript("這週過得怎麼樣？", "不太好，睡不著。", "嗯。")
        self.assertEqual(SpeakerAgent(LLM()).run(t), 2)
        self.assertEqual([(s.speaker, s.speaker_source) for s in t.segments],
                         [("therapist", "model"), ("client", "model"), ("unknown", "none")])

    def test_no_model_leaves_speakers_unknown(self):
        t = _transcript("這週過得怎麼樣？")
        self.assertEqual(SpeakerAgent(None).run(t), 0)
        self.assertEqual(t.segments[0].speaker, "unknown")

    def test_bad_model_output_is_ignored(self):
        class LLM:
            def generate_json(self, system, prompt, max_tokens=None):
                return {"speakers": "therapist"}
        t = _transcript("這週過得怎麼樣？")
        self.assertEqual(SpeakerAgent(LLM()).run(t), 0)


class GuessedSpeakerRiskTest(unittest.TestCase):
    def test_guessed_therapist_label_does_not_hide_a_disclosure(self):
        t = _transcript("有時候會覺得活著好累，會想說如果消失算了。")
        t.segments[0].speaker, t.segments[0].speaker_source = "therapist", "model"
        report = RiskAgent().run(t)
        self.assertEqual([f.segment_id for f in report.flags], [1])

    def test_unlabelled_question_is_still_scanned(self):
        # A client's question ("…你會覺得我很糟嗎？") must not be taken for screening.
        t = _transcript("我最近很想死，你會覺得我很糟嗎？")
        report = RiskAgent().run(t)
        self.assertEqual([(f.segment_id, f.level, f.speaker_unconfirmed) for f in report.flags], [(1, "review", True)])
        self.assertEqual(report.screening_asked, [])

    def test_guessed_labels_do_not_tick_the_checklist(self):
        t = _transcript("有時候會想死。", "我有在吃藥。")
        t.segments[0].speaker, t.segments[0].speaker_source = "client", "model"
        t.segments[1].speaker, t.segments[1].speaker_source = "therapist", "model"
        items = {c["item"]: c["covered"] for c in RiskAgent().run(t).checklist}
        self.assertEqual(items["工具或手段可及性"], [])

    def test_note_on_guessed_speakers_waits_for_the_therapist(self):
        from haven.agents.verifier import Verifier
        from haven.models import Note, NoteSentence
        t = _transcript("最近睡不好，半夜三點就醒來。")
        t.segments[0].speaker, t.segments[0].speaker_source = "client", "model"
        note = Note("SOAP", {"S": [NoteSentence("個案表示最近睡不好，半夜三點就醒來。", [1])]}, "test")
        Verifier().run(note, t)
        self.assertEqual(note.sections["S"][0].status, "weak")
        self.assertIn("推測", note.sections["S"][0].reason)

    def test_scripted_therapist_line_is_not_a_disclosure(self):
        t = _transcript("有時候會覺得活著好累，會想說如果消失算了。")
        t.segments[0].speaker, t.segments[0].speaker_source = "therapist", "script"
        self.assertEqual(RiskAgent().run(t).flags, [])


if __name__ == "__main__":
    unittest.main()
