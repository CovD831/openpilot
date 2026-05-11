"""Progress report generation module for daily and weekly reports.

This module generates structured progress reports based on task log entries,
providing daily summaries, weekly reviews, and retrospectives.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from reporting.task_log import TaskLogEntry, TaskLogEventType, TaskLogStore


class ReportType(str, Enum):
    """Type of progress report."""

    DAILY = "daily"
    WEEKLY = "weekly"
    CUSTOM = "custom"


class TaskSummary(BaseModel):
    """Summary of a single task in a report."""

    task_id: str
    title: str | None = None
    status: str
    events: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    notes: list[str] = Field(default_factory=list)


class ProgressReport(BaseModel):
    """Structured progress report."""

    report_type: ReportType
    period_start: str
    period_end: str
    generated_at: str

    # Daily report sections
    completed_today: list[TaskSummary] = Field(default_factory=list)
    in_progress: list[TaskSummary] = Field(default_factory=list)
    blocked: list[TaskSummary] = Field(default_factory=list)
    planned_tomorrow: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)

    # Weekly report sections
    weekly_goals: list[str] = Field(default_factory=list)
    completed_this_week: list[TaskSummary] = Field(default_factory=list)
    delayed_or_blocked: list[TaskSummary] = Field(default_factory=list)
    next_week_focus: list[str] = Field(default_factory=list)
    retrospective_notes: list[str] = Field(default_factory=list)

    # General metadata
    total_tasks: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProgressReportGenerator:
    """Generate daily and weekly progress reports from task logs."""

    def __init__(self, task_log_store: TaskLogStore) -> None:
        """Initialize report generator.

        Args:
            task_log_store: Task log store to query
        """
        self.store = task_log_store

    def generate_daily_report(
        self,
        date: str | None = None,
        user_preferences: dict[str, Any] | None = None,
    ) -> ProgressReport:
        """Generate a daily progress report.

        Args:
            date: ISO date string (YYYY-MM-DD), defaults to today
            user_preferences: Optional user preferences for report format

        Returns:
            Daily progress report
        """
        if date is None:
            date = datetime.now(UTC).date().isoformat()

        # Parse date and calculate time range
        target_date = datetime.fromisoformat(date).replace(tzinfo=UTC)
        period_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        period_end = period_start + timedelta(days=1)

        # Query task logs for the day
        entries_by_task = self.store.get_entries_by_date_range(
            since=period_start.isoformat(),
            until=period_end.isoformat(),
        )

        # Analyze tasks
        completed_today: list[TaskSummary] = []
        in_progress: list[TaskSummary] = []
        blocked: list[TaskSummary] = []
        risks: list[str] = []

        for task_id, entries in entries_by_task.items():
            summary = self._create_task_summary(task_id, entries)

            # Categorize by final status
            if any(e.event_type == TaskLogEventType.COMPLETED for e in entries):
                completed_today.append(summary)
            elif any(e.event_type == TaskLogEventType.BLOCKED for e in entries):
                blocked.append(summary)
                if summary.blocked_reason:
                    risks.append(f"{task_id}: {summary.blocked_reason}")
            elif any(
                e.event_type == TaskLogEventType.STATUS_CHANGED
                and e.new_status == "in_progress"
                for e in entries
            ):
                in_progress.append(summary)

        return ProgressReport(
            report_type=ReportType.DAILY,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            generated_at=datetime.now(UTC).isoformat(),
            completed_today=completed_today,
            in_progress=in_progress,
            blocked=blocked,
            risks=risks,
            total_tasks=len(entries_by_task),
        )

    def generate_weekly_report(
        self,
        week_start: str | None = None,
        user_preferences: dict[str, Any] | None = None,
    ) -> ProgressReport:
        """Generate a weekly progress report.

        Args:
            week_start: ISO date string for week start (Monday), defaults to current week
            user_preferences: Optional user preferences for report format

        Returns:
            Weekly progress report
        """
        if week_start is None:
            today = datetime.now(UTC).date()
            # Find Monday of current week
            days_since_monday = today.weekday()
            monday = today - timedelta(days=days_since_monday)
            week_start = monday.isoformat()

        # Parse date and calculate time range
        start_date = datetime.fromisoformat(week_start).replace(tzinfo=UTC)
        period_start = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        period_end = period_start + timedelta(days=7)

        # Query task logs for the week
        entries_by_task = self.store.get_entries_by_date_range(
            since=period_start.isoformat(),
            until=period_end.isoformat(),
        )

        # Analyze tasks
        completed_this_week: list[TaskSummary] = []
        delayed_or_blocked: list[TaskSummary] = []
        retrospective_notes: list[str] = []

        for task_id, entries in entries_by_task.items():
            summary = self._create_task_summary(task_id, entries)

            # Categorize by status
            if any(e.event_type == TaskLogEventType.COMPLETED for e in entries):
                completed_this_week.append(summary)
            elif any(
                e.event_type in (TaskLogEventType.BLOCKED, TaskLogEventType.SKIPPED)
                for e in entries
            ):
                delayed_or_blocked.append(summary)

            # Collect retrospective insights
            blocked_entries = [
                e for e in entries if e.event_type == TaskLogEventType.BLOCKED
            ]
            if blocked_entries:
                for entry in blocked_entries:
                    retrospective_notes.append(
                        f"Task {task_id} blocked: {entry.blocked_reason}"
                    )

        return ProgressReport(
            report_type=ReportType.WEEKLY,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            generated_at=datetime.now(UTC).isoformat(),
            completed_this_week=completed_this_week,
            delayed_or_blocked=delayed_or_blocked,
            retrospective_notes=retrospective_notes,
            total_tasks=len(entries_by_task),
        )

    def _create_task_summary(
        self, task_id: str, entries: list[TaskLogEntry]
    ) -> TaskSummary:
        """Create a task summary from log entries.

        Args:
            task_id: Task ID
            entries: List of task log entries

        Returns:
            Task summary
        """
        # Determine current status
        status = "unknown"
        for entry in reversed(entries):
            if entry.event_type == TaskLogEventType.COMPLETED:
                status = "completed"
                break
            elif entry.event_type == TaskLogEventType.BLOCKED:
                status = "blocked"
                break
            elif entry.event_type == TaskLogEventType.STATUS_CHANGED:
                status = entry.new_status or "unknown"
                break

        # Collect events
        event_descriptions = []
        for entry in entries:
            if entry.event_type == TaskLogEventType.STATUS_CHANGED:
                event_descriptions.append(
                    f"{entry.old_status} → {entry.new_status}"
                )
            else:
                event_descriptions.append(entry.event_type.value)

        # Find blocked reason
        blocked_reason = None
        for entry in reversed(entries):
            if entry.event_type == TaskLogEventType.BLOCKED:
                blocked_reason = entry.blocked_reason
                break

        # Collect notes
        notes = [
            entry.note
            for entry in entries
            if entry.event_type == TaskLogEventType.NOTE_ADDED and entry.note
        ]

        return TaskSummary(
            task_id=task_id,
            status=status,
            events=event_descriptions,
            blocked_reason=blocked_reason,
            notes=notes,
        )

    def format_daily_report_markdown(self, report: ProgressReport) -> str:
        """Format daily report as Markdown.

        Args:
            report: Progress report to format

        Returns:
            Markdown formatted report
        """
        lines = [
            f"# Daily Progress Report",
            f"",
            f"**Date:** {report.period_start[:10]}",
            f"**Generated:** {report.generated_at[:19]}",
            f"**Total Tasks:** {report.total_tasks}",
            f"",
        ]

        # Completed today
        lines.append("## ✅ Completed Today")
        lines.append("")
        if report.completed_today:
            for task in report.completed_today:
                lines.append(f"- **{task.task_id}** ({task.status})")
                if task.notes:
                    for note in task.notes:
                        lines.append(f"  - {note}")
        else:
            lines.append("_No tasks completed today._")
        lines.append("")

        # In progress
        lines.append("## 🔄 In Progress")
        lines.append("")
        if report.in_progress:
            for task in report.in_progress:
                lines.append(f"- **{task.task_id}** ({task.status})")
                if task.events:
                    lines.append(f"  - Events: {', '.join(task.events)}")
        else:
            lines.append("_No tasks in progress._")
        lines.append("")

        # Blocked
        lines.append("## 🚫 Blocked")
        lines.append("")
        if report.blocked:
            for task in report.blocked:
                lines.append(f"- **{task.task_id}**")
                if task.blocked_reason:
                    lines.append(f"  - Reason: {task.blocked_reason}")
        else:
            lines.append("_No blocked tasks._")
        lines.append("")

        # Risks
        if report.risks:
            lines.append("## ⚠️ Risks")
            lines.append("")
            for risk in report.risks:
                lines.append(f"- {risk}")
            lines.append("")

        # Tomorrow's plan
        lines.append("## 📅 Tomorrow's Plan")
        lines.append("")
        if report.planned_tomorrow:
            for item in report.planned_tomorrow:
                lines.append(f"- {item}")
        else:
            lines.append("_No specific plans recorded._")
        lines.append("")

        return "\n".join(lines)

    def format_weekly_report_markdown(self, report: ProgressReport) -> str:
        """Format weekly report as Markdown.

        Args:
            report: Progress report to format

        Returns:
            Markdown formatted report
        """
        lines = [
            f"# Weekly Progress Report",
            f"",
            f"**Week:** {report.period_start[:10]} to {report.period_end[:10]}",
            f"**Generated:** {report.generated_at[:19]}",
            f"**Total Tasks:** {report.total_tasks}",
            f"",
        ]

        # Weekly goals
        if report.weekly_goals:
            lines.append("## 🎯 Weekly Goals")
            lines.append("")
            for goal in report.weekly_goals:
                lines.append(f"- {goal}")
            lines.append("")

        # Completed this week
        lines.append("## ✅ Completed This Week")
        lines.append("")
        if report.completed_this_week:
            for task in report.completed_this_week:
                lines.append(f"- **{task.task_id}**")
                if task.notes:
                    for note in task.notes:
                        lines.append(f"  - {note}")
        else:
            lines.append("_No tasks completed this week._")
        lines.append("")

        # Delayed or blocked
        lines.append("## ⏸️ Delayed or Blocked")
        lines.append("")
        if report.delayed_or_blocked:
            for task in report.delayed_or_blocked:
                lines.append(f"- **{task.task_id}** ({task.status})")
                if task.blocked_reason:
                    lines.append(f"  - Reason: {task.blocked_reason}")
        else:
            lines.append("_No delayed or blocked tasks._")
        lines.append("")

        # Next week focus
        lines.append("## 🔜 Next Week Focus")
        lines.append("")
        if report.next_week_focus:
            for item in report.next_week_focus:
                lines.append(f"- {item}")
        else:
            lines.append("_No specific focus areas recorded._")
        lines.append("")

        # Retrospective
        if report.retrospective_notes:
            lines.append("## 💭 Retrospective")
            lines.append("")
            for note in report.retrospective_notes:
                lines.append(f"- {note}")
            lines.append("")

        return "\n".join(lines)
