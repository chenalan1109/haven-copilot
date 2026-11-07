"""Verifier agent: checks every note sentence against its cited transcript segments.

Three layers, cheapest first:
1. Hard rules: the sentence must cite existing segments, and every number,
   time word and gendered pronoun in it must also appear in those segments.
   "個案表示…" must cite at least one of the client's own lines.
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
# Same week, different wording; compared as one word.
_SAME_TIME = {"本週": "這週", "這一週": "這週", "這個禮拜": "這週", "下禮拜": "下週", "上禮拜": "上週"}
# The sentence says the client said it; at least one cited line must be the client's.
_CLIENT_SAID = re.compile(r"^個案(?:表示|自述|提到|說)")
# Risk statements where a dropped or added negation reverses the meaning
# ("沒有具體計畫" vs. "有具體計畫"). These are the sentences that matter most.
# 計畫 and 工具 count only in their risk sense, so "讀書計畫" is not a risk sentence.
_RISK_TERM = re.compile(r"自殺|結束生命|結束自己的生命|想死|自傷|傷害自己|輕生"
                        r"|具體(?:的)?計畫|安全計畫|(?:計畫|工具|方法)(?:去|要)?(?:傷害|結束|自殺)")
_NEGATION = re.compile(r"沒有|沒|不|未|否認|無")

SYSTEM_PROMPT = "你是嚴謹的事實查核員。判斷「紀錄句子」是否能由「逐字稿」直接支持。只輸出 JSON。"


def rule_violation(sentence: str, source: str) -> str:
    """Returns why the sentence states a detail its source does not, or ''."""
    for word, same in _SAME_TIME.items():
        sentence, source = sentence.replace(word, same), source.replace(word, same)
    for token in _TIME.findall(sentence):
        if token not in source:
            return f"時間詞「{token}」不在引用的逐字稿中"
    for token in _NUMBER.findall(sentence):
        if token not in source:
            return f"數字「{token}」不在引用的逐字稿中"
    for token in set(_PRONOUN.findall(sentence)):
        if token not in source:
            return f"代名詞「{token}」不在引用的逐字稿中，請確認指的是誰"
    if _RISK_TERM.search(sentence) and bool(_NEGATION.search(sentence)) != bool(_NEGATION.search(source)):
        return "風險相關句的否定語與逐字稿不一致，請確認語意沒有被反轉"
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
            if s.source == "measure":  # filled in from scores, not from the transcript
                s.status, s.support, s.reason = "supported", 1.0, ""
                continue
            cited = [segs[e].text for e in s.evidence if e in segs]
            if not s.evidence:
                s.status, s.support, s.reason = "unsupported", 0.0, "沒有引用任何逐字稿段落"
                continue
            if len(cited) != len(s.evidence):
                s.status, s.support, s.reason = "unsupported", 0.0, "引用了不存在的段落"
                continue
            source = "\n".join(cited)
            if _CLIENT_SAID.search(s.text) and all(segs[e].speaker == "therapist" for e in s.evidence):
                s.status, s.support, s.reason = "unsupported", 0.0, "句子寫個案表示，但引用的都是心理師的話"
                continue
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
            for i, text, _ in pending:
                if i in accepted and _RISK_TERM.search(text):
                    # A 7B model accepted "否認自殺意念" for a line that never said it.
                    # On risk sentences the model's yes is not enough on its own.
                    sentences[i].status, sentences[i].reason = "weak", "風險相關句只有本機模型判斷支持，請心理師對照原句確認"
                elif i in accepted:
                    sentences[i].status, sentences[i].reason = "supported", ""
                else:
                    sentences[i].reason = "本機模型判斷引用段落不足以支持此句"
        # Score lines are not claims about the session; leave them out of the ratio.
        claims = [s for s in sentences if s.source != "measure"]
        n = len(claims)
        counts = {k: sum(1 for s in claims if s.status == k) for k in ("supported", "weak", "unsupported")}
        return {
            "total": n,
            **counts,
            "supported_ratio": round(counts["supported"] / n, 3) if n else 0.0,
            "ready_to_sign": counts["unsupported"] == 0,
        }
