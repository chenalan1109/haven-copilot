"""Verifier agent: checks every note sentence against its cited transcript segments.

A sentence with no evidence, an unknown segment id, or too little overlap with
the segments it cites is flagged, and the UI will not sign the note until the
therapist has reviewed it.
"""

from __future__ import annotations

from ..models import Note, Transcript
from ..textutil import overlap

SUPPORTED = 0.5
WEAK = 0.25

SYSTEM_PROMPT = "你是嚴謹的事實查核員。判斷「紀錄句子」是否能由「逐字稿片段」直接支持。只輸出 JSON。"


class Verifier:
    def __init__(self, llm=None):
        self.llm = llm

    def _llm_supports(self, claim: str, source: str) -> bool:
        raw = self.llm.generate_json(
            SYSTEM_PROMPT,
            f"逐字稿片段：{source}\n紀錄句子：{claim}\n輸出 {{\"supported\": true 或 false}}",
        )
        return bool(raw and raw.get("supported") is True)

    def run(self, note: Note, t: Transcript) -> dict:
        segs = t.by_id()
        for s in note.sentences():
            cited = [segs[i].text for i in s.evidence if i in segs]
            if not cited or len(cited) != len(s.evidence):
                s.status, s.support = "unsupported", 0.0
                continue
            s.support = round(max(overlap(s.text, c) for c in cited), 2)
            if s.support >= SUPPORTED:
                s.status = "supported"
            elif s.support >= WEAK:
                s.status = "weak"
            else:
                s.status = "unsupported"
            # Paraphrases score low on overlap; let the local model rule on them.
            if s.status != "supported" and self.llm is not None and self._llm_supports(s.text, "\n".join(cited)):
                s.status = "supported"
        sentences = note.sentences()
        n = len(sentences)
        counts = {k: sum(1 for s in sentences if s.status == k) for k in ("supported", "weak", "unsupported")}
        return {
            "total": n,
            **counts,
            "supported_ratio": round(counts["supported"] / n, 3) if n else 0.0,
            "ready_to_sign": counts["unsupported"] == 0,
        }
