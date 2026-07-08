"""LLM client wrapper that records trajectory evidence for key model calls."""

from __future__ import annotations

import json
import time
from typing import Any, Callable
from uuid import uuid4

from core.exceptions import ErrorCategory, classify_error
from core.llm import LLMRequest, LLMResponse
from metadata import FailureMetadata, LLMRequestMetadata, LLMResponseMetadata
from metadata.base import json_safe
from runtime_diagnostics.hooks import RuntimeDiagnosticsHooks


class TrajectoryLLMClientProxy:
    """Proxy an LLM client and emit metadata-first trajectory evidence."""

    def __init__(
        self,
        client: Any,
        *,
        hooks: RuntimeDiagnosticsHooks,
        task_id_getter: Callable[[], str] | None = None,
        session_id_getter: Callable[[], str] | None = None,
        phase_getter: Callable[[], str] | None = None,
        goal_getter: Callable[[], str] | None = None,
    ) -> None:
        self._client = client
        self._hooks = hooks
        self._task_id_getter = task_id_getter
        self._session_id_getter = session_id_getter
        self._phase_getter = phase_getter
        self._goal_getter = goal_getter

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def complete(
        self,
        request: LLMRequest,
        max_retries: int = 3,
        use_cache: bool = True,
        stream_callback=None,
    ) -> LLMResponse:
        task_id = self._value(self._task_id_getter)
        session_id = self._value(self._session_id_getter)
        phase = self._value(self._phase_getter)
        goal = self._value(self._goal_getter)
        call_id = f"llm_{uuid4().hex}"

        request_diagnostics = self._request_diagnostics(request)
        request_metadata = LLMRequestMetadata(
            task=goal or self._request_task(request),
            purpose=self._request_purpose(request),
            trace_info={
                **self._request_trace_info(request),
                "diagnostics": request_diagnostics,
            },
        )
        self._hooks.on_llm_requested(
            request_metadata=request_metadata,
            task_id=task_id,
            session_id=session_id,
            phase=phase,
            call_id=call_id,
            request_snapshot=request.model_dump(mode="python"),
        )

        started_at = time.monotonic()
        try:
            response = self._client.complete(
                request,
                max_retries=max_retries,
                use_cache=use_cache,
                stream_callback=stream_callback,
            )
        except Exception as exc:
            self._hooks.on_llm_failed(
                failure=FailureMetadata(
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    recoverable=self._is_recoverable_llm_error(exc),
                    retry_recommended=self._is_recoverable_llm_error(exc),
                    details={
                        "trace_info": self._request_trace_info(request),
                        "diagnostics": request_diagnostics,
                        "response_format": request.response_format,
                    },
                ),
                task_id=task_id,
                session_id=session_id,
                phase=phase,
                call_id=call_id,
            )
            raise

        duration_ms = int((time.monotonic() - started_at) * 1000)
        response_metadata = LLMResponseMetadata(
            model=str(response.model or ""),
            provider=str(response.provider or ""),
            usage=json_safe(response.usage) if isinstance(json_safe(response.usage), dict) else {},
            finish_reason=response.finish_reason,
            provider_details={
                **self._json_dict(response.provider_details),
                "duration_ms": duration_ms,
                "content_length": len(response.content or ""),
                "parsed_json_present": response.parsed_json is not None,
                "parsed_json_root_type": type(response.parsed_json).__name__ if response.parsed_json is not None else None,
            },
        )
        self._hooks.on_llm_responded(
            response_metadata=response_metadata,
            task_id=task_id,
            session_id=session_id,
            phase=phase,
            call_id=call_id,
            response_content=response.content,
            parsed_json=response.parsed_json,
        )
        return response

    def _value(self, getter: Callable[[], str] | None) -> str:
        if getter is None:
            return ""
        try:
            return str(getter() or "")
        except Exception:
            return ""

    def _request_diagnostics(self, request: LLMRequest) -> dict[str, Any]:
        messages = list(request.messages or [])
        message_lengths = [len(str(getattr(message, "content", "") or "")) for message in messages]
        settings = getattr(self._client, "settings", None)
        timeout_seconds = request.timeout_seconds or getattr(settings, "timeout_seconds", None)
        return {
            "message_count": len(messages),
            "prompt_chars": sum(message_lengths),
            "max_message_chars": max(message_lengths) if message_lengths else 0,
            "response_format": request.response_format,
            "max_tokens": request.max_tokens,
            "timeout_seconds": timeout_seconds,
            "transport_retries": request.transport_retries,
            "model": str(getattr(settings, "model", "") or ""),
            "provider": str(getattr(settings, "provider", "") or ""),
        }

    def _request_trace_info(self, request: LLMRequest) -> dict[str, Any]:
        trace_info = json_safe(dict(request.trace_info or {}))
        return trace_info if isinstance(trace_info, dict) else {}

    def _request_purpose(self, request: LLMRequest) -> str:
        trace_info = self._request_trace_info(request)
        for key in ("purpose", "semantic_task", "tool", "task", "operation", "step_id"):
            value = trace_info.get(key)
            if value not in (None, ""):
                return str(value)
        return str(request.response_format)

    def _request_task(self, request: LLMRequest) -> str:
        trace_info = self._request_trace_info(request)
        if trace_info.get("task") not in (None, ""):
            return str(trace_info["task"])
        if not request.messages:
            return ""
        user_messages = [message.content for message in request.messages if message.role == "user" and message.content]
        if not user_messages:
            return request.messages[0].content[:240] if request.messages[0].content else ""
        return user_messages[-1][:240]

    def _is_recoverable_llm_error(self, exc: Exception) -> bool:
        return classify_error(exc) in {
            ErrorCategory.NETWORK,
            ErrorCategory.TIMEOUT,
            ErrorCategory.RETRYABLE,
        }

    def _json_dict(self, value: Any) -> dict[str, Any]:
        safe = json_safe(value)
        return safe if isinstance(safe, dict) else {}

    def dump_json_text(self, value: Any) -> str:
        return json.dumps(json_safe(value), ensure_ascii=False, indent=2, sort_keys=True)
