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


class ProgressTracker:
    """Track and display real-time progress of operations."""

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
                if active_ops:
                    # UI will be updated by the operations themselves
                    pass
            time.sleep(0.1)

    @contextmanager
    def track_tool_call(self, tool_name: str, params: dict[str, Any]):
        """Context manager to track a tool call."""
        op_id = self._start_operation(OperationType.TOOL_CALL, tool_name, params)

        # Show tool execution in UI
        self.ui.show_tool_execution(tool_name, params)

        try:
            yield op_id
            self._end_operation(op_id, success=True)
            self.ui.log_activity("tool", f"✓ {tool_name} completed")
        except Exception as e:
            self._end_operation(op_id, success=False, error=str(e))
            self.ui.log_activity("error", f"✗ {tool_name} failed: {str(e)}")
            raise

    @contextmanager
    def track_llm_call(self, model: str, prompt_preview: str):
        """Context manager to track an LLM call."""
        op_id = self._start_operation(
            OperationType.LLM_CALL,
            f"LLM: {model}",
            {"model": model, "prompt_preview": prompt_preview}
        )

        # Show LLM thinking in UI
        self.ui.show_llm_thinking(prompt_preview, model)

        try:
            yield op_id
            self._end_operation(op_id, success=True)
            self.ui.log_activity("llm", f"✓ {model} responded")
        except Exception as e:
            self._end_operation(op_id, success=False, error=str(e))
            self.ui.log_activity("error", f"✗ {model} failed: {str(e)}")
            raise

    @contextmanager
    def track_task(self, task_name: str, details: dict[str, Any] | None = None):
        """Context manager to track a task execution."""
        op_id = self._start_operation(
            OperationType.TASK_EXECUTION,
            task_name,
            details or {}
        )

        self.ui.log_activity("task", f"Starting: {task_name}")

        try:
            yield op_id
            self._end_operation(op_id, success=True)
            self.ui.log_activity("success", f"✓ {task_name} completed")
        except Exception as e:
            self._end_operation(op_id, success=False, error=str(e))
            self.ui.log_activity("error", f"✗ {task_name} failed: {str(e)}")
            raise

    def _start_operation(
        self,
        op_type: OperationType,
        name: str,
        details: dict[str, Any]
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
                start_time=datetime.now()
            )

            self.operations[op_id] = operation
            return op_id

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
