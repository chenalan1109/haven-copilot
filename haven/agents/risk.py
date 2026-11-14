"""Risk agent: surfaces safety cues in what was said, with the exact quote.

Tuned for recall: a negated cue ("沒有想要怎麼做") is kept at "review" level
rather than dropped. The output is a prompt for the therapist's own
judgment, never a risk rating of the client.

待心理師確認: the cue lists below were widened on 2026-11-12 from a reviewer's
list (review-2026-11-12/clinical.md: indirect and Taiwanese-language suicide
wording, suicidal behaviour, harm to others, mandated-reporting cues,
substance use). They have not been validated by a licensed psychologist. Every
entry added then is marked 待心理師確認. tests/test_risk_recall.py measures
recall on the reviewer's sentences only; that is a regression check, not a
clinical validation.

The reporting categories (通報義務線索) only prompt the therapist to assess
whether the law requires a report. Haven never files or sends a report.
"""

from __future__ import annotations

import re

from ..models import CONFIRMED, RiskFlag, RiskReport, Transcript
from ..textutil import polarity

LEVEL_ORDER = {"none": 0, "info": 1, "review": 2, "high": 3, "critical": 4}

IDEATION = "自殺意念"
INDIRECT = "自殺意念（間接表達）"
PREPARATION = "自殺準備行為"
PLAN = "自殺計畫或工具"
BEHAVIOUR = "自殺行為"
PAST = "過去自殺或自傷史"
SELF_HARM = "自傷行為"
HARM_OTHERS = "傷害他人"
FILICIDE = "攜子自殺"
EXPOSURE = "他人自殺或自傷（自殺暴露）"
HYPNOTICS = "安眠藥使用"
REPORT = "通報義務線索："
REPORT_FAMILY = REPORT + "家庭暴力"
REPORT_CHILD = REPORT + "兒少保護"
REPORT_ELDER = REPORT + "老人／身心障礙保護"
REPORT_SEXUAL = REPORT + "性侵害"
SUBSTANCE = "物質使用"
FUNCTIONING = "嚴重失功能"

_ELDER = r"(?:阿嬤|阿公|奶奶|爺爺|外婆|外公|長輩|老人家)"
_CHILD = r"(?:小孩|孩子|兒子|女兒|寶寶)"

