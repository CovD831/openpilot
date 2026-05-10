"""Normalized LLM request and response wrapper."""

from __future__ import annotations

import json
from typing import Any, Literal

from openai import APITimeoutError, OpenAI, OpenAIError
from pydantic import BaseModel, ConfigDict, Field

from openpilot.config import LLMSettings
from openpilot.exceptions import InvalidLLMResponseError, LLMProviderError, LLMTimeoutError


class LLMMessage(BaseModel):
    """A single chat message."""

    role: Literal["system", "user", "assistant"]
    content: str


class LLMRequest(BaseModel):
    """Provider-neutral chat completion request."""

    messages: list[LLMMessage]
    response_format: Literal["text", "json_object"] = "text"
    temperature: float | None = None
    max_tokens: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """Provider-neutral chat completion response."""

    model_config = ConfigDict(protected_namespaces=())

    content: str
    parsed_json: dict[str, Any] | list[Any] | None = None
    model: str
    provider: str
    usage: dict[str, Any] = Field(default_factory=dict)
    finish_reason: str | None = None
    raw_response_metadata: dict[str, Any] = Field(default_factory=dict)


class LLMClient:
    """OpenAI-compatible chat completion client."""

    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.settings = settings or LLMSettings()

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Execute a chat completion and normalize the response."""

        self.settings.require_ready()
        client = OpenAI(
            api_key=self.settings.api_key,
            base_url=self.settings.base_url,
            timeout=self.settings.timeout_seconds,
        )

        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": [message.model_dump() for message in request.messages],
            "temperature": request.temperature
            if request.temperature is not None
            else self.settings.temperature,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}

        try:
            response = client.chat.completions.create(**payload)
        except APITimeoutError as exc:
            raise LLMTimeoutError(str(exc)) from exc
        except OpenAIError as exc:
            raise LLMProviderError(str(exc)) from exc

        choice = response.choices[0]
        content = choice.message.content or ""
        parsed_json: dict[str, Any] | list[Any] | None = None
        if request.response_format == "json_object":
            try:
                parsed_json = json.loads(content)
            except json.JSONDecodeError as exc:
                raise InvalidLLMResponseError("LLM returned invalid JSON.") from exc

        usage = response.usage.model_dump() if response.usage else {}
        return LLMResponse(
            content=content,
            parsed_json=parsed_json,
            model=response.model,
            provider=self.settings.provider,
            usage=usage,
            finish_reason=choice.finish_reason,
            raw_response_metadata={"id": response.id, "created": response.created},
        )


