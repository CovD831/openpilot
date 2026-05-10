"""Tests for progress report generation module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openpilot.progress_report import (
    ProgressReport,
    ProgressReportGenerator,
    ReportType,
    TaskSummary,
)
from openpilot.task_log import TaskLogEventType, TaskLogStore, create_task_log_entry


def test_generate_daily_report_with_completed_tasks(tmp_path: Path):
    """Test generating daily report with completed tasks."""
    store = TaskLogStore(tmp_path / "task_logs")
    generator = ProgressReportGenerator(store)

    # Create task log entries for today
    today = datetime.now(UTC)
    today_str = today.date().isoformat()

    # Task 1: Created and completed today
    entry1 = create_task_log_entry(
        task_id="task1",
        event_type=TaskLogEventType.CREATED,
    )
    store.append(entry1)

    entry2 = create_task_log_entry(
        task_id="task1",
        event_type=TaskLogEventType.COMPLETED,
    )
    store.append(entry2)

    # Generate daily report
    report = generator.generate_daily_report(date=today_str)

    assert report.report_type == ReportType.DAILY
    assert len(report.completed_today) == 1
    assert report.completed_today[0].task_id == "task1"
    assert report.completed_today[0].status == "completed"
    assert report.total_tasks == 1


def test_generate_daily_report_with_blocked_tasks(tmp_path: Path):
    """Test generating daily report with blocked tasks."""
    store = TaskLogStore(tmp_path / "task_logs")
    generator = ProgressReportGenerator(store)

    today = datetime.now(UTC)
    today_str = today.date().isoformat()

    # Task blocked today
    entry1 = create_task_log_entry(
        task_id="task2",
        event_type=TaskLogEventType.CREATED,
    )
    store.append(entry1)

    entry2 = create_task_log_entry(
        task_id="task2",
        event_type=TaskLogEventType.BLOCKED,
        blocked_reason="Waiting for API access",
    )
    store.append(entry2)

    # Generate daily report
    report = generator.generate_daily_report(date=today_str)

    assert len(report.blocked) == 1
    assert report.blocked[0].task_id == "task2"
    assert report.blocked[0].blocked_reason == "Waiting for API access"
    assert len(report.risks) == 1
    assert "Waiting for API access" in report.risks[0]


def test_generate_daily_report_with_in_progress_tasks(tmp_path: Path):
    """Test generating daily report with in-progress tasks."""
    store = TaskLogStore(tmp_path / "task_logs")
    generator = ProgressReportGenerator(store)

    today = datetime.now(UTC)
    today_str = today.date().isoformat()

    # Task in progress
    entry1 = create_task_log_entry(
        task_id="task3",
        event_type=TaskLogEventType.CREATED,
    )
    store.append(entry1)

    entry2 = create_task_log_entry(
        task_id="task3",
        event_type=TaskLogEventType.STATUS_CHANGED,
        old_status="planned",
        new_status="in_progress",
    )
    store.append(entry2)

    # Generate daily report
    report = generator.generate_daily_report(date=today_str)

    assert len(report.in_progress) == 1
    assert report.in_progress[0].task_id == "task3"
    assert report.in_progress[0].status == "in_progress"


def test_generate_daily_report_empty_logs(tmp_path: Path):
    """Test generating daily report with no task logs."""
    store = TaskLogStore(tmp_path / "task_logs")
    generator = ProgressReportGenerator(store)

    today = datetime.now(UTC)
    today_str = today.date().isoformat()

    # Generate daily report with no logs
    report = generator.generate_daily_report(date=today_str)

    assert report.report_type == ReportType.DAILY
    assert len(report.completed_today) == 0
    assert len(report.in_progress) == 0
    assert len(report.blocked) == 0
    assert report.total_tasks == 0


def test_generate_weekly_report_with_completed_tasks(tmp_path: Path):
    """Test generating weekly report with completed tasks."""
    store = TaskLogStore(tmp_path / "task_logs")
    generator = ProgressReportGenerator(store)

    # Get current week start (Monday)
    today = datetime.now(UTC).date()
    days_since_monday = today.weekday()
    monday = today - timedelta(days=days_since_monday)
    week_start_str = monday.isoformat()

    # Create tasks completed this week
    entry1 = create_task_log_entry(
        task_id="weekly_task1",
        event_type=TaskLogEventType.CREATED,
    )
    store.append(entry1)

    entry2 = create_task_log_entry(
        task_id="weekly_task1",
        event_type=TaskLogEventType.COMPLETED,
    )
    store.append(entry2)

    # Generate weekly report
    report = generator.generate_weekly_report(week_start=week_start_str)

    assert report.report_type == ReportType.WEEKLY
    assert len(report.completed_this_week) == 1
    assert report.completed_this_week[0].task_id == "weekly_task1"


def test_generate_weekly_report_with_blocked_tasks(tmp_path: Path):
    """Test generating weekly report with blocked tasks."""
    store = TaskLogStore(tmp_path / "task_logs")
    generator = ProgressReportGenerator(store)

    today = datetime.now(UTC).date()
    days_since_monday = today.weekday()
    monday = today - timedelta(days=days_since_monday)
    week_start_str = monday.isoformat()

    # Create blocked task
    entry1 = create_task_log_entry(
        task_id="blocked_task",
        event_type=TaskLogEventType.CREATED,
    )
    store.append(entry1)

    entry2 = create_task_log_entry(
        task_id="blocked_task",
        event_type=TaskLogEventType.BLOCKED,
        blocked_reason="Dependency not ready",
    )
    store.append(entry2)

    # Generate weekly report
    report = generator.generate_weekly_report(week_start=week_start_str)

    assert len(report.delayed_or_blocked) == 1
    assert report.delayed_or_blocked[0].task_id == "blocked_task"
    assert len(report.retrospective_notes) == 1
    assert "Dependency not ready" in report.retrospective_notes[0]


def test_generate_weekly_report_empty_logs(tmp_path: Path):
    """Test generating weekly report with no task logs."""
    store = TaskLogStore(tmp_path / "task_logs")
    generator = ProgressReportGenerator(store)

    today = datetime.now(UTC).date()
    days_since_monday = today.weekday()
    monday = today - timedelta(days=days_since_monday)
    week_start_str = monday.isoformat()

    # Generate weekly report with no logs
    report = generator.generate_weekly_report(week_start=week_start_str)

    assert report.report_type == ReportType.WEEKLY
    assert len(report.completed_this_week) == 0
    assert len(report.delayed_or_blocked) == 0
    assert report.total_tasks == 0


def test_task_summary_creation(tmp_path: Path):
    """Test creating task summary from log entries."""
    store = TaskLogStore(tmp_path / "task_logs")
    generator = ProgressReportGenerator(store)

    # Create various log entries
    entries = [
        create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.CREATED,
        ),
        create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.STATUS_CHANGED,
            old_status="planned",
            new_status="in_progress",
        ),
        create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.NOTE_ADDED,
            note="Made good progress",
        ),
        create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.COMPLETED,
        ),
    ]

    for entry in entries:
        store.append(entry)

    # Create summary
    summary = generator._create_task_summary("task1", entries)

    assert summary.task_id == "task1"
    assert summary.status == "completed"
    assert len(summary.events) == 4
    assert "planned → in_progress" in summary.events
    assert len(summary.notes) == 1
    assert summary.notes[0] == "Made good progress"


def test_format_daily_report_markdown(tmp_path: Path):
    """Test formatting daily report as Markdown."""
    store = TaskLogStore(tmp_path / "task_logs")
    generator = ProgressReportGenerator(store)

    today = datetime.now(UTC)
    today_str = today.date().isoformat()

    # Create some tasks
    store.append(
        create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.COMPLETED,
        )
    )
    store.append(
        create_task_log_entry(
            task_id="task2",
            event_type=TaskLogEventType.BLOCKED,
            blocked_reason="Test reason",
        )
    )

    # Generate and format report
    report = generator.generate_daily_report(date=today_str)
    markdown = generator.format_daily_report_markdown(report)

    assert "# Daily Progress Report" in markdown
    assert "## ✅ Completed Today" in markdown
    assert "## 🚫 Blocked" in markdown
    assert "task1" in markdown
    assert "task2" in markdown
    assert "Test reason" in markdown


def test_format_weekly_report_markdown(tmp_path: Path):
    """Test formatting weekly report as Markdown."""
    store = TaskLogStore(tmp_path / "task_logs")
    generator = ProgressReportGenerator(store)

    today = datetime.now(UTC).date()
    days_since_monday = today.weekday()
    monday = today - timedelta(days=days_since_monday)
    week_start_str = monday.isoformat()

    # Create some tasks
    store.append(
        create_task_log_entry(
            task_id="weekly_task1",
            event_type=TaskLogEventType.COMPLETED,
        )
    )
    store.append(
        create_task_log_entry(
            task_id="weekly_task2",
            event_type=TaskLogEventType.BLOCKED,
            blocked_reason="Blocked reason",
        )
    )

    # Generate and format report
    report = generator.generate_weekly_report(week_start=week_start_str)
    markdown = generator.format_weekly_report_markdown(report)

    assert "# Weekly Progress Report" in markdown
    assert "## ✅ Completed This Week" in markdown
    assert "## ⏸️ Delayed or Blocked" in markdown
    assert "## 💭 Retrospective" in markdown
    assert "weekly_task1" in markdown
    assert "weekly_task2" in markdown
    assert "Blocked reason" in markdown


def test_daily_report_with_notes(tmp_path: Path):
    """Test daily report includes task notes."""
    store = TaskLogStore(tmp_path / "task_logs")
    generator = ProgressReportGenerator(store)

    today = datetime.now(UTC)
    today_str = today.date().isoformat()

    # Create task with notes
    store.append(
        create_task_log_entry(
            task_id="task_with_notes",
            event_type=TaskLogEventType.CREATED,
        )
    )
    store.append(
        create_task_log_entry(
            task_id="task_with_notes",
            event_type=TaskLogEventType.NOTE_ADDED,
            note="First note",
        )
    )
    store.append(
        create_task_log_entry(
            task_id="task_with_notes",
            event_type=TaskLogEventType.NOTE_ADDED,
            note="Second note",
        )
    )
    store.append(
        create_task_log_entry(
            task_id="task_with_notes",
            event_type=TaskLogEventType.COMPLETED,
        )
    )

    # Generate report
    report = generator.generate_daily_report(date=today_str)

    assert len(report.completed_today) == 1
    task = report.completed_today[0]
    assert len(task.notes) == 2
    assert "First note" in task.notes
    assert "Second note" in task.notes


def test_weekly_report_with_skipped_tasks(tmp_path: Path):
    """Test weekly report includes skipped tasks in delayed section."""
    store = TaskLogStore(tmp_path / "task_logs")
    generator = ProgressReportGenerator(store)

    today = datetime.now(UTC).date()
    days_since_monday = today.weekday()
    monday = today - timedelta(days=days_since_monday)
    week_start_str = monday.isoformat()

    # Create skipped task
    store.append(
        create_task_log_entry(
            task_id="skipped_task",
            event_type=TaskLogEventType.CREATED,
        )
    )
    store.append(
        create_task_log_entry(
            task_id="skipped_task",
            event_type=TaskLogEventType.SKIPPED,
        )
    )

    # Generate report
    report = generator.generate_weekly_report(week_start=week_start_str)

    assert len(report.delayed_or_blocked) == 1
    assert report.delayed_or_blocked[0].task_id == "skipped_task"


def test_report_metadata(tmp_path: Path):
    """Test report includes correct metadata."""
    store = TaskLogStore(tmp_path / "task_logs")
    generator = ProgressReportGenerator(store)

    today = datetime.now(UTC)
    today_str = today.date().isoformat()

    # Generate report
    report = generator.generate_daily_report(date=today_str)

    assert report.period_start.startswith(today_str)
    assert report.generated_at is not None
    assert report.total_tasks == 0
