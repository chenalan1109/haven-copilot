"""Outcome agent: routine outcome monitoring over the client's questionnaire scores.

Flags clients who are deteriorating or not improving, the group in which
progress feedback has the clearest evidence (Lambert et al., 2018).
Reliable-change thresholds follow common practice (PHQ-9: 6, GAD-7: 4, as in
NHS Talking Therapies).

"Not on track" means: from the third score on, still in the clinical range and
not reliably improved since the first score. A client who moved from 20 to 19
over eight sessions is not on track; the earlier rule (no decrease at all)
called that "no alert". This is still a heuristic, not a validated
expected-recovery curve such as Lambert's for the OQ-45. BSRS-5 has no
published reliable-change value; 3 points is used as a stand-in and said so on
screen. The thresholds and wording come from the 2026-11-12 clinical review
and are 待心理師確認.

The two single-item suicide questions raise an "item" reminder, not a
"deteriorated" alert: one answer on one item is not a trend. Both prompt the
therapist to ask from a score of 1; the BSRS-5 item adds the referral advice
of 台灣自殺防治學會 from a score of 2.
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
        # 8 is "輕度" by the bands and "clinical range" by the cut-off; say why on the chart.
        "note": "臨床切點採 8 分（IAPT）；Spitzer 等人建議以 10 分篩檢廣泛性焦慮症。",
    },
    "BSRS5": {
        "name": "BSRS-5 簡式健康量表",
        "max": 20,
        "reliable_change": None,
        "clinical_cutoff": 6,
        "bands": [(0, "正常"), (6, "輕度"), (10, "中度"), (15, "重度")],
        "note": "BSRS-5 沒有公認的可信改變值，「未達預期改善」暫以 3 分判斷。",
    },
}
# Used where a measure has no published reliable-change value (BSRS-5). A stand-in.
PROVISIONAL_CHANGE = 3
LABELS = {"deteriorated": "惡化", "not_on_track": "未達預期改善", "item_alert": "單題提醒"}

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
    step = latest - history[-2]["score"] if len(history) >= 2 else 0
    needed = rc if rc is not None else PROVISIONAL_CHANGE
    if rc is not None and change >= rc:
        status, message = "deteriorated", f"比初次惡化 {change} 分，超過可信改變門檻 {rc} 分"
    elif rc is not None and step >= rc:
        # A reliable worsening since the last session, even when the first score was higher still.
        status, message = "deteriorated", f"比上一次惡化 {step} 分，超過可信改變門檻 {rc} 分"
    elif rc is not None and change <= -rc and baseline >= spec["clinical_cutoff"] > latest:
        # Jacobson & Truax: reliable change that also crosses the clinical cutoff.
        status, message = "recovered", f"比初次改善 {-change} 分，且已低於臨床切點 {spec['clinical_cutoff']}（臨床顯著改變）"
    elif rc is not None and change <= -rc:
        status, message = "improved", f"比初次改善 {-change} 分，達可信改善"
    elif len(history) >= MIN_SESSIONS_FOR_TRACKING and latest >= spec["clinical_cutoff"] and change > -needed:
        moved = f"改善 {-change} 分" if change < 0 else f"增加 {change} 分" if change > 0 else "沒有變化"
        status = "not_on_track"
        message = (f"已 {len(history)} 次，比初次{moved}，未達可信改善（{needed} 分{'，暫定' if rc is None else ''}），"
                   f"且仍在臨床範圍（≥{spec['clinical_cutoff']}）")
    else:
        status, message = "on_track", "目前無警示"
    return {
        "measure": measure,
        "name": spec["name"],
        "max": spec["max"],
        "clinical_cutoff": spec["clinical_cutoff"],
        "history": history,
        "baseline": baseline,
        "latest": latest,
        "change": change,
        "band": band(measure, latest),
        "status": status,
        "label": LABELS.get(status, ""),
        "message": message,
        "note": spec.get("note", ""),
    }


class OutcomeAgent:
    def note_sentences(self, client: dict, session_no: int) -> list[str]:
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
            out.append(text + "。")
        return out

    def run(self, client: dict) -> dict:
        results = [assess(m, h) for m, h in client.get("scores", {}).items() if m in MEASURES and h]
        alerts = [dict(r, review=REVIEW_PROMPT) for r in results if r["status"] in ("deteriorated", "not_on_track")]
        # Single-item suicide questions are shown whatever the total score, from a
        # score of 1 on both questionnaires. They are reminders to ask, not a trend.
        phq = client.get("scores", {}).get("PHQ9", [])
        if phq and phq[-1].get("item9", 0) >= 1:
            alerts.append({
                "measure": "PHQ9",
                "name": "PHQ-9 第 9 題（死亡或自傷念頭）",
                "status": "item_alert",
                "label": LABELS["item_alert"],
                "message": f"最近一次得 {phq[-1]['item9']} 分（≥1），請於會談中詢問",
            })
        bsrs = client.get("scores", {}).get("BSRS5", [])
        item = bsrs[-1].get("suicide_item", 0) if bsrs else 0
        if item >= 1:
            alerts.append({
                "measure": "BSRS5",
                "name": "BSRS-5 第 6 題（自殺想法）",
                "status": "item_alert",
                "label": LABELS["item_alert"],
                "message": (f"最近一次自殺想法題得 {item} 分（≥2），依建議應進一步評估並考慮轉介" if item >= 2
                            else f"最近一次自殺想法題得 {item} 分（≥1），請於會談中詢問自殺想法"),
            })
        return {"measures": results, "alerts": alerts}
