"""Instrumented tool executor with UI progress tracking."""

from __future__ import annotations

from typing import Any, Callable, Optional

from tools.tool_models import ToolDefinition, ToolExecutionResult
from tools.tool_executor import ToolExecutor
from ui.progress_tracker import ProgressTracker


class InstrumentedToolExecutor(ToolExecutor):
    """Tool executor that reports progress to UI."""

    def __init__(self, registry, tracker: Optional[ProgressTracker] = None, max_workers: int = 4):
        """Initialize instrumented tool executor."""
        super().__init__(registry, max_workers)
        self.tracker = tracker

    def execute(
        self,
        tool: ToolDefinition,
        executor_func: Callable[[dict[str, Any]], dict[str, Any]],
        params: dict[str, Any],
        timeout: int | None = None,
    ) -> ToolExecutionResult:
        """Execute tool with progress tracking."""
        if self.tracker:
            with self.tracker.track_tool_call(tool.name, params):
                return super().execute(tool, executor_func, params, timeout)
        else:
            return super().execute(tool, executor_func, params, timeout)

    def execute_single(self, tool_selection, context=None):
        """Execute a selected tool with progress tracking."""
        if self.tracker:
            with self.tracker.track_tool_call(
                tool_selection.tool_name,
                self._display_params(tool_selection.input_params),
            ) as op_id:
                self.tracker.update_operation_phase(op_id, "Executing")
                result = super().execute_single(tool_selection, context)
                if result.success:
                    self.tracker.update_operation_phase(op_id, "Completed")
                    self.tracker.append_operation_line(op_id, "Tool returned successfully")
                else:
                    self.tracker.update_operation_phase(op_id, "Failed")
                    if result.error:
                        self.tracker.append_operation_line(op_id, result.error.error_message)
                return result
        return super().execute_single(tool_selection, context)

    def _display_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Trim large/sensitive values before showing them in the UI."""
        display = {}
        for key, value in params.items():
            if key.startswith("_"):
                continue
            if key in {"content", "code"} and isinstance(value, str):
                display[key] = f"<{len(value)} chars>"
            else:
                display[key] = value
        return display
