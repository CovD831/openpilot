"""JSONL audit logging for openpilot validation sessions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from utils.json_utils import append_jsonl, truncate_jsonl_file
from utils.data_structures import CircularBuffer


class OpenPilotLogger:
    """Append structured openpilot events to a JSON Lines file with bounded growth."""

    def __init__(
        self,
        log_file: str | Path,
        max_log_lines: int = 10000,
        error_buffer_size: int = 100
    ) -> None:
        """
        Initialize logger.

        Args:
            log_file: Path to log file
            max_log_lines: Maximum lines to keep in log file (prevents unbounded growth)
            error_buffer_size: Size of in-memory error buffer
        """
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.max_log_lines = max_log_lines

        # In-memory circular buffer for recent errors
        self._error_buffer = CircularBuffer(maxsize=error_buffer_size)

    def log_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        session_id: str,
        turn_id: int,
    ) -> None:
        """Write one event without storing secrets or environment values."""

        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "session_id": session_id,
            "turn_id": turn_id,
            "event_type": event_type,
            "payload": payload,
        }

        # Use efficient JSONL append
        append_jsonl(self.log_file, event)

        # If this is an error event, add to error buffer
        if event_type in ("error", "exception", "failure"):
            self._error_buffer.add(event)

        # Periodically truncate log file to prevent unbounded growth
        # Check every 100 events (simple heuristic)
        if turn_id % 100 == 0:
            self._truncate_if_needed()

    def log_structured_event(
        self,
        *,
        source_type: str,
        source_name: str,
        phase: str,
        event_type: str,
        session_id: str,
        turn_id: int,
        success: bool | None = None,
        duration_ms: int | None = None,
        input_summary: Any | None = None,
        output_summary: Any | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Write a normalized event while preserving the legacy log_event API."""
        payload = {
            "source_type": source_type,
            "source_name": source_name,
            "phase": phase,
            "success": success,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output_summary": output_summary,
            "error": error,
            "metadata": metadata or {},
        }

        self.log_event(
            event_type,
            payload,
            session_id=session_id,
            turn_id=turn_id,
        )

    def _truncate_if_needed(self) -> None:
        """Truncate log file if it exceeds max lines."""
        try:
            truncate_jsonl_file(self.log_file, max_lines=self.max_log_lines)
        except Exception:
            # Don't fail logging if truncation fails
            pass

    def get_recent_errors(self, count: int = 10) -> list[dict[str, Any]]:
        """
        Get recent error events from in-memory buffer.

        Args:
            count: Number of recent errors to retrieve

        Returns:
            List of recent error events
        """
        return self._error_buffer.get_recent(count)

    def clear_error_buffer(self) -> None:
        """Clear the in-memory error buffer."""
        self._error_buffer.clear()

