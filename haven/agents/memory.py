"""Case-memory agent: answers questions about one client from their own sessions only."""

from __future__ import annotations

from ..textutil import bigrams
from ..transcript import load_transcript

# Clinical wording vs. how clients actually talk.
SYNONYMS = {
    "父親": "爸爸 我爸", "母親": "媽媽 我媽", "失眠": "睡不著 醒來", "睡眠": "睡不著 醒來",
    "自殺": "活著 消失 結束 生命", "工作": "主管 加班 公司", "作業": "作業 練習 紀錄",
}

SYSTEM_PROMPT = "你是心理師的個案資料助理。只能根據提供的逐字稿片段回答，每個說法標註 [會談編號#段落]，資料不足就說不知道。用繁體中文。"


class CaseMemory:
    def __init__(self, llm=None):
        self.llm = llm

    def search(self, client: dict, query: str, k: int = 5) -> list[dict]:
        q = bigrams(query) - bigrams("哪幾次提到什麼時候有沒有")
        terms = [w for k, v in SYNONYMS.items() if k in query for w in v.split()]
        hits = []
        for session_id in client.get("sessions", []):
            t = load_transcript(session_id)
            for seg in t.segments:
                score = len(q & bigrams(seg.text)) + 2 * sum(w in seg.text for w in terms)
                if score:
                    hits.append({
                        "session_id": session_id,
                        "session_no": t.session_no,
                        "segment_id": seg.id,
                        "start": seg.start,
                        "speaker": seg.speaker,
                        "text": seg.text,
                        "score": score,
                    })
        hits.sort(key=lambda h: (-h["score"], h["session_no"], h["segment_id"]))
        return hits[:k]

    def ask(self, client: dict, query: str) -> dict:
        hits = self.search(client, query)
        answer = None
        if self.llm is not None and hits:
            context = "\n".join(f"[{h['session_id']}#{h['segment_id']}] {h['text']}" for h in hits)
            raw = self.llm.generate_json(SYSTEM_PROMPT, f"片段：\n{context}\n\n問題：{query}\n輸出 {{\"answer\": \"...\"}}")
            answer = raw.get("answer") if raw else None
        return {"query": query, "answer": answer, "hits": hits}
