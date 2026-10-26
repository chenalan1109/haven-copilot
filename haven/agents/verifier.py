"""Verifier agent: checks every note sentence against its cited transcript segments.

Three layers, cheapest first:
1. Hard rules: the sentence must cite existing segments, and every number,
   time word and gendered pronoun in it must also appear in those segments.
   Small models get exactly these details wrong ("下週五" for "這週五").
2. Lexical overlap between the sentence and its evidence.
3. For paraphrases that pass the rules but overlap little, one batched call
   to the local LLM.
Unsupported sentences block signing until the therapist edits, deletes or
explicitly confirms them.
"""

from __future__ import annotations

import re

from ..models import Note, Transcript
from ..textutil import overlap

SUPPORTED = 0.5
WEAK = 0.25

_TIME = re.compile(r"這週|下週|上週|本週|今天|明天|昨天|下次|上次|每天|每週|週[一二三四五六日]")
_NUMBER = re.compile(r"\d+|[零一二三四五六七八九十百兩]+(?=多?\s*(?:分|公斤|小時|天|次|點|週|個|年|月|歲|晚))")
_PRONOUN = re.compile(r"[他她]")

SYSTEM_PROMPT = "你是嚴謹的事實查核員。判斷「紀錄句子」是否能由「逐字稿」直接支持。只輸出 JSON。"


def rule_violation(sentence: str, source: str) -> str:
    """Returns why the sentence states a detail its source does not, or ''."""
    for token in _TIME.findall(sentence):
        if token not in source:
            return f"時間詞「{token}」不在引用的逐字稿中"
    for token in _NUMBER.findall(sentence):
        if token not in source:
            return f"數字「{token}」不在引用的逐字稿中"
    if _PRONOUN.search(sentence) and not _PRONOUN.search(source):
        return "使用了逐字稿沒有的性別代名詞"
    return ""


class Verifier:
    def __init__(self, llm=None):
        self.llm = llm

    def _llm_supported(self, pending: list[tuple[int, str, str]]) -> set[int]:
        """One call for all paraphrased sentences; returns the indexes the model accepts."""
        items = "\n\n".join(f"<{i}>\n逐字稿：{source}\n紀錄句子：{claim}" for i, claim, source in pending)
        raw = self.llm.generate_json(
            SYSTEM_PROMPT,
            f"{items}\n\n逐題判斷紀錄句子的每個事實是否都出現在對應逐字稿中。"
            '輸出 {"results": [{"id": 編號, "supported": true 或 false}]}',
        )
        results = raw.get("results", []) if isinstance(raw, dict) else []
        return {int(r["id"]) for r in results if isinstance(r, dict) and r.get("supported") is True and str(r.get("id")).isdigit()}

    def run(self, note: Note, t: Transcript) -> dict:
        segs = t.by_id()
        pending: list[tuple[int, str, str]] = []
        sentences = note.sentences()
        for i, s in enumerate(sentences):
            if s.status != "unchecked":  # already checked and not edited since
                continue
            cited = [segs[e].text for e in s.evidence if e in segs]
            if not s.evidence:
                s.status, s.support, s.reason = "unsupported", 0.0, "沒有引用任何逐字稿段落"
                continue
            if len(cited) != len(s.evidence):
                s.status, s.support, s.reason = "unsupported", 0.0, "引用了不存在的段落"
                continue
            source = "\n".join(cited)
            s.support = round(max(overlap(s.text, c) for c in cited), 2)
            violation = rule_violation(s.text, source)
            if violation:
                s.status, s.reason = "unsupported", violation
            elif s.support >= SUPPORTED:
                s.status, s.reason = "supported", ""
            else:
                s.status = "weak" if s.support >= WEAK else "unsupported"
                s.reason = "與引用段落的用字重疊少，請確認"
                pending.append((i, s.text, source))
        # Paraphrases score low on overlap; let the local model rule on them.
        if pending and self.llm is not None:
            accepted = self._llm_supported(pending)
            for i, _, _ in pending:
                if i in accepted:
                    sentences[i].status, sentences[i].reason = "supported", ""
                else:
                    sentences[i].reason = "本機模型判斷引用段落不足以支持此句"
        n = len(sentences)
        counts = {k: sum(1 for s in sentences if s.status == k) for k in ("supported", "weak", "unsupported")}
        return {
            "total": n,
            **counts,
            "supported_ratio": round(counts["supported"] / n, 3) if n else 0.0,
            "ready_to_sign": counts["unsupported"] == 0,
        }
