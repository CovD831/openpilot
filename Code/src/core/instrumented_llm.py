"""Instrumented LLM client with UI progress tracking."""

from __future__ import annotations

from typing import Optional

from core.llm import LLMClient, LLMRequest, LLMResponse
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
    ) -> LLMResponse:
        """Complete request with progress tracking."""
        if self.tracker:
            # Get prompt preview
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
                response = super().complete(
                    request,
                    max_retries=max_retries,
                    use_cache=use_cache,
                )
                self.tracker.update_operation_phase(op_id, "Parsing response")
                preview = " ".join(response.content.split())[:160]
                self.tracker.update_operation_progress(
                    op_id,
                    preview=preview,
                    count=len(response.content),
                )
                if response.usage:
                    self.tracker.append_operation_line(
                        op_id,
                        f"Usage: {response.usage}",
                    )
                self.tracker.append_operation_line(op_id, "Response parsed")
                return response
        else:
            return super().complete(
                request,
                max_retries=max_retries,
                use_cache=use_cache,
            )
