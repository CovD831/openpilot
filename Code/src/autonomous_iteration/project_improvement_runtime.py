"""Project improvement runtime owned by the autonomous_iteration module."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from autonomous_iteration.models import EvaluationResult, IterationResult
from autonomous_iteration.task_models import Task, TaskPriority
from autonomous_iteration.tool.project_improvement_tool import project_state_reader_executor
from metadata import ToolExecutionEnvelopeMetadata, ToolInputMetadata


class ProjectImprovementRuntime:
    """Bridge IntelligentAutopilot runtime services into the iteration pipeline."""

    STAGES = {
        "environment": "Environment Setup",
        "context_loader": "Context Loader",
        "goal_maker": "Goal Maker",
        "task_designer": "Task Designer",
        "task_decomposer": "Task Decomposer",
        "task_executor": "Task Executor",
        "modification_evaluator": "Modification Evaluator",
    }

    def __init__(self, autopilot: Any) -> None:
        self.autopilot = autopilot

    def run(
        self,
        *,
        goal: str,
        project_path: str | Path,
        written_files: list[str],
        run_command: str = "",
        readme_path: str | Path | None = None,
    ) -> dict[str, Any] | None:
        """Run the instruction-defined autonomous iteration pipeline."""
        if not self.autopilot.enable_iterative_improvement or not written_files:
            return None

        if not self.autopilot._resolve_project_improvement_iterations(goal, project_path):
            return None

        project_path = Path(project_path).expanduser()
        readme_path = Path(readme_path).expanduser() if readme_path else project_path / "README.md"

        self._log("pipeline_start", {"goal": goal, "project_path": str(project_path)}, {"written_files": len(written_files)})
        self._prepare_dashboard(goal)

        environment_result = self._prepare_environment(
            project_path=project_path,
            written_files=written_files,
            run_command=run_command,
        )
        if not environment_result.success or environment_result.output is None:
            result = self._environment_failure_result(environment_result, run_command)
            self._log("environment_failed", {"project_path": str(project_path)}, {"reason": result["failure_reason"]}, success=False)
            return result

        environment_payload = environment_result.output
        run_command = str(environment_payload.get("run_command") or run_command)

        def on_progress(event: str, payload: dict[str, Any]) -> None:
            self.autopilot._handle_iteration_progress(event, payload)

        def apply_improvement(
            iteration: int,
            evaluation: EvaluationResult,
            actions: list[str],
            improvement_report: dict[str, Any],
            is_repair: bool,
        ) -> IterationResult:
            return self.autopilot._apply_project_improvement(
                goal=goal,
                project_path=project_path,
                written_files=written_files,
                run_command=run_command,
                readme_path=readme_path,
                iteration=iteration,
                evaluation=evaluation,
                actions=actions,
                improvement_report=improvement_report,
                is_repair=is_repair,
            )

        def analyze_improvements(completed_iteration: int, evaluation: EvaluationResult) -> dict[str, Any]:
            return self.autopilot._analyze_project_improvements(
                goal=goal,
                project_path=project_path,
                written_files=written_files,
                run_command=run_command or evaluation.run_command,
                readme_path=readme_path,
                completed_iteration=completed_iteration,
                evaluation=evaluation,
            )

        def read_project_state(evaluation: EvaluationResult, iteration: int) -> dict[str, Any]:
            return self._read_project_state(
                goal=goal,
                project_path=project_path,
                written_files=written_files,
                run_command=run_command or evaluation.run_command,
                readme_path=readme_path,
                evaluation=evaluation,
                iteration=iteration,
            )

        result = self.autopilot.iterative_improvement.run_project_pipeline(
            goal=goal,
            project_path=project_path,
            written_files=written_files,
            run_command=run_command,
            readme_path=readme_path,
            apply_improvement=apply_improvement,
            analyze_improvements=analyze_improvements,
            read_project_state=read_project_state,
            on_progress=on_progress,
        )

        self._finalize_dashboard(result)
        self._log_project_improvement_result(goal, project_path, written_files, result)
        self._log(
            "pipeline_end",
            {"goal": goal, "project_path": str(project_path)},
            {
                "success": result.get("success"),
                "failure_stage": result.get("failure_stage"),
                "completed_improvements": result.get("completed_improvements"),
            },
            success=bool(result.get("success")),
            error=result.get("failure_reason"),
        )
        return result

    def _prepare_dashboard(self, goal: str) -> None:
        if self.autopilot.enhanced_ui:
            self.autopilot._reset_iteration_dashboard(goal)
            self.autopilot.enhanced_ui.set_current_task_state(
                title="Autonomous Iteration",
                details=f"Improvements applied: 0/{self.autopilot.required_successful_improvements}",
                status="running",
            )

    def _prepare_environment(
        self,
        *,
        project_path: Path,
        written_files: list[str],
        run_command: str,
    ) -> ToolExecutionEnvelopeMetadata:
        environment_task = Task(
            id=str(uuid.uuid4()),
            description="Prepare project virtual environment",
            priority=TaskPriority.HIGH,
        )
        if self.autopilot.enhanced_ui:
            self.autopilot._ensure_dashboard_iteration(1)
        result = self.autopilot._sync_project_environment(
            task=environment_task,
            step_id="iteration_initial_project_environment_tool",
            project_path=project_path,
            written_files=written_files,
            entry_files=written_files,
            run_command=run_command,
            parent_task_id=self.autopilot._dashboard_stage_id("environment"),
        )
        self._log(
            "environment_prepared",
            {"project_path": str(project_path), "written_files": len(written_files)},
            {"success": result.success},
            success=result.success,
            error=result.error_message,
        )
        return result

    def _read_project_state(
        self,
        *,
        goal: str,
        project_path: Path,
        written_files: list[str],
        run_command: str,
        readme_path: Path,
        evaluation: EvaluationResult,
        iteration: int,
    ) -> dict[str, Any]:
        if self.autopilot.enhanced_ui:
            self.autopilot._ensure_dashboard_iteration()
        task = Task(
            id=str(uuid.uuid4()),
            description="Read project state for autonomous iteration",
            priority=TaskPriority.MEDIUM,
        )
        params = {
            "project_path": str(project_path),
            "goal": goal,
            "written_files": written_files,
            "run_command": run_command,
            "readme_path": str(readme_path),
            "memory_query": f"{goal} autonomous iteration {iteration}",
            "validation_context": evaluation.model_dump(),
        }
        execute_reader = getattr(self.autopilot, "_execute_project_state_reader_agent_tool", None)
        if execute_reader is None:
            fallback = project_state_reader_executor(
                ToolInputMetadata.from_mapping("project_state_reader", {**params, "_memory_store": self.autopilot.memory_store})
            )
            payload = fallback.result
            self._log(
                "project_state_read",
                {"iteration": iteration},
                {"source": "direct", "success": payload is not None},
                success=payload is not None,
            )
            return payload.to_json_dict() if payload else {}

        result = execute_reader(
            task=task,
            step_id=f"iteration_{iteration}_project_state_reader",
            input_metadata=ToolInputMetadata.from_mapping("project_state_reader", params),
            parent_task_id=self.autopilot._dashboard_stage_id("project_state"),
        )
        if result.success and result.output is not None:
            self._log("project_state_read", {"iteration": iteration}, {"source": "tool", "success": True})
            return result.output.to_json_dict()

        fallback = project_state_reader_executor(
            ToolInputMetadata.from_mapping("project_state_reader", {**params, "_memory_store": self.autopilot.memory_store})
        )
        payload = fallback.result
        self._log(
            "project_state_read",
            {"iteration": iteration},
            {"source": "fallback", "success": payload is not None},
            success=payload is not None,
            error=result.error_message,
        )
        return payload.to_json_dict() if payload else {}

    def _environment_failure_result(self, environment_result: ToolExecutionEnvelopeMetadata, run_command: str) -> dict[str, Any]:
        reason = environment_result.error_message or "Project environment sync failed."
        evaluation = EvaluationResult(
            validation_passed=False,
            runnable=False,
            has_blocking_bugs=True,
            summary="Project environment setup failed.",
            validation_errors=[reason],
            warnings=[],
            run_command=run_command,
            recommended_actions=["Fix the project environment setup failure."],
            next_iteration_goal=f"Fix project environment setup: {reason}",
        )
        required = self.autopilot.required_successful_improvements
        return {
            "success": False,
            "partial_success": False,
            "completed_improvements": 0,
            "required_improvements": required,
            "completed_iterations": 0,
            "required_iterations": required,
            "attempts_used": 0,
            "max_iteration_attempts": self.autopilot.max_iteration_attempts,
            "validation": evaluation,
            "evaluation": evaluation,
            "evaluations": [evaluation],
            "iterations": [],
            "improvement_report": {},
            "project_state": None,
            "project_states": [],
            "iteration_goals": [],
            "designed_tasks": [],
            "mind_notes": [],
            "autonomous_iteration": None,
            "failure_stage": self.STAGES["environment"],
            "failed_iteration": 0,
            "failed_tool": "project_environment_tool",
            "failure_reason": reason,
            "retry_attempted": False,
            "retry_history": [],
            "last_successful_iteration": 0,
            "remaining_goals": [],
        }

    def _finalize_dashboard(self, result: dict[str, Any]) -> None:
        if not self.autopilot.enhanced_ui:
            return
        evaluation = result["validation"]
        validation_passed = bool(evaluation.validation_passed)
        failure_stage = result.get("failure_stage")
        if not result["success"] and failure_stage == self.STAGES["task_executor"]:
            evaluation_status = "pending"
        elif not result["success"] and failure_stage == self.STAGES["modification_evaluator"]:
            evaluation_status = "failed"
        else:
            evaluation_status = "completed" if validation_passed else "failed"
        result_status = "completed" if result["success"] else ("warning" if result.get("partial_success") else "failed")
        self.autopilot._set_dashboard_task_status(self.autopilot._dashboard_stage_id("evaluation"), evaluation_status)
        if not result["success"]:
            self.autopilot._finish_active_operations(self.autopilot._format_iteration_failure(result))
            details = (
                f"Iteration: {result.get('failed_iteration') or 'unknown'}\n"
                f"Stage: {result.get('failure_stage') or 'unknown'}\n"
                f"Tool: {result.get('failed_tool') or 'unknown'}\n"
                f"Reason: {result.get('failure_reason') or 'No failure reason reported'}\n"
                f"Retry attempted: {'yes' if result.get('retry_attempted') else 'no'}\n"
                f"Improvements applied: {result['completed_improvements']}/{result['required_improvements']}\n"
                f"Validation passed: {evaluation.validation_passed}\n"
                f"Blocking issues: {len(evaluation.validation_errors)}"
            )
        else:
            details = (
                f"Improvements applied: {result['completed_improvements']}/{result['required_improvements']}\n"
                f"Validation passed: {evaluation.validation_passed}\n"
                f"Blocking issues: {len(evaluation.validation_errors)}"
            )
        self.autopilot.enhanced_ui.set_current_task_state(
            title="Autonomous Iteration complete" if result["success"] else "Autonomous Iteration stopped",
            details=details,
            status=result_status,
        )

    def _log_project_improvement_result(
        self,
        goal: str,
        project_path: Path,
        written_files: list[str],
        result: dict[str, Any],
    ) -> None:
        evaluation = result["validation"]
        self.autopilot.logger.log_event(
            "project_iterative_improvement",
            {
                "goal": goal,
                "project_path": str(project_path),
                "written_files": written_files,
                "validation": evaluation.model_dump(),
                "completed_improvements": result["completed_improvements"],
                "required_improvements": result["required_improvements"],
                "completed_iterations": result["completed_iterations"],
                "required_iterations": result["required_iterations"],
                "improvement_report": result.get("improvement_report", {}),
                "iterations": [
                    item.model_dump() if hasattr(item, "model_dump") else item
                    for item in result["iterations"]
                ],
                "partial_success": result.get("partial_success", False),
                "failure_stage": result.get("failure_stage"),
                "failed_iteration": result.get("failed_iteration"),
                "failed_tool": result.get("failed_tool"),
                "failure_reason": result.get("failure_reason"),
                "retry_attempted": result.get("retry_attempted", False),
                "retry_history": result.get("retry_history", []),
                "last_successful_iteration": result.get("last_successful_iteration"),
                "remaining_goals": result.get("remaining_goals", []),
            },
            session_id=self.autopilot.session_id or "unknown",
            turn_id=1,
        )

    def _log(
        self,
        source_name: str,
        input_summary: Any,
        output_summary: Any,
        *,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        logger = getattr(self.autopilot, "logger", None)
        if not logger or not hasattr(logger, "log_structured_event"):
            return
        logger.log_structured_event(
            source_type="module",
            source_name=f"autonomous_iteration.project_improvement_runtime.{source_name}",
            phase="project_improvement_runtime",
            event_type="module_completed" if success else "module_failed",
            session_id=self.autopilot.session_id or "unknown",
            turn_id=1,
            success=success,
            input_summary=input_summary,
            output_summary=output_summary,
            error=error,
            annotations={"stages": self.STAGES},
        )
