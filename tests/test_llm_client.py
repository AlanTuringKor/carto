"""Tests for LLM client protocol and mock conformance."""

from __future__ import annotations

from pydantic import BaseModel, Field

from carto.llm.client import LLMClient, LLMError


class SampleResponse(BaseModel):
    """Test response model."""
    name: str
    score: float = 0.0
    tags: list[str] = Field(default_factory=list)


class MockLLMClient:
    """A mock LLM client that returns canned JSON responses."""

    def __init__(self, response_json: str) -> None:
        self._response_json = response_json
        self._last_prompt: str | None = None

    @property
    def model_name(self) -> str:
        return "mock-model"

    def complete(self, prompt: str, response_model: type) -> object:
        self._last_prompt = prompt
        return response_model.model_validate_json(self._response_json)


class FailingLLMClient:
    """A mock LLM client that always raises LLMError."""

    @property
    def model_name(self) -> str:
        return "failing-model"

    def complete(self, prompt: str, response_model: type) -> object:
        raise LLMError("failing-model", "Simulated failure")


class TestLLMClientProtocol:
    def test_mock_satisfies_protocol(self) -> None:
        client = MockLLMClient('{"name": "test"}')
        assert isinstance(client, LLMClient)

    def test_mock_complete(self) -> None:
        client = MockLLMClient('{"name": "page", "score": 0.9, "tags": ["auth"]}')
        result = client.complete("test prompt", SampleResponse)
        assert isinstance(result, SampleResponse)
        assert result.name == "page"
        assert result.score == 0.9
        assert result.tags == ["auth"]
        assert client._last_prompt == "test prompt"

    def test_failing_client_raises(self) -> None:
        client = FailingLLMClient()
        try:
            client.complete("prompt", SampleResponse)
            assert False, "Should have raised"
        except LLMError as exc:
            assert "Simulated failure" in str(exc)


class TestLLMError:
    def test_error_message(self) -> None:
        err = LLMError("gpt-4o", "Rate limited")
        assert "gpt-4o" in str(err)
        assert "Rate limited" in str(err)
        assert err.model == "gpt-4o"


class TestCreateLLMClient:
    def test_create_openai_client(self):
        from carto.llm.client import OpenAIClient, create_llm_client
        client = create_llm_client(provider="openai", model="gpt-4", api_key="sk-test", base_url="https://api.openai.com")
        assert isinstance(client, OpenAIClient)
        assert client.model_name == "gpt-4"
        assert str(client._client.base_url).rstrip('/') == "https://api.openai.com"

    def test_create_anthropic_client(self):
        from carto.llm.client import AnthropicClient, create_llm_client
        client = create_llm_client(provider="anthropic", api_key="sk-ant", base_url="https://api.anthropic.com")
        assert isinstance(client, AnthropicClient)
        assert "claude" in client.model_name
        assert str(client._client.base_url).rstrip('/') == "https://api.anthropic.com"

    def test_create_gemini_client(self):
        from carto.llm.client import GeminiClient, create_llm_client
        client = create_llm_client(provider="gemini", api_key="AIzaSy", model="gemini-1.5-pro")
        assert isinstance(client, GeminiClient)
        assert client.model_name == "gemini-1.5-pro"

    def test_create_unknown_provider(self):
        import pytest
        from carto.llm.client import create_llm_client
        with pytest.raises(ValueError, match="Unknown LLM provider: unknown"):
            create_llm_client(provider="unknown")

    def test_create_ignores_case(self):
        from carto.llm.client import OpenAIClient, create_llm_client
        client = create_llm_client(provider="OpenAI", api_key="sk-123")
        assert isinstance(client, OpenAIClient)
