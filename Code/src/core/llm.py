"""Normalized LLM request and response wrapper."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Literal

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


class LLMStreamEvent(BaseModel):
    """Public, UI-safe streaming progress from an LLM request."""

    event_type: Literal["start", "delta", "done", "cache_hit", "retry"] = "delta"
    text_delta: str = ""
    visible_text_preview: str = ""
    chars_received: int = 0
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

    def complete(
        self,
        request: LLMRequest,
        max_retries: int = 3,
        use_cache: bool = True,
        stream_callback: Callable[[LLMStreamEvent], None] | None = None,
    ) -> LLMResponse:
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
                self._emit_stream_event(
                    stream_callback,
                    LLMStreamEvent(
                        event_type="cache_hit",
                        visible_text_preview="Using cached response",
                        chars_received=len(getattr(cached, "content", "") or ""),
                        finish_reason=getattr(cached, "finish_reason", None),
                    ),
                )
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

            self._emit_stream_event(
                stream_callback,
                LLMStreamEvent(
                    event_type="start",
                    visible_text_preview="Waiting for model response",
                    provider_details={"attempt": attempt + 1},
                ),
            )
            if stream_callback is not None:
                response = self._create_streaming_completion_with_transport_retry(
                    client,
                    payload,
                    stream_callback,
                )
            else:
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
                    usage = self._usage_metadata(response)
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
                        self._emit_stream_event(
                            stream_callback,
                            LLMStreamEvent(
                                event_type="retry",
                                visible_text_preview="Response was not valid JSON; requesting repair",
                                chars_received=len(content),
                                provider_details={"attempt": attempt + 1},
                            ),
                        )
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
                usage = self._usage_metadata(response)
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

    def _emit_stream_event(
        self,
        stream_callback: Callable[[LLMStreamEvent], None] | None,
        event: LLMStreamEvent,
    ) -> None:
        if stream_callback is not None:
            stream_callback(event)

    def _create_streaming_completion_with_transport_retry(
        self,
        client: OpenAI,
        payload: dict[str, Any],
        stream_callback: Callable[[LLMStreamEvent], None],
    ) -> Any:
        streaming_payload = dict(payload)
        streaming_payload["stream"] = True
        stream = self._create_completion_with_transport_retry(client, streaming_payload)
        return self._collect_streaming_completion(stream, stream_callback)

    def _collect_streaming_completion(
        self,
        stream: Any,
        stream_callback: Callable[[LLMStreamEvent], None],
    ) -> Any:
        from types import SimpleNamespace

        content_parts: list[str] = []
        finish_reason: str | None = None
        model = self.settings.model
        response_id = None
        created = None
        usage: Any = None
        hidden_reasoning_fields: dict[str, int] = {}

        for chunk in stream:
            model = str(getattr(chunk, "model", None) or model)
            response_id = getattr(chunk, "id", response_id)
            created = getattr(chunk, "created", created)
            usage = getattr(chunk, "usage", usage)
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            finish_reason = getattr(choice, "finish_reason", None) or finish_reason
            delta = getattr(choice, "delta", None)
            hidden_reasoning_fields = self._merge_hidden_reasoning_fields(
                hidden_reasoning_fields,
                self._hidden_reasoning_field_lengths(delta),
            )
            text_delta = self._stream_delta_content(delta)
            if text_delta:
                content_parts.append(text_delta)
                content = "".join(content_parts)
                stream_callback(
                    LLMStreamEvent(
                        event_type="delta",
                        text_delta=text_delta,
                        visible_text_preview=content[-1200:],
                        chars_received=len(content),
                        provider_details={"hidden_reasoning_fields": dict(hidden_reasoning_fields)}
                        if hidden_reasoning_fields
                        else {},
                    )
                )

        content = "".join(content_parts)
        message = SimpleNamespace(content=content)
        choice = SimpleNamespace(message=message, finish_reason=finish_reason)
        response = SimpleNamespace(
            choices=[choice],
            usage=usage,
            model=model,
            id=response_id,
            created=created,
            provider_details={"hidden_reasoning_fields": hidden_reasoning_fields},
        )
        stream_callback(
            LLMStreamEvent(
                event_type="done",
                visible_text_preview=content[-1200:],
                chars_received=len(content),
                finish_reason=finish_reason,
                provider_details={"hidden_reasoning_fields": hidden_reasoning_fields}
                if hidden_reasoning_fields
                else {},
            )
        )
        return response

    def _stream_delta_content(self, delta: Any) -> str:
        if delta is None:
            return ""
        if isinstance(delta, dict):
            value = delta.get("content")
        else:
            value = getattr(delta, "content", None)
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "\n".join(part for item in value if (part := self._content_part_text(item)))
        return ""

    def _hidden_reasoning_field_lengths(self, delta: Any) -> dict[str, int]:
        fields = ("reasoning_content", "thinking", "reasoning")
        lengths: dict[str, int] = {}
        for field_name in fields:
            if isinstance(delta, dict):
                value = delta.get(field_name)
            else:
                value = getattr(delta, field_name, None)
            if value is None:
                continue
            if isinstance(value, str):
                lengths[field_name] = len(value)
            else:
                lengths[field_name] = len(str(value))
        return lengths

    def _merge_hidden_reasoning_fields(self, current: dict[str, int], update: dict[str, int]) -> dict[str, int]:
        merged = dict(current)
        for key, value in update.items():
            merged[key] = merged.get(key, 0) + value
        return merged

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
        metadata = {
            "id": getattr(response, "id", None),
            "created": getattr(response, "created", None),
            "transport_retry_history": getattr(self, "_last_transport_retry_history", []),
            "json_repair_attempt": json_repair_attempt,
            "content_diagnostics": content_diagnostics,
            "empty_length_response": finish_reason == "length" and not content.strip(),
        }
        provider_details = getattr(response, "provider_details", None)
        if isinstance(provider_details, dict):
            metadata.update(provider_details)
        return metadata

    def _usage_metadata(self, response: Any) -> dict[str, Any]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return {}
        if isinstance(usage, dict):
            return usage
        if hasattr(usage, "model_dump"):
            return usage.model_dump()
        if hasattr(usage, "__dict__"):
            return dict(vars(usage))
        return {}

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
