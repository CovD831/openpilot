"""Deterministic task-tree and timeline construction."""

from __future__ import annotations

import re

from openpilot.planner_models import (
    ExecutionPlan,
    TaskNode,
    TimelinePlan,
    TimelineSlot,
)


TIME_HORIZON_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(两周|2\s*周|14\s*天|two[-\s]?weeks?|14\s*days?)", re.I), "within two weeks"),
    (re.compile(r"(一周|1\s*周|7\s*天|one[-\s]?week|7\s*days?)", re.I), "within one week"),
    (re.compile(r"(一个月|1\s*个月|30\s*天|one[-\s]?month|30\s*days?)", re.I), "within one month"),
)


def attach_timeline(plan: ExecutionPlan) -> ExecutionPlan:
    """Attach a normalized timeline derived from the validated execution steps."""

    timeline = build_timeline(plan)
    return plan.model_copy(update={"timeline": timeline})


def build_timeline(plan: ExecutionPlan) -> TimelinePlan:
    """Create a planning-only task tree and timeline from an execution plan."""

    time_horizon = _extract_time_horizon(plan)
    nodes = [
        TaskNode(
            id=step.id,
            title=step.title,
            description=step.description,
            risk_level=step.risk_level,
            required_resources=step.required_resources,
            expected_output=step.expected_output,
            dependencies=step.dependencies,
            confirmation_required=step.confirmation_required,
        )
        for step in plan.steps
    ]
    slots = [
        TimelineSlot(
            id=f"slot-{index}",
            title=step.title,
            task_ids=[step.id],
            start_label=start_label,
            end_label=end_label,
        )
        for index, (step, (start_label, end_label)) in enumerate(
            zip(plan.steps, _timeline_labels(len(plan.steps), time_horizon)),
            start=1,
        )
    ]
    reminders = [
        f"Review progress before {slot.end_label}: {slot.title}"
        for slot in slots
    ]
    milestones = [
        f"{step.id}: {step.expected_output}"
        for step in plan.steps
        if step.expected_output
    ]
    notes = [
        "Planning-only timeline; no calendar reminders or tools are executed.",
    ]

    return TimelinePlan(
        goal=plan.task_card.goal,
        time_horizon=time_horizon,
        task_tree=nodes,
        timeline=slots,
        reminder_plan=reminders,
        milestones=milestones,
        notes=notes,
    )


def _extract_time_horizon(plan: ExecutionPlan) -> str:
    text = "\n".join(
        [
            plan.task_card.goal,
            *plan.task_card.constraints,
            *plan.task_card.expected_deliverables,
        ]
    )
    for pattern, label in TIME_HORIZON_PATTERNS:
        if pattern.search(text):
            return label
    return "unspecified"


def _timeline_labels(count: int, time_horizon: str) -> list[tuple[str, str]]:
    if count <= 0:
        return []

    total_days = {
        "within one week": 7,
        "within two weeks": 14,
        "within one month": 30,
    }.get(time_horizon)

    if total_days is None:
        return [(f"phase {index}", f"phase {index}") for index in range(1, count + 1)]

    labels: list[tuple[str, str]] = []
    for index in range(1, count + 1):
        start_day = int(((index - 1) * total_days) / count) + 1
        end_day = max(start_day, int((index * total_days) / count))
        labels.append((f"day {start_day}", f"day {end_day}"))
    return labels
