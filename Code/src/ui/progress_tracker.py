"""Real-time progress tracker for tool calls and LLM operations."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from rich.console import Console


class OperationType(Enum):
    """Type of operation being tracked."""
    TOOL_CALL = "tool"
    LLM_CALL = "llm"
    TASK_EXECUTION = "task"
    FILE_OPERATION = "file"
    NETWORK = "network"
    OTHER = "other"


@dataclass
class Operation:
    """Represents an ongoing operation."""
    id: str
    type: OperationType
    name: str
    details: dict[str, Any]
    start_time: datetime
    end_time: Optional[datetime] = None
    success: Optional[bool] = None
    error: Optional[str] = None
    phase: str = "Starting"
    display_lines: list[str] | None = None
    spinner_frame: str = ""
    spinner_index: int = 0
    prompt_preview: str = ""
    response_preview: str = ""
    tokens_or_chars: int = 0

    @property
    def started_at(self) -> datetime:
        """Alias for callers that prefer the newer field name."""
        return self.start_time


class ProgressTracker:
    """Track and display real-time progress of operations."""

    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, ui):
        """Initialize progress tracker with UI instance."""
        from ui.enhanced_ui import EnhancedUI
        self.ui: EnhancedUI = ui
        self.operations: dict[str, Operation] = {}
        self.operation_counter = 0
        self.lock = threading.Lock()
        self._update_thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()

    def start_tracking(self):
        """Start background thread for UI updates."""
        if self._update_thread is None or not self._update_thread.is_alive():
            self._stop_flag.clear()
            self._update_thread = threading.Thread(target=self._update_loop, daemon=True)
            self._update_thread.start()

    def stop_tracking(self):
        """Stop background thread."""
        self._stop_flag.set()
        if self._update_thread:
            self._update_thread.join(timeout=1.0)

    def _update_loop(self):
        """Background loop to update UI."""
        while not self._stop_flag.is_set():
            with self.lock:
                # Update UI with current operations
                active_ops = [op for op in self.operations.values() if op.end_time is None]
                for op in active_ops:
                    op.spinner_index = (op.spinner_index + 1) % len(self.SPINNER_FRAMES)
                    op.spinner_frame = self.SPINNER_FRAMES[op.spinner_index]
            self.ui.set_active_operations(active_ops)
            time.sleep(0.5)

    @contextmanager
    def track_tool_call(self, tool_name: str, params: dict[str, Any]):
        """Context manager to track a tool call."""
        op_id = self._start_operation(
            OperationType.TOOL_CALL,
            tool_name,
            params,
            phase="Running tool",
        )
        self.append_operation_line(op_id, "Preparing tool call")
        for key, value in params.items():
            self.append_operation_line(op_id, f"{key}: {value}")

        # Show tool execution in UI
        if hasattr(self.ui, "show_tool_execution"):
            self.ui.show_tool_execution(tool_name, params)

        try:
            yield op_id
            self.update_operation_phase(op_id, "Completed")
            self._end_operation(op_id, success=True)
            self.ui.log_activity("tool", f"✓ {tool_name} completed")
        except Exception as e:
            self.update_operation_phase(op_id, "Failed")
            self.append_operation_line(op_id, f"Error: {str(e)}")
            self._end_operation(op_id, success=False, error=str(e))
            self.ui.log_activity("error", f"✗ {tool_name} failed: {str(e)}")
            raise

    @contextmanager
    def track_llm_call(self, model: str, prompt_preview: str):
        """Context manager to track an LLM call."""
        op_id = self._start_operation(
            OperationType.LLM_CALL,
            f"LLM: {model}",
            {"model": model, "prompt_preview": prompt_preview},
            phase="Preparing request",
        )
        self.append_operation_line(op_id, "Preparing request")
        if prompt_preview:
            self.append_operation_line(op_id, f"Prompt preview: {prompt_preview}")
        self.append_operation_line(op_id, "Waiting for model response")

        # Show LLM thinking in UI
        if hasattr(self.ui, "set_current_task_state"):
            self.ui.set_current_task_state(
                title=f"LLM: {model}",
                details=prompt_preview,
                status="waiting for model",
            )
        if hasattr(self.ui, "show_llm_thinking"):
            self.ui.show_llm_thinking(prompt_preview, model)

        try:
            yield op_id
            self.update_operation_phase(op_id, "Completed")
            self._end_operation(op_id, success=True)
            self.ui.log_activity("llm", f"✓ {model} responded")
        except Exception as e:
            self.update_operation_phase(op_id, "Failed")
            self.append_operation_line(op_id, f"Error: {str(e)}")
            self._end_operation(op_id, success=False, error=str(e))
            self.ui.log_activity("error", f"✗ {model} failed: {str(e)}")
            raise

    @contextmanager
    def track_task(self, task_name: str, details: dict[str, Any] | None = None):
        """Context manager to track a task execution."""
        op_id = self._start_operation(
            OperationType.TASK_EXECUTION,
            task_name,
            details or {},
            phase="Running task",
        )

        self.ui.log_activity("task", f"Starting: {task_name}")
        if hasattr(self.ui, "set_current_task_state"):
            detail_text = "\n".join(f"{key}: {value}" for key, value in (details or {}).items())
            self.ui.set_current_task_state(
                title=task_name,
                details=detail_text,
                status="running",
            )

        try:
            yield op_id
            self._end_operation(op_id, success=True)
            if hasattr(self.ui, "set_current_task_state"):
                self.ui.set_current_task_state(
                    title=task_name,
                    status="completed",
                )
            self.ui.log_activity("success", f"✓ {task_name} completed")
        except Exception as e:
            self._end_operation(op_id, success=False, error=str(e))
            if hasattr(self.ui, "set_current_task_state"):
                self.ui.set_current_task_state(
                    title=task_name,
                    details=str(e),
                    status="failed",
                )
            self.ui.log_activity("error", f"✗ {task_name} failed: {str(e)}")
            raise

    def _start_operation(
        self,
        op_type: OperationType,
        name: str,
        details: dict[str, Any],
        phase: str = "Starting",
    ) -> str:
        """Start tracking an operation."""
        with self.lock:
            self.operation_counter += 1
            op_id = f"op_{self.operation_counter}"

            operation = Operation(
                id=op_id,
                type=op_type,
                name=name,
                details=details,
                start_time=datetime.now(),
                phase=phase,
                display_lines=[],
                spinner_frame=self.SPINNER_FRAMES[0],
                prompt_preview=str(details.get("prompt_preview", "")),
            )

            self.operations[op_id] = operation
            return op_id

    def append_operation_line(self, op_id: str, text: str) -> None:
        """Append a public transient trace line to an active operation."""
        with self.lock:
            op = self.operations.get(op_id)
            if not op:
                return

            lines = op.display_lines or []
            lines.append(text)
            max_lines = getattr(self.ui, "max_active_trace_lines", 8)
            op.display_lines = lines[-max_lines:]

    def update_operation_phase(self, op_id: str, phase: str) -> None:
        """Update the public phase label for an active operation."""
        with self.lock:
            op = self.operations.get(op_id)
            if op:
                op.phase = phase

    def update_operation_progress(
        self,
        op_id: str,
        preview: str = "",
        count: int | None = None,
    ) -> None:
        """Update public response progress for an active operation."""
        with self.lock:
            op = self.operations.get(op_id)
            if not op:
                return
            if preview:
                op.response_preview = preview
            if count is not None:
                op.tokens_or_chars = count

    def _end_operation(
        self,
        op_id: str,
        success: bool,
        error: Optional[str] = None
    ):
        """Mark an operation as completed."""
        with self.lock:
            if op_id in self.operations:
                op = self.operations[op_id]
                op.end_time = datetime.now()
                op.success = success
                op.error = error

    def get_active_operations(self) -> list[Operation]:
        """Get list of currently active operations."""
        with self.lock:
            return [op for op in self.operations.values() if op.end_time is None]

    def finish_active_operations(self, success: bool = False, error: str | None = None) -> None:
        """Force-close active operations so stale traces do not remain visible."""
        with self.lock:
            now = datetime.now()
            for op in self.operations.values():
                if op.end_time is None:
                    op.end_time = now
                    op.success = success
                    op.error = error
                    if error:
                        op.phase = "Failed"
                        lines = op.display_lines or []
                        lines.append(f"Stopped: {error}")
                        max_lines = getattr(self.ui, "max_active_trace_lines", 8)
                        op.display_lines = lines[-max_lines:]
        self.ui.set_active_operations([])

    def get_completed_operations(self, limit: int = 10) -> list[Operation]:
        """Get list of recently completed operations."""
        with self.lock:
            completed = [op for op in self.operations.values() if op.end_time is not None]
            completed.sort(key=lambda x: x.end_time or x.start_time, reverse=True)
            return completed[:limit]

    def clear_old_operations(self, max_age_seconds: int = 300):
        """Clear operations older than max_age_seconds."""
        with self.lock:
            now = datetime.now()
            to_remove = []

            for op_id, op in self.operations.items():
                if op.end_time:
                    age = (now - op.end_time).total_seconds()
                    if age > max_age_seconds:
                        to_remove.append(op_id)

            for op_id in to_remove:
                del self.operations[op_id]
