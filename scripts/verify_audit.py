"""Checks the audit log's hash chain and prints the head hash.

    python3 scripts/verify_audit.py            # the database in HAVEN_DATA_DIR (default data/)
    python3 scripts/verify_audit.py path.db

Each audit row stores the hash of the row before it. A row that was changed,
inserted or deleted in the middle breaks the chain, and this reports the first
row that does not fit. It cannot detect a chain rebuilt from scratch or rows cut
off the end: for that, compare the head hash printed here with a copy written
down somewhere else (on paper, or in the clinic's own records).

Exit status: 0 when the chain verifies, 1 when it does not.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from haven import config, store  # noqa: E402

if len(sys.argv) > 1:
    config.DB_FILE = Path(sys.argv[1]).resolve()
    config.DATA_DIR = config.DB_FILE.parent
if not config.DB_FILE.exists():
    sys.exit(f"no database at {config.DB_FILE}")
result = store.verify_audit()
if result["ok"]:
    print(f"audit log OK: {result['rows']} rows, head {result['head']}")
else:
    print(f"audit log DOES NOT VERIFY: first bad row id {result['first_bad_id']} of {result['rows']} rows")
sys.exit(0 if result["ok"] else 1)
