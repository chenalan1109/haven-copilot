"""Measures Haven on this machine and writes the performance data the finals ask for.

    python3 scripts/benchmark.py                 # each demo session once, one at a time
    python3 scripts/benchmark.py --rooms 4       # also N sessions at once (N therapy rooms)
    python3 scripts/benchmark.py --label b70-vllm-qwen27b
    python3 scripts/benchmark.py --repeat 3      # each session 3 times; tables show the median

Every sentence the verifier did not pass also goes to docs/benchmarks/<label>-review.csv,
one row per sentence, with an empty column for a clinician to mark it a real error
(caught correctly) or a correct sentence (blocked by mistake). scripts/review_summary.py
turns a marked sheet into the three numbers for the slides.

Uses whatever model HAVEN_LLM / HAVEN_LLM_URL / HAVEN_MODEL point at. Results go to
docs/benchmarks/<label>.json and a Markdown table to docs/benchmarks/<label>.md.
The run uses a throwaway database, so the demo data and signed notes are untouched.
"""

import argparse
import csv
import json
import platform
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from haven import config  # noqa: E402
from haven.llm import get_llm  # noqa: E402
from haven.orchestrator import Orchestrator, load_clients  # noqa: E402


def flagged_sentences(r: dict) -> list[dict]:
    """Every sentence the verifier did not pass, with the lines it cited."""
    segs = {seg["id"]: seg for seg in r["transcript"]}
    out = []
    for section, items in r["note"]["sections"].items():
        for s in items:
            if s.get("source") == "measure" or s["status"] == "supported":
                continue
            cited = [f"[{e}] {segs[e]['speaker']}: {segs[e]['text']}" for e in s["evidence"] if e in segs]
            out.append({"section": section, "sentence": s["text"], "status": s["status"],
                        "reason": s["reason"], "must_confirm": s.get("must_confirm", False),
                        "cited": " / ".join(cited)})
    return out


def run_one(session_id: str) -> dict:
    # A model client per run, so its token counts belong to this session only.
    llm = get_llm()
    orch = Orchestrator(llm=llm, use_llm=llm is not None)
    t0 = time.perf_counter()
    r = orch.process_session(session_id)
    total = time.perf_counter() - t0
    calls = llm.calls if llm else []
    out_tokens = sum(c["completion_tokens"] for c in calls)
    llm_seconds = sum(c["seconds"] for c in calls)
    v = r["verification"]
    return {
        "session_id": session_id,
        "speech_seconds": round(r["transcript"][-1]["end"], 1) if r["transcript"] else 0,
        "total_seconds": round(total, 1),
        "agents_ms": r["timings_ms"],
        "llm_calls": len(calls),
        "prompt_tokens": sum(c["prompt_tokens"] for c in calls),
        "completion_tokens": out_tokens,
        "output_tokens_per_second": round(out_tokens / llm_seconds, 1) if llm_seconds else None,
        "sentences_supported": v["supported"],
        "sentences_total": v["total"],
        "sentences_weak": v["weak"],
        "sentences_unsupported": v["unsupported"],
        "risk_level": r["risk"]["level"],
        "flagged": flagged_sentences(r),
    }


def summarize(session_id: str, runs: list[dict]) -> dict:
    """Median over repeated runs of one session; notes vary from run to run."""
    med = lambda k: statistics.median(x[k] for x in runs)  # noqa: E731
    tps = [x["output_tokens_per_second"] for x in runs if x["output_tokens_per_second"]]
    sup = [x["sentences_supported"] for x in runs]
    return {
        "session_id": session_id,
        "repeats": len(runs),
        "speech_seconds": runs[0]["speech_seconds"],
        "total_seconds": round(med("total_seconds"), 1),
        "agents_ms": {a: round(statistics.median(x["agents_ms"][a] for x in runs), 1) for a in runs[0]["agents_ms"]},
        "output_tokens_per_second": round(statistics.median(tps), 1) if tps else None,
        "sentences_supported": med("sentences_supported"),
        "sentences_supported_range": [min(sup), max(sup)],
        "sentences_total": med("sentences_total"),
        "runs": runs,
    }


