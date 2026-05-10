"""Tests for task log module."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openpilot.task_log import (
    TaskLogEntry,
    TaskLogEventType,
    TaskLogStore,
    create_task_log_entry,
)


def test_task_log_entry_validation():
    """Test TaskLogEntry validation."""
    timestamp = datetime.now(UTC).isoformat()

    # Valid entry
    entry = TaskLogEntry(
        id="task1_created_123",
        timestamp=timestamp,
        task_id="task1",
        event_type=TaskLogEventType.CREATED,
    )
    assert entry.task_id == "task1"
    assert entry.event_type == TaskLogEventType.CREATED

    # Blocked event must have reason
    with pytest.raises(ValueError, match="blocked events must include blocked_reason"):
        TaskLogEntry(
            id="task1_blocked_123",
            timestamp=timestamp,
            task_id="task1",
            event_type=TaskLogEventType.BLOCKED,
        )

    # Blocked event with reason is valid
    entry = TaskLogEntry(
        id="task1_blocked_123",
        timestamp=timestamp,
        task_id="task1",
        event_type=TaskLogEventType.BLOCKED,
        blocked_reason="waiting for dependency",
    )
    assert entry.blocked_reason == "waiting for dependency"


def test_create_task_log_entry():
    """Test helper function for creating task log entries."""
    entry = create_task_log_entry(
        task_id="task1",
        event_type=TaskLogEventType.CREATED,
    )
    assert entry.task_id == "task1"
    assert entry.event_type == TaskLogEventType.CREATED
    assert entry.timestamp is not None
    assert entry.id.startswith("task1_created_")

    # Status change entry
    entry = create_task_log_entry(
        task_id="task2",
        event_type=TaskLogEventType.STATUS_CHANGED,
        old_status="planned",
        new_status="in_progress",
    )
    assert entry.old_status == "planned"
    assert entry.new_status == "in_progress"

    # Blocked entry with reason
    entry = create_task_log_entry(
        task_id="task3",
        event_type=TaskLogEventType.BLOCKED,
        blocked_reason="missing API key",
    )
    assert entry.blocked_reason == "missing API key"


def test_task_log_store_append_and_read(tmp_path: Path):
    """Test appending and reading task log entries."""
    store = TaskLogStore(tmp_path / "task_logs")

    # Append entries
    entry1 = create_task_log_entry(
        task_id="task1",
        event_type=TaskLogEventType.CREATED,
    )
    store.append(entry1)

    entry2 = create_task_log_entry(
        task_id="task1",
        event_type=TaskLogEventType.STATUS_CHANGED,
        old_status="planned",
        new_status="in_progress",
    )
    store.append(entry2)

    # Read entries
    entries = store.get_entries("task1")
    assert len(entries) == 2
    assert entries[0].event_type == TaskLogEventType.CREATED
    assert entries[1].event_type == TaskLogEventType.STATUS_CHANGED


def test_task_log_store_filter_by_event_type(tmp_path: Path):
    """Test filtering entries by event type."""
    store = TaskLogStore(tmp_path / "task_logs")

    # Create multiple event types
    store.append(
        create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.CREATED,
        )
    )
    store.append(
        create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.STATUS_CHANGED,
            old_status="planned",
            new_status="in_progress",
        )
    )
    store.append(
        create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.BLOCKED,
            blocked_reason="waiting for approval",
        )
    )

    # Filter by event type
    blocked_entries = store.get_entries(
        task_id="task1",
        event_type=TaskLogEventType.BLOCKED,
    )
    assert len(blocked_entries) == 1
    assert blocked_entries[0].blocked_reason == "waiting for approval"


def test_task_log_store_filter_by_date_range(tmp_path: Path):
    """Test filtering entries by date range."""
    store = TaskLogStore(tmp_path / "task_logs")

    now = datetime.now(UTC)
    yesterday = now - timedelta(days=1)
    tomorrow = now + timedelta(days=1)

    # Create entry with custom timestamp
    entry = TaskLogEntry(
        id="task1_created_123",
        timestamp=now.isoformat(),
        task_id="task1",
        event_type=TaskLogEventType.CREATED,
    )
    store.append(entry)

    # Query with date range
    entries = store.get_entries(
        task_id="task1",
        since=yesterday.isoformat(),
        until=tomorrow.isoformat(),
    )
    assert len(entries) == 1

    # Query outside date range
    entries = store.get_entries(
        task_id="task1",
        since=tomorrow.isoformat(),
    )
    assert len(entries) == 0


def test_task_log_store_status_history(tmp_path: Path):
    """Test getting status change history."""
    store = TaskLogStore(tmp_path / "task_logs")

    # Create status changes
    store.append(
        create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.CREATED,
        )
    )
    store.append(
        create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.STATUS_CHANGED,
            old_status="planned",
            new_status="in_progress",
        )
    )
    store.append(
        create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.STATUS_CHANGED,
            old_status="in_progress",
            new_status="done",
        )
    )

    # Get status history
    history = store.get_status_history("task1")
    assert len(history) == 2
    assert history[0].new_status == "in_progress"
    assert history[1].new_status == "done"


def test_task_log_store_blocked_entries(tmp_path: Path):
    """Test getting blocked entries with reasons."""
    store = TaskLogStore(tmp_path / "task_logs")

    # Create blocked events
    store.append(
        create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.BLOCKED,
            blocked_reason="waiting for API key",
        )
    )
    store.append(
        create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.UNBLOCKED,
        )
    )
    store.append(
        create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.BLOCKED,
            blocked_reason="dependency not ready",
        )
    )

    # Get blocked entries
    blocked = store.get_blocked_entries("task1")
    assert len(blocked) == 2
    assert blocked[0].blocked_reason == "waiting for API key"
    assert blocked[1].blocked_reason == "dependency not ready"


def test_task_log_store_multiple_tasks(tmp_path: Path):
    """Test handling multiple tasks."""
    store = TaskLogStore(tmp_path / "task_logs")

    # Create entries for different tasks
    store.append(
        create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.CREATED,
        )
    )
    store.append(
        create_task_log_entry(
            task_id="task2",
            event_type=TaskLogEventType.CREATED,
        )
    )

    # Get all task IDs
    task_ids = store.get_all_task_ids()
    assert len(task_ids) == 2
    assert "task1" in task_ids or "task1" in [tid.replace("_", "/") for tid in task_ids]
    assert "task2" in task_ids or "task2" in [tid.replace("_", "/") for tid in task_ids]

    # Get entries for specific task
    entries1 = store.get_entries("task1")
    assert len(entries1) == 1
    assert entries1[0].task_id == "task1"


def test_task_log_store_get_entries_by_date_range(tmp_path: Path):
    """Test getting entries across all tasks by date range."""
    store = TaskLogStore(tmp_path / "task_logs")

    now = datetime.now(UTC)
    yesterday = now - timedelta(days=1)
    tomorrow = now + timedelta(days=1)

    # Create entries for multiple tasks
    entry1 = TaskLogEntry(
        id="task1_created_123",
        timestamp=now.isoformat(),
        task_id="task1",
        event_type=TaskLogEventType.CREATED,
    )
    store.append(entry1)

    entry2 = TaskLogEntry(
        id="task2_created_456",
        timestamp=now.isoformat(),
        task_id="task2",
        event_type=TaskLogEventType.CREATED,
    )
    store.append(entry2)

    # Query by date range
    result = store.get_entries_by_date_range(
        since=yesterday.isoformat(),
        until=tomorrow.isoformat(),
    )
    assert len(result) == 2
    assert "task1" in result
    assert "task2" in result


def test_task_log_store_nonexistent_task(tmp_path: Path):
    """Test querying nonexistent task returns empty list."""
    store = TaskLogStore(tmp_path / "task_logs")

    entries = store.get_entries("nonexistent_task")
    assert entries == []


def test_task_log_store_metadata(tmp_path: Path):
    """Test storing and retrieving metadata."""
    store = TaskLogStore(tmp_path / "task_logs")

    entry = create_task_log_entry(
        task_id="task1",
        event_type=TaskLogEventType.NOTE_ADDED,
        note="User feedback received",
        metadata={"user_rating": 5, "feedback": "Great progress"},
    )
    store.append(entry)

    entries = store.get_entries("task1")
    assert len(entries) == 1
    assert entries[0].metadata["user_rating"] == 5
    assert entries[0].metadata["feedback"] == "Great progress"


def test_task_log_store_creates_directory(tmp_path: Path):
    """Test that TaskLogStore creates directory if it doesn't exist."""
    log_dir = tmp_path / "nested" / "task_logs"
    assert not log_dir.exists()

    store = TaskLogStore(log_dir)
    assert log_dir.exists()

    # Should be able to append entries
    entry = create_task_log_entry(
        task_id="task1",
        event_type=TaskLogEventType.CREATED,
    )
    store.append(entry)

    entries = store.get_entries("task1")
    assert len(entries) == 1
