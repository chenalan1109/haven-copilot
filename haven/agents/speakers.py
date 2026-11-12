"""Speaker agent: labels each segment of uploaded audio as therapist or client.

Whisper gives text without speakers. A therapy session has two people, and what
each says is distinctive (the therapist asks, reflects, summarises and sets
homework; the client tells their own experience), so the local LLM labels each
segment from its words. Labels are marked as guessed (speaker_source="model");
the UI shows them as guesses and the risk agent does not let a guessed
"therapist" label hide a client disclosure.
"""

from __future__ import annotations

import json

from ..llm import DATA_ONLY
from ..models import Transcript

SYSTEM = (
    "你在整理一段心理諮商錄音的逐字稿，對話中只有一位心理師和一位個案。"
    "判斷每一段話是誰說的。心理師通常提問、反映情緒、摘要、說明練習與作業、安排下次會談；"
    "個案敘述自己的經驗、感受和生活。只輸出 JSON。"
    + DATA_ONLY
)
CHUNK = 60  # segments per request; a 50-minute session is several hundred


class SpeakerAgent:
    def __init__(self, llm=None):
        self.llm = llm

    def run(self, t: Transcript) -> int:
        """Fills in unknown speakers in place. Returns how many were labelled."""
        unknown = [s for s in t.segments if s.speaker == "unknown"]
        if not self.llm or not unknown:
            return 0
        labelled = 0
        for i in range(0, len(t.segments), CHUNK):
            chunk = t.segments[i : i + CHUNK]
            if not any(s.speaker == "unknown" for s in chunk):
                continue
            lines = "\n".join(json.dumps({"id": s.id, "text": s.text}, ensure_ascii=False) for s in chunk)
            out = self.llm.generate_json(
                SYSTEM,
                f"{lines}\n\n回傳格式：{{\"speakers\": [{{\"id\": 段落編號, \"speaker\": \"therapist\" 或 \"client\"}}]}}",
                max_tokens=100 + 20 * len(chunk),
            ) or {}
            guesses = {}
            for item in out.get("speakers", []) if isinstance(out.get("speakers"), list) else []:
                try:
                    guesses[int(item["id"])] = item["speaker"]
                except (KeyError, TypeError, ValueError):
                    continue
            for s in chunk:
                if s.speaker == "unknown" and guesses.get(s.id) in ("therapist", "client"):
                    s.speaker = guesses[s.id]
                    s.speaker_source = "model"
                    labelled += 1
        return labelled
