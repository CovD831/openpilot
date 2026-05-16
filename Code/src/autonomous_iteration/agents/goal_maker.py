"""Goal Maker agent facade."""

from __future__ import annotations

from typing import Any, Callable


class GoalMakerAgent:
    """Generate improvement goals from context."""

    def __init__(self, delegate: Callable[..., list[Any]]) -> None:
        self.delegate = delegate

    def run(self, project_state: Any, evaluation: Any, improvement_report: dict[str, Any], completed_iteration: int) -> list[Any]:
        return self.delegate(project_state, evaluation, improvement_report, completed_iteration)