# category -> (level, cue patterns). A cue is a regular expression; most are plain words.
LEXICON: dict[str, tuple[str, list[str]]] = {
    IDEATION: ("high", [
        "想死", "自殺", "結束自己的生命", "結束生命", "不想活", "活著好累", "活著沒意思", "消失算了", "消失就好", "如果消失", "一了百了", "輕生",
        # 待心理師確認 (CLN-1): indirect and colloquial wording
        "想解脫", "解脫", "不要醒來", "不想醒來", "不想再醒來", "活著沒意義", "活著沒有意義", "活著沒有意思", "活著幹嘛", "死一死", "死了算了",
        "死掉算了", "不如死", "死掉比較好", "去死", "不想存在", "離開這個世界", "離開這世界", "想消失",
        # 待心理師確認 (CLN-1): Taiwanese (台語)
        "毋想活", "無想欲活", "欲死", "欲去死", "死死咧", "規氣死", "活咧無意思", "活落去無意思",
    ]),
    # 待心理師確認 (CLN-1): wording that often, not always, carries suicidal meaning. Kept at
    # "review" so that everyday uses ("工作撐不下去") do not raise the highest alerts.
    INDIRECT: ("review", ["撐不下去", "撐不住", "擋不住", "擋袂牢", "袂堪得", "活不下去", r"我.{0,2}不在了", r"(?:是|成為|變成).{0,6}負擔", "拖累"]),
    # 待心理師確認 (CLN-1): putting affairs in order
    PREPARATION: ("critical", ["遺書", "遺囑", "交代後事", r"東西.{0,4}送人", r"(?:存款|錢|財產).{0,6}轉給",
                               "最後一次見", r"查.{0,10}(?:怎麼死|會死|致死|致命)"]),
    # 待心理師確認 (CLN-3): attempts, interrupted attempts. Past ones are re-labelled PAST below.
    BEHAVIOUR: ("critical", [
        r"(?:吞|吃)(?:了|過).{0,4}(?:一整|整罐|整排|整盒|很多|一堆|一把|大量).{0,6}藥", r"(?:吞|吃).{0,2}(?:一整|整)(?:罐|排|盒|瓶).{0,6}藥",
        r"吞過.{0,3}藥", "吞藥", r"燒了.{0,2}炭", "燒過炭", "洗胃", r"割(?:過|了)(?:手|腕|自己|好幾)", r"(?:試過|試著|試圖).{0,6}(?:上吊|跳|割|吞|燒炭|自殺|結束)",
        r"繩子?.{0,2}斷", r"自殺(?:過|未遂)",
    ]),
    PLAN: ("critical", [
        "燒炭", "木炭", "跳樓", "上吊", "存藥", "買了繩子",
        # 待心理師確認 (CLN-1, CLN-3)
        r"存了.{0,8}藥", r"囤.{0,6}藥", r"頂樓.{0,6}跳", r"從.{0,4}(?:頂樓|樓上|橋上)", "跳下去", "跳落去", "跳海", "跳河", "跳軌", "臥軌", "農藥", "巴拉刈",
    ]),
    SELF_HARM: ("high", ["割手", "割腕", "自殘", "傷害自己", "撞牆", "自傷", "拿刀割", "燙自己", "刀片", "打自己"]),  # last five 待心理師確認
    # 待心理師確認 (CLN-5): raised from high to critical and widened
    HARM_OTHERS: ("critical", [r"殺了(?:他|她|你|他們|她們)", "想打死", r"打死(?:他|她)", r"報復(?!性)", "殺掉", "殺光", "殺人", r"(?:想|要|拿刀).{0,3}砍",
                               r"砍(?:他|她|人|死)", "捅", "刺死", "掐死", "弄死", "同歸於盡", "一起死", "付出代價", "炸掉"]),
    # 待心理師確認 (CLN-5): murder-suicide involving a child
    FILICIDE: ("critical", [rf"帶著?(?:{_CHILD}|他們).{{0,2}}(?:一起|一塊)(?:走|死|離開)(?![路去進到出])", rf"{_CHILD}.{{0,8}}活不下去", "一起帶走"]),
    # 待心理師確認 (CLN-4): mandated-reporting cues. Prompts only; nothing is reported automatically.
    REPORT_FAMILY: ("critical", [
        "家暴", "動手打", "被打", "摔東西", r"打我(?!的?(?:手機|電話)|們)", r"打(?:我媽|我爸|媽媽|爸爸|小孩|孩子)",
        r"(?:用|拿)皮帶", "皮帶抽", r"(?:用|拿)衣架", "藤條", "抽我", r"掐我|掐(?:住|著)?.{0,2}脖子", r"勒我|勒住", "踹", r"拿刀.{0,4}(?:對|指|威脅|追|要)",
        r"要殺了?我|殺了我|殺了你", r"威脅(?:我|要(?:殺|打|傷害)|說要(?:殺|打|傷害))", "恐嚇", r"跟蹤我|被跟蹤", "不讓我出門", r"控制.{0,3}錢",
    ]),
    REPORT_CHILD: ("critical", [rf"{_CHILD}.{{0,10}}(?:瘀青|傷痕).{{0,10}}(?:打|掐|捏|弄的)", rf"{_CHILD}.{{0,6}}被.{{0,3}}打", r"瘀青.{0,10}(?:打的|爸|媽)", rf"(?:打|揍|餓){_CHILD}", "不要跟別人說"]),
    REPORT_ELDER: ("high", [rf"{_ELDER}.{{0,8}}(?:被.{{0,4}}打|被虐|挨打)", r"看護.{0,3}(?:打|虐|罵)", "被看護", r"拿走.{0,8}(?:退休金|存款|年金)",
                            r"(?:退休金|存款|年金).{0,6}拿走", "老不死", "遺棄", "丟著不管"]),
    REPORT_SEXUAL: ("critical", ["性侵", "強暴", "迷姦", "猥褻", "性騷擾", r"強迫.{0,6}(?:發生關係|上床|做愛|性)", r"趁.{0,6}(?:喝醉|睡著)", r"摸我(?!的?頭)",
                                 r"摸.{0,3}(?:身體|下面|胸)", r"(?:十[一二三四五]|1[0-5])歲.{0,24}(?:發生關係|上床|做愛)"]),
    SUBSTANCE: ("review", [
        "喝醉", "喝很多酒", r"吃很多.{0,3}(?:藥|普拿疼)", "嗑",
        # 待心理師確認 (CLN-14)
        "喝酒", r"每天.{0,6}喝.{0,6}(?:酒|瓶|杯|醉)", "威士忌", "高粱", "啤酒", "斷片", "宿醉", "安非他命", "冰毒", "K他命", "K菸", "搖頭丸", "大麻", "吸毒", "毒品", "咖啡包",
        "笑氣", "海洛因", "FM2", "史蒂諾斯",
    ]),
    FUNCTIONING: ("review", ["整天躺在床上", "幾乎睡不著", "沒有味道", r"瘦了"]),
}
# Confinement and withheld food: an elder on the line makes it an elder cue, otherwise a child cue. 待心理師確認
_NEGLECT = re.compile(rf"把(?:我|他|她|{_CHILD}|{_ELDER}|爸|媽).{{0,3}}(?:鎖|關)在|被(?:鎖|關)在|不給.{{0,3}}吃|餓肚子")
_ELDER_WORD = re.compile(_ELDER)

