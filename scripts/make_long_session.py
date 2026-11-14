"""Writes a 50-minute simulated session with the local model, for load tests.

    HAVEN_LLM=openai HAVEN_MODEL=qwen3-32b-awq python3 scripts/make_long_session.py

The three demo sessions are 2-4 minutes long; a real session is about 50. This asks
the local model for fourteen parts of a CBT session (client C002, simulated) and
writes data/sessions/C002-L50.json. The session is not listed under the client, so it
does not show in the demo UI; scripts/benchmark.py --sessions C002-L50 processes it.
Timing assumes about four characters a second, an ordinary pace for Mandarin.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from haven import config  # noqa: E402
from haven.files import write_private  # noqa: E402
from haven.llm import get_llm  # noqa: E402

PARTS = [
    "開場與近況：這兩週的心情，期中考剛結束",
    "睡眠與作息：熬夜、早上爬不起來，對上課的影響",
    "回顧作業：課堂上主動發問的練習，做了一次，發問前後的焦慮分數",
    "一次沒做到的經驗：想發問但放棄，當下腦中的想法",
    "辨識自動化想法：「問笨問題大家會看不起我」，找支持與反對的證據",
    "行為實驗：下週再發問一次，先寫下預測，事後比較實際結果",
    "拖延與讀書計畫：番茄鐘的執行情形，手機干擾",
    "與室友的相處：不好意思請室友晚上小聲一點",
    "角色扮演：練習向室友提出請求，心理師回饋",
    "社團與人際：想參加社團活動，但害怕自我介紹",
    "家人的期待：父母對成績的要求，個案的感受",
    "自我要求：「不是第一名就是失敗」的想法，從哪裡學來的",
    "整理今天的收穫：個案用自己的話摘要",
    "下週作業與結束：向室友提出一次請求、每天兩個番茄鐘、安排下次會談",
]
SYSTEM = ("你是編劇，替心理治療訓練教材寫模擬會談逐字稿。內容為虛構，使用繁體中文與台灣用語，"
          "口語自然。這是認知行為治療第六次會談，個案是大學生，主訴社交焦慮與拖延。只輸出 JSON。")
CHARS_PER_SECOND = 4.0


def main() -> None:
    llm = get_llm()
    if llm is None:
        sys.exit("needs a local model: set HAVEN_LLM and HAVEN_MODEL")
    turns: list[dict] = []
    for n, topic in enumerate(PARTS, start=1):
        tail = "\n".join(f"{'心理師' if t['speaker'] == 'therapist' else '個案'}：{t['text']}" for t in turns[-4:])
        prompt = (
            f"這是會談的第 {n}/{len(PARTS)} 段，主題：{topic}。\n"
            + (f"前一段的結尾：\n{tail}\n接著寫下去，不要重複。\n" if tail else "從心理師的開場白開始。\n")
            + "寫 24 句左右，心理師與個案輪流說話，個案的話比較長（兩到四句），心理師的話短。全段約 1200 字。"
            '輸出 {"turns": [{"speaker": "therapist" 或 "client", "text": "..."}]}'
        )
        out = llm.generate_json(SYSTEM, prompt) or {}
        part = [t for t in out.get("turns", []) if isinstance(t, dict)
                and t.get("speaker") in ("therapist", "client") and isinstance(t.get("text"), str) and t["text"].strip()]
        if not part:
            sys.exit(f"part {n}: the model returned no usable turns")
        turns += part
        print(f"part {n}: {len(part)} turns, {sum(len(t['text']) for t in part)} characters")

    segments, clock = [], 0.0
    for i, t in enumerate(turns, start=1):
        seconds = round(max(2.0, len(t["text"]) / CHARS_PER_SECOND), 1)
        segments.append({"id": i, "start": round(clock, 1), "end": round(clock + seconds, 1),
                         "speaker": t["speaker"], "text": t["text"].strip()})
        clock += seconds
    session = {
        "session_id": "C002-L50", "client_id": "C002", "session_no": 6, "date": "2026-10-20", "simulated": True,
        "note": f"模擬會談，由本機模型（{llm.label}）依大綱撰寫，供長會談效能測試，非真實個案。",
        "segments": segments,
    }
    path = config.SESSIONS_DIR / "C002-L50.json"
    write_private(path, json.dumps(session, ensure_ascii=False, indent=1))  # 0600, like every session file Haven writes
    print(f"wrote {path}: {len(segments)} segments, {sum(len(s['text']) for s in segments)} characters, {clock / 60:.0f} minutes")


if __name__ == "__main__":
    main()
