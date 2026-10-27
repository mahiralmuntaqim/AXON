"""Flexible LLM API layer tests (SEGMENT 9) — all offline, no network."""

import pytest

from axon.llm.backends import (
    AnthropicBackend,
    CallableBackend,
    OpenAICompatBackend,
    build_backend,
    register_backend,
)
from axon.llm.client import LLMClient, LLMError, MockLLM


def test_callable_backend_wraps_a_function():
    be = CallableBackend(lambda p: f"echo:{p}")
    client = LLMClient(be, LLMClient.from_config({"provider": "mock"}).config)
    assert client.complete_text("hi") == "echo:hi"


def test_build_backend_defaults_to_mock():
    assert isinstance(build_backend({"provider": "mock"}), MockLLM)
    assert isinstance(build_backend({}), MockLLM)  # no provider -> mock
    assert isinstance(build_backend({"model": "mock", "provider": "openai"}), MockLLM)


def test_build_backend_openai_and_openrouter_and_anthropic():
    oa = build_backend({"provider": "openai", "model": "gpt-4o-mini"})
    assert isinstance(oa, OpenAICompatBackend)
    assert oa.base_url == "https://api.openai.com/v1"

    orr = build_backend({"provider": "openrouter", "model": "anthropic/claude-3.7-sonnet"})
    assert isinstance(orr, OpenAICompatBackend)
    assert orr.base_url == "https://openrouter.ai/api/v1"
    assert orr.api_key_env == "OPENROUTER_API_KEY"

    an = build_backend({"provider": "anthropic", "model": "claude-3-7-sonnet-latest"})
    assert isinstance(an, AnthropicBackend)


def test_base_url_implies_openai_compat():
    be = build_backend({"model": "llama3.1", "base_url": "http://localhost:11434/v1", "api_key_env": None})
    assert isinstance(be, OpenAICompatBackend)
    assert be.base_url == "http://localhost:11434/v1"


def test_unknown_provider_raises():
    with pytest.raises(LLMError):
        build_backend({"provider": "nope", "model": "x"})


def test_register_custom_backend():
    register_backend("myprov", lambda cfg: CallableBackend(lambda p: "custom"))
    be = build_backend({"provider": "myprov", "model": "whatever"})
    assert be.generate("hi", temperature=0.0, timeout_s=1.0) == "custom"


def test_response_parsers():
    assert OpenAICompatBackend._parse_response(
        {"choices": [{"message": {"content": "hello"}}]}
    ) == "hello"
    assert AnthropicBackend._parse_response(
        {"content": [{"type": "text", "text": "hi"}]}
    ) == "hi"
    with pytest.raises(LLMError):
        OpenAICompatBackend._parse_response({"bad": 1})


def test_missing_api_key_fails_loudly_before_network():
    be = OpenAICompatBackend(model="gpt-4o-mini", api_key_env="AXON_DEFINITELY_UNSET_KEY_123")
    with pytest.raises(LLMError, match="not set"):
        be.generate("hi", temperature=0.0, timeout_s=1.0)


def test_from_config_builds_mock_by_default():
    client = LLMClient.from_config({"provider": "mock", "model": "mock"})
    assert isinstance(client.backend, MockLLM)
