"""Normalized LLM request and response wrapper."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Literal

from openai import APITimeoutError, OpenAI, OpenAIError
from pydantic import BaseModel, ConfigDict, Field

from core.config import LLMSettings
from core.exceptions import (
    ErrorCategory,
    InvalidLLMResponseError,
    LLMProviderError,
    LLMTimeoutError,
    classify_error,
)
from utils.json_utils import safe_parse_json


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
    trace_info: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """Provider-neutral chat completion response."""

    model_config = ConfigDict(protected_namespaces=())

    content: str
    parsed_json: dict[str, Any] | list[Any] | None = None
    model: str
    provider: str
    usage: dict[str, Any] = Field(default_factory=dict)
    finish_reason: str | None = None
    provider_details: dict[str, Any] = Field(default_factory=dict)


class LLMClient:
    """OpenAI-compatible chat completion client with caching."""

    def __init__(self, settings: LLMSettings | None = None, enable_cache: bool = True) -> None:
        self.settings = settings or LLMSettings()
        self._cache = None
        if enable_cache:
            from utils.cache import TTLCache
            # Cache responses for 1 hour
            self._cache = TTLCache(ttl_seconds=3600)

    def _make_cache_key(self, request: LLMRequest) -> str:
        """Generate a cache key from the request."""
        messages_str = json.dumps([m.model_dump() for m in request.messages], sort_keys=True)
        temp = request.temperature if request.temperature is not None else self.settings.temperature
        return f"{self.settings.model}:{request.response_format}:{temp}:{request.max_tokens}:{messages_str}"

    def complete(self, request: LLMRequest, max_retries: int = 3, use_cache: bool = True) -> LLMResponse:
        """Execute a chat completion and normalize the response.

        Args:
            request: The LLM request
            max_retries: Maximum number of retries for invalid JSON (default: 3)
            use_cache: Whether to use cached responses (default: True)

        Returns:
            LLMResponse with parsed content

        Raises:
            InvalidLLMResponseError: If JSON parsing fails after all retries
            LLMTimeoutError: If request times out
            LLMProviderError: If provider returns an error
        """
        # Check cache first
        if use_cache and self._cache is not None:
            cache_key = self._make_cache_key(request)
            status, cached = self._cache.get(cache_key)
            if status in ('hit', 'stale'):
                return cached

        self.settings.require_ready()
        client = OpenAI(
            api_key=self.settings.api_key,
            base_url=self.settings.base_url,
            timeout=self.settings.timeout_seconds,
        )

        last_error = None
        repair_messages = list(request.messages)
        for attempt in range(max_retries):
            payload: dict[str, Any] = {
                "model": self.settings.model,
                "messages": [message.model_dump() for message in repair_messages],
                "temperature": request.temperature
                if request.temperature is not None
                else self.settings.temperature,
            }
            if request.max_tokens is not None:
                payload["max_tokens"] = request.max_tokens
            if request.response_format == "json_object":
                payload["response_format"] = {"type": "json_object"}

            response = self._create_completion_with_transport_retry(client, payload)

            choice = response.choices[0]
            content, content_diagnostics = self._extract_message_content(choice.message)
            parsed_json: dict[str, Any] | list[Any] | None = None

            if request.response_format == "json_object":
                # Try to extract JSON from markdown code blocks if present
                cleaned_content = self._extract_json_from_content(content)
                # Use safe_parse_json for better error handling and caching
                parsed_json = safe_parse_json(cleaned_content)

                if parsed_json is not None:
                    # Success! Return the response
                    usage = response.usage.model_dump() if response.usage else {}
                    result = LLMResponse(
                        content=content,
                        parsed_json=parsed_json,
                        model=response.model,
                        provider=self.settings.provider,
                        usage=usage,
                        finish_reason=choice.finish_reason,
                        provider_details=self._response_metadata(
                            response=response,
                            choice=choice,
                            content=content,
                            content_diagnostics=content_diagnostics,
                            json_repair_attempt=attempt + 1,
                        ),
                    )

                    # Cache successful response
                    if use_cache and self._cache is not None and self._should_cache_response(result):
                        cache_key = self._make_cache_key(request)
                        self._cache.put(cache_key, result)

                    return result
                else:
                    # JSON parsing failed
                    last_error = InvalidLLMResponseError(
                        f"Failed to parse JSON (attempt {attempt + 1}/{max_retries})"
                    )
                    if attempt < max_retries - 1:
                        # Add a stronger instruction for the next attempt
                        repair_messages.append(
                            LLMMessage(
                                role="assistant",
                                content=content
                            )
                        )
                        repair_messages.append(
                            LLMMessage(
                                role="user",
                                content="The previous response was not valid JSON. Please return ONLY valid JSON without any markdown formatting, explanations, or extra text. Start with { or [ and end with } or ]."
                            )
                        )
                        continue
                    else:
                        # Last attempt failed, raise error
                        raise last_error
            else:
                # Not JSON mode, return as-is
                usage = response.usage.model_dump() if response.usage else {}
                result = LLMResponse(
                    content=content,
                    parsed_json=parsed_json,
                    model=response.model,
                    provider=self.settings.provider,
                    usage=usage,
                    finish_reason=choice.finish_reason,
                    provider_details=self._response_metadata(
                        response=response,
                        choice=choice,
                        content=content,
                        content_diagnostics=content_diagnostics,
                        json_repair_attempt=attempt + 1,
                    ),
                )

                # Cache successful response
                if use_cache and self._cache is not None and self._should_cache_response(result):
                    cache_key = self._make_cache_key(request)
                    self._cache.put(cache_key, result)

                return result

        # Should never reach here, but just in case
        raise InvalidLLMResponseError(
            f"LLM returned invalid JSON after {max_retries} attempts."
        )

    def _create_completion_with_transport_retry(self, client: OpenAI, payload: dict[str, Any]) -> Any:
        attempts = max(0, int(getattr(self.settings, "transport_retries", 0))) + 1
        delay = max(0.0, float(getattr(self.settings, "retry_initial_delay", 0.0)))
        max_delay = max(delay, float(getattr(self.settings, "retry_max_delay", delay)))
        last_error: OpenAIError | None = None
        history: list[dict[str, Any]] = []
        self._last_transport_retry_history = history

        for attempt in range(1, attempts + 1):
            try:
                response = client.chat.completions.create(**payload)
                history.append(
                    {
                        "attempt": attempt,
                        "status": "success",
                        "retryable": False,
                    }
                )
                return response
            except APITimeoutError as exc:
                last_error = exc
                category = ErrorCategory.TIMEOUT
                retryable = True
            except OpenAIError as exc:
                last_error = exc
                category = self._classify_provider_error(exc)
                retryable = self._is_retryable_provider_error(exc, category)

            history.append(
                {
                    "attempt": attempt,
                    "status": "failed",
                    "category": category.value,
                    "retryable": retryable,
                    "error_type": type(last_error).__name__ if last_error else None,
                    "error": str(last_error)[:500] if last_error else "",
                }
            )

            if not retryable or attempt >= attempts:
                break
            if delay > 0:
                time.sleep(min(delay, max_delay))
                delay = min(delay * 2 if delay else 0, max_delay)

        if isinstance(last_error, APITimeoutError):
            error = LLMTimeoutError(str(last_error), timeout_seconds=self.settings.timeout_seconds)
            error.context["transport_retry_history"] = history
            raise error from last_error
        if last_error is not None:
            category = self._classify_provider_error(last_error)
            status_code = getattr(last_error, "status_code", None)
            error = LLMProviderError(
                f"{category}: {last_error}",
                status_code=status_code,
                retryable=self._is_retryable_provider_error(last_error, category),
                category=category,
            )
            error.context["transport_retry_history"] = history
            raise error from last_error
        raise LLMProviderError("Provider request failed without an error.", retryable=True, category=ErrorCategory.RETRYABLE)

    def _classify_provider_error(self, exc: OpenAIError) -> ErrorCategory:
        status_code = getattr(exc, "status_code", None)
        if status_code == 429:
            return ErrorCategory.RETRYABLE
        if isinstance(status_code, int) and status_code >= 500:
            return ErrorCategory.RETRYABLE
        if isinstance(status_code, int) and 400 <= status_code < 500:
            if status_code in {401, 403}:
                return ErrorCategory.AUTH
            return ErrorCategory.TERMINAL
        return classify_error(exc)

    def _is_retryable_provider_error(self, exc: OpenAIError, category: ErrorCategory) -> bool:
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int):
            return status_code == 429 or status_code >= 500
        return category in {ErrorCategory.RETRYABLE, ErrorCategory.TIMEOUT, ErrorCategory.NETWORK}

    def _extract_message_content(self, message: Any) -> tuple[str, dict[str, Any]]:
        raw_content = getattr(message, "content", None)
        diagnostics = {
            "content_type": type(raw_content).__name__,
            "content_part_count": len(raw_content) if isinstance(raw_content, list) else None,
            "message_field_names": self._message_field_names(message),
        }
        if isinstance(raw_content, str):
            return raw_content, diagnostics
        if isinstance(raw_content, list):
            parts = [text for part in raw_content if (text := self._content_part_text(part))]
            return "\n".join(parts), diagnostics
        if raw_content is not None:
            return str(raw_content), diagnostics

        for field_name in ("text", "message", "output_text"):
            value = getattr(message, field_name, None)
            if isinstance(value, str):
                diagnostics["fallback_content_field"] = field_name
                return value, diagnostics
        return "", diagnostics

    def _content_part_text(self, part: Any) -> str:
        if isinstance(part, str):
            return part
        if isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str):
                return text
            if part.get("type") in {"text", "output_text"} and isinstance(part.get("content"), str):
                return str(part["content"])
            return ""
        text = getattr(part, "text", None)
        if isinstance(text, str):
            return text
        content = getattr(part, "content", None)
        if isinstance(content, str):
            return content
        return ""

    def _message_field_names(self, message: Any) -> list[str]:
        if hasattr(message, "model_dump"):
            try:
                return sorted(str(key) for key in message.model_dump().keys())
            except Exception:
                pass
        if hasattr(message, "__dict__"):
            return sorted(str(key) for key in vars(message).keys())
        return []

    def _response_metadata(
        self,
        *,
        response: Any,
        choice: Any,
        content: str,
        content_diagnostics: dict[str, Any],
        json_repair_attempt: int,
    ) -> dict[str, Any]:
        finish_reason = getattr(choice, "finish_reason", None)
        return {
            "id": getattr(response, "id", None),
            "created": getattr(response, "created", None),
            "transport_retry_history": getattr(self, "_last_transport_retry_history", []),
            "json_repair_attempt": json_repair_attempt,
            "content_diagnostics": content_diagnostics,
            "empty_length_response": finish_reason == "length" and not content.strip(),
        }

    def _should_cache_response(self, response: LLMResponse) -> bool:
        if response.finish_reason == "length" and not response.content.strip():
            return False
        return True

    def _extract_json_from_content(self, content: str) -> str:
        """Extract JSON from content, handling markdown code blocks.

        Args:
            content: Raw content from LLM

        Returns:
            Cleaned JSON string
        """
        # Remove markdown code blocks if present
        # Pattern: ```json\n{...}\n``` or ```\n{...}\n```
        content = content.strip()

        # Try to extract from markdown code block
        json_block_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', content)
        if json_block_match:
            return json_block_match.group(1).strip()

        # Try to find JSON object or array
        # Look for content between first { and last } or first [ and last ]
        if '{' in content and '}' in content:
            start = content.find('{')
            end = content.rfind('}') + 1
            return content[start:end]
        elif '[' in content and ']' in content:
            start = content.find('[')
            end = content.rfind(']') + 1
            return content[start:end]

        # Return as-is if no patterns found
        return content
