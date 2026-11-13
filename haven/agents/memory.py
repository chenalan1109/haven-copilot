"""Case-memory agent: answers questions about one client from their own sessions only.

Keyword search, not understanding. A question is widened with the words clients
actually use ("父親" also finds "我爸"), every session is searched, and the answer
says how many lines matched in each session, so a topic raised in three sessions
is not shown as if it came up once. Finding nothing means the words did not
match; the UI says that this is not evidence the topic never came up.

The word families below were widened from the 2026-11-12 clinical review and are
待心理師確認: not yet checked by a licensed psychologist.
"""

from __future__ import annotations

import json
import re

from ..llm import DATA_ONLY
from ..textutil import bigrams
from ..transcript import load_transcript

# (words a therapist might type, words to look for in the transcript)
FAMILIES = [
    ("父親 爸爸 爸", "父親 爸爸 我爸 爸 老爸 阿爸"),
    ("母親 媽媽 媽", "母親 媽媽 我媽 媽 阿母"),
    ("失眠 睡眠 睡", "失眠 睡不著 睡不好 醒來 睡眠 睡覺"),
    ("自殺 想死 輕生 不想活 自殺意念", "自殺 想死 不想活 活著 消失 結束 生命 撐不下去 解脫 不要醒來 燒炭 安眠藥 跳樓 輕生"),
    ("自傷 自殘 傷害自己", "自傷 割 自殘 傷害自己 撞牆 燙 刀片"),
    ("保護因子 支持 撐下來", "不想讓 撐下來 理由 陪 支持"),
    ("安全計畫 專線 轉介", "安全計畫 專線 急診 轉介 身心科"),
    ("工作 職場", "工作 主管 加班 公司 同事"),
    ("作業 練習", "作業 練習 紀錄"),
    ("喝酒 飲酒 物質", "喝酒 酒 藥 毒"),
]
# Question scaffolding; not what is being asked about.
_STOP = bigrams("哪幾次提到什麼時候有沒有談到說過講過曾經個案哪一次是否幾次")
_STOP_PHRASES = sorted("哪幾次 哪一次 哪次 幾次 什麼時候 有沒有 是否 曾經 提到 提過 談到 談過 說過 講過 個案 關於 他 她 的 嗎 呢 了 過".split(), key=len, reverse=True)
_PUNCT = re.compile(r"[\s\W_]+")


def topic(query: str) -> str:
    """What is left of a question once the scaffolding is gone: 「哪幾次提到貓？」 → 「貓」."""
    rest = _PUNCT.sub("", query)
    for w in _STOP_PHRASES:
        rest = rest.replace(w, "")
    return rest
PER_SESSION = 3  # lines shown per session; the count of all matching lines is always given
MAX_SHOWN = 30

SYSTEM_PROMPT = "你是心理師的個案資料助理。只能根據提供的逐字稿片段回答，每個說法標註 [會談編號#段落]，資料不足就說不知道。用繁體中文。" + DATA_ONLY


def expand(query: str) -> list[str]:
    """Transcript words to look for, when the question uses a word from a family."""
    terms: list[str] = []
    for asked, found in FAMILIES:
        if any(w in query for w in asked.split()):
            terms += [w for w in found.split() if w not in terms]
    return terms


class CaseMemory:
    def __init__(self, llm=None):
        self.llm = llm

    def search(self, client: dict, query: str) -> list[dict]:
        """Every matching line in every session of this client, best first within a session."""
        terms = expand(query)
        rest = topic(query)
        if not terms and 0 < len(rest) <= 2:
            # One or two characters (貓, 藥, 哥哥 would be 2): bigrams of the whole
            # question never match, so look for the word itself.
            terms = [rest]
        q = bigrams(query) - _STOP
        hits = []
        for session_id in client.get("sessions", []):
            try:
                t = load_transcript(session_id)
            except (OSError, ValueError, KeyError, TypeError):
                continue  # a listed session whose file is missing or damaged
            for seg in t.segments:
                by_term = sum(w in seg.text for w in terms)
                # With a known topic, a line must contain one of its words: the rest
                # of the question ("提到", "幾次") matches almost anything.
                score = 2 * by_term + len(q & bigrams(seg.text)) if (by_term or not terms) else 0
                if score:
                    hits.append({
                        "session_id": session_id,
                        "session_no": t.session_no,
                        "segment_id": seg.id,
                        "start": seg.start,
                        # As labelled in the transcript: "unknown" stays unknown, a guess stays a guess.
                        "speaker": seg.speaker,
                        "speaker_source": seg.speaker_source,
                        "text": seg.text,
                        "score": score,
                    })
        hits.sort(key=lambda h: (h["session_no"], -h["score"], h["segment_id"]))
        return hits

    def ask(self, client: dict, query: str) -> dict:
        found = self.search(client, query)
        sessions: dict[str, dict] = {}
        shown = []
        for h in found:
            group = sessions.setdefault(h["session_id"], {"session_id": h["session_id"], "session_no": h["session_no"], "count": 0})
            group["count"] += 1
            if group["count"] <= PER_SESSION and len(shown) < MAX_SHOWN:
                shown.append(h)
        answer = None
        if self.llm is not None and shown:
            context = "\n".join(json.dumps({"ref": f"{h['session_id']}#{h['segment_id']}", "text": h["text"]}, ensure_ascii=False) for h in shown)
            raw = self.llm.generate_json(SYSTEM_PROMPT, f"片段（每行一段，ref 是會談編號#段落）：\n{context}\n\n問題：{json.dumps(query, ensure_ascii=False)}\n輸出 {{\"answer\": \"...\"}}", max_tokens=600)
            answer = raw.get("answer") if isinstance(raw, dict) and isinstance(raw.get("answer"), str) else None
        return {
            "query": query, "answer": answer, "hits": shown,
            # One entry per session with a match, so "which sessions" is answered even without a model.
            "sessions": list(sessions.values()), "total": len(found), "expanded": expand(query),
        }
