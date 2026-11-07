"""ASR agent: turns session audio (or a prepared transcript) into segments."""

from __future__ import annotations

import json
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


PROMPT = "以下是心理諮商會談的逐字稿，使用繁體中文。"


def _faster_whisper(audio_path: Path) -> list[tuple[float, float, str]]:
    raw_segments, _info = _whisper_model().transcribe(str(audio_path), language="zh", vad_filter=True, initial_prompt=PROMPT)
    return [(s.start, s.end, s.text) for s in raw_segments]


def _openai_server(audio_path: Path) -> list[tuple[float, float, str]]:
    """Sends the audio to a local server with the OpenAI transcription API (vLLM serving
    Whisper on the B70). The same local-only rule as the note model applies."""
    from .llm import _OPENER, assert_local

    assert_local(config.ASR_URL)
    boundary = uuid.uuid4().hex
    fields = {"model": config.ASR_MODEL, "language": "zh", "prompt": PROMPT, "response_format": "verbose_json"}
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
    with _OPENER.open(req, timeout=config.LLM_TIMEOUT) as r:
        out = json.load(r)
    segments = out.get("segments") or []
    if not segments and out.get("text"):
        segments = [{"start": 0.0, "end": out.get("duration", 0.0), "text": out["text"]}]
    return [(float(s["start"]), float(s["end"]), s["text"]) for s in segments]


def transcribe_audio(audio_path: Path, session_id: str, client_id: str, session_no: int, date: str, simulated: bool = True) -> Transcript:
    """Speech to timestamped segments. Speakers are left "unknown" for the speaker agent."""
    raw = _openai_server(audio_path) if config.ASR_BACKEND == "openai" else _faster_whisper(audio_path)
    # Number only the segments with words, so ids stay 1, 2, 3… for citations.
    spoken = [(start, end, text.strip()) for start, end, text in raw if text.strip()]
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
