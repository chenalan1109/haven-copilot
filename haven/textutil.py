"""Small Chinese text helpers shared by the agents."""

import re

_PUNCT = re.compile(r"[\s，。、！？：；「」『』（）()…,.!?:;\"'\-—]+")
# Words that change between a quote and a note ("我" becomes "個案") or are
# note scaffolding; ignored when comparing a note sentence with its evidence.
_NEUTRAL = ["個案表示", "個案自述", "心理師", "計畫", "個案", "我們", "我", "你", "他", "她", "嗯", "好像", "就是"]


def normalize(text: str) -> str:
    for w in _NEUTRAL:
        text = text.replace(w, "")
    return _PUNCT.sub("", text)


def bigrams(text: str) -> set[str]:
    t = normalize(text)
    if len(t) < 2:
        return {t} if t else set()
    return {t[i : i + 2] for i in range(len(t) - 1)}


def overlap(claim: str, source: str) -> float:
    """Share of the claim's bigrams that appear in the source (0..1)."""
    c = bigrams(claim)
    if not c:
        return 0.0
    return len(c & bigrams(source)) / len(c)


def third_person(text: str, speaker: str) -> str:
    """Rewrites a quote so the client is referred to as 個案."""
    if speaker == "client":
        text = text.replace("我們", "個案與心理師").replace("我", "個案")
    elif speaker == "therapist":
        text = text.replace("你", "個案")
    return re.sub(r"^(嗯|好|對|那)[，,]\s*", "", text).rstrip("。！？!?")