LAW = {  # 待心理師確認: article numbers as given by the reviewer; check against 全國法規資料庫 before relying on them.
    REPORT_FAMILY: "家庭暴力防治法第 50 條",
    REPORT_CHILD: "兒童及少年福利與權益保障法第 53 條",
    REPORT_ELDER: "老人福利法第 43 條、身心障礙者權益保障法第 76 條",
    REPORT_SEXUAL: "性侵害犯罪防治法；對未滿 16 歲者另涉刑法第 227 條",
}
REPORT_PROMPT = "可能涉及法定通報義務（多數為知悉後 24 小時內），請依法評估是否通報：{law}。系統只提示，不會自動通報。"
NOTES = {
    BEHAVIOUR: "提及自殺行為（含中斷或未完成的企圖）：請確認時間與目前安全，並依自殺防治法評估是否通報。系統不會自動通報。",
    PAST: "過去的自殺或自傷行為是重要的風險因子：請確認時間、方式與當時的處置。",
    FILICIDE: "同時涉及自殺風險、傷害他人與兒少保護（" + LAW[REPORT_CHILD] + "），請依法評估是否通報。系統不會自動通報。",
    HARM_OTHERS: "提及傷害他人：請評估對象、計畫與手段，並記錄保密例外的判斷。",
    EXPOSURE: "說的是別人的自殺或自傷，不是個案本人的意念。身邊的人自殺是重大失落，也是風險因子：可詢問與當事人的關係，以及個案自己是否有過這樣的念頭。",
    HYPNOTICS: "提到安眠藥：可順帶詢問取得方式與手邊存量。",
    INDIRECT: "間接的說法，不一定指自殺：請直接詢問個案的意思。",
}
MINOR_SUBSTANCE = "個案未滿 18 歲：未成年人使用酒精或藥物，請依" + LAW[REPORT_CHILD] + "評估是否通報。系統不會自動通報。"
REFLECTION = "這是心理師複述的內容，請確認個案是否同意這個描述。"

# Categories that are about the client's own suicide or self-harm: they open the
# checklist, and a third person's act is re-labelled EXPOSURE.
SUICIDE_CATEGORIES = {IDEATION, INDIRECT, PREPARATION, PLAN, BEHAVIOUR, PAST, SELF_HARM, FILICIDE}
_OWN_ACT = {IDEATION, PLAN, BEHAVIOUR, PAST, SELF_HARM}

# Idioms that contain a cue and mean nothing of the kind.
_IDIOM = re.compile(r"想死[你妳]了|想死我了|笑死|累死了?|熱死|餓死|氣死(?!死)|嚇死|忙死|煩死|冷死|無聊死")
# "怎麼做" is everyday wording. It is a cue only next to suicide talk (CLN-11).
_CONTEXT_CUES = [(PLAN, "critical", re.compile(r"怎麼(?:做|死|結束)")), (IDEATION, "high", re.compile(r"不是沒有?想過|毋是無想過"))]
_PAST = re.compile(r"以前|之前|曾經|去年|前年|小時候|國小|國中|高中|大學時|那次|那時|當年|年前|多年|(?:割|吞|試|燒|自殺)過")
_RECENT = re.compile(r"昨天|今天|剛剛|這週|上週|前天|前幾天|這個月|上個月|最近|又")
# Someone else is the one who did it: "我朋友上個月自殺了", "我媽以前自殺過".
_THIRD_PARTY = re.compile(
    r"(?:朋友|同學|同事|室友|鄰居|媽媽?|爸爸?|哥哥?|姊姊?|姐姐?|弟弟?|妹妹?|家人|老公|先生|太太|老婆|兒子|女兒|阿公|阿嬤|新聞|藝人|他|她)"
    r"(?:的)?(?:也|又|就|都|曾經?|以前|之前|上個月|去年|前年|上週|上禮拜|昨天|前幾天|最近|那時候?|當年|在|有|是|會|想|要|說|常)*$"
)
_HYPNOTIC_STOCK = re.compile(r"存|囤|一整|很多|一次吃|全部吃|吞")
_HYPNOTIC_PRESCRIBED = re.compile(r"醫生|醫師|醫囑|按時|處方")
_WEIGHT_OK = re.compile(r"減肥|健身|運動|開心|高興")
_UNDER_16 = LEXICON[REPORT_SEXUAL][1][-1]

