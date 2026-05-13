"""Iterative project improvement controller."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from agents.project_evaluator import ProjectEvaluatorAgent
from models.evaluation_models import EvaluationResult, IterationResult


ApplyImprovement = Callable[[int, EvaluationResult, list[str]], IterationResult]
ProgressCallback = Callable[[str, dict[str, Any]], None]


class IterativeImprovementController:
    """Run evaluate-improve-evaluate loops for generated projects."""

    def __init__(
        self,
        evaluator: ProjectEvaluatorAgent,
        satisfaction_threshold: float = 0.85,
        max_iterations: int = 2,
    ):
        self.evaluator = evaluator
        self.satisfaction_threshold = satisfaction_threshold
        self.max_iterations = max_iterations

    def run(
        self,
        *,
        goal: str,
        project_path: str | Path,
        written_files: list[str],
        run_command: str = "",
        readme_path: str | Path | None = None,
        static_review: dict[str, Any] | None = None,
        apply_improvement: ApplyImprovement,
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        """Evaluate a project and apply bounded improvements until approved."""
        evaluations: list[EvaluationResult] = []
        iterations: list[IterationResult] = []

        current = self.evaluator.evaluate_project(
            goal=goal,
            project_path=project_path,
            written_files=written_files,
            run_command=run_command,
            readme_path=readme_path,
            static_review=static_review,
            iteration=0,
        )
        evaluations.append(current)
        self._notify(on_progress, "evaluation", {"iteration": 0, "evaluation": current})

        iteration_number = 0
        while (
            not current.approved
            and current.satisfaction_score < self.satisfaction_threshold
            and iteration_number < self.max_iterations
        ):
            iteration_number += 1
            actions = self._select_actions(current)
            self._notify(
                on_progress,
                "iteration_started",
                {
                    "iteration": iteration_number,
                    "before_score": current.satisfaction_score,
                    "actions": actions,
                },
            )
            iteration_result = apply_improvement(iteration_number, current, actions)
            iterations.append(iteration_result)

            if not iteration_result.success:
                self._notify(
                    on_progress,
                    "iteration_failed",
                    {"iteration": iteration_number, "result": iteration_result},
                )
                break

            current = self.evaluator.evaluate_project(
                goal=goal,
                project_path=project_path,
                written_files=written_files,
                run_command=run_command,
                readme_path=readme_path,
                static_review=static_review,
                iteration=iteration_number,
            )
            iteration_result.after_score = current.satisfaction_score
            evaluations.append(current)
            self._notify(
                on_progress,
                "iteration_completed",
                {
                    "iteration": iteration_number,
                    "result": iteration_result,
                    "evaluation": current,
                },
            )

        return {
            "approved": current.approved,
            "evaluation": current,
            "evaluations": evaluations,
            "iterations": iterations,
            "satisfaction_threshold": self.satisfaction_threshold,
            "max_iterations": self.max_iterations,
        }

    def _select_actions(self, evaluation: EvaluationResult) -> list[str]:
        if evaluation.recommended_actions:
            return evaluation.recommended_actions[:2]
        if evaluation.improvement_opportunities:
            return evaluation.improvement_opportunities[:2]
        if evaluation.next_iteration_goal:
            return [evaluation.next_iteration_goal]
        return ["Improve the project based on the evaluation findings."]

    def _notify(self, callback: ProgressCallback | None, event: str, payload: dict[str, Any]) -> None:
        if callback:
            callback(event, payload)
