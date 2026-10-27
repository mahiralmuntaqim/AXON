"""LLM client tests (SEGMENT 9): parsing, retries, validation, and the frozen-model contract."""

import pytest

from axon.llm.client import (
    FrozenRemoteLLM,
    LLMClient,
    LLMConfig,
    LLMError,
    MockLLM,
    extract_json,
)


def test_extract_json_handles_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('here you go: {"b": 2} thanks') == {"b": 2}


def test_extract_json_raises_when_absent():
    with pytest.raises(LLMError):
        extract_json("no json at all")


def test_complete_json_validates_and_retries():
    attempts = {"n": 0}

    def responder(_p):
        attempts["n"] += 1
        return "garbage" if attempts["n"] == 1 else '{"keep": []}'

    backend = MockLLM(routes=[(lambda p: True, responder)])
    client = LLMClient(backend, LLMConfig(retries=3))
    out = client.complete_json(
        "prompt", validate=lambda d: isinstance(d, dict) and "keep" in d
    )
    assert out == {"keep": []}
    assert attempts["n"] == 2  # retried once after the garbage reply


def test_complete_json_fails_cleanly_after_retries():
    backend = MockLLM(routes=[(lambda p: True, lambda p: "not json")])
    client = LLMClient(backend, LLMConfig(retries=2))
    with pytest.raises(LLMError):
        client.complete_json("prompt")


def test_frozen_remote_backend_has_no_training_path_and_is_a_stub():
    # The frozen remote backend is inference-only and intentionally unimplemented here.
    backend = FrozenRemoteLLM("some-model")
    with pytest.raises(NotImplementedError):
        backend.generate("hi", temperature=0.0, timeout_s=1.0)
