"""Note-writer agent: drafts a SOAP / DAP progress note with evidence links.

Every sentence carries the transcript segment ids it is based on, so the
verifier agent and the therapist can check it against what was said.

Risk content has its own section, R (風險與安全), in both templates. Whatever
engine wrote the note, a transcript line with a high-level risk cue that no
sentence cites is added to R as a quote, so a disclosure cannot be dropped by a
sentence limit or by the model.
"""

from __future__ import annotations

import re

from ..models import Note, NoteSentence, Segment, Transcript
from ..textutil import third_person
from .risk import RiskAgent

_A = "評估（只寫心理師在會談中說出口的觀察、概念化與介入重點，並引用心理師說的段落；心理師沒說出口的評估不要寫，寧可少寫）"
_P = ("計畫（會談中談定的作業、下次會談安排、轉介、安全措施；個案自己提出的計畫寫「個案計畫…」，心理師提出的才寫「心理師建議…」；"
      "心理師只是提議、逐字稿中沒有完成的事寫「心理師提議…」）")
_R = ("風險與安全（逐字稿中凡是提到自殺、自傷、傷害他人、受暴或受虐、物質使用，都必須寫在這一欄，不受句數限制；"
      "保留否定語、時間和主詞：他人的事寫明是誰，過去的事寫明時間；也寫保護因子與談到的安全措施；沒有這類內容就留空陣列）")
TEMPLATES = {
    "SOAP": {
        "S": "主觀資料（個案自述的困擾、感受、症狀、睡眠、體重、作業完成情形）",
        # SOAP's O is what the clinician observes. The transcript is all the model has, so
        # each observation still cites the lines it shows in; the rest the therapist adds.
        "O": ("客觀資料（心理師對個案在會談中的行為與情緒表現的觀察，例如哭泣、沉默、語速、坐立不安；"
              "每句都要引用看得出這項觀察的段落，逐字稿看不出來的不要寫；量表分數由系統自動填入，不要寫；沒有就留空陣列）"),
        "A": _A,
        "P": _P,
        "R": _R,
    },
    "DAP": {
        "D": ("資料（個案自述，以及心理師對個案在會談中的行為與情緒表現的觀察，觀察要引用看得出來的段落；"
              "量表分數由系統自動填入，不要寫）"),
        "A": _A,
        "P": _P,
        "R": _R,
    },
}

SYSTEM_PROMPT = (
    "你是協助台灣心理師撰寫會談紀錄的助理。只能根據逐字稿內容撰寫，不可加入逐字稿沒有的資訊，"
    "不可做診斷。使用繁體中文，以第三人稱稱呼「個案」，不要用他或她。每一句都必須附上支持它的逐字稿段落編號，"
    "且句中每個事實都要出現在那些段落裡。日期、次數、時間詞照逐字稿原文寫，不可推測變化趨勢。"
    "個案說「沒有」的事要保留否定，例如「沒有具體計畫」不可寫成「有計畫」；"
    "「沒有一天不想死」是每天都想，不可寫成「沒有想死」。"
    "評估欄只寫心理師在會談中表達的看法，不要自行下結論或做風險分級。"
    "誰說的就寫誰：寫「心理師認為、觀察到、建議」的句子，引用的段落必須是心理師說的；"
    "寫「個案表示」的句子，引用的段落必須是個案說的。"
    "心理師提議而逐字稿中沒有完成的事（例如「我們來擬安全計畫，好嗎？」）寫成「心理師提議…」，不可寫成已經完成。"
    "個案對自己的負面評價是個案的感受，寫成「個案表示覺得…」，不可寫成事實。"
)
# Segments per request. A 50-minute session is several hundred segments: one request
# would overrun the model's context, and the note would cover only the opening minutes.
CHUNK = 60
FALLBACK_ENGINE = "規則引擎（本機模型未回應）"


def _prompt(t: Transcript, template: str, segments: list[Segment] | None = None, part: tuple[int, int] | None = None) -> str:
    def who(s):
        name = {"therapist": "心理師", "client": "個案"}.get(s.speaker, "說話者")
        return name + ("（推測）" if s.speaker_source == "model" else "")
    segments = t.segments if segments is None else segments
    lines = [f"[{s.id}] {who(s)}：{s.text}" for s in segments]
    sections = "\n".join(f'- "{k}": {v}' for k, v in TEMPLATES[template].items())
    keys = ", ".join(f'"{k}": [{{"text": "...", "evidence": [段落編號]}}]' for k in TEMPLATES[template])
    where = f"（全長分成 {part[1]} 段處理，這是第 {part[0]} 段，只寫這一段的內容）" if part else ""
    return (
        f"第 {t.session_no} 次會談逐字稿{where}：\n" + "\n".join(lines)
        + f"\n\n請撰寫 {template} 格式紀錄，各欄位意義：\n{sections}\n"
        + f"R 以外每欄 2 到 5 句，每句簡短。只輸出 JSON：{{{keys}}}"
    )