# Protective factors. A reason to live counts wherever it is said; a bare
# "孩子" or "朋友" counts only on a line with no risk cue (CLN-5, CLN-10).
_PROTECTIVE_REASON = re.compile(r"不想讓|捨不得|放不下|活下去的理由|為了.{0,6}(?:孩子|小孩|家人|妹妹|弟弟|爸|媽|貓|狗)|想陪.{0,6}長大")
PROTECTIVE = ["妹妹", "弟弟", "家人", "朋友", "貓", "狗", "信仰", "孩子"]
# One list for "was suicide asked about": the screening line and the first checklist item (CLN-I3).
SCREENING = ["自殺", "想死", "不想活", "結束自己的生命", "結束生命", "傷害自己", "輕生"]
SAFETY = ["安全計畫", "一九二五", "1925", "安心專線", "急診", "身心科"]

# Elements of a suicide risk inquiry, after the structure of the Columbia
# Suicide Severity Rating Scale and common safety-planning practice.
# (item, therapist pattern, how many lines back suicide talk must be for the
# therapist pattern, client pattern, the same for the client pattern). None for a
# distance means the pattern is specific enough on its own. Everyday words
# (藥, 方法, 打算, 曾經, 計畫, 買了) no longer tick an item by themselves (CLN-9).
# Missing items are shown as "consider asking or documenting", never as an error.
CHECKLIST: list[tuple[str, str | None, int | None, str | None, int | None]] = [
    ("自殺意念", "|".join(SCREENING), None, None, None),
    ("頻率或強度", r"頻率|多常|多久一次|幾次|多強烈", 6, r"個晚上|常常|每天晚上|每天都", 4),
    ("計畫或方法", r"(?:想過|有沒有|打算).{0,8}(?:怎麼做|用什麼方式|什麼方法)|具體的?計畫|計畫要.{0,6}(?:傷害|結束|自殺)|用什麼方式", 6, r"怎麼做|方法|計畫", 2),
    ("意圖", r"(?:打算|會不會|想不想).{0,8}(?:去做|付諸|真的做|這麼做|行動)|付諸行動|意圖", 6, r"想要怎麼做|打算|會去做", 2),
    ("工具或手段可及性", r"(?:家裡|手邊|身邊|拿得到|取得).{0,8}(?:藥|刀|炭|繩|農藥|工具)|(?:藥|刀|炭|繩|工具).{0,6}(?:拿得到|手邊|放在哪|收起來|交給)|(?:存|囤).{0,4}藥", None,
     r"存藥|存了.{0,8}藥|囤.{0,4}藥|安眠藥|買了.{0,4}(?:繩|炭|木炭|刀)|木炭|繩子", 4),
    ("過去自殺或自傷史", r"(?:以前|過去|之前|曾經).{0,12}(?:自殺|傷害自己|自傷|割|吞藥|想不開|試過|這樣的念頭|這種念頭|這樣想)", None,
     r"(?:以前|曾經|之前).{0,8}(?:自殺|割|吞|試過|想死)", None),
    ("保護因子", r"撐下來|支持你|重要的人|活下去的理由", 6, r"不想讓|活下去的理由|捨不得", None),
    ("安全計畫", "安全計畫", None, None, None),
    ("危機資源或轉介", r"一九二五|1925|安心專線|急診|身心科|精神科", None, None, None),
]
_REFLECTS = re.compile(r"(?:^|[。！？，])\s*(?:所以|你剛剛?才?說|你是說|你提到|聽起來你)")


