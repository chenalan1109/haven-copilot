"""Processes every demo session ahead of time, so the UI opens instantly while recording.

    python3 scripts/prepare_demo.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from haven import store  # noqa: E402
from haven.orchestrator import Orchestrator, load_clients  # noqa: E402

orch = Orchestrator()
print(f"engine: {orch.engine}")
for client in load_clients():
    for session_id in client.get("sessions", []):
        t0 = time.perf_counter()
        try:
            r = orch.process_session(session_id)
        except store.AlreadySignedError:
            print(f"{session_id}: already signed, left as it is")
            continue
        v = r["verification"]
        print(f"{session_id}: {time.perf_counter() - t0:.1f}s, {v['supported']}/{v['total']} supported, risk={r['risk']['level']}")
