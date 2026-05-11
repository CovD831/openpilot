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
        use_cache: bool = True,
        stream: bool = False
    ) -> LLMResponse:
        """Complete request with progress tracking."""
        if self.tracker:
            # Get prompt preview
            prompt_preview = ""
            if request.messages:
                first_msg = request.messages[0]
                prompt_preview = first_msg.content[:200] if first_msg.content else ""

            model = self.settings.model if self.settings else "unknown"

            with self.tracker.track_llm_call(model, prompt_preview):
                return super().complete(request, use_cache, stream)
        else:
            return super().complete(request, use_cache, stream)
