"""Autonomous project iteration agent.

The agent composes prompts, functions, and tool calls into a project-wise
iteration pipeline:
Read Project State -> Goal Maker -> Task Designer -> Decomposition ->
Execution -> Modification Evaluation -> Mind System.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Callable

from agents.project_evaluator import ProjectEvaluatorAgent
from core.llm import LLMMessage, LLMRequest
from agents.evaluation_models import (
    AutonomousIterationResult,
    DesignedImprovementTask,
    EvaluationResult,
    ImprovementGoal,
    IterationResult,
    ProjectStateSnapshot,
)
from memory.memory_models import MemoryRecord, MemoryType
from tools.project_improvement_tool import project_state_reader_executor


ApplyImprovement = Callable[[int, EvaluationResult, list[str], dict[str, Any], bool], IterationResult]
AnalyzeImprovements = Callable[[int, EvaluationResult], dict[str, Any]]
ReadProjectState = Callable[[EvaluationResult, int], dict[str, Any]]
ProgressCallback = Callable[[str, dict[str, Any]], None]


class AutonomousIterationAgent:
    """Run a stable autonomous improvement pipeline for generated projects."""

    def __init__(
        self,
        evaluator: ProjectEvaluatorAgent,
        required_successful_iterations: int | None = None,
        required_successful_improvements: int = 2,
        max_iteration_attempts: int = 4,
        llm_client: Any | None = None,
        memory_store: Any | None = None,
    ):
        self.evaluator = evaluator
        if required_successful_iterations is not None:
            required_successful_improvements = required_successful_iterations
        self.required_successful_improvements = required_successful_improvements
        self.max_iteration_attempts = max_iteration_attempts
        self.llm_client = llm_client or getattr(evaluator, "llm_client", None)
        self.memory_store = memory_store

    def run_project_pipeline(
        self,
        *,
        goal: str,
        project_path: str | Path,
        written_files: list[str],
        run_command: str = "",
        readme_path: str | Path | None = None,
        static_review: dict[str, Any] | None = None,
        apply_improvement: ApplyImprovement,
        analyze_improvements: AnalyzeImprovements | None = None,
        read_project_state: ReadProjectState | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        """Validate and improve through the full autonomous iteration pipeline."""
        evaluations: list[EvaluationResult] = []
        iterations: list[IterationResult] = []
        project_states: list[ProjectStateSnapshot] = []
        iteration_goals: list[ImprovementGoal] = []
        designed_tasks: list[DesignedImprovementTask] = []
        mind_notes: list[str] = []
        completed_improvements = 0
        attempts_used = 0
        improvement_report: dict[str, Any] | None = None
        failure_context: dict[str, Any] = {}

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
        self._notify(on_progress, "validation", {"attempt": attempts_used, "evaluation": current, "baseline": True})

        while completed_improvements < self.required_successful_improvements:
            project_state = self._read_project_state(
                reader=read_project_state,
                goal=goal,
                project_path=project_path,
                written_files=written_files,
                run_command=run_command or current.run_command,
                readme_path=readme_path,
                evaluation=current,
                iteration=completed_improvements,
            )
            project_states.append(project_state)
            self._notify(on_progress, "project_state", {"state": project_state, "iteration": completed_improvements})

            if current.validation_passed:
                improvement_report = self._analyze_improvements(
                    analyze_improvements,
                    completed_improvements,
                    current,
                )
                self._notify(
                    on_progress,
                    "improvement_report",
                    {
                        "completed_improvements": completed_improvements,
                        "required_improvements": self.required_successful_improvements,
                        "report": improvement_report,
                    },
                )

                goals = self._make_goals(project_state, current, improvement_report, completed_improvements)
                selected_goal = goals[0]
                iteration_goals.extend(goals)
                self._notify(
                    on_progress,
                    "goal_maker",
                    {"goals": goals, "selected_goal": selected_goal, "iteration": completed_improvements},
                )

                tasks = self._design_tasks(project_state, selected_goal, improvement_report, completed_improvements)
                designed_tasks.extend(tasks)
                self._notify(
                    on_progress,
                    "task_designer",
                    {"tasks": tasks, "selected_goal": selected_goal, "iteration": completed_improvements},
                )
                self._notify(on_progress, "decomposition", {"tasks": tasks, "iteration": completed_improvements})

                actions = self._actions_from_tasks(tasks)
                improvement_report = {
                    **improvement_report,
                    "selected_goal": selected_goal.model_dump(),
                    "designed_tasks": [task.model_dump() for task in tasks],
                    "next_iteration_goal": selected_goal.title,
                    "must_implement_next": selected_goal.acceptance_criteria,
                }
                is_repair = False
            else:
                goals = []
                tasks = []
                improvement_report = {}
                actions = self._select_repair_actions(current)
                is_repair = True

            if attempts_used >= self.max_iteration_attempts:
                self._notify(
                    on_progress,
                    "max_attempts_reached",
                    {
                        "attempts_used": attempts_used,
                        "max_iteration_attempts": self.max_iteration_attempts,
                        "completed_improvements": completed_improvements,
                        "required_improvements": self.required_successful_improvements,
                        "evaluation": current,
                    },
                )
                break

            attempts_used += 1
            self._notify(
                on_progress,
                "iteration_started",
                {
                    "iteration": attempts_used,
                    "completed_improvements": completed_improvements,
                    "required_improvements": self.required_successful_improvements,
                    "actions": actions,
                    "repair": is_repair,
                    "improvement_report": improvement_report,
                },
            )

            iteration_result = apply_improvement(attempts_used, current, actions, improvement_report, is_repair)
            if not iteration_result.success:
                failure_context = self._failure_context(
                    iteration_result,
                    attempts_used,
                    "Task Executor",
                    actions,
                    improvement_report,
                    completed_improvements,
                )
                note = self._record_mind_note(
                    goal,
                    attempts_used,
                    False,
                    actions,
                    iteration_result.failure_reason or iteration_result.error,
                    failure_context,
                )
                mind_notes.append(note)
                self._notify(on_progress, "mind_system", {"note": note, "iteration": attempts_used})
                self._notify(
                    on_progress,
                    "iteration_failed",
                    {"iteration": attempts_used, "result": iteration_result, **failure_context},
                )
                break

            current = self.evaluator.evaluate_project(
                goal=goal,
                project_path=project_path,
                written_files=written_files,
                run_command=run_command,
                readme_path=readme_path,
                static_review=static_review,
                iteration=attempts_used,
            )
            iteration_result.validation_passed = current.validation_passed
            iteration_result.completed_successful_iteration = self._evaluate_modification(
                current,
                iteration_result,
                tasks,
                is_repair,
            )
            evaluations.append(current)
            self._notify(
                on_progress,
                "modification_evaluation",
                {
                    "iteration": attempts_used,
                    "evaluation": current,
                    "result": iteration_result,
                    "tasks": tasks,
                },
            )

            if iteration_result.completed_successful_iteration:
                completed_improvements += 1
                iterations.append(iteration_result)
                failure_context = {}
                self._notify(
                    on_progress,
                    "successful_improvement",
                    {
                        "completed_improvements": completed_improvements,
                        "required_improvements": self.required_successful_improvements,
                        "evaluation": current,
                        "result": iteration_result,
                    },
                )
            elif not is_repair:
                failure_context = self._failure_context(
                    iteration_result,
                    attempts_used,
                    "Modification Evaluator",
                    actions,
                    improvement_report,
                    completed_improvements,
                    default_reason="Modification did not satisfy validation or change requirements.",
                )
                iterations.append(iteration_result)

            note = self._record_mind_note(
                goal,
                attempts_used,
                iteration_result.completed_successful_iteration,
                actions,
                iteration_result.error or current.summary,
                failure_context if not iteration_result.completed_successful_iteration else None,
            )
            mind_notes.append(note)
            self._notify(on_progress, "mind_system", {"note": note, "iteration": attempts_used})
            self._notify(on_progress, "validation", {"attempt": attempts_used, "evaluation": current, "baseline": False})
            self._notify(
                on_progress,
                "iteration_completed",
                {"iteration": attempts_used, "result": iteration_result, "evaluation": current},
            )

        success = completed_improvements >= self.required_successful_improvements and current.validation_passed
        partial_success = bool(current.validation_passed or (evaluations and evaluations[0].validation_passed))
        remaining_goals = self._remaining_goal_titles(iteration_goals, completed_improvements)
        agent_result = AutonomousIterationResult(
            project_state=project_states[-1] if project_states else None,
            iteration_goals=iteration_goals,
            designed_tasks=designed_tasks,
            evaluations=evaluations,
            iterations=iterations,
            mind_notes=mind_notes,
        )
        return {
            "success": success,
            "partial_success": partial_success and not success,
            "completed_improvements": completed_improvements,
            "required_improvements": self.required_successful_improvements,
            "completed_iterations": completed_improvements,
            "required_iterations": self.required_successful_improvements,
            "attempts_used": attempts_used,
            "max_iteration_attempts": self.max_iteration_attempts,
            "validation": current,
            "evaluation": current,
            "evaluations": evaluations,
            "iterations": iterations,
            "improvement_report": improvement_report or {},
            "project_state": agent_result.project_state,
            "project_states": project_states,
            "iteration_goals": iteration_goals,
            "designed_tasks": designed_tasks,
            "mind_notes": mind_notes,
            "autonomous_iteration": agent_result,
            "failure_stage": failure_context.get("failure_stage"),
            "failed_iteration": failure_context.get("failed_iteration"),
            "failed_tool": failure_context.get("failed_tool"),
            "failure_reason": failure_context.get("failure_reason"),
            "last_successful_iteration": completed_improvements,
            "remaining_goals": remaining_goals,
        }

    def run(self, **kwargs) -> dict[str, Any]:
        """Backward-compatible entry point."""
        return self.run_project_pipeline(**kwargs)

    def _read_project_state(
        self,
        *,
        reader: ReadProjectState | None,
        goal: str,
        project_path: str | Path,
        written_files: list[str],
        run_command: str,
        readme_path: str | Path | None,
        evaluation: EvaluationResult,
        iteration: int,
    ) -> ProjectStateSnapshot:
        params = {
            "project_path": str(project_path),
            "goal": goal,
            "written_files": written_files,
            "run_command": run_command,
            "readme_path": str(readme_path) if readme_path else "",
            "memory_query": f"{goal} iteration {iteration}",
            "validation_context": evaluation.model_dump(),
        }
        if reader is not None:
            payload = reader(evaluation, iteration)
        else:
            payload = project_state_reader_executor({**params, "_memory_store": self.memory_store})
        return ProjectStateSnapshot(**payload)

    def _make_goals(
        self,
        project_state: ProjectStateSnapshot,
        evaluation: EvaluationResult,
        improvement_report: dict[str, Any],
        completed_iteration: int,
    ) -> list[ImprovementGoal]:
        prompt = (
            "You are OpenPilot's Goal Maker Agent. Create 1-3 concrete, evaluable project "
            "improvement goals. Avoid vague goals like 'make it better'. Return ONLY JSON.\n\n"
            f"Completed successful improvements: {completed_iteration}\n"
            f"Project state JSON: {project_state.model_dump_json()}\n"
            f"Validation JSON: {evaluation.model_dump_json()}\n"
            f"Improvement report JSON: {json.dumps(improvement_report, ensure_ascii=False, default=str)}\n\n"
            "Return: {\"goals\": [{\"id\":\"goal_1\",\"title\":\"specific goal\","
            "\"category\":\"feature|ux|robustness|code_quality|documentation\","
            "\"rationale\":\"public reason\",\"acceptance_criteria\":[\"observable criterion\"],"
            "\"priority\":\"high|medium|low\"}]}"
        )
        payload = self._complete_json(prompt)
        goals = []
        for index, raw_goal in enumerate((payload or {}).get("goals") or [], 1):
            goal = self._coerce_goal(raw_goal, index)
            if goal is not None:
                goals.append(goal)
        return goals or [self._fallback_goal(improvement_report, evaluation)]

    def _design_tasks(
        self,
        project_state: ProjectStateSnapshot,
        goal: ImprovementGoal,
        improvement_report: dict[str, Any],
        completed_iteration: int,
    ) -> list[DesignedImprovementTask]:
        prompt = (
            "You are OpenPilot's Task Designer Agent. Convert one improvement goal into 1-2 "
            "specific implementation tasks with target files and acceptance criteria. Return ONLY JSON.\n\n"
            f"Completed successful improvements: {completed_iteration}\n"
            f"Selected goal JSON: {goal.model_dump_json()}\n"
            f"Project state JSON: {project_state.model_dump_json()}\n"
            f"Improvement report JSON: {json.dumps(improvement_report, ensure_ascii=False, default=str)}\n\n"
            "Return: {\"tasks\": [{\"id\":\"task_1\",\"goal_id\":\"goal_1\","
            "\"description\":\"specific implementation task\",\"target_files\":[\"path\"],"
            "\"acceptance_criteria\":[\"observable criterion\"],\"risk_notes\":[\"risk or empty\"]}]}"
        )
        payload = self._complete_json(prompt)
        tasks = []
        for index, raw_task in enumerate((payload or {}).get("tasks") or [], 1):
            task = self._coerce_task(raw_task, goal, project_state, index)
            if task is not None:
                tasks.append(task)
        return (tasks or [self._fallback_task(goal, project_state)])[:1]

    def _complete_json(self, prompt: str) -> dict[str, Any] | None:
        if not self.llm_client or not hasattr(self.llm_client, "complete"):
            return None
        try:
            response = self.llm_client.complete(
                LLMRequest(
                    messages=[LLMMessage(role="user", content=prompt)],
                    response_format="json_object",
                    temperature=0.2,
                ),
                max_retries=2,
                use_cache=False,
            )
        except Exception:
            return None
        if isinstance(response.parsed_json, dict):
            return response.parsed_json
        try:
            return json.loads(response.content)
        except (TypeError, json.JSONDecodeError):
            return None

    def _coerce_goal(self, raw_goal: Any, index: int) -> ImprovementGoal | None:
        if not isinstance(raw_goal, dict):
            return None
        title = str(raw_goal.get("title") or "").strip()
        if not title or title.lower() in {"make the project better", "improve the project", "make it better"}:
            return None
        criteria = self._coerce_string_list(raw_goal.get("acceptance_criteria"))
        return ImprovementGoal(
            id=str(raw_goal.get("id") or f"goal_{index}"),
            title=title,
            category=str(raw_goal.get("category") or "feature"),
            rationale=str(raw_goal.get("rationale") or ""),
            acceptance_criteria=criteria or [f"The project visibly implements: {title}"],
            priority=str(raw_goal.get("priority") or "medium"),
        )

    def _coerce_task(
        self,
        raw_task: Any,
        goal: ImprovementGoal,
        project_state: ProjectStateSnapshot,
        index: int,
    ) -> DesignedImprovementTask | None:
        if not isinstance(raw_task, dict):
            return None
        description = str(raw_task.get("description") or "").strip()
        if not description:
            return None
        target_files = self._coerce_string_list(raw_task.get("target_files")) or project_state.safe_target_files[:1]
        return DesignedImprovementTask(
            id=str(raw_task.get("id") or f"task_{index}"),
            goal_id=str(raw_task.get("goal_id") or goal.id),
            description=description,
            target_files=target_files,
            acceptance_criteria=self._coerce_string_list(raw_task.get("acceptance_criteria")) or goal.acceptance_criteria,
            risk_notes=self._coerce_string_list(raw_task.get("risk_notes")),
        )

    def _fallback_goal(self, report: dict[str, Any], evaluation: EvaluationResult) -> ImprovementGoal:
        next_goal = str(report.get("next_iteration_goal") or evaluation.next_iteration_goal or "").strip()
        if not next_goal:
            actions = self._coerce_string_list(report.get("recommended_actions")) or evaluation.recommended_actions
            next_goal = actions[0] if actions else "Add one visible, testable improvement aligned with the original goal."
        criteria = self._coerce_string_list(report.get("must_implement_next")) or [f"Implemented and visible: {next_goal}"]
        return ImprovementGoal(
            id=f"goal_{uuid.uuid4().hex[:8]}",
            title=next_goal,
            category="feature",
            rationale=str(report.get("summary") or evaluation.summary),
            acceptance_criteria=criteria,
            priority="high",
        )

    def _fallback_task(self, goal: ImprovementGoal, project_state: ProjectStateSnapshot) -> DesignedImprovementTask:
        return DesignedImprovementTask(
            id=f"task_{uuid.uuid4().hex[:8]}",
            goal_id=goal.id,
            description=goal.title,
            target_files=project_state.safe_target_files[:1],
            acceptance_criteria=goal.acceptance_criteria,
            risk_notes=[],
        )

    def _actions_from_tasks(self, tasks: list[DesignedImprovementTask]) -> list[str]:
        actions = []
        for task in tasks[:2]:
            actions.append(task.description)
        return actions or ["Apply one concrete project improvement."]

    def _evaluate_modification(
        self,
        evaluation: EvaluationResult,
        iteration_result: IterationResult,
        tasks: list[DesignedImprovementTask],
        is_repair: bool,
    ) -> bool:
        notes = []
        if not evaluation.validation_passed:
            notes.append("Hard validation did not pass after modification.")
        if not iteration_result.changed_files:
            notes.append("No changed files were reported by the task executor.")
        if tasks:
            criteria = [item for task in tasks for item in task.acceptance_criteria]
            if criteria:
                notes.append("Acceptance criteria reviewed: " + "; ".join(criteria[:4]))
        iteration_result.evaluation_notes = notes
        if notes and not iteration_result.failure_reason:
            iteration_result.failure_reason = "; ".join(notes)
            iteration_result.failure_stage = "Modification Evaluator"
        return bool(evaluation.validation_passed and not is_repair and iteration_result.changed_files)

    def _record_mind_note(
        self,
        goal: str,
        iteration: int,
        success: bool,
        actions: list[str],
        detail: str | None,
        failure_context: dict[str, Any] | None = None,
    ) -> str:
        state = "succeeded" if success else "failed"
        note = f"Iteration {iteration} {state}: {'; '.join(actions[:2])}"
        if detail:
            note += f" | {detail}"
        if failure_context:
            note += (
                f" | stage={failure_context.get('failure_stage') or 'unknown'}"
                f" tool={failure_context.get('failed_tool') or 'unknown'}"
            )
        if self.memory_store and hasattr(self.memory_store, "save"):
            try:
                self.memory_store.save(
                    MemoryRecord(
                        id="",
                        memory_type=MemoryType.PROJECT if success else MemoryType.TASK,
                        content=note,
                        tags=["autonomous_iteration", state, "project"],
                        confidence=0.8 if success else 0.45,
                        metadata={
                            "goal": goal,
                            "iteration": iteration,
                            "success": success,
                            **(failure_context or {}),
                        },
                    )
                )
            except Exception:
                pass
        return note

    def _analyze_improvements(
        self,
        analyzer: AnalyzeImprovements | None,
        completed_iterations: int,
        evaluation: EvaluationResult,
    ) -> dict[str, Any]:
        if analyzer is None:
            return {
                "summary": evaluation.summary,
                "improvement_opportunities": evaluation.improvement_opportunities,
                "recommended_actions": evaluation.recommended_actions,
                "next_iteration_goal": evaluation.next_iteration_goal,
                "blocking_risks": evaluation.validation_errors,
            }
        report = analyzer(completed_iterations, evaluation)
        return report if isinstance(report, dict) else {}

    def _select_repair_actions(self, evaluation: EvaluationResult) -> list[str]:
        if evaluation.recommended_actions:
            return evaluation.recommended_actions[:2]
        if evaluation.validation_errors:
            return evaluation.validation_errors[:2]
        return ["Fix the blocking validation errors before adding new features."]

    def _coerce_string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value)]

    def _failure_context(
        self,
        iteration_result: IterationResult,
        iteration: int,
        stage: str,
        actions: list[str],
        improvement_report: dict[str, Any] | None,
        completed_improvements: int,
        default_reason: str | None = None,
    ) -> dict[str, Any]:
        selected_goal = (improvement_report or {}).get("selected_goal") or {}
        designed_tasks = (improvement_report or {}).get("designed_tasks") or []
        reason = (
            iteration_result.failure_reason
            or iteration_result.error
            or default_reason
            or "Iteration failed before completing the required improvement."
        )
        failed_tool = iteration_result.failed_tool
        if not failed_tool and "timeout" in reason.lower():
            failed_tool = "code_generator"
        iteration_result.failure_stage = iteration_result.failure_stage or stage
        iteration_result.failed_tool = failed_tool
        iteration_result.failure_reason = reason
        return {
            "failure_stage": iteration_result.failure_stage,
            "failed_iteration": iteration,
            "failed_tool": failed_tool,
            "failure_reason": reason,
            "failed_actions": actions,
            "selected_goal": selected_goal,
            "designed_tasks": designed_tasks,
            "completed_improvements": completed_improvements,
            "required_improvements": self.required_successful_improvements,
        }

    def _remaining_goal_titles(self, goals: list[ImprovementGoal], completed_improvements: int) -> list[str]:
        titles = []
        for goal in goals[completed_improvements:]:
            if goal.title not in titles:
                titles.append(goal.title)
        return titles

    def _notify(self, callback: ProgressCallback | None, event: str, payload: dict[str, Any]) -> None:
        if callback:
            callback(event, payload)


class IterativeImprovementController(AutonomousIterationAgent):
    """Backward-compatible name for the autonomous iteration agent."""
