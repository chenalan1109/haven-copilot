"""The clinical review sheet: flagged sentences out, three numbers back."""

import csv
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ["HAVEN_LLM"] = "demo"

ROOT = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bench = load("benchmark")
review = load("review_summary")

RESULT = {
    "transcript": [
        {"id": 1, "speaker": "client", "text": "我這週睡得很差。"},
        {"id": 2, "speaker": "therapist", "text": "下次我們談談睡前的習慣。"},
    ],
    "note": {"sections": {
        "S": [
            {"text": "個案表示這週睡得很差。", "evidence": [1], "status": "supported", "reason": "", "source": "transcript"},
            {"text": "個案表示每天只睡三小時。", "evidence": [1], "status": "unsupported",
             "reason": "數字「三」不在引用的逐字稿中", "source": "transcript"},
        ],
        "O": [{"text": "PHQ-9 12 分。", "evidence": [], "status": "supported", "reason": "", "source": "measure"}],
        "P": [{"text": "下週討論睡前習慣。", "evidence": [2], "status": "weak", "reason": "與引用段落的用字重疊少，請確認",
               "source": "transcript", "must_confirm": False}],
    }},
}


def run(supported, flagged):
    return {"session_id": "C9", "speech_seconds": 10, "total_seconds": 1.0, "agents_ms": {"writer": 1, "verifier": 1},
            "output_tokens_per_second": 20.0, "sentences_supported": supported, "sentences_total": 3,
            "flagged": flagged}


class ReviewSheetTest(unittest.TestCase):
    def test_flagged_skips_supported_and_scores(self):
        fl = bench.flagged_sentences(RESULT)
        self.assertEqual([f["sentence"] for f in fl], ["個案表示每天只睡三小時。", "下週討論睡前習慣。"])
        self.assertIn("client: 我這週睡得很差", fl[0]["cited"])

    def test_summarize_takes_median_and_range(self):
        s = bench.summarize("C9", [run(1, []), run(3, []), run(2, [])])
        self.assertEqual(s["sentences_supported"], 2)
        self.assertEqual(s["sentences_supported_range"], [1, 3])
        self.assertEqual(s["repeats"], 3)

    def test_sheet_round_trip(self):
        fl = bench.flagged_sentences(RESULT)
        summ = bench.summarize("C9", [run(1, fl), run(3, [])])
        with tempfile.TemporaryDirectory() as d:
            sheet = Path(d) / "x-review.csv"
            self.assertEqual(bench.write_review_sheet(sheet, [summ]), 2)
            (Path(d) / "x.json").write_text(json.dumps({"sequential": [summ]}), encoding="utf-8")
            rows = list(csv.DictReader(sheet.open(encoding="utf-8-sig")))
            rows[0][review.VERDICT_COL] = "真錯"
            rows[1][review.VERDICT_COL] = "wrongly_blocked"
            with sheet.open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=rows[0].keys())
                w.writeheader()
                w.writerows(rows)
            r = review.summarize(sheet)["C9"]
        self.assertEqual((r["supported"], r["real_error"], r["wrongly_blocked"], r["unmarked"]), (4, 1, 1, 0))
        self.assertEqual(r["clicks_per_note_median"], 1)  # run 1 had 2 flags, run 2 had 0


if __name__ == "__main__":
    unittest.main()
