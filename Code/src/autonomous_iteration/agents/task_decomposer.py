"""Task Decomposer agent facade."""

from __future__ import annotations

from typing import Any, Callable


class TaskDecomposerAgent:
    """Decompose tasks until they are easy enough to execute."""

    def __init__(
        self,
        action_builder: Callable[[list[Any]], list[str]],
        difficulty_evaluator: Callable[[list[Any]], dict[str, Any]],
        *,
        easy_threshold: int = 4,
        max_depth: int = 3,
    ) -> None:
        self.action_builder = action_builder
        self.difficulty_evaluator = difficulty_evaluator
        self.easy_threshold = easy_threshold
        self.max_depth = max_depth

    def run(self, tasks: list[Any], context: dict[str, Any] | None = None, depth: int = 0) -> dict[str, Any]:
        difficulty = self.difficulty_evaluator(tasks)
        if difficulty["score"] <= self.easy_threshold or depth >= self.max_depth:
            return {
                "actions": self.action_builder(tasks),
                "difficulty": difficulty,
                "depth": depth,
                "subtasks": tasks,
            }

        subtasks = self._split_tasks(tasks)
        if subtasks == tasks:
            return {
                "actions": self.action_builder(tasks),
                "difficulty": difficulty,
                "depth": depth,
                "subtasks": tasks,
            }
        return self.run(subtasks, context=context, depth=depth + 1)

    def _split_tasks(self, tasks: list[Any]) -> list[Any]:
        split = []
        for task in tasks:
            target_files = list(getattr(task, "target_files", []) or [])
            if len(target_files) <= 1:
                split.append(task)
                continue
            for index, target_file in enumerate(target_files, 1):
                clone = task.model_copy(deep=True)
                clone.id = f"{task.id}_subtask_{index}"
                clone.target_files = [target_file]
                clone.description = f"{task.description} ({target_file})"
                split.append(clone)
        return split
