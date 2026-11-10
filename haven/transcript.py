"""ASR agent: turns session audio (or a prepared transcript) into segments."""

from __future__ import annotations

import json
import re
import urllib.error
import uuid
import urllib.request
from pathlib import Path

from . import config
from .models import Segment, Transcript


def load_transcript(session_id: str) -> Transcript:
    path = config.SESSIONS_DIR / f"{session_id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Transcript(
        session_id=raw["session_id"],
        client_id=raw["client_id"],
        session_no=raw["session_no"],
        date=raw["date"],
        simulated=raw.get("simulated", True),
        segments=[Segment(**s) for s in raw["segments"]],
    )


_whisper = None


def _whisper_model():
    """Loads the model once per process; loading takes longer than a short clip."""
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel  # optional dependency

        _whisper = WhisperModel(config.ASR_MODEL, device="auto", compute_type="int8")
    return _whisper


def asr_prompt() -> str:
    if config.ASR_PROMPT is not None:
        return config.ASR_PROMPT
    return "" if config.ASR_BACKEND == "openai" else "以下是心理諮商會談的逐字稿，使用繁體中文。"


_HALF = {",": "，", "?": "？", "!": "！", ";": "；", ":": "："}
_HALF_RE = re.compile(r"(?<![0-9A-Za-z])[,?!;:]|[,?!;:](?![0-9A-Za-z])")
_opencc = None


def _clean(text: str) -> str:
    """Whisper may write half-width punctuation or Simplified characters. The risk
    lexicon and the verifier rules are written in Traditional Chinese with full-width
    punctuation, so the transcript is brought to that form before any agent reads it."""
    global _opencc
    text = _HALF_RE.sub(lambda m: _HALF[m.group()], text.strip())
    if _opencc is None:
        try:
            from opencc import OpenCC  # optional: pip install opencc-python-reimplemented
            _opencc = OpenCC("s2twp").convert
        except ImportError:
            _opencc = False
    return _opencc(text) if _opencc else text


class ASRError(Exception):
    """The speech-to-text server answered, but not with a usable transcript."""


def _sentences(text: str, duration: float) -> list[tuple[float, float, str]]:
    """Splits a transcript without timestamps at sentence ends, spreading the time
    by length, so a whole session is never one line that every citation points to."""
    parts = [p for p in re.findall(r"[^。！？!?]+[。！？!?]?", text) if p.strip()]
    total = sum(len(p) for p in parts) or 1
    out, t = [], 0.0
    for p in parts:
        d = duration * len(p) / total
        out.append((t, t + d, p))
        t += d
    return out


def _faster_whisper(audio_path: Path) -> list[tuple[float, float, str]]:
    raw_segments, _info = _whisper_model().transcribe(str(audio_path), language="zh", vad_filter=True, initial_prompt=asr_prompt() or None)
    return [(s.start, s.end, s.text) for s in raw_segments]


def _openai_server(audio_path: Path) -> list[tuple[float, float, str]]:
    """Sends the audio to a local server with the OpenAI transcription API (vLLM serving
    Whisper on the B70). The same local-only rule as the note model applies."""
    from .llm import _OPENER, assert_local

    assert_local(config.ASR_URL)
    boundary = uuid.uuid4().hex
    fields = {"model": config.ASR_MODEL, "language": "zh", "response_format": "verbose_json"}
    if asr_prompt():
        fields["prompt"] = asr_prompt()
    body = b"".join(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode() for k, v in fields.items()
    ) + (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"audio{audio_path.suffix}\"\r\n"
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + audio_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{config.ASR_URL.rstrip('/')}/v1/audio/transcriptions",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with _OPENER.open(req, timeout=config.ASR_TIMEOUT) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:  # an answer, not a connection failure
        raise ASRError(f"HTTP {e.code}") from e
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ASRError("reply is not JSON") from e
    if not isinstance(out, dict):
        raise ASRError("reply is not a JSON object")
    segments = out.get("segments")
    if isinstance(segments, list) and segments:
        try:
            return [(float(s["start"]), float(s["end"]), str(s.get("text") or "")) for s in segments]
        except (KeyError, TypeError, ValueError) as e:
            raise ASRError("segments without start, end or text") from e
    if isinstance(out.get("text"), str) and out["text"].strip():
        try:
            duration = float(out.get("duration") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        return _sentences(out["text"], duration)
    raise ASRError("no transcript in the reply")


def transcribe_audio(audio_path: Path, session_id: str, client_id: str, session_no: int, date: str, simulated: bool = True) -> Transcript:
    """Speech to timestamped segments. Speakers are left "unknown" for the speaker agent."""
    raw = _openai_server(audio_path) if config.ASR_BACKEND == "openai" else _faster_whisper(audio_path)
    # Number only the segments with words, so ids stay 1, 2, 3… for citations.
    spoken = [(start, end, _clean(text)) for start, end, text in raw if text.strip()]
    segments = [
        Segment(id=i, start=round(start, 1), end=round(end, 1), speaker="unknown", text=text, speaker_source="none")
        for i, (start, end, text) in enumerate(spoken, start=1)
    ]
    return Transcript(session_id, client_id, session_no, date, segments, simulated=simulated)


def save_transcript(t: Transcript) -> Path:
    path = config.SESSIONS_DIR / f"{t.session_id}.json"
    payload = {
        "session_id": t.session_id,
        "client_id": t.client_id,
        "session_no": t.session_no,
        "date": t.date,
        "simulated": t.simulated,
        "segments": [s.__dict__ for s in t.segments],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
