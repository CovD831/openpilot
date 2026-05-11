"""Rule-based clarification for task-progress planning."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field


class ClarificationQuestion(BaseModel):
    field: str
    prompt: str
    reason: str
    default_assumption: str


class ClarificationAnswer(BaseModel):
    field: str
    answer: str


class TaskBrief(BaseModel):
    goal: str
    constraints: list[str] = Field(default_factory=list)
    answers: list[ClarificationAnswer] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    ready_for_planning: bool = True

    def planning_constraints(self) -> list[str]:
        """Return constraints suitable for planner input."""

        constraints = list(self.constraints)
        constraints.extend(
            f"{answer.field}: {answer.answer}"
            for answer in self.answers
            if answer.answer.strip()
        )
        constraints.extend(f"assumption: {item}" for item in self.assumptions)
        return constraints


class Clarifier:
    """Detect missing planning details with deterministic rules."""

    def detect(
        self, goal: str, constraints: list[str] | None = None
    ) -> list[ClarificationQuestion]:
        text = _normalize(goal, constraints)
        questions: list[ClarificationQuestion] = []
        vague_goal = _is_vague_goal(goal)

        if not _has_deadline(text):
            questions.append(QUESTIONS["deadline"])
        if not _has_deliverable(text):
            questions.append(QUESTIONS["deliverables"])

        if vague_goal:
            for field in ("priority", "available_time", "dependencies", "scope"):
                questions.append(QUESTIONS[field])

        seen: set[str] = set()
        unique_questions: list[ClarificationQuestion] = []
        for question in questions:
            if question.field not in seen:
                unique_questions.append(question)
                seen.add(question.field)
        return unique_questions

    def build_brief(
        self,
        goal: str,
        constraints: list[str] | None = None,
        answers: list[ClarificationAnswer] | None = None,
        assume_defaults: bool = False,
    ) -> TaskBrief:
        constraints = constraints or []
        answers = answers or []
        answered_fields = {answer.field for answer in answers if answer.answer.strip()}
        questions = [
            question
            for question in self.detect(goal, constraints)
            if question.field not in answered_fields
        ]
        assumptions = [
            question.default_assumption
            for question in questions
            if assume_defaults
        ]
        return TaskBrief(
            goal=goal,
            constraints=constraints,
            answers=answers,
            assumptions=assumptions,
            missing_fields=[question.field for question in questions],
            ready_for_planning=not questions or assume_defaults,
        )


QUESTIONS = {
    "deadline": ClarificationQuestion(
        field="deadline",
        prompt="What is the deadline or target completion window?",
        reason="A timeline needs a target date or duration.",
        default_assumption="deadline unspecified",
    ),
    "deliverables": ClarificationQuestion(
        field="deliverables",
        prompt="What concrete deliverables should be produced?",
        reason="The plan needs expected outputs to define success.",
        default_assumption="deliverables to be clarified",
    ),
    "priority": ClarificationQuestion(
        field="priority",
        prompt="How urgent or important is this task?",
        reason="Priority affects scheduling and tradeoffs.",
        default_assumption="normal priority assumed",
    ),
    "available_time": ClarificationQuestion(
        field="available_time",
        prompt="How much time can you spend per day or week?",
        reason="Available time affects the timeline.",
        default_assumption="available time unspecified",
    ),
    "dependencies": ClarificationQuestion(
        field="dependencies",
        prompt="Are there dependencies, blockers, or required resources?",
        reason="Dependencies affect execution order and risk.",
        default_assumption="no known blockers assumed",
    ),
    "scope": ClarificationQuestion(
        field="scope",
        prompt="What scope should OpenPilot include or exclude?",
        reason="Scope prevents over-planning.",
        default_assumption="scope to be refined during planning",
    ),
}

DEADLINE_PATTERNS = (
    r"\b(today|tomorrow|this week|next week|deadline|by|before|within)\b",
    r"\b\d+\s*(day|days|week|weeks|month|months)\b",
    r"\b\d{4}-\d{1,2}-\d{1,2}\b",
    r"(今天|明天|本周|下周|截止|之前|以内|内|天|周|月|两周|一周|一个月)",
)

DELIVERABLE_PATTERNS = (
    r"\b(report|brief|prototype|demo|slides|presentation|document|code|test|summary)\b",
    r"(交付|产出|报告|原型|演示|展示|材料|文档|代码|实现|测试|调研|汇报|总结|日报|周报)",
)

VAGUE_GOAL_PATTERNS = (
    r"^\s*(帮我)?规划(一下)?(一个)?项目\s*$",
    r"^\s*(help me )?plan (a )?project\s*$",
    r"^\s*make a plan\s*$",
)


def _normalize(goal: str, constraints: list[str] | None) -> str:
    return "\n".join([goal, *(constraints or [])]).lower()


def _has_deadline(text: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in DEADLINE_PATTERNS)


def _has_deliverable(text: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in DELIVERABLE_PATTERNS)


def _is_vague_goal(goal: str) -> bool:
    normalized = goal.strip().lower()
    if len(normalized) <= 8:
        return True
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in VAGUE_GOAL_PATTERNS)
