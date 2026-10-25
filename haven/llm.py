"""Local LLM client.

Haven only ever talks to a model server on this machine or the clinic LAN.
Any non-local endpoint is refused, so session content cannot be sent to a
cloud API by misconfiguration.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

from . import config


class NonLocalEndpointError(ValueError):
    pass


def assert_local(url: str) -> None:
    host = urlparse(url).hostname or ""
    if host in ("localhost",) or host.endswith(".local"):
        return
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise NonLocalEndpointError(f"LLM endpoint must be local, got {host!r}")
    if not (ip.is_loopback or ip.is_private):
        raise NonLocalEndpointError(f"LLM endpoint must be local, got {host!r}")


class OllamaLLM:
    """Talks to Ollama's /api/chat. Any server with the same API works."""

    name = "ollama"

    def __init__(self, url: str = config.LLM_URL, model: str = config.LLM_MODEL):
        assert_local(url)
        self.url = url.rstrip("/")
        self.model = model

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=2) as r:
                tags = json.load(r)
        except (urllib.error.URLError, TimeoutError, OSError):
            return False
        names = {m.get("name") for m in tags.get("models", [])}
        return self.model in names or f"{self.model}:latest" in names

    def generate_json(self, system: str, prompt: str) -> dict | None:
        body = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        req = urllib.request.Request(
            f"{self.url}/api/chat",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=config.LLM_TIMEOUT) as r:
                content = json.load(r)["message"]["content"]
            return json.loads(content)
        except (urllib.error.URLError, TimeoutError, OSError, KeyError, json.JSONDecodeError):
            return None

    @property
    def label(self) -> str:
        return f"{self.name}:{self.model}"


def get_llm() -> OllamaLLM | None:
    """Returns a local LLM, or None to use the rule-based demo engine."""
    if config.LLM_BACKEND == "demo":
        return None
    llm = OllamaLLM()
    if llm.available():
        return llm
    if config.LLM_BACKEND == "ollama":
        raise RuntimeError(f"HAVEN_LLM=ollama but model {config.LLM_MODEL} is not reachable at {config.LLM_URL}")
    return None