def write_review_sheet(path: Path, sequential: list[dict]) -> int:
    cols = ["session_id", "run", "section", "status", "must_confirm", "reason", "sentence", "cited",
            "clinician_verdict (real_error / wrongly_blocked / unsure)", "clinician_note"]
    n = 0
    with path.open("w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig: Excel opens Chinese correctly
        w = csv.writer(f)
        w.writerow(cols)
        for summ in sequential:
            for k, run in enumerate(summ["runs"], 1):
                for fl in run["flagged"]:
                    w.writerow([summ["session_id"], k, fl["section"], fl["status"], fl["must_confirm"],
                                fl["reason"], fl["sentence"], fl["cited"], "", ""])
                    n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rooms", type=int, default=0, help="also run this many sessions at once")
    ap.add_argument("--label", default=None)
    ap.add_argument("--repeat", type=int, default=1, help="run each session this many times (median reported)")
    args = ap.parse_args()

    tmp = tempfile.TemporaryDirectory()
    config.DB_FILE = Path(tmp.name) / "bench.db"

    llm = get_llm()
    engine = llm.label if llm else "rule-based demo"
    label = args.label or f"{platform.machine()}-{engine.replace(':', '-').replace('/', '-')}"
    sessions = [s for c in load_clients() for s in c.get("sessions", [])]

    print(f"engine: {engine}")
    sequential = []
    for s in sessions:
        runs = []
        for k in range(max(1, args.repeat)):
            res = run_one(s)
            runs.append(res)
            print(f"  {s} run {k + 1}: {res['total_seconds']}s, {res['output_tokens_per_second']} tok/s, "
                  f"{res['sentences_supported']}/{res['sentences_total']} supported")
        sequential.append(summarize(s, runs))

    concurrent = None
    if args.rooms > 1:
        jobs = [sessions[i % len(sessions)] for i in range(args.rooms)]
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.rooms) as ex:
            runs = list(ex.map(run_one, jobs))
        wall = time.perf_counter() - t0
        concurrent = {
            "rooms": args.rooms,
            "wall_seconds": round(wall, 1),
            "slowest_session_seconds": max(r["total_seconds"] for r in runs),
            "aggregate_output_tokens_per_second": round(sum(r["completion_tokens"] for r in runs) / wall, 1),
            "runs": runs,
        }
        print(f"  {args.rooms} rooms at once: all done in {concurrent['wall_seconds']}s, "
              f"{concurrent['aggregate_output_tokens_per_second']} output tok/s in total")

    report = {
        "label": label,
        "date": datetime.now().astimezone().isoformat(timespec="seconds"),
        "engine": engine,
        "llm_endpoint": llm.url if llm else None,
        # No hostname: these files go into the public repository.
        "machine": {"system": platform.platform(), "processor": platform.processor()},
        "repeats": max(1, args.repeat),
        "sequential": sequential,
        "median_session_seconds": statistics.median(r["total_seconds"] for r in sequential),
        "concurrent": concurrent,
    }
    out = ROOT / "docs" / "benchmarks"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{label}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# {label}", "", f"- Engine: `{engine}`", f"- Date: {report['date']}",
             f"- Machine: {report['machine']['system']}",
             "- Output tok/s = completion tokens ÷ model time, so it includes reading the prompt.", "",
             f"- Each session run {max(1, args.repeat)} time(s); times and counts are medians, "
             "Supported shows the range across runs in brackets.", "",
             "| Session | Speech | Total | Writer | Verifier | Output tok/s | Supported |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in sequential:
        lines.append(f"| {r['session_id']} | {r['speech_seconds']} s | {r['total_seconds']} s | "
                     f"{r['agents_ms']['writer'] / 1000:.1f} s | {r['agents_ms']['verifier'] / 1000:.1f} s | "
                     f"{r['output_tokens_per_second'] or '-'} | {r['sentences_supported']:g}/{r['sentences_total']:g}"
                     + (f" ({r['sentences_supported_range'][0]}–{r['sentences_supported_range'][1]})" if r["repeats"] > 1 else "")
                     + " |")
    if concurrent:
        lines += ["", f"**{concurrent['rooms']} rooms at once:** all notes done in {concurrent['wall_seconds']} s "
                  f"(slowest session {concurrent['slowest_session_seconds']} s), "
                  f"{concurrent['aggregate_output_tokens_per_second']} output tokens/s in total."]
    n_flagged = write_review_sheet(out / f"{label}-review.csv", sequential)
    lines += ["", f"Sentences the verifier did not pass: {n_flagged}, listed in `{label}-review.csv` for clinical review "
              "(`scripts/review_summary.py` counts real errors caught vs. correct sentences blocked)."]
    (out / f"{label}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote docs/benchmarks/{label}.json, .md and -review.csv ({n_flagged} flagged sentences)")


if __name__ == "__main__":
    main()
