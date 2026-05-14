from __future__ import annotations

import io
import unittest

from core.instrumented_llm import InstrumentedLLMClient
from core.llm import LLMResponse
from rich.console import Console
from ui.enhanced_ui import EnhancedUI
from ui.progress_tracker import OperationType, ProgressTracker


class TokenUsageFormattingTest(unittest.TestCase):
    def test_formats_openai_usage_fields(self):
        client = InstrumentedLLMClient(settings=None, tracker=None)

        text = client._format_token_usage(
            {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        )

        self.assertEqual(text, "Tokens: input=10 output=20 total=30")

    def test_formats_input_output_usage_fields_and_computes_total(self):
        client = InstrumentedLLMClient(settings=None, tracker=None)

        text = client._format_token_usage({"input_tokens": 11, "output_tokens": 22})

        self.assertEqual(text, "Tokens: input=11 output=22 total=33")

    def test_empty_usage_is_unavailable(self):
        client = InstrumentedLLMClient(settings=None, tracker=None)

        self.assertEqual(client._format_token_usage({}), "Token usage unavailable")


class TokenUsageUITest(unittest.TestCase):
    def test_tracker_stores_token_usage_text(self):
        ui = EnhancedUI(Console(file=io.StringIO(), force_terminal=True, width=100))
        tracker = ProgressTracker(ui)

        with tracker.track_llm_call("test-model", "hello") as op_id:
            tracker.update_operation_token_usage(op_id, "Tokens: input=1 output=2 total=3")
            op = tracker.operations[op_id]
            self.assertEqual(op.token_usage_text, "Tokens: input=1 output=2 total=3")

    def test_current_task_panel_renders_token_usage(self):
        output = io.StringIO()
        ui = EnhancedUI(Console(file=output, force_terminal=True, width=100))
        tracker = ProgressTracker(ui)
        op_id = tracker._start_operation(
            OperationType.LLM_CALL,
            "LLM: test-model",
            {"model": "test-model", "prompt_preview": "hello"},
            phase="Parsing response",
        )
        tracker.update_operation_progress(op_id, preview="world", count=5)
        tracker.update_operation_token_usage(op_id, "Tokens: input=10 output=20 total=30")
        ui.set_active_operations(tracker.get_active_operations())

        ui.console.print(ui.create_current_task_panel())
        rendered = output.getvalue()

        self.assertIn("Tokens: input=10 output=20 total=30", rendered)
        self.assertIn("Response: 5 chars", rendered)


class FakeTrackedLLMClient(InstrumentedLLMClient):
    def __init__(self, tracker: ProgressTracker, response: LLMResponse):
        self.tracker = tracker
        self.settings = type("Settings", (), {"model": "fake-model"})()
        self._response = response

    def complete(self, request, max_retries: int = 3, use_cache: bool = True):
        if self.tracker:
            with self.tracker.track_llm_call("fake-model", "prompt") as op_id:
                usage_text = self._format_token_usage(self._response.usage)
                self.tracker.update_operation_token_usage(op_id, usage_text)
                return self._response
        return self._response


if __name__ == "__main__":
    unittest.main()
