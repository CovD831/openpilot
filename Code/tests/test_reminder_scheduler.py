from openpilot.planner_models import (
    ExecutionPlan,
    RiskLevel,
    TaskCard,
    TimelinePlan,
    TimelineSlot,
)
from openpilot.reminder_models import ReminderStatus, ReminderType
from openpilot.reminder_scheduler import ReminderScheduler


def test_reminder_scheduler_builds_start_and_due_reminders():
    timeline = TimelinePlan(
        goal="Ship a project",
        timeline=[
            TimelineSlot(
                id="slot-1",
                title="Clarify scope",
                task_ids=["step-1"],
                start_label="day 1",
                end_label="day 2",
            )
        ],
    )

    reminder_plan = ReminderScheduler().build(timeline)

    assert len(reminder_plan.items) >= 2
    assert reminder_plan.items[0].reminder_type == ReminderType.START
    assert reminder_plan.items[0].status == ReminderStatus.PLANNED
    assert reminder_plan.items[0].channel == "local_plan_only"
    assert reminder_plan.items[1].reminder_type == ReminderType.BEFORE_DUE


def test_reminder_scheduler_uses_stable_fallback_labels():
    timeline = TimelinePlan(
        goal="Ship a project",
        timeline=[
            TimelineSlot(
                id="slot-1",
                title="Clarify scope",
                task_ids=[],
                start_label="",
                end_label="",
            )
        ],
    )

    reminder_plan = ReminderScheduler().build(timeline)

    assert reminder_plan.items[0].remind_at == "phase 1 start"
    assert reminder_plan.items[1].remind_at == "phase 1 review"


def test_reminder_scheduler_handles_execution_plan_without_timeline():
    plan = ExecutionPlan(
        task_card=TaskCard(
            goal="Plan a project",
            task_type="planning",
            risk_level=RiskLevel.LOW,
        ),
        steps=[],
    )

    reminder_plan = ReminderScheduler().build(plan)

    assert reminder_plan.goal == "Plan a project"
    assert reminder_plan.items == []
    assert "No timeline available" in reminder_plan.notes[0]


def test_reminder_plan_serializes_to_json():
    timeline = TimelinePlan(
        goal="Ship a project",
        timeline=[
            TimelineSlot(
                id="slot-1",
                title="Clarify scope",
                task_ids=["step-1"],
                start_label="day 1",
                end_label="day 2",
            )
        ],
    )

    payload = ReminderScheduler().build(timeline).model_dump(mode="json")

    assert payload["items"][0]["status"] == "planned"
    assert payload["items"][0]["reminder_type"] == "start"
