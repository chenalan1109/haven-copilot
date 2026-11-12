"""Files that hold session content are readable by the therapist's account only.

Not encryption: another account on the machine cannot read them, but anyone
with the disk, or with this account, can. Full-disk encryption (FileVault,
LUKS) is still needed; SQLCipher is not built yet.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import config

PRIVATE_DIR, PRIVATE_FILE = 0o700, 0o600


def write_private(path: Path, text: str) -> None:
    """Writes beside the target with mode 0600 and renames, so a reader never
    sees half a file and the content is never world-readable, even briefly."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_FILE)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, PRIVATE_FILE)  # the file may have existed with wider permissions
    tmp.replace(path)


def temp_dir() -> Path:
    """Where an upload waits for transcription: inside the data directory, 0700,
    not the system temp directory shared with other programs."""
    path = config.DATA_DIR / "tmp"
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, PRIVATE_DIR)
    return path


def clear_temp() -> int:
    """Deletes recordings left behind by a crash or a power cut. Run at start-up."""
    removed = 0
    for leftover in temp_dir().iterdir():
        if leftover.is_file():
            leftover.unlink()
            removed += 1
    return removed


def secure_data_dir() -> None:
    """Tightens the data directory and everything Haven keeps in it. Run at start-up."""
    config.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    for directory in (config.DATA_DIR, config.SESSIONS_DIR, config.DATA_DIR / "audio"):
        if directory.is_dir():
            os.chmod(directory, PRIVATE_DIR)
    files = [config.CLIENTS_FILE, *config.DATA_DIR.glob("*.db*"), *config.SESSIONS_DIR.glob("*.json")]
    for file in files:
        if file.is_file():
            os.chmod(file, PRIVATE_FILE)
