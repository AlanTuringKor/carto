"""
LLM client abstraction for Carto.

Provides a protocol-based interface so agents are decoupled from any
specific LLM provider.  The default implementation uses OpenAI's API
with structured JSON output.

Usage:
    client = OpenAIClient(model="gpt-4o")
    result = client.complete(prompt, ActionInventoryResponse)
"""

from __future__ import annotations

import json
from typing import Protocol, TypeVar, runtime_checkable

import structlog
from pydantic import BaseModel, ValidationError

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMClient(Protocol):
    """
    Minimal interface every LLM backend must satisfy.

    ``complete`` sends a prompt and returns a parsed Pydantic model.
    Implementations MUST handle JSON extraction and validation internally
    so that agents always receive a typed result or a clear error.
    """

    @property
    def model_name(self) -> str: ...

    def complete(self, prompt: str, response_model: type[T]) -> T:
        """
        Send *prompt* to the LLM and parse the response into *response_model*.

        Parameters
        ----------
        prompt:
            The full system+user prompt string.
        response_model:
            A Pydantic model class.  The LLM is instructed to return JSON
            conforming to this schema.

        Returns
        -------
        T
            A validated instance of *response_model*.

        Raises
        ------
        LLMError
            If the API call fails or the response cannot be parsed.
        """
        ...


class LLMError(Exception):
    """Raised when an LLM call fails or produces unparseable output."""

    def __init__(self, model: str, reason: str) -> None:
        self.model = model
        self.reason = reason
        super().__init__(f"[{model}] {reason}")


# ---------------------------------------------------------------------------
# OpenAI implementation
# ---------------------------------------------------------------------------


class OpenAIClient:
    """
    OpenAI-backed LLM client using JSON-mode structured output.

    Requires the ``openai`` package and a valid API key set via
    ``OPENAI_API_KEY`` environment variable (or passed explicitly).

    Parameters
    ----------
    model:
        Model identifier (e.g. ``"gpt-4o"``, ``"gpt-4o-mini"``).
    temperature:
        Sampling temperature.  Lower = more deterministic.
    max_tokens:
        Maximum tokens in the response.
    api_key:
        Optional explicit API key.  Falls back to ``OPENAI_API_KEY`` env var.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        temperature: float = 0.2,
        max_tokens: int = 4096,
        api_key: str | None = None,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "The 'openai' package is required for OpenAIClient. "
                "Install it with: pip install openai"
            ) from exc

        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client = OpenAI(api_key=api_key) if api_key else OpenAI()

    @property
    def model_name(self) -> str:
        return self._model

    def complete(self, prompt: str, response_model: type[T]) -> T:
        """Call OpenAI and parse the JSON response into *response_model*."""
        schema = response_model.model_json_schema()
        system_msg = (
            "You are a structured-output assistant.  "
            "Respond ONLY with a JSON object conforming to this schema:\n\n"
            f"```json\n{json.dumps(schema, indent=2)}\n```\n\n"
            "Do not include markdown fences, explanations, or any text "
            "outside the JSON object."
        )

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
            )
        except Exception as exc:
            raise LLMError(self._model, f"API call failed: {exc}") from exc

        raw = response.choices[0].message.content
        if not raw:
            raise LLMError(self._model, "Empty response from API.")

        logger.debug("llm.raw_response", model=self._model, length=len(raw))

        try:
            return response_model.model_validate_json(raw)
        except (ValidationError, json.JSONDecodeError) as exc:
            raise LLMError(
                self._model,
                f"Failed to parse response into {response_model.__name__}: {exc}",
            ) from exc
