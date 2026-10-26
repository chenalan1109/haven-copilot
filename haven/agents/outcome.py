"""Outcome agent: routine outcome monitoring over the client's questionnaire scores.

Flags clients who are deteriorating or not improving, the group in which
progress feedback has the clearest evidence (Lambert et al., 2018).
Reliable-change thresholds follow common practice (PHQ-9: 6, GAD-7: 4); the
"not on track" rule is a simple heuristic, not a validated expected-recovery
curve.
"""

from __future__ import annotations

MEASURES = {
    "PHQ9": {
        "name": "PHQ-9 憂鬱",
        "max": 27,
        "reliable_change": 6,
        "clinical_cutoff": 10,
        "bands": [(0, "極輕微"), (5, "輕度"), (10, "中度"), (15, "中重度"), (20, "重度")],
    },
    "GAD7": {
        "name": "GAD-7 焦慮",
        "max": 21,
        "reliable_change": 4,
        "clinical_cutoff": 8,
        "bands": [(0, "極輕微"), (5, "輕度"), (10, "中度"), (15, "重度")],
    },
    "BSRS5": {
        "name": "BSRS-5 簡式健康量表",
        "max": 20,
        "reliable_change": None,
        "clinical_cutoff": 6,
        "bands": [(0, "正常"), (6, "輕度"), (10, "中度"), (15, "重度")],
    },
}

MIN_SESSIONS_FOR_TRACKING = 3

# For a not-on-track client, feedback works best paired with a structured
# review of why (Lambert's clinical support tools). Shown as a prompt only.
REVIEW_PROMPT = "可與個案一起檢視量表回饋，並檢視治療同盟、改變動機、社會支持與近期生活事件"


def band(measure: str, score: int) -> str:
    label = ""
    for floor, name in MEASURES[measure]["bands"]:
        if score >= floor:
            label = name
    return label


def assess(measure: str, history: list[dict]) -> dict:
    spec = MEASURES[measure]
    baseline, latest = history[0]["score"], history[-1]["score"]
    change = latest - baseline
    rc = spec["reliable_change"]
    if rc is not None and change >= rc:
        status, message = "deteriorated", f"比初次惡化 {change} 分，超過可信改變門檻 {rc} 分"
    elif rc is not None and change <= -rc and baseline >= spec["clinical_cutoff"] > latest:
        # Jacobson & Truax: reliable change that also crosses the clinical cutoff.
        status, message = "recovered", f"比初次改善 {-change} 分，且已低於臨床切點 {spec['clinical_cutoff']}（臨床顯著改變）"
    elif rc is not None and change <= -rc:
        status, message = "improved", f"比初次改善 {-change} 分，達可信改善"
    elif len(history) >= MIN_SESSIONS_FOR_TRACKING and latest >= spec["clinical_cutoff"] and change >= 0:
        status, message = "not_on_track", f"已 {len(history)} 次仍未改善，且在臨床範圍（≥{spec['clinical_cutoff']}）"
    else:
        status, message = "on_track", "目前無警示"
    return {
        "measure": measure,
        "name": spec["name"],
        "max": spec["max"],
        "history": history,
        "baseline": baseline,
        "latest": latest,
        "change": change,
        "band": band(measure, latest),
        "status": status,
        "message": message,
    }


class OutcomeAgent:
    def note_sentences(self, client: dict, session_no: int) -> list[dict]:
        """Score lines for the note's objective section, taken from the questionnaires
        completed for this session, so the writer never has to restate numbers."""
        out = []
        for measure, history in client.get("scores", {}).items():
            if measure not in MEASURES:
                continue
            now = next((h for h in history if h.get("session") == session_no), None)
            if now is None:
                continue
            text = f"{MEASURES[measure]['name'].split(' ')[0]} {now['score']} 分（{band(measure, now['score'])}）"
            if history[0] is not now:
                text += f"，初次 {history[0]['score']} 分"
            if measure == "BSRS5" and "suicide_item" in now:
                text += f"，自殺想法題 {now['suicide_item']} 分"
            if measure == "PHQ9" and "item9" in now:
                text += f"，第 9 題 {now['item9']} 分"
            out.append({"text": text + "。", "date": now.get("date", "")})
        return out

    def run(self, client: dict) -> dict:
        results = [assess(m, h) for m, h in client.get("scores", {}).items() if m in MEASURES and h]
        alerts = [dict(r, review=REVIEW_PROMPT) for r in results if r["status"] in ("deteriorated", "not_on_track")]
        # Single-item suicide questions are alerted on regardless of the total score.
        phq = client.get("scores", {}).get("PHQ9", [])
        if phq and phq[-1].get("item9", 0) >= 1:
            alerts.append({
                "measure": "PHQ9",
                "name": "PHQ-9 第 9 題（死亡或自傷念頭）",
                "status": "deteriorated",
                "message": f"最近一次得 {phq[-1]['item9']} 分（≥1），請於會談中詢問",
            })
        bsrs = client.get("scores", {}).get("BSRS5", [])
        if bsrs and bsrs[-1].get("suicide_item", 0) >= 2:
            alerts.append({
                "measure": "BSRS5",
                "name": "BSRS-5 第 6 題（自殺想法）",
                "status": "deteriorated",
                "message": f"最近一次自殺想法題得 {bsrs[-1]['suicide_item']} 分（≥2），依建議應進一步評估並考慮轉介",
            })
        return {"measures": results, "alerts": alerts}
