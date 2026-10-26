"""Note-writer agent: drafts a SOAP / DAP progress note with evidence links.

Every sentence carries the transcript segment ids it is based on, so the
verifier agent and the therapist can check it against what was said.
"""

from __future__ import annotations

import re

from ..models import Note, NoteSentence, Transcript
from ..textutil import third_person

TEMPLATES = {
    "SOAP": {
        "S": "主觀資料（個案自述的困擾、感受、症狀）",
        "O": "客觀資料（可觀察或可量化的事實，如自評分數、睡眠時數、體重變化）",
        "A": "評估（心理師的觀察、概念化與介入重點）",
        "P": "計畫（作業、下次會談安排、轉介、安全措施）",
    },
    "DAP": {
        "D": "資料（個案自述與可觀察的事實）",
        "A": "評估（心理師的觀察、概念化與介入重點）",
        "P": "計畫（作業、下次會談安排、轉介、安全措施）",
    },
}

SYSTEM_PROMPT = (
    "你是協助台灣心理師撰寫會談紀錄的助理。只能根據逐字稿內容撰寫，不可加入逐字稿沒有的資訊，"
    "不可做診斷。使用繁體中文，以第三人稱稱呼「個案」，不要用他或她。每一句都必須附上支持它的逐字稿段落編號，"
    "且句中每個事實都要出現在那些段落裡。日期、次數、時間詞照逐字稿原文寫，不可推測變化趨勢。"
)


def _prompt(t: Transcript, template: str) -> str:
    lines = [f"[{s.id}] {'心理師' if s.speaker == 'therapist' else '個案' if s.speaker == 'client' else '說話者'}：{s.text}" for s in t.segments]
    sections = "\n".join(f'- "{k}": {v}' for k, v in TEMPLATES[template].items())
    keys = ", ".join(f'"{k}": [{{"text": "...", "evidence": [段落編號]}}]' for k in TEMPLATES[template])
    return (
        f"第 {t.session_no} 次會談逐字稿：\n" + "\n".join(lines)
        + f"\n\n請撰寫 {template} 格式紀錄，各欄位意義：\n{sections}\n"
        + f"每欄 2 到 5 句，每句簡短。只輸出 JSON：{{{keys}}}"
    )


def _parse(raw: dict | None, template: str, valid_ids: set[int]) -> dict[str, list[NoteSentence]] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, list[NoteSentence]] = {}
    for key in TEMPLATES[template]:
        items = raw.get(key, [])
        if not isinstance(items, list):
            return None
        sentences = []
        for item in items:
            if not isinstance(item, dict) or not str(item.get("text", "")).strip():
                continue
            ev = [int(e) for e in item.get("evidence", []) if str(e).isdigit()]
            # Keep invalid ids: the verifier must see and flag them.
            sentences.append(NoteSentence(text=str(item["text"]).strip(), evidence=ev))
        out[key] = sentences
    return out if any(out.values()) else None


# Rule-based fallback when no local model is running. It only rewrites and
# selects what was said, so it cannot invent content; quality is lower.
_FEELING = ["累", "睡", "醒", "生氣", "覺得", "怕", "難過", "沒用", "提不起勁", "吃", "瘦", "抖", "焦慮", "活著", "消失"]
_MEASURE = ["分", "公斤", "小時", "點", "天", "次", "晚上"]
_ASSESS = ["所以", "連結", "很像", "聽起來", "發現", "效果", "注意到", "勾起", "重要"]
_PLAN = ["作業", "下週", "下次", "計畫", "建議", "專線", "急診", "再見", "挑戰"]
_PLAN_WEAK = ["練習", "記錄"]
# A trailing check-in such as "，好嗎？" turns a plan into a question; drop it.
_TAG_QUESTION = re.compile(r"[，,]\s*(你)?(好嗎|可以嗎|願意嗎|好不好)？$")


def _therapist_clauses(text: str) -> list[tuple[str, str]]:
    """Splits a therapist turn into (section, clause) pairs, skipping questions."""
    out = []
    for part in (p.strip() for p in re.split(r"(?<=[。！？])", text)):
        part = _TAG_QUESTION.sub("。", part)
        if not part or part.endswith(("？", "?")):
            continue
        if any(k in part for k in _PLAN):
            out.append(("P", part))
        elif any(k in part for k in _ASSESS):
            out.append(("A", part))
        elif any(k in part for k in _PLAN_WEAK):
            out.append(("P", part))
    return out


def _rule_based(t: Transcript, template: str) -> dict[str, list[NoteSentence]]:
    s_items, o_items, a_items, p_items = [], [], [], []
    for seg in t.segments:
        text = third_person(seg.text, seg.speaker)
        if seg.speaker == "client":
            body = text[2:] if text.startswith("個案") else text
            if any(k in seg.text for k in _MEASURE) and any(ch.isdigit() or ch in "一二三四五六七八九十百" for ch in seg.text):
                o_items.append(NoteSentence(f"個案自述{body}。", [seg.id]))
            elif any(k in seg.text for k in _FEELING) and len(seg.text) > 6:
                s_items.append(NoteSentence(f"個案表示{body}。", [seg.id]))
        elif seg.speaker == "therapist":
            for section, clause in _therapist_clauses(seg.text):
                clause = third_person(clause, "therapist")
                if section == "P":
                    p_items.append(NoteSentence(f"{clause}。", [seg.id]))
                else:
                    a_items.append(NoteSentence(f"心理師指出：{clause}。", [seg.id]))
    if template == "DAP":
        return {"D": (s_items + o_items)[:7], "A": a_items[:4], "P": p_items[:5]}
    return {"S": s_items[:5], "O": o_items[:4], "A": a_items[:4], "P": p_items[:5]}


class NoteWriter:
    def __init__(self, llm=None):
        self.llm = llm

    def run(self, t: Transcript, template: str = "SOAP") -> Note:
        if self.llm is not None:
            parsed = _parse(self.llm.generate_json(SYSTEM_PROMPT, _prompt(t, template)), template, set(t.by_id()))
            if parsed:
                return Note(template, parsed, engine=self.llm.label)
        return Note(template, _rule_based(t, template), engine="rule-based demo")
