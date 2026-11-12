#!/usr/bin/env python3
"""Git pre-commit check: keeps real session content out of the repository.

Refuses a commit that stages
  - a database file (*.db, *.db-journal, *.db-wal, *.db-shm),
  - a recording (anything under data/audio/ except .gitkeep, or an audio file),
  - a transcript marked "simulated": false, or a JSON file under data/sessions/
    that cannot be read as a simulated transcript.

Install it in a clone (it is an example; nothing installs it for you):

    ln -s ../../scripts/pre_commit_check.py .git/hooks/pre-commit

It reads the staged content, not the working tree. It is a guard against a
slip, not a control: `git commit --no-verify` skips it.
"""

import json
import re
import subprocess
import sys

DB = re.compile(r"\.db(-journal|-wal|-shm)?$")
AUDIO = re.compile(r"\.(wav|mp3|m4a|flac|ogg|opus|webm)$", re.IGNORECASE)


def staged() -> list[str]:
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"], capture_output=True, check=True).stdout
    return [p for p in out.decode().split("\0") if p]


def problem(path: str) -> str:
    if DB.search(path):
        return "database file"
    if AUDIO.search(path) or (path.startswith("data/audio/") and not path.endswith(".gitkeep")):
        return "recording"
    if path.endswith(".json") and (path.startswith("data/sessions/") or "/sessions/" in path):
        blob = subprocess.run(["git", "show", f":{path}"], capture_output=True).stdout
        try:
            data = json.loads(blob)
        except (ValueError, UnicodeDecodeError):
            return "session file that is not readable JSON"
        if not isinstance(data, dict) or data.get("simulated") is not True:
            return 'transcript without "simulated": true'
    return ""


def main() -> int:
    bad = [(p, why) for p in staged() if (why := problem(p))]
    for path, why in bad:
        print(f"pre-commit: refusing {path} ({why})", file=sys.stderr)
    if bad:
        print("pre-commit: session content must not be committed. Unstage the file(s) with `git restore --staged <file>`.", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
