"""Tiny rule-based planner for the standalone coding agent."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from coding_agent.context import CodingContext
from coding_agent.contract import CodingAction, CodingActionKind, CodingActionResult, CodingTask


class CodingPlanner(Protocol):
    def next_action(
        self,
        task: CodingTask,
        context: CodingContext,
        history: Sequence[CodingActionResult],
    ) -> CodingAction:
        ...


class RuleBasedPlanner:
    """Deterministic read -> edit -> verify loop."""

    def next_action(
        self,
        task: CodingTask,
        context: CodingContext,
        history: Sequence[CodingActionResult],
    ) -> CodingAction:
        if not history:
            if context.target_exists:
                return CodingAction(kind=CodingActionKind.READ, path=task.target_path, reason="inspect target")
            if task.draft_text:
                return CodingAction(kind=CodingActionKind.WRITE, path=task.target_path, content=task.draft_text, reason="apply draft")
            if task.patch_text:
                return CodingAction(
                    kind=CodingActionKind.PATCH,
                    path=task.target_path,
                    content=task.patch_text,
                    line_start=task.line_start,
                    line_end=task.line_end,
                    reason="apply patch",
                )
            if task.validation_command:
                return CodingAction(kind=CodingActionKind.RUN, command=list(task.validation_command), reason="validate current state")
            return CodingAction(kind=CodingActionKind.STOP, reason="nothing to do")

        last = history[-1].action.kind
        if last == CodingActionKind.READ:
            if task.draft_text and context.current_text.strip() != task.draft_text.strip():
                return CodingAction(kind=CodingActionKind.WRITE, path=task.target_path, content=task.draft_text, reason="apply draft")
            if task.patch_text:
                return CodingAction(
                    kind=CodingActionKind.PATCH,
                    path=task.target_path,
                    content=task.patch_text,
                    line_start=task.line_start,
                    line_end=task.line_end,
                    reason="apply patch",
                )
            if task.validation_command:
                return CodingAction(kind=CodingActionKind.RUN, command=list(task.validation_command), reason="validate current state")
            return CodingAction(kind=CodingActionKind.STOP, reason="inspected target")

        if last in {CodingActionKind.WRITE, CodingActionKind.PATCH}:
            if task.validation_command:
                return CodingAction(kind=CodingActionKind.RUN, command=list(task.validation_command), reason="verify change")
            return CodingAction(kind=CodingActionKind.STOP, reason="edit applied")

        if last == CodingActionKind.RUN:
            return CodingAction(kind=CodingActionKind.STOP, reason="verification complete")

        return CodingAction(kind=CodingActionKind.STOP, reason="finished")
