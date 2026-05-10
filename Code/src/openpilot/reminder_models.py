"""Pydantic contracts for local reminder planning."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ReminderStatus(str, Enum):
    PLANNED = "planned"
    SENT = "sent"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ReminderType(str, Enum):
    START = "start"
    BEFORE_DUE = "before_due"
    BLOCKED_REVIEW = "blocked_review"
    DAILY_REPORT = "daily_report"
    WEEKLY_REPORT = "weekly_report"


class ReminderItem(BaseModel):
    id: str
    task_id: str
    title: str
    remind_at: str
    reason: str
    channel: str = "local_plan_only"
    status: ReminderStatus = ReminderStatus.PLANNED
    reminder_type: ReminderType


class ReminderPlan(BaseModel):
    goal: str
    items: list[ReminderItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