def _evidence(value) -> list[int]:
    """Segment ids from whatever the model wrote: [4, 12], 4, "12", "#4, #12", ["4"], null.
    Ids that do not exist are kept: the verifier must see and flag them."""
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, str):
        return [int(n) for n in re.findall(r"\d+", value)]  # "12" is segment 12, not 1 and 2
    if isinstance(value, list):
        return [n for item in value for n in _evidence(item)]
    return []


def _parse(raw: dict | None, template: str) -> dict[str, list[NoteSentence]] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, list[NoteSentence]] = {}
    for key in TEMPLATES[template]:
        items = raw.get(key)
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            items = []  # one bad field (null, a string) does not throw the other sections away
        sentences = []
        for item in items:
            if not isinstance(item, dict) or not str(item.get("text") or "").strip():
                continue
            sentences.append(NoteSentence(text=str(item["text"]).strip(), evidence=_evidence(item.get("evidence"))))
        out[key] = sentences
    return out if any(out.values()) else None


# Rule-based engine, used when no local model is running or when it does not
# answer. It selects what was said and rewrites the speaker ("我" to "個案"); it
# adds no content of its own. Quality is lower: the notes read like quotes.
_FEELING = ["累", "睡", "醒", "生氣", "覺得", "怕", "難過", "沒用", "提不起勁", "吃", "瘦", "抖", "焦慮", "活著", "消失"]
_MEASURE = ["分", "公斤", "小時", "點", "天", "次", "晚上"]
_ASSESS = ["所以", "連結", "很像", "聽起來", "發現", "效果", "注意到", "勾起", "重要"]
_PLAN = ["作業", "下週", "下次", "計畫", "建議", "專線", "急診", "再見", "挑戰"]
_PLAN_WEAK = ["練習", "記錄"]
# A trailing check-in such as "，好嗎？" makes the clause a proposal, not something done.
_TAG_QUESTION = re.compile(r"[，,]\s*(你)?(好嗎|可以嗎|願意嗎|好不好)？$")
# Risk cues about functioning (sleep, weight) stay in S; everything else goes to R.
_NOT_IN_R = {"嚴重失功能"}
SHORT_REPLY = 15


def _therapist_clauses(text: str) -> list[tuple[str, str, bool]]:
    """Splits a therapist turn into (section, clause, proposed) triples, skipping questions.
    ``proposed`` marks a clause that ended in a check-in ("…，好嗎？")."""
    out = []
    for part in (p.strip() for p in re.split(r"(?<=[。！？])", text)):
        proposed = bool(_TAG_QUESTION.search(part))
        part = _TAG_QUESTION.sub("。", part)
        if not part or part.endswith(("？", "?")):
            continue
        if any(k in part for k in _PLAN):
            out.append(("P", part, proposed))
        elif any(k in part for k in _ASSESS):
            out.append(("A", part, proposed))
        elif any(k in part for k in _PLAN_WEAK):
            out.append(("P", part, proposed))
    return out


def _plan_sentence(clause: str, proposed: bool, seg: Segment, reply: Segment | None) -> NoteSentence:
    """A plan line in the third person. "我們來擬安全計畫，好嗎？" is a proposal: it is
    written as one, with the client's answer, never as a finished plan."""
    clause = third_person(clause, "therapist").replace("我會建議", "心理師建議").replace("我建議", "心理師建議")
    if not proposed:
        return NoteSentence(f"{clause.replace('我們', '心理師與個案')}。", [seg.id])
    clause = clause.replace("我們", "")
    text = clause if "心理師建議" in clause else f"心理師提議：{clause}"
    if reply is not None:
        return NoteSentence(f"{text}（個案回應：{reply.text.rstrip('。！')}）。", [seg.id, reply.id])
    return NoteSentence(f"{text}。", [seg.id])


