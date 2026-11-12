"""Prints a simulated session as a two-person script, to be read aloud for a speech-to-text test.

So far only C001-S04 lines #10-#12 have been recorded this way (docs/asr-eval).

    python3 scripts/print_script.py C001-S04
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from haven import config  # noqa: E402  (honours HAVEN_DATA_DIR)

ROLE = {"therapist": "心理師", "client": "個案"}

session = json.loads((config.SESSIONS_DIR / f"{sys.argv[1]}.json").read_text(encoding="utf-8"))
print(f"# {session['session_id']}（模擬會談，第 {session['session_no']} 次）\n")
for seg in session["segments"]:
    print(f"{ROLE.get(seg['speaker'], '說話者')}：{seg['text']}\n")
