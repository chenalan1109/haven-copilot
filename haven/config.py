"""Runtime configuration, read from environment variables."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("HAVEN_DATA_DIR", ROOT / "data"))
SESSIONS_DIR = DATA_DIR / "sessions"
CLIENTS_FILE = DATA_DIR / "clients.json"
DB_FILE = DATA_DIR / "haven.db"
WEB_DIR = ROOT / "web"

# "demo" runs the rule-based engine with no model; "ollama" uses a local LLM.
LLM_BACKEND = os.environ.get("HAVEN_LLM", "auto")
LLM_URL = os.environ.get("HAVEN_LLM_URL", "http://127.0.0.1:11434")
LLM_MODEL = os.environ.get("HAVEN_MODEL", "qwen2.5:7b")
LLM_TIMEOUT = float(os.environ.get("HAVEN_LLM_TIMEOUT", "180"))

ASR_MODEL = os.environ.get("HAVEN_ASR_MODEL", "small")

HOST = os.environ.get("HAVEN_HOST", "127.0.0.1")
PORT = int(os.environ.get("HAVEN_PORT", "8765"))
