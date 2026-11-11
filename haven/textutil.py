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


# ---- negation next to a word -------------------------------------------------
# "沒有想死" denies; "沒有一天不想死" affirms, strongly. Both the risk agent and the
# verifier ask the same question: is this word, at this place, denied?

_CLAUSE_BREAK = re.compile(r"[，。！？；,.!?;：:\n]")
# Two negations that cancel: the statement stands.
_DOUBLE_NEGATION = re.compile(
    r"(沒有一天不|沒有一天沒|沒有一刻不|沒有一晚不|沒辦法不|無法不|不是不|不會不|不是沒有?|不能不|不得不|沒有不|毋是無|毋是毋|無一工無)[^，。]{0,4}$"
)
# "有沒有想過", "會不會想死": a question form, not a denial.
_A_NOT_A = re.compile(r"有沒有|會不會|是不是|要不要|能不能|想不想|該不該|敢不敢")
# Words that contain 不 / 沒 / 無 / 未 without denying what follows.
_NOT_A_NEGATION = re.compile(
    r"不如|不過|不只|不僅|不但|不然|不小心|不知道|不好意思|差不多|忍不住|不停|不斷|受不了|睡不著|睡不好|吃不下|撐不下去|撐不住|擋不住"
    r"|活不下去|不由得|巴不得|恨不得|沒關係|沒錯|沒事|沒用|沒辦法|無聊|無論|無奈|無助|無力|無法|未來|不太好|不舒服|不開心|不快樂|對不起"
)
# Narrow: what the risk agent treats as a denial (a wrong "denied" lowers a cue to review).
_NEGATION_NARROW = re.compile(r"(否認|從來沒有?|沒有?|不會|不是|不曾|不再|毋|無|袂)[^，。]{0,4}$")
# Broad: what the verifier compares between a note sentence and its source.
_NEGATION_BROAD = re.compile(r"(否認|從來沒有?|從未|未曾|並未|沒有?|不|未|毋|無|袂)[^，。]{0,4}$")


def polarity(text: str, start: int, broad: bool = False) -> str:
    """How the word starting at ``start`` is meant: "denied", "double" (two
    negations, so it is affirmed) or "stated". Only the same clause is read,
    so "我睡不好，常常想死" does not deny 想死."""
    window = text[max(0, start - 12) : start]
    window = _CLAUSE_BREAK.split(window)[-1]
    if _DOUBLE_NEGATION.search(window):
        return "double"
    window = _A_NOT_A.sub(lambda m: "＿" * len(m.group()), window)
    window = _NOT_A_NEGATION.sub(lambda m: "＿" * len(m.group()), window)
    return "denied" if (_NEGATION_BROAD if broad else _NEGATION_NARROW).search(window) else "stated"


def denied(text: str, start: int, broad: bool = False) -> bool:
    return polarity(text, start, broad) == "denied"


def has_negation(text: str) -> bool:
    """Coarse: does the text deny anything at all (ignoring words like 睡不著)?"""
    masked = _NOT_A_NEGATION.sub("＿", _A_NOT_A.sub("＿", text))
    return bool(re.search(r"否認|沒|不|未|毋|無|袂", masked))


def clauses(text: str) -> list[str]:
    return [c for c in re.split(r"[，；。,;]", text) if c.strip()]
