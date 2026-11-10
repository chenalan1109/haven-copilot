"""Measures speech-to-text and speaker guessing on a recording of a scripted session.

    python3 scripts/asr_eval.py recording.ogg --session C001-S04 --segments 10-12 --label b70-whisper-turbo

The recording is someone reading segments of a demo session aloud, so the script is
the reference. Reports the character error rate (edit distance over reference length,
punctuation and spaces ignored), how long transcription took, and how many of the
transcribed segments the speaker agent labelled as the script does.

Uses the same settings as the app (HAVEN_ASR, HAVEN_ASR_URL, HAVEN_LLM, ...). Recordings
are not kept in the repository; results go to docs/asr-eval/<label>.md and .json.
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from haven import config  # noqa: E402
from haven.agents.speakers import SpeakerAgent  # noqa: E402
from haven.llm import get_llm  # noqa: E402
from haven.transcript import asr_prompt, load_transcript, transcribe_audio  # noqa: E402

_KEEP = re.compile(r"[^一-鿿A-Za-z0-9]")


def plain(text: str) -> str:
    return _KEEP.sub("", text)


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(reference: str, hypothesis: str) -> float:
    ref = plain(reference)
    return edit_distance(ref, plain(hypothesis)) / len(ref) if ref else 0.0


def closest(text: str, references: list) -> object:
    """The reference segment a transcribed segment most likely came from."""
    grams = lambda s: {s[i:i + 2] for i in range(len(s) - 1)}  # noqa: E731
    g = grams(plain(text))
    return max(references, key=lambda r: len(g & grams(plain(r.text))))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", type=Path)
    ap.add_argument("--session", required=True, help="demo session the recording reads from")
    ap.add_argument("--segments", required=True, help="first-last segment ids read aloud, e.g. 10-12")
    ap.add_argument("--label", required=True)
    args = ap.parse_args()

    first, last = (int(x) for x in args.segments.split("-"))
    reference = [s for s in load_transcript(args.session).segments if first <= s.id <= last]

    t0 = time.perf_counter()
    t = transcribe_audio(args.audio, "ASR-EVAL", "C000", 1, "2026-01-01")
    asr_seconds = time.perf_counter() - t0
    audio_seconds = t.segments[-1].end if t.segments else 0.0

    llm = get_llm()
    t1 = time.perf_counter()
    labelled = SpeakerAgent(llm).run(t)
    speaker_seconds = time.perf_counter() - t1
    rows = []
    for s in t.segments:
        ref = closest(s.text, reference)
        rows.append({"start": s.start, "end": s.end, "text": s.text, "speaker_guess": s.speaker,
                     "script_segment": ref.id, "script_speaker": ref.speaker})
    right = sum(r["speaker_guess"] == r["script_speaker"] for r in rows)

    report = {
        "label": args.label,
        "date": datetime.now().astimezone().isoformat(timespec="seconds"),
        "asr": f"{config.ASR_BACKEND}:{config.ASR_MODEL}",
        "asr_prompt": asr_prompt(),
        "speaker_model": llm.label if llm else None,
        "reference": f"{args.session} segments {first}-{last}",
        "audio_seconds": round(audio_seconds, 1),
        "asr_seconds": round(asr_seconds, 1),
        "speaker_seconds": round(speaker_seconds, 1),
        "reference_characters": len(plain("".join(s.text for s in reference))),
        "cer": round(cer("".join(s.text for s in reference), "".join(s.text for s in t.segments)), 4),
        "segments": len(rows),
        "speakers_labelled": labelled,
        "speakers_right": right,
        "rows": rows,
    }
    out = ROOT / "docs" / "asr-eval"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.label}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# Speech-to-text check: {args.label}", "",
        f"- Speech-to-text: `{report['asr']}`" + (f", prompt 「{asr_prompt()}」" if asr_prompt() else ", no prompt"),
        f"- Speaker guessing: `{report['speaker_model']}`",
        f"- Date: {report['date']}",
        f"- Recording: {report['reference']} read aloud, {report['audio_seconds']} s. The recording is not in the repository.",
        f"- Reference: the script ({report['reference_characters']} characters). A reader who strays from the script counts as an error.", "",
        f"**Character error rate {report['cer']:.1%}** · transcribed in {report['asr_seconds']} s "
        f"· speakers guessed right in {right}/{len(rows)} segments ({report['speaker_seconds']} s)", "",
        "| Time | Transcribed | Guessed speaker | Script line | Script speaker |", "| --- | --- | --- | --- | --- |",
    ]
    lines += [f"| {r['start']}–{r['end']} s | {r['text']} | {r['speaker_guess']} | #{r['script_segment']} | {r['script_speaker']} |" for r in rows]
    lines += ["", "Script:", ""] + [f"- #{s.id} {s.speaker}: {s.text}" for s in reference]
    (out / f"{args.label}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"CER {report['cer']:.1%}, ASR {report['asr_seconds']} s for {report['audio_seconds']} s of audio, "
          f"speakers {right}/{len(rows)}")
    print(f"wrote docs/asr-eval/{args.label}.md")


if __name__ == "__main__":
    main()
