"""Prints a simulated session as a two-person script for actors to record.

    python3 scripts/print_script.py C001-S04
"""

import json
import sys
from pathlib import Path

ROLE = {"therapist": "心理師", "client": "個案"}

session = json.loads((Path(__file__).resolve().parent.parent / "data" / "sessions" / f"{sys.argv[1]}.json").read_text(encoding="utf-8"))
print(f"# {session['session_id']}（模擬會談，第 {session['session_no']} 次）\n")
for seg in session["segments"]:
    print(f"{ROLE.get(seg['speaker'], '說話者')}：{seg['text']}\n")
