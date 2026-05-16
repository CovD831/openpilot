"""Task Executor agent facade."""

from __future__ import annotations

from typing import Any, Callable

from autonomous_iteration.models import IterationResult


class TaskExecutorAgent:
    """Execute decomposed subtasks through the provided executor callback."""

    def __init__(self, executor: Callable[..., IterationResult]) -> None:
        self.executor = executor

    def run(
        self,
        iteration: int,
        evaluation: Any,
        actions: list[str],
        improvement_report: dict[str, Any],
        is_repair: bool,
    ) -> IterationResult:
        try:
            return self.executor(iteration, evaluation, actions, improvement_report, is_repair)
        except Exception as exc:
            return IterationResult(
                iteration=iteration,
                validation_passed=False,
                completed_successful_iteration=False,
                applied_actions=actions,
                changed_files=[],
                success=False,
                error=str(exc),
                failure_stage="Task Executor",
                failure_reason=f"Task Executor failed: {type(exc).__name__}: {str(exc)[:300]}",
            )
