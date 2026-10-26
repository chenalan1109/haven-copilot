"""Risk agent: surfaces safety cues in what the client said, with the exact quote.

Tuned for recall: a negated cue ("沒有想要怎麼做") is kept at "review" level
rather than dropped. The output is a prompt for the therapist's own
judgment, never a risk rating of the client.
"""

from __future__ import annotations

import re

from ..models import RiskFlag, RiskReport, Transcript

LEVEL_ORDER = {"none": 0, "info": 1, "review": 2, "high": 3, "critical": 4}

# category -> (level, cues)
LEXICON: dict[str, tuple[str, list[str]]] = {
    "自殺意念": ("high", ["想死", "自殺", "結束自己的生命", "結束生命", "不想活", "活著好累", "活著沒意思", "消失算了", "消失就好", "一了百了", "輕生", "遺書"]),
    "自殺計畫或工具": ("critical", ["怎麼做", "安眠藥", "燒炭", "木炭", "跳樓", "上吊", "存藥", "買了繩子"]),
    "自傷行為": ("high", ["割手", "割腕", "自殘", "傷害自己", "撞牆"]),
    "傷害他人": ("high", ["殺了他", "想打死", "報復他"]),
    "家庭暴力": ("high", ["打我", "被打", "家暴", "動手打", "摔東西"]),
    "物質使用": ("review", ["喝醉", "喝很多酒", "吃很多藥", "嗑"]),
    "嚴重失功能": ("review", ["整天躺在床上", "幾乎睡不著", "瘦了", "沒有味道"]),
}
PROTECTIVE = ["不想讓", "妹妹", "弟弟", "家人", "朋友", "貓", "狗", "信仰", "孩子"]
SCREENING = ["結束自己的生命", "傷害自己", "想死", "自殺的念頭"]
SAFETY = ["安全計畫", "一九二五", "1925", "安心專線", "急診", "身心科", "提前"]

# Elements of a suicide risk inquiry, after the structure of the Columbia
# Suicide Severity Rating Scale and common safety-planning practice.
# (item, therapist cues, client cues): an item counts as covered when the
# therapist asked about it or the client spoke to it. Missing items are shown
# as "consider asking or documenting", never as an error.
CHECKLIST: list[tuple[str, list[str], list[str]]] = [
    ("自殺意念", ["結束自己的生命", "想死", "自殺", "傷害自己", "不想活"], []),
    ("頻率或強度", ["頻率", "多常", "多久一次", "幾次", "多強烈"], ["個晚上", "常常", "每天晚上"]),
    ("計畫或方法", ["計畫要", "具體的計畫", "方法", "用什麼方式", "想過怎麼做"], ["怎麼做", "方法", "計畫"]),
    ("意圖", ["打算", "會去做", "付諸行動", "意圖"], ["想要怎麼做", "打算", "會去做"]),
    ("工具或手段可及性", ["藥", "工具", "繩", "炭", "拿得到", "手邊有"], ["存藥", "安眠藥", "買了", "木炭", "繩子"]),
    ("過去自殺或自傷史", ["以前有沒有", "過去有沒有", "曾經", "之前有沒有"], ["以前有", "曾經"]),
    ("保護因子", ["撐下來", "支持你", "重要的人", "活下去的理由"], ["不想讓"]),
    ("安全計畫", ["安全計畫"], []),
    ("危機資源或轉介", ["一九二五", "1925", "安心專線", "急診", "身心科", "精神科"], []),
]
_NEGATION = re.compile(r"(沒有|沒|不會|不是|從來沒)[^，。]{0,4}$")


def _negated(text: str, cue: str) -> bool:
    i = text.find(cue)
    return bool(_NEGATION.search(text[max(0, i - 8) : i]))


def checklist(t: Transcript) -> list[dict]:
    """Which parts of a suicide risk inquiry appear in the session, with segment ids."""
    out = []
    for item, therapist_cues, client_cues in CHECKLIST:
        covered = [
            seg.id for seg in t.segments
            if any(c in seg.text for c in (therapist_cues if seg.speaker != "client" else client_cues))
        ]
        out.append({"item": item, "covered": covered})
    return out


def _is_question(text: str) -> bool:
    return text.rstrip().endswith(("？", "?"))


class RiskAgent:
    def run(self, t: Transcript) -> RiskReport:
        report = RiskReport(level="none")
        for seg in t.segments:
            # Without diarization (uploaded audio) a question is most likely the
            # therapist screening, not the client disclosing.
            if seg.speaker == "therapist" or (seg.speaker == "unknown" and _is_question(seg.text)):
                if any(c in seg.text for c in SCREENING):
                    report.screening_asked.append(seg.id)
                if any(c in seg.text for c in SAFETY):
                    report.safety_actions.append(seg.id)
                continue
            for category, (level, cues) in LEXICON.items():
                for cue in cues:
                    if cue not in seg.text:
                        continue
                    negated = _negated(seg.text, cue)
                    report.flags.append(RiskFlag(category, "review" if negated else level, seg.id, seg.text, cue, negated))
                    break
            for cue in PROTECTIVE:
                if cue in seg.text:
                    report.protective.append(RiskFlag("保護因子", "info", seg.id, seg.text, cue))
                    break
        if report.flags:
            report.level = max((f.level for f in report.flags), key=LEVEL_ORDER.__getitem__)
        if any(f.category.startswith("自殺") or f.category == "自傷行為" for f in report.flags):
            report.checklist = checklist(t)
        return report