def plain_cues() -> list[str]:
    """Cue words that are plain text, for the verifier's negation check."""
    return [cue for _, cues in LEXICON.values() for cue in cues if re.fullmatch(r"\w+", cue)]


_COMPILED = {category: (level, [re.compile(c) for c in cues]) for category, (level, cues) in LEXICON.items()}


def _mask(text: str) -> str:
    return _IDIOM.sub(lambda m: "＿" * len(m.group()), text)


def _suicide_talk(text: str) -> bool:
    """Does the line use suicide wording, whoever says it? Used as context for
    cues and checklist items that mean nothing on their own."""
    text = _mask(text)
    if any(c in text for c in SCREENING):
        return True
    return any(p.search(text) for category in (IDEATION, PREPARATION, PLAN, BEHAVIOUR, SELF_HARM) for p in _COMPILED[category][1])


def _near(talk: list[bool], i: int, back: int) -> bool:
    return any(talk[max(0, i - back) : i + 1])


def _is_question(text: str) -> bool:
    return text.rstrip().endswith(("？", "?"))


def _known_therapist(seg) -> bool:
    return seg.speaker == "therapist" and seg.speaker_source in CONFIRMED


def _third_party(text: str, start: int) -> bool:
    clause = re.split(r"[，。！？；,.!?;]", text[:start])[-1]
    return bool(_THIRD_PARTY.search(clause))


def _cues(text: str, in_context: bool, age: int | None) -> list[tuple[str, str, str, int]]:
    """(category, level, cue, position) for one line, before negation and speaker are considered."""
    text = _mask(text)
    found: dict[str, tuple[str, str, int]] = {}
    for category, (level, patterns) in _COMPILED.items():
        for p in patterns:
            m = p.search(text)
            if m:
                found[category] = (level, m.group(), m.start())
                break
    if in_context:
        for category, level, p in _CONTEXT_CUES:
            m = p.search(text)
            if m and category not in found:
                found[category] = (level, m.group(), m.start())
    if FUNCTIONING in found and found[FUNCTIONING][1] == "瘦了" and _WEIGHT_OK.search(text):
        del found[FUNCTIONING]  # "減肥瘦了兩公斤，很開心"
    # Sleeping pills: stockpiled is a means, prescribed and taken as told is background.
    m = re.search("安眠藥", text)
    if m and BEHAVIOUR not in found and PLAN not in found:
        if _HYPNOTIC_STOCK.search(text):
            found[PLAN] = ("critical", "安眠藥", m.start())
        else:
            found[HYPNOTICS] = ("info" if _HYPNOTIC_PRESCRIBED.search(text) else "review", "安眠藥", m.start())
    # An attempt told as history ("去年試過上吊") is history, not a current plan.
    if BEHAVIOUR in found:
        found.pop(PLAN, None)
        if _PAST.search(text) and not _RECENT.search(text):
            _, cue, at = found.pop(BEHAVIOUR)
            found[PAST] = ("high", cue, at)
    # Withheld food or confinement.
    m = _NEGLECT.search(text)
    if m:
        target = REPORT_ELDER if _ELDER_WORD.search(text) else REPORT_CHILD
        found.setdefault(target, (LEXICON[target][0], m.group(), m.start()))
    if re.search(_UNDER_16, text):
        found.setdefault(REPORT_CHILD, ("critical", re.search(_UNDER_16, text).group(), re.search(_UNDER_16, text).start()))
    if FILICIDE in found:
        found.setdefault(REPORT_CHILD, ("critical",) + found[FILICIDE][1:])
    # Someone else's suicide or self-harm.
    others = [c for c in _OWN_ACT if c in found and _third_party(text, found[c][2])]
    if others:
        _, cue, at = found[others[0]]
        for c in others:
            del found[c]
        found[EXPOSURE] = ("info", cue, at)
    if age is not None and age < 18:
        if SUBSTANCE in found:
            found[SUBSTANCE] = ("high",) + found[SUBSTANCE][1:]
        for c in (REPORT_FAMILY, REPORT_SEXUAL):
            if c in found:
                found.setdefault(REPORT_CHILD, ("critical",) + found[c][1:])
    return [(category, level, cue, at) for category, (level, cue, at) in found.items()]


