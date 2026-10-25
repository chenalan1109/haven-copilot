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
    def run(self, client: dict) -> dict:
        results = [assess(m, h) for m, h in client.get("scores", {}).items() if m in MEASURES and h]
        alerts = [r for r in results if r["status"] in ("deteriorated", "not_on_track")]
        bsrs = client.get("scores", {}).get("BSRS5", [])
        if bsrs and bsrs[-1].get("suicide_item", 0) >= 2:
            alerts.append({
                "measure": "BSRS5",
                "name": "BSRS-5 第 6 題（自殺想法）",
                "status": "deteriorated",
                "message": f"最近一次自殺想法題得 {bsrs[-1]['suicide_item']} 分（≥2），建議評估",
            })
        return {"measures": results, "alerts": alerts}
