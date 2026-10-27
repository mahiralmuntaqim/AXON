"""Flexible LLM API layer — plug in ANY inference provider (SEGMENT 9).

Every model call in AXON goes through one wrapper (``LLMClient``); this module is where you
choose *what* that wrapper talks to. The model stays **frozen** — these backends only call an
inference endpoint, never train or update weights.

Pick a backend from config (``llm.provider``) or register your own:

* ``mock``          — deterministic offline backend (tests).
* ``openai`` / ``openai-compat`` — any OpenAI-compatible Chat Completions endpoint. Covers
  OpenAI, OpenRouter, Together, Groq, Fireworks, and local servers (Ollama ``/v1``, vLLM,
  LM Studio, llama.cpp) — just set ``base_url`` and ``api_key_env``.
* ``anthropic``     — Anthropic Messages API.
* ``<your name>``   — anything you register with :func:`register_backend`, or a plain Python
  function wrapped by :class:`CallableBackend`.

Only the Python standard library is used (``urllib``), so no extra dependency is required.

**Keys are read from environment variables named in config (``api_key_env``) — never hard-code a
key in the config or the repo.**
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from .client import LLMBackend, LLMError


# --------------------------------------------------------------------------------------------
# Custom / callable backends + a registry
# --------------------------------------------------------------------------------------------
class CallableBackend(LLMBackend):
    """Wrap any ``fn(prompt: str) -> str`` as an LLM backend.

    The simplest way to plug in a provider AXON doesn't ship: write a function that takes a
    prompt and returns the model's text, and hand it here (or register it).
    """

    def __init__(self, fn: Callable[[str], str]) -> None:
        self.fn = fn

    def generate(self, prompt: str, *, temperature: float, timeout_s: float) -> str:
        return self.fn(prompt)


# name -> factory(llm_cfg: dict) -> LLMBackend
BACKEND_REGISTRY: dict[str, Callable[[dict], LLMBackend]] = {}


def register_backend(name: str, factory: Callable[[dict], LLMBackend]) -> None:
    """Register a custom backend factory under ``name`` so ``llm.provider: <name>`` selects it."""
    BACKEND_REGISTRY[name.strip().lower()] = factory


# --------------------------------------------------------------------------------------------
# HTTP helper (stdlib only)
# --------------------------------------------------------------------------------------------
def _post_json(url: str, payload: dict, headers: dict, timeout_s: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # surface the body for debugging
        body = exc.read().decode("utf-8", "replace")[:500]
        raise LLMError(f"HTTP {exc.code} from {url}: {body}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LLMError(f"request to {url} failed: {exc}") from exc


def _resolve_key(api_key_env: Optional[str]) -> Optional[str]:
    if not api_key_env:
        return None
    key = os.environ.get(api_key_env)
    if not key:
        raise LLMError(
            f"API key env var {api_key_env!r} is not set; export it before running "
            "(keys are never stored in config)"
        )
    return key


# --------------------------------------------------------------------------------------------
# OpenAI-compatible Chat Completions
# --------------------------------------------------------------------------------------------
class OpenAICompatBackend(LLMBackend):
    """Any OpenAI-compatible ``/chat/completions`` endpoint (inference only)."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        api_key_env: Optional[str] = "OPENAI_API_KEY",
        endpoint_path: str = "/chat/completions",
        max_tokens: int = 1024,
        extra_headers: Optional[dict] = None,
        system: Optional[str] = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.endpoint_path = endpoint_path if endpoint_path.startswith("/") else "/" + endpoint_path
        self.max_tokens = max_tokens
        self.extra_headers = dict(extra_headers or {})
        self.system = system

    def generate(self, prompt: str, *, temperature: float, timeout_s: float) -> str:
        messages = []
        if self.system:
            messages.append({"role": "system", "content": self.system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self.max_tokens,
        }
        headers = dict(self.extra_headers)
        key = _resolve_key(self.api_key_env)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        resp = _post_json(self.base_url + self.endpoint_path, payload, headers, timeout_s)
        return self._parse_response(resp)

    @staticmethod
    def _parse_response(resp: dict) -> str:
        try:
            return resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected OpenAI-compatible response shape: {str(resp)[:300]}") from exc


# --------------------------------------------------------------------------------------------
# Anthropic Messages API
# --------------------------------------------------------------------------------------------
class AnthropicBackend(LLMBackend):
    """Anthropic Messages API (inference only)."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str = "https://api.anthropic.com",
        api_key_env: str = "ANTHROPIC_API_KEY",
        version: str = "2023-06-01",
        max_tokens: int = 1024,
        extra_headers: Optional[dict] = None,
        system: Optional[str] = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.version = version
        self.max_tokens = max_tokens
        self.extra_headers = dict(extra_headers or {})
        self.system = system

    def generate(self, prompt: str, *, temperature: float, timeout_s: float) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self.system:
            payload["system"] = self.system
        headers = dict(self.extra_headers)
        headers["x-api-key"] = _resolve_key(self.api_key_env) or ""
        headers["anthropic-version"] = self.version
        resp = _post_json(self.base_url + "/v1/messages", payload, headers, timeout_s)
        return self._parse_response(resp)

    @staticmethod
    def _parse_response(resp: dict) -> str:
        try:
            parts = resp["content"]
            return "".join(p.get("text", "") for p in parts if p.get("type") == "text") or parts[0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected Anthropic response shape: {str(resp)[:300]}") from exc


# --------------------------------------------------------------------------------------------
# Selection from config
# --------------------------------------------------------------------------------------------
def build_backend(llm_cfg: dict) -> LLMBackend:
    """Construct a backend from the ``llm`` config block.

    ``provider`` chooses the backend. If absent, falls back to ``mock`` unless a ``base_url`` is
    given (then ``openai-compat``). Register custom providers with :func:`register_backend`.
    """
    from .client import MockLLM  # local import to avoid a cycle at module load

    provider = str(llm_cfg.get("provider") or ("openai-compat" if llm_cfg.get("base_url") else "mock")).lower()
    model = llm_cfg.get("model", "mock")

    if provider in ("mock", "") or model == "mock":
        return MockLLM()

    if provider in BACKEND_REGISTRY:
        return BACKEND_REGISTRY[provider](llm_cfg)

    if provider == "openrouter":
        # OpenRouter is OpenAI-compatible; preset its base_url + key env (matches the
        # existing agent-pentest OpenRouterClient setup: OPENROUTER_API_KEY).
        return OpenAICompatBackend(
            model=model if model != "mock" else "anthropic/claude-3.7-sonnet",
            base_url=llm_cfg.get("base_url", "https://openrouter.ai/api/v1"),
            api_key_env=llm_cfg.get("api_key_env", "OPENROUTER_API_KEY"),
            endpoint_path=llm_cfg.get("endpoint_path", "/chat/completions"),
            max_tokens=int(llm_cfg.get("max_tokens", 1024)),
            extra_headers=llm_cfg.get("extra_headers"),
            system=llm_cfg.get("system"),
        )

    if provider in ("openai", "openai-compat", "openai_compatible"):
        return OpenAICompatBackend(
            model=model,
            base_url=llm_cfg.get("base_url", "https://api.openai.com/v1"),
            api_key_env=llm_cfg.get("api_key_env", "OPENAI_API_KEY"),
            endpoint_path=llm_cfg.get("endpoint_path", "/chat/completions"),
            max_tokens=int(llm_cfg.get("max_tokens", 1024)),
            extra_headers=llm_cfg.get("extra_headers"),
            system=llm_cfg.get("system"),
        )

    if provider == "anthropic":
        return AnthropicBackend(
            model=model,
            base_url=llm_cfg.get("base_url", "https://api.anthropic.com"),
            api_key_env=llm_cfg.get("api_key_env", "ANTHROPIC_API_KEY"),
            version=llm_cfg.get("version", "2023-06-01"),
            max_tokens=int(llm_cfg.get("max_tokens", 1024)),
            extra_headers=llm_cfg.get("extra_headers"),
            system=llm_cfg.get("system"),
        )

    raise LLMError(
        f"unknown llm provider {provider!r}; use mock/openai/openai-compat/anthropic or "
        f"register_backend({provider!r}, ...). Registered: {sorted(BACKEND_REGISTRY)}"
    )
