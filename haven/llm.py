"""Local LLM client.

Haven only ever talks to a model server on this machine or the clinic LAN.
Any non-local endpoint is refused, so session content cannot be sent to a
cloud API by misconfiguration.
"""

from __future__ import annotations

import ipaddress
import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from . import config


class NonLocalEndpointError(ValueError):
    pass


# urllib honours HTTP(S)_PROXY and the macOS system proxy, which would send
# session text through a proxy server. Haven's requests never use one.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


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


def _parse_json(content: str) -> dict | None:
    """Parses a JSON object, tolerating a ```json fence some servers add and a
    <think> block from reasoning models (Qwen3) whose thinking was not turned off."""
    content = content.strip()
    if "</think>" in content:
        content = content.split("</think>", 1)[1].strip()
    if content.startswith("```"):
        content = content.strip("`").removeprefix("json").strip()
    try:
        out = json.loads(content)
    except json.JSONDecodeError:
        return None
    return out if isinstance(out, dict) else None


class _LocalLLM:
    name = "local"
    default_url = config.LLM_URL

    def __init__(self, url: str | None = None, model: str = config.LLM_MODEL):
        url = url or self.default_url
        assert_local(url)
        self.url = url.rstrip("/")
        self.model = model
        # One entry per call: prompt/completion tokens and wall time. Read by
        # scripts/benchmark.py for the performance data in docs/benchmarks.
        self.calls: list[dict] = []

    def _post(self, path: str, body: dict) -> dict | None:
        req = urllib.request.Request(
            f"{self.url}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with _OPENER.open(req, timeout=config.LLM_TIMEOUT) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            return None

    def _get(self, path: str) -> dict | None:
        try:
            with _OPENER.open(f"{self.url}{path}", timeout=2) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            return None

    def _messages(self, system: str, prompt: str) -> list[dict]:
        return [{"role": "system", "content": system}, {"role": "user", "content": prompt}]

    @property
    def label(self) -> str:
        return f"{self.name}:{self.model}"


class OllamaLLM(_LocalLLM):
    """Talks to Ollama's /api/chat. Any server with the same API works."""

    name = "ollama"

    def available(self) -> bool:
        tags = self._get("/api/tags")
        if tags is None:
            return False
        names = {m.get("name") for m in tags.get("models", [])}
        return self.model in names or f"{self.model}:latest" in names

    def generate_json(self, system: str, prompt: str) -> dict | None:
        t0 = time.perf_counter()
        out = self._post("/api/chat", {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
            "messages": self._messages(system, prompt),
        })
        if out is None or "message" not in out:
            return None
        self.calls.append({"prompt_tokens": out.get("prompt_eval_count", 0),
                           "completion_tokens": out.get("eval_count", 0),
                           "seconds": round(time.perf_counter() - t0, 2)})
        return _parse_json(out["message"].get("content", ""))


class OpenAICompatLLM(_LocalLLM):
    """Talks to an OpenAI-compatible /v1/chat/completions server running locally:
    vLLM (XPU), llama.cpp's llama-server (SYCL) or OpenVINO Model Server. These are
    the servers that run on the Arc Pro B70. Only the API shape is OpenAI's; the
    endpoint is still checked to be on this machine or the clinic LAN."""

    name = "openai-compat"
    default_url = "http://127.0.0.1:8000" if "HAVEN_LLM_URL" not in os.environ else config.LLM_URL

    def available(self) -> bool:
        models = self._get("/v1/models")
        if models is None:
            return False
        ids = {m.get("id") for m in models.get("data", [])}
        return not ids or self.model in ids

    def generate_json(self, system: str, prompt: str) -> dict | None:
        t0 = time.perf_counter()
        out = self._post("/v1/chat/completions", {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            # Qwen3 thinks out loud by default; vLLM and llama-server pass this to the chat template.
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": self._messages(system, prompt),
        })
        try:
            content = out["choices"][0]["message"]["content"]
        except (TypeError, KeyError, IndexError):
            return None
        usage = out.get("usage") or {}
        self.calls.append({"prompt_tokens": usage.get("prompt_tokens", 0),
                           "completion_tokens": usage.get("completion_tokens", 0),
                           "seconds": round(time.perf_counter() - t0, 2)})
        return _parse_json(content or "")


BACKENDS = {"ollama": OllamaLLM, "openai": OpenAICompatLLM}


def get_llm() -> _LocalLLM | None:
    """Returns a local LLM, or None to use the rule-based demo engine.

    HAVEN_LLM: "demo" (no model), "ollama", "openai" (vLLM / llama-server / OVMS),
    or "auto" (Ollama if its model is there, otherwise the demo engine)."""
    if config.LLM_BACKEND == "demo":
        return None
    llm = BACKENDS.get(config.LLM_BACKEND, OllamaLLM)()
    if llm.available():
        return llm
    if config.LLM_BACKEND in BACKENDS:
        raise RuntimeError(f"HAVEN_LLM={config.LLM_BACKEND} but model {config.LLM_MODEL} is not reachable at {llm.url}")
    return None