def _note(category: str, age: int | None) -> str:
    if category in LAW:
        return REPORT_PROMPT.format(law=LAW[category])
    if category == SUBSTANCE and age is not None and age < 18:
        return MINOR_SUBSTANCE
    return NOTES.get(category, "")


def checklist(t: Transcript, talk: list[bool] | None = None, past: set[int] = frozenset(), protective: set[int] = frozenset()) -> list[dict]:
    """Which parts of a suicide risk inquiry appear in the session, with segment ids."""
    talk = talk if talk is not None else [_suicide_talk(s.text) for s in t.segments]
    out = []
    for item, therapist, therapist_back, client, client_back in CHECKLIST:
        covered = []
        for i, seg in enumerate(t.segments):
            # Therapist patterns count only on lines known to be the therapist's;
            # a guessed label must not tick an item.
            pattern, back = (therapist, therapist_back) if _known_therapist(seg) else (client, client_back)
            hit = bool(pattern) and re.search(pattern, seg.text) and (back is None or _near(talk, i, back))
            if not _known_therapist(seg):
                hit = hit or (item == "過去自殺或自傷史" and seg.id in past) or (item == "保護因子" and seg.id in protective)
            if hit:
                covered.append(seg.id)
        out.append({"item": item, "covered": covered})
    return out


class RiskAgent:
    def run(self, t: Transcript) -> RiskReport:
        report = RiskReport(level="none")
        age = t.client_age
        talk = [_suicide_talk(s.text) for s in t.segments]
        report.speakers_confirmed = any(_known_therapist(s) for s in t.segments)
        for i, seg in enumerate(t.segments):
            # Screening and safety steps count only on lines known to be the
            # therapist's. With uploaded audio the speaker is a guess, so every
            # line is scanned: a wrong guess must not hide what the client said.
            reflection = False
            if _known_therapist(seg):
                if any(c in seg.text for c in SCREENING):
                    report.screening_asked.append(seg.id)
                if any(c in seg.text for c in SAFETY):
                    report.safety_actions.append(seg.id)
                # A therapist's own line is scanned only when it restates what the
                # client disclosed ("所以你昨天吞了一整罐藥"); the client may only have nodded.
                reflection = bool(_REFLECTS.search(seg.text)) or (not _is_question(seg.text) and "你" in seg.text)
                if not reflection:
                    continue
            unconfirmed = seg.speaker_source not in CONFIRMED or seg.speaker not in ("therapist", "client")
            # Only a likely therapist question ("你有想過…嗎？") from an unconfirmed
            # speaker is lowered to review. A first-person statement such as
            # "我想燒炭" keeps its level whoever the model guessed said it.
            maybe_therapist = unconfirmed and _is_question(seg.text) and ("你" in seg.text or "妳" in seg.text)
            flagged = set()
            for category, level, cue, at in _cues(seg.text, _near(talk, i, 2), age):
                if reflection and "你" not in seg.text[:at] and not _REFLECTS.search(seg.text):
                    continue
                negated = polarity(_mask(seg.text), at) == "denied"
                lvl = "review" if (negated or maybe_therapist) and LEVEL_ORDER[level] > LEVEL_ORDER["review"] else level
                note = " ".join(x for x in (_note(category, age), REFLECTION if reflection else "") if x)
                report.flags.append(RiskFlag(category, lvl, seg.id, seg.text, cue, negated, unconfirmed, note, maybe_therapist, reflection))
                flagged.add(category)
            if reflection:
                continue  # a therapist's "家人" is not the client's protective factor
            reason = _PROTECTIVE_REASON.search(seg.text)
            if reason and not flagged & {FILICIDE, HARM_OTHERS}:
                report.protective.append(RiskFlag("保護因子", "info", seg.id, seg.text, reason.group(), speaker_unconfirmed=unconfirmed))
            elif not flagged:
                for cue in PROTECTIVE:
                    if cue in seg.text:
                        report.protective.append(RiskFlag("保護因子", "info", seg.id, seg.text, cue, speaker_unconfirmed=unconfirmed))
                        break
        if report.flags:
            report.level = max((f.level for f in report.flags), key=LEVEL_ORDER.__getitem__)
        if any(f.category in SUICIDE_CATEGORIES for f in report.flags):
            report.checklist = checklist(t, talk, {f.segment_id for f in report.flags if f.category == PAST},
                                         {p.segment_id for p in report.protective})
        return report