def _quote(seg: Segment) -> NoteSentence:
    """What a line said, attributed to whoever said it."""
    if seg.speaker == "client" and seg.speaker_source == "script":
        text = third_person(seg.text, "client")
        return NoteSentence(f"個案表示{text[2:] if text.startswith('個案') else text}。", [seg.id])
    if seg.speaker == "therapist" and seg.speaker_source == "script":
        return NoteSentence(f"心理師提到：{third_person(seg.text, 'therapist')}。", [seg.id])
    return NoteSentence(f"逐字稿提到（說話者未確認）：{seg.text.rstrip('。！？')}。", [seg.id])


def _risk_segments(t: Transcript) -> tuple[set[int], set[int], set[int]]:
    """(lines with a risk cue for R, of those the high-level ones, lines with a protective factor)."""
    report = RiskAgent().run(t)
    flags = [f for f in report.flags if f.category not in _NOT_IN_R]
    return ({f.segment_id for f in flags}, {f.segment_id for f in flags if f.level in ("high", "critical")},
            {p.segment_id for p in report.protective} if flags else set())


def _rule_based(t: Transcript, template: str, segments: list[Segment] | None = None) -> dict[str, list[NoteSentence]]:
    segments = t.segments if segments is None else segments
    risky, _, protective = _risk_segments(t)
    after = {a.id: b for a, b in zip(t.segments, t.segments[1:])}
    s_items, a_items, p_items, r_items = [], [], [], []
    for seg in segments:
        if seg.id in risky or seg.id in protective:
            # Never subject to the sentence limits below.
            r_items.append(_quote(seg))
            continue
        text = third_person(seg.text, seg.speaker)
        if seg.speaker == "client":
            body = text[2:] if text.startswith("個案") else text
            if any(k in seg.text for k in _FEELING + _MEASURE) and len(seg.text) > 6:
                s_items.append(NoteSentence(f"個案表示{body}。", [seg.id]))
        elif seg.speaker == "therapist":
            nxt = after.get(seg.id)
            reply = nxt if nxt is not None and nxt.speaker == "client" and len(nxt.text) <= SHORT_REPLY else None
            for section, clause, proposed in _therapist_clauses(seg.text):
                if section == "P":
                    p_items.append(_plan_sentence(clause, proposed, seg, reply))
                else:
                    a_items.append(NoteSentence(f"心理師指出：{third_person(clause, 'therapist')}。", [seg.id]))
    if template == "DAP":
        return {"D": s_items[:6], "A": a_items[:4], "P": p_items[:5], "R": r_items}
    return {"S": s_items[:6], "O": [], "A": a_items[:4], "P": p_items[:5], "R": r_items}


class NoteWriter:
    def __init__(self, llm=None):
        self.llm = llm

    def _ask(self, prompt: str):
        try:
            return self.llm.generate_json(SYSTEM_PROMPT, prompt)
        except Exception:  # a model fault falls back to the rule engine, and says so
            return None

    def run(self, t: Transcript, template: str = "SOAP") -> Note:
        # Long sessions are written in parts and joined, so the note covers the whole hour.
        parts = [t.segments[i : i + CHUNK] for i in range(0, len(t.segments), CHUNK)] or [[]]
        sections: dict[str, list[NoteSentence]] = {k: [] for k in TEMPLATES[template]}
        failed: list[int] = []
        for n, segments in enumerate(parts, start=1):
            parsed = None
            if self.llm is not None:
                parsed = _parse(self._ask(_prompt(t, template, segments, (n, len(parts)) if len(parts) > 1 else None)), template)
                if parsed is None:
                    failed.append(n)
            if parsed is None:
                parsed = _rule_based(t, template, segments)
            for key, items in parsed.items():
                sections[key].extend(items)
        warnings: list[str] = []
        if self.llm is None:
            engine = "rule-based demo"
        elif not failed:
            engine = self.llm.label
        elif len(failed) == len(parts):
            engine = FALLBACK_ENGINE
            warnings.append(f"本機模型（{self.llm.label}）未回應，這份草稿改由規則引擎產生：只摘錄逐字稿原句，品質較低，請仔細核對。")
        else:
            where = "、".join(str(n) for n in failed)
            engine = f"{self.llm.label}＋規則引擎（第 {where} 段本機模型未回應）"
            warnings.append(f"逐字稿分成 {len(parts)} 段撰寫，其中第 {where} 段本機模型未回應，該段改由規則引擎摘錄原句。")
        # A high-level risk cue that no sentence cites is added as a quote.
        cited = {e for items in sections.values() for s in items for e in s.evidence}
        _, must_have, _ = _risk_segments(t)
        by_id = t.by_id()
        sections["R"].extend(_quote(by_id[i]) for i in sorted(must_have - cited))
        return Note(template, sections, engine=engine, warnings=warnings)
