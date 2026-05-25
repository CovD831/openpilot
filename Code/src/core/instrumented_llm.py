"""Instrumented LLM client with UI progress tracking."""

from __future__ import annotations

from typing import Any, Optional

from core.llm import LLMClient, LLMRequest, LLMResponse, LLMStreamEvent
from ui.progress_tracker import ProgressTracker


class InstrumentedLLMClient(LLMClient):
    """LLM client that reports progress to UI."""

    def __init__(self, settings=None, tracker: Optional[ProgressTracker] = None):
        """Initialize instrumented LLM client."""
        super().__init__(settings)
        self.tracker = tracker

    def complete(
        self,
        request: LLMRequest,
        max_retries: int = 3,
        use_cache: bool = True,
        stream_callback=None,
    ) -> LLMResponse:
        """Complete request with progress tracking."""
        if self.tracker:
            ui_session = getattr(getattr(self.tracker, "ui", None), "transient_operation_session", None)
            if callable(ui_session):
                with ui_session():
                    return self._complete_with_tracking(request, max_retries, use_cache, stream_callback)
            return self._complete_with_tracking(request, max_retries, use_cache, stream_callback)
        else:
            return super().complete(
                request,
                max_retries=max_retries,
                use_cache=use_cache,
                stream_callback=stream_callback,
            )

    def _complete_with_tracking(
        self,
        request: LLMRequest,
        max_retries: int,
        use_cache: bool,
        stream_callback,
    ) -> LLMResponse:
        prompt_preview = ""
        if request.messages:
            first_msg = request.messages[0]
            prompt_preview = first_msg.content[:200] if first_msg.content else ""

        model = self.settings.model if self.settings else "unknown"

        with self.tracker.track_llm_call(model, prompt_preview) as op_id:
            self.tracker.append_operation_line(
                op_id,
                f"Response format: {request.response_format}",
            )
            self.tracker.append_operation_line(
                op_id,
                f"Cache {'enabled' if use_cache else 'disabled'}; retries allowed: {max_retries}",
            )
            self.tracker.update_operation_phase(op_id, "Waiting for model")
            callback = stream_callback or self._tracker_stream_callback(op_id)
            response = super().complete(
                request,
                max_retries=max_retries,
                use_cache=use_cache,
                stream_callback=callback,
            )
            self.tracker.update_operation_phase(op_id, "Parsing response")
            preview = " ".join(response.content.split())[:160]
            self.tracker.update_operation_progress(
                op_id,
                preview=preview,
                count=len(response.content),
            )
            token_usage_text = self._format_token_usage(response.usage)
            self.tracker.update_operation_token_usage(op_id, token_usage_text)
            self.tracker.append_operation_line(op_id, token_usage_text)
            self.tracker.append_operation_line(op_id, "Response parsed")
            return response

    def _tracker_stream_callback(self, op_id: str):
        def callback(event: LLMStreamEvent) -> None:
            if not self.tracker:
                return
            if event.event_type == "start":
                self.tracker.update_operation_phase(op_id, "Waiting for model")
                return
            if event.event_type == "cache_hit":
                self.tracker.update_operation_phase(op_id, "Using cached response")
                self.tracker.append_operation_line(op_id, "Using cached response")
                return
            if event.event_type == "retry":
                self.tracker.update_operation_phase(op_id, "Repairing response")
                self.tracker.append_operation_line(op_id, event.visible_text_preview)
                return
            if event.event_type == "done":
                self.tracker.update_operation_phase(op_id, "Parsing response")
                self.tracker.update_operation_progress(
                    op_id,
                    preview=" ".join(event.visible_text_preview.split())[:160],
                    count=event.chars_received,
                )
                return
            self.tracker.update_operation_phase(op_id, "Streaming response")
            self.tracker.update_operation_stream_delta(
                op_id,
                event.text_delta,
                visible_text_preview=event.visible_text_preview,
                chars_received=event.chars_received,
            )

        return callback

    def _format_token_usage(self, usage: dict[str, Any] | None) -> str:
        """Format provider token usage for transient UI display."""
        usage = usage or {}
        if not usage:
            return "Token usage unavailable"

        input_tokens = self._coerce_int(
            usage.get("prompt_tokens")
            or usage.get("input_tokens")
            or usage.get("prompt_token_count")
        )
        output_tokens = self._coerce_int(
            usage.get("completion_tokens")
            or usage.get("output_tokens")
            or usage.get("completion_token_count")
        )
        total_tokens = self._coerce_int(usage.get("total_tokens") or usage.get("total_token_count"))
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens

        if input_tokens is None and output_tokens is None and total_tokens is None:
            return "Token usage unavailable"

        def fmt(value: int | None) -> str:
            return str(value) if value is not None else "?"

        return f"Tokens: input={fmt(input_tokens)} output={fmt(output_tokens)} total={fmt(total_tokens)}"

    def _coerce_int(self, value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
