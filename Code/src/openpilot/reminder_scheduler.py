"""Build local reminder plans from task timelines."""

from __future__ import annotations

from openpilot.planner_models import ExecutionPlan, TaskStatus, TimelinePlan
from openpilot.reminder_models import ReminderItem, ReminderPlan, ReminderType


class ReminderScheduler:
    """Create planning-only reminders without triggering notifications."""

    def build(self, plan: ExecutionPlan | TimelinePlan) -> ReminderPlan:
        timeline = plan.timeline if isinstance(plan, ExecutionPlan) else plan
        if timeline is None:
            return ReminderPlan(
                goal=plan.task_card.goal if isinstance(plan, ExecutionPlan) else "",
                notes=["No timeline available; reminder plan is empty."],
            )

        items: list[ReminderItem] = []
        for index, slot in enumerate(timeline.timeline, start=1):
            task_id = slot.task_ids[0] if slot.task_ids else slot.id
            start_label = _stable_label(slot.start_label, f"phase {index} start")
            end_label = _stable_label(slot.end_label, f"phase {index} review")
            items.append(
                ReminderItem(
                    id=f"{slot.id}-start",
                    task_id=task_id,
                    title=f"Start: {slot.title}",
                    remind_at=start_label,
                    reason="Start this planned task window.",
                    reminder_type=ReminderType.START,
                )
            )
            items.append(
                ReminderItem(
                    id=f"{slot.id}-before-due",
                    task_id=task_id,
                    title=f"Review before due: {slot.title}",
                    remind_at=end_label,
                    reason="Check progress before this task window ends.",
                    reminder_type=ReminderType.BEFORE_DUE,
                )
            )
            if slot.status is TaskStatus.BLOCKED:
                items.append(
                    ReminderItem(
                        id=f"{slot.id}-blocked-review",
                        task_id=task_id,
                        title=f"Review blocker: {slot.title}",
                        remind_at=f"{end_label} blocker review",
                        reason="Blocked tasks need an explicit follow-up check.",
                        reminder_type=ReminderType.BLOCKED_REVIEW,
                    )
                )

        if timeline.timeline:
            items.append(
                ReminderItem(
                    id="daily-report",
                    task_id="progress-report",
                    title="Prepare daily progress report",
                    remind_at="end of each planned day",
                    reason="Summarize completed, active, and blocked tasks.",
                    reminder_type=ReminderType.DAILY_REPORT,
                )
            )
            items.append(
                ReminderItem(
                    id="weekly-report",
                    task_id="progress-report",
                    title="Prepare weekly progress report",
                    remind_at="end of each planned week",
                    reason="Review weekly progress, risks, and next priorities.",
                    reminder_type=ReminderType.WEEKLY_REPORT,
                )
            )

        return ReminderPlan(
            goal=timeline.goal,
            items=items,
            notes=["Local plan only; no system notifications, calendar events, or emails are created."],
        )


def _stable_label(value: str, fallback: str) -> str:
    normalized = value.strip()
    return normalized if normalized else fallback
