"""Autonomous project iteration agent.

The agent composes prompts, functions, and tool calls into a project-wise
iteration pipeline:
Read Project State -> Goal Maker -> Task Designer -> Decomposition ->
Execution -> Modification Evaluation -> Mind System.
"""

from __future__ import annotations

import json
import math
import uuid
from pathlib import Path
from typing import Any, Callable

from autonomous_iteration.agents.context_loader import ContextLoaderAgent
from autonomous_iteration.agents.goal_maker import GoalMakerAgent
from autonomous_iteration.agents.project_evaluator import ProjectEvaluatorAgent
from autonomous_iteration.agents.task_decomposer import TaskDecomposerAgent
from autonomous_iteration.agents.task_designer import TaskDesignerAgent
from autonomous_iteration.pipeline import AutonomousIterationPipeline
from autonomous_iteration.project_diagnosis import ProjectDiagnoser, ReferenceProvider
from core.llm import LLMMessage, LLMRequest
from autonomous_iteration.models import (
    AutonomousIterationResult,
    DesignedImprovementTask,
    EvaluationResult,
    ImprovementGoal,
    IterationResult,
    ProjectStateSnapshot,
)
from memory.memory_models import MemoryRecord, MemoryType
from autonomous_iteration.tool.project_improvement_tool import project_state_reader_executor
from metadata import ProjectObjectiveMetadata, SuccessMetricMetadata, ToolInputMetadata


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
        memory_context_builder: Any | None = None,
        logger: Any | None = None,
        project_objective_override: ProjectObjectiveMetadata | None = None,
        success_metric_overrides: list[SuccessMetricMetadata] | None = None,
        preferred_improvement_dimensions: list[str] | None = None,
        disallowed_improvement_directions: list[str] | None = None,
        allow_reference_search: bool = True,
        reference_provider: ReferenceProvider | None = None,
    ):
        self.evaluator = evaluator
        if required_successful_iterations is not None:
            required_successful_improvements = required_successful_iterations
        self.required_successful_improvements = required_successful_improvements
        self.max_iteration_attempts = max(
            max_iteration_attempts,
            self.minimum_attempt_budget(required_successful_improvements),
        )
        self.llm_client = llm_client or getattr(evaluator, "llm_client", None)
        self.memory_store = memory_store
        self.memory_context_builder = memory_context_builder
        self.logger = logger
        self.project_diagnoser = ProjectDiagnoser(
            objective_override=project_objective_override,
            metric_overrides=success_metric_overrides,
            preferred_dimensions=preferred_improvement_dimensions,
            disallowed_directions=disallowed_improvement_directions,
            allow_reference_search=allow_reference_search,
            reference_provider=reference_provider,
        )
        self.pipeline = AutonomousIterationPipeline(
            context_loader=ContextLoaderAgent(memory_context_builder),
            goal_maker=GoalMakerAgent(self._make_goals),
            task_designer=TaskDesignerAgent(self._design_tasks),
            task_decomposer=TaskDecomposerAgent(
                self._actions_from_tasks,
                self._evaluate_task_difficulty,
            ),
        )

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
        self._log_agent(
            "autonomous_iteration_started",
            input_summary={"goal": goal, "project_path": str(project_path), "written_files": len(written_files)},
            success=None,
        )
        try:
            result = self._run_project_pipeline_impl(
                goal=goal,
                project_path=project_path,
                written_files=written_files,
                run_command=run_command,
                readme_path=readme_path,
                static_review=static_review,
                apply_improvement=apply_improvement,
                analyze_improvements=analyze_improvements,
                read_project_state=read_project_state,
                on_progress=on_progress,
            )
        except Exception as exc:
            self._log_agent(
                "autonomous_iteration_failed",
                input_summary={"goal": goal, "project_path": str(project_path)},
                success=False,
                error=str(exc),
            )
            raise
        self._log_agent(
            "autonomous_iteration_completed",
            input_summary={"goal": goal, "project_path": str(project_path)},
            output_summary={
                "success": result.get("success"),
                "completed_improvements": result.get("completed_improvements"),
                "failure_stage": result.get("failure_stage"),
            },
            success=bool(result.get("success")),
        )
        return result

    def _run_project_pipeline_impl(
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
        diagnoses = []
        mind_notes: list[str] = []
        completed_goal_titles: list[str] = []
        repair_attempts = 0
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
            if attempts_used >= self.max_iteration_attempts:
                failure_context = self._budget_exhausted_context(attempts_used, completed_improvements)
                self._notify(
                    on_progress,
                    "max_attempts_reached",
                    {
                        "attempts_used": attempts_used,
                        "max_iteration_attempts": self.max_iteration_attempts,
                        "completed_improvements": completed_improvements,
                        "required_improvements": self.required_successful_improvements,
                        "repair_attempts": repair_attempts,
                        "evaluation": current,
                        **failure_context,
                    },
                )
                break

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
            memory_context = self._load_context(
                goal=goal,
                project_path=project_path,
                iteration=completed_improvements,
            )
            project_state.memory_context = memory_context
            self._notify(
                on_progress,
                "context_loader",
                {
                    "context": memory_context,
                    "state": project_state,
                    "iteration": completed_improvements,
                },
            )

            if current.validation_passed:
                improvement_report = self._analyze_improvements(
                    analyze_improvements,
                    completed_improvements,
                    current,
                )
                diagnosis = self.project_diagnoser.diagnose(
                    project_state=project_state,
                    evaluation=current,
                    iteration=completed_improvements,
                    analysis_seed=improvement_report,
                )
                diagnoses.append(diagnosis)
                improvement_report = self._merge_diagnosis_report(improvement_report, diagnosis)
                self._notify(
                    on_progress,
                    "improvement_report",
                    {
                        "completed_improvements": completed_improvements,
                        "required_improvements": self.required_successful_improvements,
                        "report": improvement_report,
                    },
                )
                self._notify(
                    on_progress,
                    "project_diagnosis",
                    {
                        "completed_improvements": completed_improvements,
                        "diagnosis": diagnosis,
                        "selected_candidate": diagnosis.selected_candidate,
                    },
                )
                if diagnosis.selected_candidate is None:
                    failure_context = {
                        "failure_stage": "Project Diagnosis",
                        "failed_iteration": attempts_used + 1,
                        "failed_tool": "project_diagnoser",
                        "failure_reason": diagnosis.candidate_shortage_reason or "Diagnosis found no high-value improvement candidate.",
                        "retry_attempted": False,
                        "retry_history": [],
                    }
                    break

                self._notify(on_progress, "goal_maker_started", {"iteration": completed_improvements})
                goals = self._run_goal_maker(
                    project_state,
                    current,
                    improvement_report,
                    completed_improvements,
                )
                selected_goal = goals[0]
                iteration_goals.extend(goals)
                self._notify(
                    on_progress,
                    "goal_maker",
                    {"goals": goals, "selected_goal": selected_goal, "iteration": completed_improvements},
                )

                self._notify(on_progress, "task_designer_started", {"iteration": completed_improvements, "selected_goal": selected_goal})
                tasks = self._run_task_designer(
                    project_state,
                    selected_goal,
                    improvement_report,
                    completed_improvements,
                )
                designed_tasks.extend(tasks)
                self._notify(
                    on_progress,
                    "task_designer",
                    {"tasks": tasks, "selected_goal": selected_goal, "iteration": completed_improvements},
                )
                self._notify(on_progress, "decomposition_started", {"iteration": completed_improvements, "tasks": tasks})
                decomposition = self._run_task_decomposer(tasks)
                self._notify(
                    on_progress,
                    "decomposition",
                    {
                        "tasks": tasks,
                        "iteration": completed_improvements,
                        **decomposition,
                    },
                )

                actions = decomposition["actions"]
                improvement_report = {
                    **improvement_report,
                    "selected_goal": selected_goal.model_dump(),
                    "designed_tasks": [task.model_dump() for task in tasks],
                    "task_difficulty": decomposition["difficulty"],
                    "next_iteration_goal": selected_goal.title,
                    "must_implement_next": selected_goal.acceptance_criteria,
                }
                is_repair = False
            else:
                repair_diagnosis = self.project_diagnoser.diagnose(
                    project_state=project_state,
                    evaluation=current,
                    iteration=completed_improvements,
                    analysis_seed={},
                )
                diagnoses.append(repair_diagnosis)
                self._notify(
                    on_progress,
                    "project_diagnosis",
                    {
                        "completed_improvements": completed_improvements,
                        "diagnosis": repair_diagnosis,
                        "selected_candidate": repair_diagnosis.selected_candidate,
                        "repair": True,
                    },
                )
                self._notify(on_progress, "goal_maker_started", {"iteration": completed_improvements, "repair": True})
                selected_goal = self._repair_goal(current)
                goals = [selected_goal]
                iteration_goals.extend(goals)
                self._notify(
                    on_progress,
                    "goal_maker",
                    {"goals": goals, "selected_goal": selected_goal, "iteration": completed_improvements, "repair": True},
                )

                self._notify(on_progress, "task_designer_started", {"iteration": completed_improvements, "selected_goal": selected_goal, "repair": True})
                tasks = [self._repair_task(selected_goal, project_state, current)]
                designed_tasks.extend(tasks)
                self._notify(
                    on_progress,
                    "task_designer",
                    {"tasks": tasks, "selected_goal": selected_goal, "iteration": completed_improvements, "repair": True},
                )

                self._notify(on_progress, "decomposition_started", {"iteration": completed_improvements, "tasks": tasks, "repair": True})
                decomposition = self._run_task_decomposer(tasks)
                self._notify(
                    on_progress,
                    "decomposition",
                    {
                        "tasks": tasks,
                        "iteration": completed_improvements,
                        "repair": True,
                        **decomposition,
                    },
                )
                actions = decomposition["actions"]
                improvement_report = {
                    "repair": True,
                    "summary": current.summary,
                    "validation_errors": current.validation_errors,
                    "recommended_actions": self._select_repair_actions(current),
                    "selected_goal": selected_goal.model_dump(),
                    "designed_tasks": [task.model_dump() for task in tasks],
                    "task_difficulty": decomposition["difficulty"],
                    "next_iteration_goal": selected_goal.title,
                    "must_implement_next": selected_goal.acceptance_criteria,
                    "diagnosis": repair_diagnosis.to_json_dict(),
                    "improvement_candidates": [candidate.to_json_dict() for candidate in repair_diagnosis.improvement_candidates],
                    "selected_candidate": (
                        repair_diagnosis.selected_candidate.to_json_dict()
                        if repair_diagnosis.selected_candidate is not None
                        else {}
                    ),
                }
                is_repair = True

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

            iteration_result = self._run_task_executor(
                apply_improvement,
                attempts_used,
                current,
                actions,
                improvement_report,
                is_repair,
            )
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

            self._notify(on_progress, "modification_evaluation_started", {"iteration": attempts_used, "result": iteration_result})
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
                improvement_report,
            )
            if is_repair and iteration_result.success and current.validation_passed:
                iteration_result.repair_completed = True
                repair_attempts += 1
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
                selected_goal_title = self._selected_goal_title(improvement_report)
                if selected_goal_title and selected_goal_title not in completed_goal_titles:
                    completed_goal_titles.append(selected_goal_title)
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
            elif iteration_result.repair_completed:
                iterations.append(iteration_result)
                failure_context = {}
                self._notify(
                    on_progress,
                    "repair_completed",
                    {
                        "iteration": attempts_used,
                        "completed_improvements": completed_improvements,
                        "required_improvements": self.required_successful_improvements,
                        "repair_attempts": repair_attempts,
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
                iteration_result.completed_successful_iteration or iteration_result.repair_completed,
                actions,
                "Repair completed; project validation passed." if iteration_result.repair_completed else iteration_result.error or current.summary,
                improvement_report,
                failure_context if not (iteration_result.completed_successful_iteration or iteration_result.repair_completed) else None,
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
        remaining_goals = self._remaining_goal_titles(iteration_goals, completed_goal_titles)
        agent_result = AutonomousIterationResult(
            project_state=project_states[-1] if project_states else None,
            iteration_goals=iteration_goals,
            designed_tasks=designed_tasks,
            evaluations=evaluations,
            diagnoses=diagnoses,
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
            "repair_attempts": repair_attempts,
            "validation": current,
            "evaluation": current,
            "evaluations": evaluations,
            "iterations": iterations,
            "improvement_report": improvement_report or {},
            "project_state": agent_result.project_state,
            "project_states": project_states,
            "iteration_goals": iteration_goals,
            "designed_tasks": designed_tasks,
            "diagnoses": diagnoses,
            "mind_notes": mind_notes,
            "autonomous_iteration": agent_result,
            "failure_stage": failure_context.get("failure_stage"),
            "failed_iteration": failure_context.get("failed_iteration"),
            "failed_tool": failure_context.get("failed_tool"),
            "failure_reason": failure_context.get("failure_reason"),
            "retry_attempted": failure_context.get("retry_attempted", False),
            "retry_history": failure_context.get("retry_history", []),
            "last_successful_iteration": completed_improvements,
            "remaining_goals": remaining_goals,
        }

    def run(self, **kwargs) -> dict[str, Any]:
        """Backward-compatible entry point."""
        return self.run_project_pipeline(**kwargs)

    @staticmethod
    def minimum_attempt_budget(required_successful_improvements: int) -> int:
        if required_successful_improvements <= 0:
            return 0
        repair_retry_buffer = max(2, math.ceil(required_successful_improvements * 0.5))
        return required_successful_improvements + repair_retry_buffer

    def _load_context(
        self,
        *,
        goal: str,
        project_path: str | Path,
        iteration: int,
    ) -> dict[str, Any]:
        """Context Loader agent function with safe fallback."""
        try:
            return self.pipeline.load_context(goal, project_path, iteration)
        except Exception as exc:
            return {
                "error": f"Context Loader failed: {type(exc).__name__}: {str(exc)[:300]}",
                "system_prompt": "",
                "dialog_context": [],
                "related_memories": [],
                "related_files": [],
                "environment_context": [],
                "prompt_text": "",
            }

    def _run_goal_maker(
        self,
        project_state: ProjectStateSnapshot,
        evaluation: EvaluationResult,
        improvement_report: dict[str, Any],
        completed_iteration: int,
    ) -> list[ImprovementGoal]:
        """Goal Maker agent function."""
        return self.pipeline.make_goals(project_state, evaluation, improvement_report, completed_iteration)

    def _run_task_designer(
        self,
        project_state: ProjectStateSnapshot,
        goal: ImprovementGoal,
        improvement_report: dict[str, Any],
        completed_iteration: int,
    ) -> list[DesignedImprovementTask]:
        """Task Designer agent function."""
        return self.pipeline.design_tasks(project_state, goal, improvement_report, completed_iteration)

    def _run_task_decomposer(self, tasks: list[DesignedImprovementTask]) -> dict[str, Any]:
        """Task Decomposer agent function with a lightweight difficulty score."""
        return self.pipeline.decompose_tasks(tasks)

    def _run_task_executor(
        self,
        apply_improvement: ApplyImprovement,
        iteration: int,
        evaluation: EvaluationResult,
        actions: list[str],
        improvement_report: dict[str, Any],
        is_repair: bool,
    ) -> IterationResult:
        """Task Executor agent function."""
        return self.pipeline.execute_task(
            apply_improvement,
            iteration,
            evaluation,
            actions,
            improvement_report,
            is_repair,
        )

    def _evaluate_task_difficulty(self, tasks: list[DesignedImprovementTask]) -> dict[str, Any]:
        """Estimate task difficulty from observable task structure."""
        target_file_count = sum(len(task.target_files) for task in tasks)
        acceptance_criteria_count = sum(len(task.acceptance_criteria) for task in tasks)
        risk_note_count = sum(len(task.risk_notes) for task in tasks)
        score = len(tasks) + target_file_count + acceptance_criteria_count + (risk_note_count * 2)
        if score >= 8:
            level = "high"
        elif score >= 4:
            level = "medium"
        else:
            level = "low"
        return {
            "level": level,
            "score": score,
            "task_count": len(tasks),
            "target_file_count": target_file_count,
            "acceptance_criteria_count": acceptance_criteria_count,
            "risk_note_count": risk_note_count,
        }

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
            payload = project_state_reader_executor(
                ToolInputMetadata.from_mapping("project_state_reader", {**params, "_memory_store": self.memory_store})
            )
            payload = payload.result.to_json_dict() if payload.result else {}
        return ProjectStateSnapshot(**payload)

    def _make_goals(
        self,
        project_state: ProjectStateSnapshot,
        evaluation: EvaluationResult,
        improvement_report: dict[str, Any],
        completed_iteration: int,
    ) -> list[ImprovementGoal]:
        selected_candidate = improvement_report.get("selected_candidate") if isinstance(improvement_report, dict) else None
        candidate_goal = self._goal_from_candidate(selected_candidate, improvement_report, evaluation)
        if candidate_goal is not None:
            return [candidate_goal]
        prompt = (
            "You are OpenPilot's Goal Maker Agent. Create 1-3 concrete, evaluable project "
            "improvement goals. Avoid vague goals like 'make it better'. Return ONLY JSON.\n"
            "Respect any Prompt Context in the improvement report as parent intent. Treat product fit "
            "and default user expectations as first-class evaluation criteria, not optional polish.\n\n"
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

    def _goal_from_candidate(
        self,
        candidate: Any,
        report: dict[str, Any],
        evaluation: EvaluationResult,
    ) -> ImprovementGoal | None:
        if not isinstance(candidate, dict):
            return None
        title = str(candidate.get("title") or "").strip()
        if not title:
            return None
        criteria = self._coerce_string_list(candidate.get("acceptance_criteria"))
        return ImprovementGoal(
            id=str(candidate.get("candidate_id") or f"goal_{uuid.uuid4().hex[:8]}"),
            title=title,
            category=str(candidate.get("dimension") or "feature"),
            rationale=str(candidate.get("rationale") or report.get("summary") or evaluation.summary),
            acceptance_criteria=criteria or [f"Observable evidence improves the selected diagnosis gap: {title}"],
            priority="high" if float(candidate.get("priority_score") or 0.0) >= 0.7 else "medium",
        )

    def _design_tasks(
        self,
        project_state: ProjectStateSnapshot,
        goal: ImprovementGoal,
        improvement_report: dict[str, Any],
        completed_iteration: int,
    ) -> list[DesignedImprovementTask]:
        prompt = (
            "You are OpenPilot's Task Designer Agent. Convert one improvement goal into 1-2 "
            "specific implementation tasks with target files and acceptance criteria. Return ONLY JSON.\n"
            "Carry forward the Prompt Context/rubric from the improvement report exactly. Do not dilute "
            "a product-fit migration goal into terminal-only polish tasks.\n\n"
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

    def _repair_goal(self, evaluation: EvaluationResult) -> ImprovementGoal:
        primary_issue = self._primary_validation_issue(evaluation)
        if primary_issue is not None:
            title = primary_issue.recommended_action or f"Fix {primary_issue.category}: {primary_issue.message}"
            criteria = [primary_issue.message]
            intent = primary_issue.product_intent or evaluation.product_intent
            if intent is not None:
                criteria.extend(intent.non_regression_constraints[:3])
                criteria.extend([f"Do not use substitute: {item}" for item in intent.disallowed_substitutions[:3]])
            return ImprovementGoal(
                id=f"repair_goal_{uuid.uuid4().hex[:8]}",
                title=title,
                category="robustness" if primary_issue.category != "product_intent_drift" else "ux",
                rationale=evaluation.summary,
                acceptance_criteria=criteria or ["The project passes validation while preserving product intent."],
                priority="high",
            )
        repair_actions = self._select_repair_actions(evaluation)
        title = repair_actions[0] if repair_actions else "Fix the blocking validation failure."
        criteria = repair_actions or evaluation.validation_errors or ["The project passes the failing validation path."]
        return ImprovementGoal(
            id=f"repair_goal_{uuid.uuid4().hex[:8]}",
            title=title,
            category="robustness",
            rationale=evaluation.summary,
            acceptance_criteria=criteria,
            priority="high",
        )

    def _repair_task(
        self,
        goal: ImprovementGoal,
        project_state: ProjectStateSnapshot,
        evaluation: EvaluationResult,
    ) -> DesignedImprovementTask:
        target_files = project_state.safe_target_files[:1] or project_state.written_files[:1]
        primary_issue = self._primary_validation_issue(evaluation)
        intent = (primary_issue.product_intent if primary_issue else None) or evaluation.product_intent
        risk_notes = [issue.message for issue in evaluation.validation_issues[:3]] or evaluation.validation_errors[:3] or evaluation.warnings[:3]
        if intent is not None:
            risk_notes.extend(intent.non_regression_constraints[:3])
        return DesignedImprovementTask(
            id=f"repair_task_{uuid.uuid4().hex[:8]}",
            goal_id=goal.id,
            description=f"Fix the validation failure: {goal.title}",
            target_files=target_files,
            acceptance_criteria=goal.acceptance_criteria,
            risk_notes=risk_notes,
        )

    def _primary_validation_issue(self, evaluation: EvaluationResult):
        priority = {
            "product_intent_drift": 0,
            "runtime_error": 1,
            "runtime_warning": 2,
            "environment": 3,
            "code_quality": 4,
        }
        issues = list(getattr(evaluation, "validation_issues", []) or [])
        blocking = [issue for issue in issues if getattr(issue, "severity", "blocking") == "blocking"]
        candidates = blocking or issues
        if not candidates:
            return None
        return sorted(candidates, key=lambda issue: priority.get(getattr(issue, "category", ""), 99))[0]

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
        improvement_report: dict[str, Any] | None = None,
    ) -> bool:
        failure_notes = []
        informational_notes = []
        if not evaluation.validation_passed:
            failure_notes.append("Hard validation did not pass after modification.")
        if not iteration_result.changed_files and not (is_repair and evaluation.validation_passed):
            failure_notes.append("No changed files were reported by the task executor.")
        product_note = self._diagnosis_failure_note(improvement_report or {}, iteration_result, tasks)
        if product_note:
            failure_notes.append(product_note)
        if tasks:
            criteria = [item for task in tasks for item in task.acceptance_criteria]
            if criteria:
                informational_notes.append("Acceptance criteria reviewed: " + "; ".join(criteria[:4]))
        iteration_result.evaluation_notes = [*failure_notes, *informational_notes]
        if failure_notes and not iteration_result.failure_reason:
            iteration_result.failure_reason = "; ".join(failure_notes)
            iteration_result.failure_stage = "Modification Evaluator"
        if is_repair:
            return False
        return bool(evaluation.validation_passed and not is_repair and iteration_result.changed_files and not product_note)

    def _diagnosis_failure_note(
        self,
        improvement_report: dict[str, Any],
        iteration_result: IterationResult,
        tasks: list[DesignedImprovementTask],
    ) -> str | None:
        selected = improvement_report.get("selected_candidate") if isinstance(improvement_report, dict) else None
        if not isinstance(selected, dict):
            return None
        criteria = self._coerce_string_list(selected.get("acceptance_criteria"))
        if not criteria or not tasks:
            return None
        if not iteration_result.changed_files:
            return "Selected diagnosis candidate did not produce changed files."
        return None

    def _record_mind_note(
        self,
        goal: str,
        iteration: int,
        success: bool,
        actions: list[str],
        detail: str | None,
        improvement_report: dict[str, Any] | None = None,
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
                diagnosis = (improvement_report or {}).get("diagnosis") if isinstance(improvement_report, dict) else {}
                selected_candidate = (improvement_report or {}).get("selected_candidate") if isinstance(improvement_report, dict) else {}
                unmet_metrics = []
                if isinstance(diagnosis, dict):
                    unmet_metrics = [
                        str(metric.get("metric_id") or metric.get("name") or "")
                        for metric in diagnosis.get("success_metrics") or []
                        if isinstance(metric, dict) and metric.get("satisfied") is False
                    ]
                self.memory_store.save(
                    MemoryRecord(
                        id="",
                        memory_type=MemoryType.PROJECT if success else MemoryType.TASK,
                        content=note,
                        tags=["autonomous_iteration", state, "project"],
                        confidence=0.8 if success else 0.45,
                        attributes={
                            "goal": goal,
                            "iteration": iteration,
                            "success": success,
                            "selected_candidate": (
                                selected_candidate.get("title")
                                if isinstance(selected_candidate, dict)
                                else ""
                            ),
                            "selected_dimension": (
                                selected_candidate.get("dimension")
                                if isinstance(selected_candidate, dict)
                                else ""
                            ),
                            "unmet_metrics": [item for item in unmet_metrics if item][:5],
                            **(failure_context or {}),
                        },
                    )
                )
            except Exception:
                pass
        return note

    def _merge_diagnosis_report(self, report: dict[str, Any], diagnosis: Any) -> dict[str, Any]:
        selected = diagnosis.selected_candidate
        recommended = list(report.get("recommended_actions") or [])
        opportunities = list(report.get("improvement_opportunities") or [])
        must_implement = list(report.get("must_implement_next") or [])
        if selected is not None:
            recommended = [selected.title, *recommended]
            opportunities = [selected.rationale or selected.title, *opportunities]
            must_implement = [*selected.acceptance_criteria, *must_implement]
        return {
            **report,
            "summary": diagnosis.summary or report.get("summary") or "",
            "improvement_opportunities": self._dedupe_text(opportunities),
            "recommended_actions": self._dedupe_text(recommended),
            "next_iteration_goal": selected.title if selected is not None else report.get("next_iteration_goal"),
            "must_implement_next": self._dedupe_text(must_implement),
            "diagnosis": diagnosis.to_json_dict(),
            "improvement_candidates": [candidate.to_json_dict() for candidate in diagnosis.improvement_candidates],
            "selected_candidate": selected.to_json_dict() if selected is not None else {},
        }

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

    def _dedupe_text(self, items: list[Any]) -> list[str]:
        return self._coerce_string_list(items) if len(items) <= 1 else list(dict.fromkeys(self._coerce_string_list(items)))

    def _select_repair_actions(self, evaluation: EvaluationResult) -> list[str]:
        primary_issue = self._primary_validation_issue(evaluation)
        if primary_issue is not None:
            action = primary_issue.recommended_action or primary_issue.message
            constraints = []
            intent = primary_issue.product_intent or evaluation.product_intent
            if intent is not None:
                constraints = intent.non_regression_constraints[:2]
            return [item for item in [action, *constraints] if item][:2]
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
        if not failed_tool and stage == "Modification Evaluator":
            failed_tool = "project_evaluator"
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
            "retry_attempted": iteration_result.retry_attempted,
            "retry_history": iteration_result.retry_history,
            "failed_actions": actions,
            "selected_goal": selected_goal,
            "designed_tasks": designed_tasks,
            "completed_improvements": completed_improvements,
            "required_improvements": self.required_successful_improvements,
        }

    def _budget_exhausted_context(self, attempts_used: int, completed_improvements: int) -> dict[str, Any]:
        reason = (
            "Attempt budget exhausted before starting next iteration. "
            f"Used {attempts_used}/{self.max_iteration_attempts} attempts while completing "
            f"{completed_improvements}/{self.required_successful_improvements} successful improvements."
        )
        return {
            "failure_stage": "Iteration Budget",
            "failed_iteration": attempts_used + 1,
            "failed_tool": "iteration_controller",
            "failure_reason": reason,
            "retry_attempted": False,
            "retry_history": [],
        }

    def _selected_goal_title(self, improvement_report: dict[str, Any] | None) -> str:
        selected_goal = (improvement_report or {}).get("selected_goal") or {}
        if isinstance(selected_goal, dict):
            return str(selected_goal.get("title") or "").strip()
        return str(getattr(selected_goal, "title", "") or "").strip()

    def _remaining_goal_titles(self, goals: list[ImprovementGoal], completed_goal_titles: list[str]) -> list[str]:
        completed = set(completed_goal_titles)
        titles = []
        for goal in goals:
            if goal.id.startswith("repair_goal_"):
                continue
            if goal.title in completed:
                continue
            if goal.title not in titles:
                titles.append(goal.title)
        return titles

    def _notify(self, callback: ProgressCallback | None, event: str, payload: dict[str, Any]) -> None:
        if callback:
            callback(event, payload)

    def _log_agent(
        self,
        event_type: str,
        *,
        success: bool | None,
        input_summary: Any | None = None,
        output_summary: Any | None = None,
        error: str | None = None,
    ) -> None:
        if not self.logger or not hasattr(self.logger, "log_structured_event"):
            return
        self.logger.log_structured_event(
            source_type="agent",
            source_name="autonomous_iteration.agents.iteration_agent",
            phase="autonomous_iteration",
            event_type=event_type,
            session_id="unknown",
            turn_id=1,
            success=success,
            input_summary=input_summary,
            output_summary=output_summary,
            error=error,
        )


class IterativeImprovementController(AutonomousIterationAgent):
    """Backward-compatible name for the autonomous iteration agent."""
