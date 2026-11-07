"""Runtime configuration, read from environment variables."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("HAVEN_DATA_DIR", ROOT / "data"))
SESSIONS_DIR = DATA_DIR / "sessions"
CLIENTS_FILE = DATA_DIR / "clients.json"
DB_FILE = DATA_DIR / "haven.db"
WEB_DIR = ROOT / "web"

# "demo" runs the rule-based engine with no model; "ollama" uses Ollama; "openai" uses a
# local OpenAI-compatible server (vLLM, llama-server, OpenVINO Model Server) such as on the B70.
LLM_BACKEND = os.environ.get("HAVEN_LLM", "auto")
LLM_URL = os.environ.get("HAVEN_LLM_URL", "http://127.0.0.1:11434")
LLM_MODEL = os.environ.get("HAVEN_MODEL", "qwen2.5:7b")
LLM_TIMEOUT = float(os.environ.get("HAVEN_LLM_TIMEOUT", "180"))
# A 50-minute recording takes far longer than one note.
ASR_TIMEOUT = float(os.environ.get("HAVEN_ASR_TIMEOUT", "900"))

# "faster-whisper" runs Whisper in this process (CPU); "openai" sends the audio to a local
# server with the OpenAI transcription API, such as vLLM serving Whisper on the B70.
ASR_BACKEND = os.environ.get("HAVEN_ASR", "faster-whisper")
ASR_URL = os.environ.get("HAVEN_ASR_URL", "http://127.0.0.1:8001")
ASR_MODEL = os.environ.get("HAVEN_ASR_MODEL", "small" if ASR_BACKEND == "faster-whisper" else "whisper")

HOST = os.environ.get("HAVEN_HOST", "127.0.0.1")
PORT = int(os.environ.get("HAVEN_PORT", "8765"))
