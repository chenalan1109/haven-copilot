"""Turns a clinician-marked review sheet into the numbers for the slides.

    python3 scripts/review_summary.py docs/benchmarks/b70-vllm-qwen3-32b-awq-review.csv

The sheet comes from scripts/benchmark.py. A clinician fills the verdict column for each
flagged sentence: real_error (the note was wrong and the verifier caught it),
wrongly_blocked (the sentence was fine; the verifier was too strict) or unsure.

Prints, per session and overall:
  - real errors caught    what the verifier is for
  - wrongly blocked       the cost: extra clicks for the therapist
  - unmarked / unsure     not counted either way
  - clicks per note       flagged sentences per note (median over runs)
The supported count comes from the matching .json, so the three groups add up to all sentences.
"""

import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

VERDICT_COL = "clinician_verdict (real_error / wrongly_blocked / unsure)"
ALIASES = {"real_error": "real_error", "real": "real_error", "真錯": "real_error", "攔得好": "real_error",
           "wrongly_blocked": "wrongly_blocked", "wrong": "wrongly_blocked", "誤擋": "wrongly_blocked",
           "unsure": "unsure", "不確定": "unsure"}


def summarize(sheet: Path) -> dict:
    per = defaultdict(lambda: defaultdict(int))
    per_run = defaultdict(int)
    with sheet.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            v = ALIASES.get(row.get(VERDICT_COL, "").strip().lower(), "unmarked")
            per[row["session_id"]][v] += 1
            per_run[(row["session_id"], row["run"])] += 1

    report_json = sheet.with_name(sheet.name.replace("-review.csv", ".json"))
    supported, runs_per_session = {}, {}
    if report_json.exists():
        rep = json.loads(report_json.read_text(encoding="utf-8"))
        for s in rep["sequential"]:
            runs = s.get("runs") or [s]
            supported[s["session_id"]] = sum(r["sentences_supported"] for r in runs)
            runs_per_session[s["session_id"]] = len(runs)

    sessions = sorted(set(per) | set(supported))
    out = {}
    for sid in sessions:
        n_runs = runs_per_session.get(sid, len({r for (s, r) in per_run if s == sid}) or 1)
        clicks = [per_run.get((sid, str(k)), 0) for k in range(1, n_runs + 1)]
        out[sid] = {"supported": supported.get(sid), **{k: per[sid][k] for k in ("real_error", "wrongly_blocked", "unsure", "unmarked")},
                    "runs": n_runs, "clicks_per_note_median": statistics.median(clicks)}
    return out


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    res = summarize(Path(sys.argv[1]))
    tot = defaultdict(float)
    print("| Session | Runs | Passed | Real errors caught | Wrongly blocked | Unsure/unmarked | Clicks per note (median) |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for sid, r in res.items():
        print(f"| {sid} | {r['runs']} | {r['supported'] if r['supported'] is not None else '?'} | {r['real_error']} | "
              f"{r['wrongly_blocked']} | {r['unsure'] + r['unmarked']} | {r['clicks_per_note_median']:g} |")
        for k in ("real_error", "wrongly_blocked", "unsure", "unmarked"):
            tot[k] += r[k]
    flagged = tot["real_error"] + tot["wrongly_blocked"]
    if flagged:
        print(f"\nOf {flagged:g} marked flags, {tot['real_error'] / flagged:.0%} were real errors "
              f"(precision of the verifier's flags).")
    if tot["unmarked"]:
        print(f"{tot['unmarked']:g} flagged sentences are not marked yet.")


if __name__ == "__main__":
    main()
