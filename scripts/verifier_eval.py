"""Measures how many wrong note sentences the verifier catches, and how many right ones it flags.

    python3 scripts/verifier_eval.py                     # rule + overlap layers only
    HAVEN_LLM=openai python3 scripts/verifier_eval.py    # also the local-LLM layer
    python3 scripts/verifier_eval.py --label b70-qwen27b

Cases are in data/verifier_eval/cases.json. A case is "blocked" when the verifier marks
it unsupported (the therapist cannot sign until they edit, delete or keep it) and
"flagged" when it is unsupported or weak. Results go to docs/verifier-eval/<label>.json
and .md.
"""

import argparse
import json
import platform
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from haven.agents.verifier import Verifier  # noqa: E402
from haven.llm import get_llm  # noqa: E402
from haven.models import Note, NoteSentence  # noqa: E402
from haven.transcript import load_transcript  # noqa: E402


def evaluate(cases: list[dict], llm=None) -> list[dict]:
    by_session = defaultdict(list)
    for c in cases:
        by_session[c["session_id"]].append(c)
    results = []
    for sid, group in by_session.items():
        t = load_transcript(sid)
        # One note per session, so the LLM layer sees one batch as it would in use.
        note = Note("SOAP", {"S": [NoteSentence(c["text"], c["evidence"]) for c in group]}, "eval")
        Verifier(llm).run(note, t)
        for c, s in zip(group, note.sections["S"]):
            results.append({**c, "status": s.status, "support": s.support, "reason": s.reason})
    return results


def summarize(results: list[dict]) -> dict:
    ok = [r for r in results if r["label"] == "ok"]
    errors = [r for r in results if r["label"] != "ok"]
    per_label = {}
    for label in sorted({r["label"] for r in errors}):
        rs = [r for r in errors if r["label"] == label]
        per_label[label] = {
            "n": len(rs),
            "blocked": sum(r["status"] == "unsupported" for r in rs),
            "flagged": sum(r["status"] != "supported" for r in rs),
        }
    return {
        "errors": len(errors),
        "errors_blocked": sum(r["status"] == "unsupported" for r in errors),
        "errors_flagged": sum(r["status"] != "supported" for r in errors),
        "correct": len(ok),
        "correct_blocked": sum(r["status"] == "unsupported" for r in ok),
        "correct_flagged": sum(r["status"] != "supported" for r in ok),
        "per_label": per_label,
    }


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({a / b:.0%})" if b else "-"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default=None)
    args = ap.parse_args()

    spec = json.loads((ROOT / "data" / "verifier_eval" / "cases.json").read_text(encoding="utf-8"))
    llm = get_llm()
    engine = llm.label if llm else "rules + overlap (no LLM)"
    label = args.label or f"{platform.machine()}-{engine.split(' ')[0].replace(':', '-').replace('/', '-')}"

    results = evaluate(spec["cases"], llm)
    summary = summarize(results)
    print(f"engine: {engine}")
    print(f"  wrong sentences blocked: {pct(summary['errors_blocked'], summary['errors'])}, "
          f"flagged: {pct(summary['errors_flagged'], summary['errors'])}")
    print(f"  right sentences blocked (false alarms): {pct(summary['correct_blocked'], summary['correct'])}")

    report = {"label": label, "date": datetime.now().astimezone().isoformat(timespec="seconds"),
              "engine": engine, "summary": summary, "results": results}
    out = ROOT / "docs" / "verifier-eval"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{label}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# Verifier test set: {label}", "", f"- Engine: `{engine}`", f"- Date: {report['date']}",
             f"- Cases: {len(results)} sentences about the simulated sessions ({summary['correct']} correct, "
             f"{summary['errors']} with a known error)",
             "- Blocked = marked unsupported, so the note cannot be signed until the therapist acts. "
             "Flagged = blocked or marked weak.", "",
             "| | Blocked | Flagged |", "| --- | --- | --- |",
             f"| Wrong sentences | {pct(summary['errors_blocked'], summary['errors'])} | "
             f"{pct(summary['errors_flagged'], summary['errors'])} |",
             f"| Correct sentences (false alarms) | {pct(summary['correct_blocked'], summary['correct'])} | "
             f"{pct(summary['correct_flagged'], summary['correct'])} |", "",
             "| Error type | Blocked | Flagged |", "| --- | --- | --- |"]
    for k, v in summary["per_label"].items():
        lines.append(f"| {k}: {spec['labels'][k]} | {pct(v['blocked'], v['n'])} | {pct(v['flagged'], v['n'])} |")
    lines += ["", "## Misses and false alarms", "", "| Case | Type | Sentence | Status | Reason |", "| --- | --- | --- | --- | --- |"]
    for r in results:
        missed = r["label"] != "ok" and r["status"] == "supported"
        false_alarm = r["label"] == "ok" and r["status"] == "unsupported"
        if missed or false_alarm:
            lines.append(f"| {r['id']} | {r['label']} | {r['text']} | {r['status']} | {r['reason'] or '-'} |")
    (out / f"{label}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote docs/verifier-eval/{label}.md")


if __name__ == "__main__":
    main()
