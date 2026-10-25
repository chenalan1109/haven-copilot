"""ASR agent: turns session audio (or a prepared transcript) into segments."""

from __future__ import annotations

import json
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


def transcribe_audio(audio_path: Path, session_id: str, client_id: str, session_no: int, date: str) -> Transcript:
    """Runs faster-whisper locally. Speaker separation is left to Stage II (pyannote)."""
    from faster_whisper import WhisperModel  # optional dependency

    model = WhisperModel(config.ASR_MODEL, device="auto", compute_type="int8")
    raw_segments, _info = model.transcribe(
        str(audio_path),
        language="zh",
        vad_filter=True,
        initial_prompt="以下是心理諮商會談的逐字稿，使用繁體中文。",
    )
    segments = [
        Segment(id=i, start=round(s.start, 1), end=round(s.end, 1), speaker="unknown", text=s.text.strip())
        for i, s in enumerate(raw_segments, start=1)
    ]
    return Transcript(session_id, client_id, session_no, date, segments, simulated=True)


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
