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
_NEGATION = re.compile(r"(沒有|沒|不會|不是|從來沒)[^，。]{0,4}$")


def _negated(text: str, cue: str) -> bool:
    i = text.find(cue)
    return bool(_NEGATION.search(text[max(0, i - 8) : i]))


class RiskAgent:
    def run(self, t: Transcript) -> RiskReport:
        report = RiskReport(level="none")
        for seg in t.segments:
            if seg.speaker == "therapist":
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
        return report
