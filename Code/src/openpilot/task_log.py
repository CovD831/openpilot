"""Task log module for recording task progress and state changes.

This module provides structured logging for task lifecycle events, separate from
the audit log. Task logs are used for product features like daily reports, weekly
summaries, and progress tracking.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class TaskLogEventType(str, Enum):
    """Event types for task log entries."""

    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    BLOCKED = "blocked"
    UNBLOCKED = "unblocked"
    NOTE_ADDED = "note_added"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    TIMELINE_UPDATED = "timeline_updated"


class TaskLogEntry(BaseModel):
    """Single task log entry."""

    id: str
    timestamp: str
    task_id: str
    event_type: TaskLogEventType
    old_status: str | None = None
    new_status: str | None = None
    blocked_reason: str | None = None
    note: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        """Validate blocked events have a reason."""
        if self.event_type == TaskLogEventType.BLOCKED and not self.blocked_reason:
            raise ValueError("blocked events must include blocked_reason")


class TaskLogStore:
    """Local JSONL storage for task logs."""

    def __init__(self, log_dir: str | Path) -> None:
        """Initialize task log store.

        Args:
            log_dir: Directory for task log files (e.g., Code/data/task_logs/)
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _get_log_file(self, task_id: str) -> Path:
        """Get log file path for a specific task."""
        safe_task_id = task_id.replace("/", "_").replace("\\", "_")
        return self.log_dir / f"{safe_task_id}.jsonl"

    def append(self, entry: TaskLogEntry) -> None:
        """Append a task log entry.

        Args:
            entry: Task log entry to append
        """
        log_file = self._get_log_file(entry.task_id)
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json(exclude_none=True) + "\n")

    def get_entries(
        self,
        task_id: str,
        event_type: TaskLogEventType | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[TaskLogEntry]:
        """Query task log entries.

        Args:
            task_id: Task ID to query
            event_type: Optional filter by event type
            since: Optional ISO timestamp to filter entries after
            until: Optional ISO timestamp to filter entries before

        Returns:
            List of matching task log entries
        """
        log_file = self._get_log_file(task_id)
        if not log_file.exists():
            return []

        entries: list[TaskLogEntry] = []
        with log_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                entry = TaskLogEntry.model_validate(data)

                # Apply filters
                if event_type and entry.event_type != event_type:
                    continue
                if since and entry.timestamp < since:
                    continue
                if until and entry.timestamp > until:
                    continue

                entries.append(entry)

        return entries

    def get_all_task_ids(self) -> list[str]:
        """Get all task IDs that have log entries.

        Returns:
            List of task IDs
        """
        task_ids: list[str] = []
        for log_file in self.log_dir.glob("*.jsonl"):
            task_id = log_file.stem.replace("_", "/")
            task_ids.append(task_id)
        return task_ids

    def get_entries_by_date_range(
        self,
        since: str,
        until: str,
        event_type: TaskLogEventType | None = None,
    ) -> dict[str, list[TaskLogEntry]]:
        """Get all task log entries within a date range.

        Args:
            since: ISO timestamp start of range
            until: ISO timestamp end of range
            event_type: Optional filter by event type

        Returns:
            Dictionary mapping task_id to list of entries
        """
        result: dict[str, list[TaskLogEntry]] = {}
        for task_id in self.get_all_task_ids():
            entries = self.get_entries(
                task_id=task_id,
                event_type=event_type,
                since=since,
                until=until,
            )
            if entries:
                result[task_id] = entries
        return result

    def get_status_history(self, task_id: str) -> list[TaskLogEntry]:
        """Get status change history for a task.

        Args:
            task_id: Task ID to query

        Returns:
            List of status change entries in chronological order
        """
        return self.get_entries(
            task_id=task_id,
            event_type=TaskLogEventType.STATUS_CHANGED,
        )

    def get_blocked_entries(self, task_id: str) -> list[TaskLogEntry]:
        """Get all blocked events for a task.

        Args:
            task_id: Task ID to query

        Returns:
            List of blocked entries with reasons
        """
        return self.get_entries(
            task_id=task_id,
            event_type=TaskLogEventType.BLOCKED,
        )


def create_task_log_entry(
    task_id: str,
    event_type: TaskLogEventType,
    old_status: str | None = None,
    new_status: str | None = None,
    blocked_reason: str | None = None,
    note: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TaskLogEntry:
    """Create a task log entry with automatic timestamp and ID.

    Args:
        task_id: Task ID
        event_type: Type of event
        old_status: Previous status (for status_changed events)
        new_status: New status (for status_changed events)
        blocked_reason: Reason for blocking (required for blocked events)
        note: Optional note text
        metadata: Optional additional metadata

    Returns:
        TaskLogEntry instance
    """
    timestamp = datetime.now(UTC).isoformat()
    entry_id = f"{task_id}_{event_type.value}_{timestamp}"

    return TaskLogEntry(
        id=entry_id,
        timestamp=timestamp,
        task_id=task_id,
        event_type=event_type,
        old_status=old_status,
        new_status=new_status,
        blocked_reason=blocked_reason,
        note=note,
        metadata=metadata or {},
    )
