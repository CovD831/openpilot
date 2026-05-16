"""Task Designer agent facade."""

from __future__ import annotations

from typing import Any, Callable


class TaskDesignerAgent:
    """Design concrete tasks from one improvement goal."""

    def __init__(self, delegate: Callable[..., list[Any]]) -> None:
        self.delegate = delegate

    def run(self, project_state: Any, goal: Any, improvement_report: dict[str, Any], completed_iteration: int) -> list[Any]:
        return self.delegate(project_state, goal, improvement_report, completed_iteration)
