"""Instrumented tool executor with UI progress tracking."""

from __future__ import annotations

from typing import Any, Callable, Optional

from models.tool_models import ToolDefinition, ToolExecutionResult
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
