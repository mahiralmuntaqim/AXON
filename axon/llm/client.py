"""Frozen-model wrapper — the single call site for every LLM interaction (SEGMENT 9).

Hard rule 1: the model is FROZEN. Nothing in this file (or anywhere) trains, fine-tunes, or
updates weights. This wrapper only *calls* a model for inference and parses its reply. Putting
every call here is what makes AXON model-agnostic (a core claim of the paper): swap the backend
and nothing else changes.

Two backends ship:

* :class:`MockLLM` — deterministic, offline, used by every unit test. No network.
* :class:`FrozenRemoteLLM` — a thin placeholder (STUB) for a real inference endpoint. It does
  NOT include any training code and never will.

Rules enforced here:
* Raw model text never becomes a graph write directly — callers must go through
  :meth:`LLMClient.complete_json`, which validates JSON, retries, then fails the step cleanly.
* Retries and timeouts are configured once (from config), not scattered across modules.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol


class LLMError(RuntimeError):
    """Raised when the model cannot be reached or its output cannot be parsed after retries."""


class LLMBackend(Protocol):
    """Anything that turns a prompt into text. Inference only — no training."""

    def generate(self, prompt: str, *, temperature: float, timeout_s: float) -> str: ...


@dataclass
class LLMConfig:
    model: str = "mock"
    temperature: float = 0.0
    timeout_s: float = 60.0
    retries: int = 3
    seed: int = 0


# --------------------------------------------------------------------------------------------
# JSON extraction helpers
# --------------------------------------------------------------------------------------------
_JSON_BLOCK = re.compile(r"\{.*\}|\[.*\]", re.DOTALL)


def extract_json(text: str) -> Any:
    """Pull the first JSON object/array out of a model reply. Raises on failure."""
    text = text.strip()
    # Strip ```json ... ``` fences if present.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_BLOCK.search(text)
        if not m:
            raise LLMError(f"no JSON found in model reply: {text[:200]!r}")
        return json.loads(m.group(0))


# --------------------------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------------------------
class MockLLM(LLMBackend):
    """Deterministic offline backend for tests.

    It is driven by a routing table: a list of (predicate, responder) pairs. The first
    predicate that matches the prompt wins, and its responder returns the reply string. This
    lets a test say exactly what the "model" should answer without any network or randomness.
    """

    def __init__(
        self,
        routes: Optional[list[tuple[Callable[[str], bool], Callable[[str], str]]]] = None,
        default: str = "{}",
    ) -> None:
        self.routes = routes or []
        self.default = default
        self.calls: list[str] = []  # recorded prompts, for assertions

    def generate(self, prompt: str, *, temperature: float, timeout_s: float) -> str:
        self.calls.append(prompt)
        for predicate, responder in self.routes:
            if predicate(prompt):
                return responder(prompt)
        return self.default


class FrozenRemoteLLM(LLMBackend):
    """STUB: a frozen remote inference endpoint.

    Intentionally not wired to a provider here. Fill ``_call_endpoint`` with an inference-only
    HTTP call to your chosen model. There is deliberately no training/fine-tuning path.
    """

    def __init__(self, model: str) -> None:
        self.model = model

    def generate(self, prompt: str, *, temperature: float, timeout_s: float) -> str:
        raise NotImplementedError(
            "STUB: FrozenRemoteLLM.generate is not wired to a provider. Supply an "
            "inference-only backend. (No training code belongs here — the model stays frozen.)"
        )


# --------------------------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------------------------
class LLMClient:
    """The one wrapper every module uses. Handles retries, timeout, and JSON validation."""

    def __init__(self, backend: LLMBackend, config: LLMConfig) -> None:
        self.backend = backend
        self.config = config

    @classmethod
    def from_config(cls, cfg: dict[str, Any], *, backend: Optional[LLMBackend] = None) -> "LLMClient":
        llm_cfg = LLMConfig(
            model=cfg.get("model", "mock"),
            temperature=float(cfg.get("temperature", 0.0)),
            timeout_s=float(cfg.get("timeout_s", 60.0)),
            retries=int(cfg.get("retries", cfg.get("llm_retries", 3))),
            seed=int(cfg.get("seed", 0)),
        )
        if backend is None:
            # Flexible provider selection (openai/openrouter/anthropic/custom/mock).
            from .backends import build_backend

            backend = build_backend(cfg)
        return cls(backend, llm_cfg)

    def complete_text(self, prompt: str) -> str:
        """Raw text completion with retry. Prefer :meth:`complete_json` for anything structured."""
        last: Optional[Exception] = None
        for _ in range(max(1, self.config.retries)):
            try:
                return self.backend.generate(
                    prompt, temperature=self.config.temperature, timeout_s=self.config.timeout_s
                )
            except Exception as exc:  # noqa: BLE001 — retry any backend failure/timeout
                last = exc
        raise LLMError(f"LLM call failed after {self.config.retries} retries: {last}")

    def complete_json(self, prompt: str, *, validate: Optional[Callable[[Any], bool]] = None) -> Any:
        """Completion that MUST parse as JSON (and optionally pass a validator).

        Retries on both call failure and parse/validation failure. Raising :class:`LLMError`
        here lets the caller skip the step cleanly instead of writing malformed data to a graph.
        """
        last: Optional[Exception] = None
        for _ in range(max(1, self.config.retries)):
            try:
                raw = self.backend.generate(
                    prompt, temperature=self.config.temperature, timeout_s=self.config.timeout_s
                )
                parsed = extract_json(raw)
                if validate is not None and not validate(parsed):
                    raise LLMError("parsed JSON failed validation")
                return parsed
            except Exception as exc:  # noqa: BLE001
                last = exc
        raise LLMError(f"LLM JSON call failed after {self.config.retries} retries: {last}")
