"""Task Executor implementation for the Autonomous Iteration module."""

from __future__ import annotations

import ast
import json
import uuid
from pathlib import Path
from typing import Any

from autonomous_iteration.models import EvaluationResult, IterationResult
from autonomous_iteration.task_models import Task, TaskPriority
from metadata import ToolExecutionEnvelopeMetadata, ToolInputMetadata


class AutonomousTaskExecutor:
    """Execute instruction-defined autonomous iteration subtasks."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def execute_improvement(
        self,
        *,
        goal: str,
        project_path: Path,
        written_files: list[str],
        run_command: str,
        readme_path: Path,
        iteration: int,
        evaluation: EvaluationResult,
        actions: list[str],
        improvement_report: dict[str, Any] | None = None,
        is_repair: bool = False,
    ) -> IterationResult:
        """Run the Task Executor stage for one project improvement."""
        self._log_agent(
            "task_executor_started",
            {"iteration": iteration, "actions": actions[:3]},
            {"project_path": str(project_path)},
        )
        target_file = self.runtime._select_iteration_target_file(written_files, actions)
        if target_file is None:
            reason = "No safe target file could be selected for automatic improvement."
            return self._failure(iteration, actions, reason, "file_selector")

        try:
            current_code = target_file.read_text(encoding="utf-8")
        except OSError as exc:
            reason = f"Failed to read {target_file}: {exc}"
            return self._failure(iteration, actions, reason, "file_reader")

        task = Task(
            id=str(uuid.uuid4()),
            description=f"Improve project iteration {iteration}",
            priority=TaskPriority.HIGH,
        )
        if self.runtime.enhanced_ui:
            self.runtime._set_dashboard_task_status(self.runtime._dashboard_stage_id("execution"), "running")
            self.runtime._set_dashboard_task_status(getattr(self.runtime, "_dashboard_current_iteration_id", None), "running")
            self.runtime.enhanced_ui.set_current_task_state(
                title=f"{'Repair' if is_repair else 'Improvement'} {iteration}",
                details="\n".join(actions),
                status="running",
            )

        improvement_report = improvement_report or {}
        if is_repair and self._should_use_bug_fix(evaluation):
            return self._execute_bug_fix(
                task=task,
                iteration=iteration,
                target_file=target_file,
                run_command=run_command or evaluation.run_command,
                evaluation=evaluation,
                actions=actions,
            )

        code_result, retry_history = self.run_code_generation_retry_pipeline(
            task=task,
            iteration=iteration,
            goal=goal,
            target_file=target_file,
            current_code=current_code,
            evaluation=evaluation,
            actions=actions,
            improvement_report=improvement_report,
            is_repair=is_repair,
        )
        retry_attempted = len(retry_history) > 1
        if not code_result.success or code_result.output is None:
            failure_reason = self.visible_tool_failure_summary(
                tool="code_generator",
                tool_result=code_result,
                retry_attempted=retry_attempted,
            )
            self.log_iteration_failure(
                iteration=iteration,
                stage="Task Executor",
                tool="code_generator",
                target_file=target_file,
                actions=actions,
                error=failure_reason,
                prompt_length=retry_history[0].get("prompt_length", 0) if retry_history else 0,
                current_code_length=len(current_code),
                retry_attempted=retry_attempted,
                tool_result=code_result,
                retry_history=retry_history,
            )
            return self._failure(
                iteration,
                actions,
                failure_reason,
                "code_generator",
                retry_attempted=retry_attempted,
                retry_history=retry_history,
            )

        improved_code = str(code_result.output.get("code", ""))
        if improved_code.strip() == current_code.strip():
            reason = "Generated improvement did not change the target file."
            return self._failure(
                iteration,
                actions,
                reason,
                "code_generator",
                retry_attempted=retry_attempted,
                retry_history=retry_history,
            )
        try:
            ast.parse(improved_code)
        except SyntaxError as exc:
            reason = f"Generated improvement has syntax error on line {exc.lineno}: {exc.msg}"
            return self._failure(
                iteration,
                actions,
                reason,
                "code_generator",
                retry_attempted=retry_attempted,
                retry_history=retry_history,
            )

        write_result = self.runtime._execute_fast_tool(
            task=task,
            step_id=f"iteration_{iteration}_file_writer",
            tool_name="file_writer",
            input_metadata=ToolInputMetadata.from_mapping("file_writer", {
                "file_path": str(target_file),
                "content": improved_code,
                "encoding": "utf-8",
                "create_dirs": True,
                "overwrite": True,
            }),
            parent_task_id=self.runtime._dashboard_stage_id("execution"),
        )
        self._log_agent(
            "file_writer_completed",
            {"iteration": iteration, "target_file": str(target_file)},
            {"success": write_result.success},
            success=write_result.success,
            error=write_result.error_message,
        )
        if not write_result.success:
            reason = write_result.error_message or "Failed to write improved code."
            return self._failure(
                iteration,
                actions,
                reason,
                "file_writer",
                retry_attempted=retry_attempted,
                retry_history=retry_history,
            )

        environment_result = self.runtime._sync_project_environment(
            task=task,
            step_id=f"iteration_{iteration}_project_environment_tool",
            project_path=project_path,
            written_files=[str(target_file)],
            entry_files=[str(target_file)],
            run_command=run_command,
            parent_task_id=self.runtime._dashboard_stage_id("environment"),
        )
        self._log_agent(
            "environment_sync_completed",
            {"iteration": iteration, "project_path": str(project_path)},
            {"success": environment_result.success},
            success=environment_result.success,
            error=environment_result.error_message,
        )
        if not environment_result.success or environment_result.output is None:
            reason = environment_result.error_message or "Project environment sync failed."
            return IterationResult(
                iteration=iteration,
                validation_passed=False,
                completed_successful_iteration=False,
                applied_actions=actions,
                changed_files=[str(target_file)],
                success=False,
                error=reason,
                failure_stage="Environment Setup",
                failed_tool="project_environment_tool",
                failure_reason=reason,
                retry_attempted=retry_attempted,
                retry_history=retry_history,
            )
        environment_payload = environment_result.output
        run_command = str(environment_payload.get("run_command") or run_command)

        review_result = self.runtime._execute_fast_tool(
            task=task,
            step_id=f"iteration_{iteration}_code_reviewer",
            tool_name="code_reviewer",
            input_metadata=ToolInputMetadata.from_mapping("code_reviewer", {
                "code": improved_code,
                "language": "python",
                "prompt_context": self.runtime._build_prompt_context(
                    original_goal=goal,
                    project_path=project_path,
                    written_files=[str(target_file)],
                    run_command=run_command,
                    evaluation=evaluation,
                    iteration_goal=str(improvement_report.get("next_iteration_goal") or (actions[0] if actions else "")),
                    acceptance_criteria=improvement_report.get("must_implement_next") or actions[:2],
                    tool_task="Review generated code against safety, correctness, and product-fit rubric.",
                    agent_instruction="Code Reviewer context: reject changes that pass syntax but fail the product-fit rubric.",
                    target_file=target_file,
                    current_code=improved_code,
                    code_context=self.budget_code_context(improved_code, max_chars=3000),
                    mode="review",
                ),
            }),
            parent_task_id=self.runtime._dashboard_stage_id("execution"),
        )
        self._log_agent(
            "code_review_completed",
            {"iteration": iteration},
            {"success": review_result.success},
            success=review_result.success,
            error=review_result.error_message,
        )
        readme_result = self.runtime._execute_fast_tool(
            task=task,
            step_id=f"iteration_{iteration}_readme_tool",
            tool_name="readme_tool",
            input_metadata=ToolInputMetadata.from_mapping("readme_tool", {
                "project_path": str(project_path),
                "project_summary": f"{goal}\n\nRecent Improvements:\n- " + "\n- ".join(
                    (getattr(self.runtime, "_project_improvement_actions", []) or []) + actions
                ),
                "written_files": written_files,
                "entry_files": [str(target_file)],
                "run_command": run_command,
                "setup_commands": environment_payload.get("setup_commands") or [],
                "environment": self.runtime._readme_environment_context(environment_payload),
                "overwrite": True,
            }),
            parent_task_id=self.runtime._dashboard_stage_id("execution"),
        )
        self._log_agent(
            "readme_update_completed",
            {"iteration": iteration},
            {"success": readme_result.success},
            success=readme_result.success,
            error=readme_result.error_message,
        )

        review_payload = review_result.output or {}
        review_approved = bool(review_payload.get("approved", True))
        product_intent_retry_history: list[dict[str, Any]] = []
        if review_result.success and not review_approved and self._is_product_intent_rejection(review_payload):
            retry_result, product_intent_retry_history = self._run_product_intent_retry(
                task=task,
                iteration=iteration,
                goal=goal,
                target_file=target_file,
                rejected_code=improved_code,
                evaluation=evaluation,
                actions=actions,
                improvement_report=improvement_report,
                review_payload=review_payload,
                is_repair=is_repair,
            )
            retry_attempted = True
            retry_history.extend(product_intent_retry_history)
            if retry_result.get("success"):
                improved_code = str(retry_result["code"])
                review_result = retry_result["review_result"]
                write_result = retry_result["write_result"]
                review_payload = review_result.output or {}
                review_approved = bool(review_payload.get("approved", True))
                readme_result = self.runtime._execute_fast_tool(
                    task=task,
                    step_id=f"iteration_{iteration}_product_intent_retry_readme_tool",
                    tool_name="readme_tool",
                    input_metadata=ToolInputMetadata.from_mapping("readme_tool", {
                        "project_path": str(project_path),
                        "project_summary": f"{goal}\n\nRecent Improvements:\n- " + "\n- ".join(
                            (getattr(self.runtime, "_project_improvement_actions", []) or []) + actions
                        ),
                        "written_files": written_files,
                        "entry_files": [str(target_file)],
                        "run_command": run_command,
                        "setup_commands": environment_payload.get("setup_commands") or [],
                        "environment": self.runtime._readme_environment_context(environment_payload),
                        "overwrite": True,
                    }),
                    parent_task_id=self.runtime._dashboard_stage_id("execution"),
                )

        success = review_result.success and review_approved and readme_result.success
        if success:
            self.runtime._project_improvement_actions = (getattr(self.runtime, "_project_improvement_actions", []) or []) + actions
        if self.runtime.enhanced_ui:
            self.runtime._set_dashboard_task_status(self.runtime._dashboard_stage_id("execution"), "completed" if success else "failed")
        failed_tool = None if success else ("code_reviewer" if (not review_result.success or not review_approved) else "readme_tool")
        failure_reason = None
        if not success:
            failed_result = review_result if failed_tool == "code_reviewer" else readme_result
            if failed_tool == "code_reviewer" and review_result.success and not review_approved:
                suggestions = review_payload.get("suggestions") or review_payload.get("warnings") or []
                failure_reason = "; ".join(str(item) for item in suggestions[:2]) or "Code review rejected the product-fit of the generated code."
            else:
                failure_reason = self.visible_tool_failure_summary(
                    tool=failed_tool or "tool",
                    tool_result=failed_result,
                    retry_attempted=retry_attempted,
                )
        self._log_agent(
            "task_executor_completed",
            {"iteration": iteration},
            {"success": success, "failed_tool": failed_tool},
            success=success,
            error=failure_reason,
        )
        return IterationResult(
            iteration=iteration,
            validation_passed=success,
            completed_successful_iteration=False,
            applied_actions=actions,
            changed_files=[str(target_file)],
            success=success,
            error=failure_reason,
            failure_stage=None if success else "Task Executor",
            failed_tool=failed_tool,
            failure_reason=failure_reason,
            retry_attempted=retry_attempted,
            retry_history=retry_history,
        )

    def _is_product_intent_rejection(self, review_payload: Any) -> bool:
        if not hasattr(review_payload, "get"):
            return False
        categories = [str(item) for item in review_payload.get("rejection_categories") or []]
        warnings = " ".join(str(item) for item in (review_payload.get("warnings") or []) + (review_payload.get("suggestions") or []))
        return "product_intent_drift" in categories or "Product intent drift" in warnings or "Product-fit rubric not satisfied" in warnings

    def _run_product_intent_retry(
        self,
        *,
        task: Task,
        iteration: int,
        goal: str,
        target_file: Path,
        rejected_code: str,
        evaluation: EvaluationResult,
        actions: list[str],
        improvement_report: dict[str, Any],
        review_payload: Any,
        is_repair: bool,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        reviewer_feedback = []
        if hasattr(review_payload, "get"):
            reviewer_feedback = [str(item) for item in (review_payload.get("suggestions") or review_payload.get("warnings") or [])[:5]]
        retry_report = {
            **improvement_report,
            "reviewer_rejection": {
                "category": "product_intent_drift",
                "feedback": reviewer_feedback,
            },
            "must_implement_next": [
                *reviewer_feedback[:3],
                "Regenerate the implementation so it fixes the issue while preserving product intent.",
            ],
        }
        prompt_context = self.build_code_generation_prompt_context(
            goal=goal,
            target_file=target_file,
            current_code=rejected_code,
            evaluation=evaluation,
            actions=actions,
            improvement_report=retry_report,
            is_repair=is_repair,
            simplified=True,
            mode="product_intent_retry",
        )
        prompt_context["reviewer_rejection"] = retry_report["reviewer_rejection"]
        code_result = self.execute_code_generation_for_improvement(
            task=task,
            iteration=iteration,
            target_file=target_file,
            improvement_prompt="Regenerate after product intent drift rejection.",
            simplified=True,
            mode="product_intent_retry",
            prompt_context=prompt_context,
        )
        history = [
            self.code_generation_attempt_summary(
                mode="product_intent_retry",
                prompt=json.dumps(prompt_context, ensure_ascii=False, default=str),
                result=code_result,
                attempt=1,
            )
        ]
        self.append_code_generation_attempt_to_dashboard(iteration, history[0])
        if not code_result.success or code_result.output is None:
            return {"success": False}, history
        retry_code = str(code_result.output.get("code", ""))
        try:
            ast.parse(retry_code)
        except SyntaxError:
            return {"success": False}, history
        write_result = self.runtime._execute_fast_tool(
            task=task,
            step_id=f"iteration_{iteration}_product_intent_retry_file_writer",
            tool_name="file_writer",
            input_metadata=ToolInputMetadata.from_mapping("file_writer", {
                "file_path": str(target_file),
                "content": retry_code,
                "encoding": "utf-8",
                "create_dirs": True,
                "overwrite": True,
            }),
            parent_task_id=self.runtime._dashboard_stage_id("execution"),
        )
        if not write_result.success:
            return {"success": False, "write_result": write_result}, history
        review_result = self.runtime._execute_fast_tool(
            task=task,
            step_id=f"iteration_{iteration}_product_intent_retry_code_reviewer",
            tool_name="code_reviewer",
            input_metadata=ToolInputMetadata.from_mapping("code_reviewer", {
                "code": retry_code,
                "language": "python",
                "prompt_context": prompt_context,
            }),
            parent_task_id=self.runtime._dashboard_stage_id("execution"),
        )
        return {
            "success": review_result.success,
            "code": retry_code,
            "write_result": write_result,
            "review_result": review_result,
        }, history

    def _should_use_bug_fix(self, evaluation: EvaluationResult) -> bool:
        warning_check = getattr(evaluation, "warning_check_result", None)
        if warning_check and warning_check.requires_fix:
            return True
        issues = list(getattr(evaluation, "validation_issues", []) or [])
        return any(
            getattr(issue, "severity", "blocking") == "blocking"
            and getattr(issue, "category", "") in {"runtime_error", "runtime_warning"}
            for issue in issues
        )

    def _execute_bug_fix(
        self,
        *,
        task: Task,
        iteration: int,
        target_file: Path,
        run_command: str,
        evaluation: EvaluationResult,
        actions: list[str],
    ) -> IterationResult:
        warning_check = evaluation.warning_check_result
        primary_issue = self._primary_bug_fix_issue(evaluation)
        fix_instruction = (
            "Fix only the runtime/program execution failure reported by validation. "
            "Do not change product behavior, controls, scoring, UX goals, or unrelated semantics."
        )
        if primary_issue is not None:
            fix_instruction += f"\nValidation issue: {primary_issue.message}"
            if primary_issue.recommended_action:
                fix_instruction += f"\nRecommended action: {primary_issue.recommended_action}"
        if warning_check:
            fix_instruction += f"\nWarning reason: {warning_check.reason}"
            fix_instruction += f"\nRecommended fix: {warning_check.recommended_fix}"
        result = self.runtime._execute_fast_tool(
            task=task,
            step_id=f"iteration_{iteration}_bug_fix_tool",
            tool_name="bug_fix_tool",
            input_metadata=ToolInputMetadata.from_mapping(
                "bug_fix_tool",
                {
                    "command": run_command,
                    "cwd": str(target_file.parent),
                    "file_paths": [str(target_file)],
                    "timeout": 30,
                    "warning_check_required": bool(warning_check and warning_check.requires_fix),
                    "warning_check_result": warning_check.to_json_dict() if warning_check else None,
                    "fix_instruction": fix_instruction,
                    "_llm_client": getattr(self.runtime, "llm_client", None),
                },
            ),
            parent_task_id=self.runtime._dashboard_stage_id("execution"),
        )
        if result.success:
            return IterationResult(
                iteration=iteration,
                validation_passed=True,
                completed_successful_iteration=False,
                applied_actions=actions,
                changed_files=[str(target_file)],
                success=True,
                failure_stage=None,
                failed_tool=None,
            )
        reason = result.error_message or "bug_fix_tool failed to repair the runtime execution issue."
        return self._failure(iteration, actions, reason, "bug_fix_tool")

    def _primary_bug_fix_issue(self, evaluation: EvaluationResult):
        issues = [
            issue
            for issue in (getattr(evaluation, "validation_issues", []) or [])
            if getattr(issue, "category", "") in {"runtime_error", "runtime_warning"}
        ]
        blocking = [issue for issue in issues if getattr(issue, "severity", "blocking") == "blocking"]
        return (blocking or issues or [None])[0]

    def run_code_generation_retry_pipeline(
        self,
        *,
        task: Task,
        iteration: int,
        goal: str,
        target_file: Path,
        current_code: str,
        evaluation: EvaluationResult,
        actions: list[str],
        improvement_report: dict[str, Any],
        is_repair: bool,
    ) -> tuple[ToolExecutionEnvelopeMetadata, list[dict[str, Any]]]:
        attempts = [
            (
                "full",
                self.build_code_generation_prompt_context(
                    goal=goal,
                    target_file=target_file,
                    current_code=current_code,
                    evaluation=evaluation,
                    actions=actions,
                    improvement_report=improvement_report,
                    is_repair=is_repair,
                    simplified=False,
                    mode="full",
                ),
            ),
            (
                "compact",
                self.build_code_generation_prompt_context(
                    goal=goal,
                    target_file=target_file,
                    current_code=current_code,
                    evaluation=evaluation,
                    actions=actions,
                    improvement_report=improvement_report,
                    is_repair=is_repair,
                    simplified=True,
                    mode="compact",
                ),
            ),
            (
                "surgical",
                self.build_code_generation_prompt_context(
                    goal=goal,
                    target_file=target_file,
                    current_code=current_code,
                    evaluation=evaluation,
                    actions=actions,
                    improvement_report=improvement_report,
                    is_repair=is_repair,
                    simplified=True,
                    mode="surgical",
                ),
            ),
        ]
        retry_history: list[dict[str, Any]] = []
        last_result: ToolExecutionEnvelopeMetadata | None = None

        for attempt_index, (mode, prompt_context) in enumerate(attempts, 1):
            prompt_length = len(json.dumps(prompt_context, ensure_ascii=False, default=str))
            if attempt_index > 1:
                previous_error = last_result.error_message if last_result else "unknown error"
                self.runtime.logger.log_event(
                    "autonomous_iteration_code_generation_retry",
                    {
                        "iteration": iteration,
                        "tool": "code_generator",
                        "mode": mode,
                        "attempt": attempt_index,
                        "previous_error": previous_error,
                        "prompt_length": prompt_length,
                        "prompt_layers": self.runtime._prompt_context_layer_summary(prompt_context),
                        "selected_actions": actions,
                        "target_file": str(target_file),
                    },
                    session_id=self.runtime.session_id or "unknown",
                    turn_id=1,
                )
                self._log_agent(
                    "code_generation_retry",
                    {"iteration": iteration, "mode": mode, "previous_error": previous_error},
                    {"prompt_length": prompt_length},
                )
                if self.runtime.enhanced_ui:
                    self.runtime.enhanced_ui.set_current_task_state(
                        title=f"Improvement {iteration} retry",
                        details=(
                            f"Retry mode: {mode}\n"
                            f"Prompt length: {prompt_length}\n"
                            f"Previous error: {previous_error}"
                        ),
                        status="running",
                    )

            result = self.execute_code_generation_for_improvement(
                task=task,
                iteration=iteration,
                target_file=target_file,
                improvement_prompt=str(prompt_context.get("tool_task") or (actions[0] if actions else "")),
                prompt_context=prompt_context,
                simplified=(mode == "compact"),
                mode=mode,
            )
            last_result = result
            attempt_summary = self.code_generation_attempt_summary(
                mode=mode,
                prompt=json.dumps(prompt_context, ensure_ascii=False, default=str),
                result=result,
                attempt=attempt_index,
            )
            retry_history.append(attempt_summary)
            self.append_code_generation_attempt_to_dashboard(iteration, attempt_summary)
            if result.success and result.output is not None:
                return result, retry_history
            if not self.should_retry_code_generation_attempt(result):
                return result, retry_history

        if last_result is None:
            last_result = ToolExecutionEnvelopeMetadata(
                tool_name="code_generator",
                step_id=f"iteration_{iteration}_code_generator",
                status="fail",
                success=False,
                input_metadata=ToolInputMetadata(tool_name="code_generator"),
                failure={
                    "kind": "failure",
                    "error_type": "CodeGenerationError",
                    "error_message": "No code generation attempts were executed.",
                },
            )
        return last_result, retry_history

    def build_code_generation_prompt_context(
        self,
        *,
        goal: str,
        target_file: Path,
        current_code: str,
        evaluation: EvaluationResult,
        actions: list[str],
        improvement_report: dict[str, Any],
        is_repair: bool,
        simplified: bool,
        mode: str,
    ) -> dict[str, Any]:
        if mode == "surgical":
            code_context = self.compact_code_context(current_code, actions, max_chars=1000)
            agent_instruction = (
                "Surgical retry: make the smallest complete source replacement that satisfies the iteration goal. "
                "Avoid unrelated rewrites."
            )
        elif simplified:
            code_context = self.compact_code_context(current_code, actions, max_chars=2200)
            agent_instruction = (
                "Compact retry: previous attempt was too expensive or failed. Use only the relevant code context "
                "and preserve existing useful behavior."
            )
        else:
            code_context = self.budget_code_context(current_code, max_chars=7000)
            agent_instruction = (
                "Full improvement: implement the selected autonomous iteration goal while honoring the product-fit rubric."
            )

        acceptance = (
            improvement_report.get("must_implement_next")
            or improvement_report.get("selected_goal", {}).get("acceptance_criteria")
            or actions[:2]
        )
        tool_task = actions[0] if actions else str(improvement_report.get("next_iteration_goal") or "Apply the selected improvement.")
        prompt_context = self.runtime._build_prompt_context(
            original_goal=goal,
            project_path=target_file.parent,
            written_files=[str(target_file)],
            run_command="",
            evaluation=evaluation,
            iteration_goal=str(improvement_report.get("next_iteration_goal") or tool_task),
            acceptance_criteria=[str(item) for item in acceptance[:5]],
            tool_task=tool_task,
            agent_instruction=agent_instruction,
            target_file=target_file,
            current_code=current_code,
            code_context=code_context,
            mode=mode,
        )
        prompt_context["improvement_report_summary"] = {
            "summary": improvement_report.get("summary") or "",
            "opportunities": (improvement_report.get("improvement_opportunities") or [])[:4],
            "recommended_actions": (improvement_report.get("recommended_actions") or [])[:4],
            "blocking_risks": (improvement_report.get("blocking_risks") or [])[:3],
        }
        if isinstance(improvement_report.get("diagnosis"), dict):
            prompt_context["diagnosis"] = improvement_report["diagnosis"]
        if isinstance(improvement_report.get("selected_candidate"), dict):
            prompt_context["selected_candidate"] = improvement_report["selected_candidate"]
        return prompt_context

    def build_surgical_project_improvement_prompt(
        self,
        *,
        goal: str,
        target_file: Path,
        current_code: str,
        evaluation: EvaluationResult,
        actions: list[str],
        improvement_report: dict[str, Any],
        is_repair: bool,
    ) -> str:
        requirements = improvement_report.get("must_implement_next") or actions[:2]
        code_context = self.compact_code_context(current_code, actions, max_chars=900)
        return (
            "SURGICAL RETRY MODE: previous code-generation attempts timed out or failed.\n"
            "Make the smallest safe complete replacement for this Python file.\n"
            f"Goal: {goal}\n"
            f"Target file: {target_file.name}\n"
            f"Mode: {'repair validation failure' if is_repair else 'single focused improvement'}\n"
            f"Only action: {self.runtime._short_dashboard_text(actions[0] if actions else '', 300)}\n"
            f"Acceptance criteria: {requirements[:3]}\n"
            f"Current validation errors: {evaluation.validation_errors[:2]}\n"
            "Do not add unrelated features. Preserve existing gameplay, controls, score, food, collision, restart/quit, and entry point.\n"
            "Return only full Python source code.\n\n"
            f"Minimal relevant code context:\n{code_context}"
        )

    def code_generation_attempt_summary(
        self,
        *,
        mode: str,
        prompt: str,
        result: ToolExecutionEnvelopeMetadata,
        attempt: int,
    ) -> dict[str, Any]:
        return {
            "attempt": attempt,
            "mode": mode,
            "step_id": result.step_id,
            "prompt_length": len(prompt),
            "status": result.status,
            "success": result.success,
            "duration_seconds": result.duration_seconds,
            "error_type": result.failure.error_type if result.failure else None,
            "error": result.error_message,
            "timeout_override": result.timeout_override,
            "tool_retry_count": result.retry_count,
            "tool_retry_history": result.retry_history,
        }

    def append_code_generation_attempt_to_dashboard(self, iteration: int, attempt: dict[str, Any]) -> None:
        if not self.runtime.enhanced_ui:
            return
        status = "completed" if attempt.get("success") else "failed"
        duration = attempt.get("duration_seconds")
        duration_text = f"; duration={duration:.0f}s" if isinstance(duration, (int, float)) else ""
        error = attempt.get("error") or ""
        self.runtime._append_dashboard_stage_child(
            "execution",
            child_id=f"code_generation_attempt_{iteration}_{attempt.get('mode')}",
            description=(
                f"code_generator {attempt.get('mode')} attempt: "
                f"prompt={attempt.get('prompt_length')} chars; status={attempt.get('status')}"
                f"{duration_text}" + (f"; error={self.runtime._short_dashboard_text(error, 80)}" if error else "")
            ),
            kind="result",
            status=status,
        )

    def should_retry_code_generation_attempt(self, result: ToolExecutionEnvelopeMetadata) -> bool:
        if result.success:
            return False
        return self.is_timeout_tool_result(result)

    def build_project_improvement_prompt(
        self,
        *,
        goal: str,
        target_file: Path,
        current_code: str,
        evaluation: EvaluationResult,
        actions: list[str],
        improvement_report: dict[str, Any],
        is_repair: bool,
        simplified: bool,
    ) -> str:
        report_summary = improvement_report.get("summary") or ""
        report_opportunities = improvement_report.get("improvement_opportunities") or []
        report_recommended_actions = improvement_report.get("recommended_actions") or []
        report_must_implement = improvement_report.get("must_implement_next") or []
        report_blocking_risks = improvement_report.get("blocking_risks") or []
        selected_goal = improvement_report.get("selected_goal") or {}
        designed_tasks = improvement_report.get("designed_tasks") or []
        if simplified:
            compact_requirements = report_must_implement or actions[:2]
            code_context = self.compact_code_context(current_code, actions, max_chars=1800)
            return (
                "COMPACT RETRY MODE: the previous code-generation request timed out.\n"
                "Make the smallest complete replacement for the target Python file.\n"
                f"Original user goal: {goal}\n"
                f"Target file: {target_file.name}\n"
                f"Iteration mode: {'repair blocking validation failure' if is_repair else 'focused improvement'}\n"
                f"Selected action: {self.runtime._short_dashboard_text(actions[0] if actions else '', 500)}\n"
                f"Must satisfy: {compact_requirements[:3]}\n"
                f"Validation errors: {evaluation.validation_errors[:3]}\n"
                "Preserve existing controls, scoring, food, collision/game-over, restart/quit, and runnable entry point.\n"
                "Return only the full replacement Python code.\n\n"
                f"Relevant current code:\n{code_context}"
            )
        observable_requirement = (
            "Fix the blocking validation problem without adding unrelated features."
            if is_repair
            else (
                "Implement one visible, user-observable upgrade from the selected task. "
                "Do not rewrite unrelated parts, remove existing behavior, or simplify the game. "
                "Preserve controls, score display, food, collision/game-over handling, restart/quit behavior, and README run compatibility."
            )
        )
        code_context = self.budget_code_context(current_code, max_chars=9000)
        return (
            "FULL IMPROVEMENT MODE\n"
            f"Improve this Python project for the original user goal: {goal}\n"
            f"Target file: {target_file}\n"
            f"Iteration mode: {'repair blocking validation failure' if is_repair else 'feature/quality improvement'}\n"
            f"Latest validation passed: {evaluation.validation_passed}\n"
            f"Validation errors: {evaluation.validation_errors}\n"
            f"Warnings: {evaluation.warnings[:3]}\n"
            f"Improvement report summary: {report_summary}\n"
            f"Improvement opportunities: {report_opportunities[:4]}\n"
            f"Recommended actions from report: {report_recommended_actions[:3]}\n"
            f"Must implement next: {report_must_implement[:4]}\n"
            f"Blocking risks from report: {report_blocking_risks[:3]}\n"
            f"Selected goal: {selected_goal}\n"
            f"Designed tasks: {designed_tasks[:1]}\n"
            f"Selected actions for this iteration: {actions[:2]}\n"
            f"Implementation requirement: {observable_requirement}\n\n"
            "Return a complete replacement for the target Python file only. "
            "Preserve a runnable entry point and avoid unrelated rewrites.\n\n"
            f"Current code context:\n{code_context}"
        )

    def execute_code_generation_for_improvement(
        self,
        *,
        task: Task,
        iteration: int,
        target_file: Path,
        improvement_prompt: str,
        simplified: bool,
        mode: str | None = None,
        prompt_context: dict[str, Any] | None = None,
    ) -> ToolExecutionEnvelopeMetadata:
        mode = mode or ("compact" if simplified else "full")
        step_prefix = "" if mode == "full" else f"{mode}_"
        input_metadata_payload = {
            "task_description": improvement_prompt,
            "language": "python",
            "context": f"Improve {target_file} ({mode} retry mode)",
        }
        if prompt_context:
            input_metadata_payload["prompt_context"] = prompt_context
        result = self.runtime._execute_fast_tool(
            task=task,
            step_id=f"iteration_{iteration}_{step_prefix}code_generator",
            tool_name="code_generator",
            input_metadata=ToolInputMetadata.from_mapping("code_generator", input_metadata_payload),
            parent_task_id=self.runtime._dashboard_stage_id("execution"),
        )
        self._log_agent(
            "code_generation_completed",
            {"iteration": iteration, "mode": mode, "target_file": str(target_file)},
            {"success": result.success, "status": result.status},
            success=result.success,
            error=result.error_message,
        )
        return result

    def is_timeout_tool_result(self, result: ToolExecutionEnvelopeMetadata) -> bool:
        if result.success:
            return False
        error_type = result.failure.error_type if result.failure else ""
        error_text = f"{error_type} {result.error_message or ''} {result.status or ''}"
        return "timeout" in error_text.lower()

    def visible_tool_failure_summary(
        self,
        *,
        tool: str,
        tool_result: ToolExecutionEnvelopeMetadata,
        retry_attempted: bool = False,
    ) -> str:
        raw_error = tool_result.error_message or f"{tool} failed."
        timeout = self.is_timeout_tool_result(tool_result)
        timeout_seconds = tool_result.timeout_override
        duration = tool_result.duration_seconds
        if timeout:
            elapsed = timeout_seconds or (f"{duration:.0f}" if isinstance(duration, (int, float)) else None)
            elapsed_text = f" after {elapsed}s" if elapsed else ""
            return f"{tool} timed out{elapsed_text}; compact retry attempted: {'yes' if retry_attempted else 'no'}"
        return str(raw_error)

    def budget_code_context(self, code: str, max_chars: int) -> str:
        if len(code) <= max_chars:
            return code
        head = code[: max_chars // 2]
        tail = code[-max_chars // 2 :]
        return (
            f"{head}\n\n"
            f"# [OpenPilot prompt budget: omitted {len(code) - len(head) - len(tail)} middle chars]\n\n"
            f"{tail}"
        )

    def compact_code_context(self, code: str, actions: list[str], max_chars: int) -> str:
        if len(code) <= max_chars:
            return code
        lines = code.splitlines()
        action_text = " ".join(actions).lower()
        keywords = {"def ", "class ", "if __name__"}
        if "key" in action_text or "control" in action_text or "pause" in action_text or "wasd" in action_text:
            keywords.update({"on_key", "bind", "update", "draw"})
        snippets: list[str] = []
        for idx, line in enumerate(lines):
            if any(keyword in line for keyword in keywords):
                start = max(0, idx - 4)
                end = min(len(lines), idx + 18)
                snippet = "\n".join(lines[start:end])
                if snippet not in snippets:
                    snippets.append(snippet)
        context = "\n\n# ...\n\n".join(snippets)
        if not context:
            context = "\n".join(lines[:80])
        if len(context) > max_chars:
            context = context[:max_chars] + "\n# [OpenPilot compact prompt truncated]"
        return context

    def log_iteration_failure(
        self,
        *,
        iteration: int,
        stage: str,
        tool: str,
        target_file: Path,
        actions: list[str],
        error: str,
        prompt_length: int,
        current_code_length: int,
        retry_attempted: bool,
        tool_result: ToolExecutionEnvelopeMetadata,
        retry_history: list[dict[str, Any]] | None = None,
    ) -> None:
        visible_summary = self.visible_tool_failure_summary(
            tool=tool,
            tool_result=tool_result,
            retry_attempted=retry_attempted,
        )
        self.runtime.logger.log_event(
            "autonomous_iteration_stage_failed",
            {
                "iteration": iteration,
                "stage": stage,
                "tool": tool,
                "target_file": str(target_file),
                "iteration_goal": actions[0] if actions else "",
                "actions": actions,
                "selected_actions": actions,
                "error": visible_summary,
                "error_type": tool_result.failure.error_type if tool_result.failure else None,
                "status": tool_result.status,
                "timeout_override": tool_result.timeout_override,
                "duration_seconds": tool_result.duration_seconds,
                "prompt_length": prompt_length,
                "current_code_length": current_code_length,
                "retry_attempted": retry_attempted,
                "compact_retry_used": retry_attempted,
                "retry_history": retry_history or [],
                "retry_attempts_used": len(retry_history or []),
                "visible_summary": visible_summary,
            },
            session_id=self.runtime.session_id or "unknown",
            turn_id=1,
        )
        self._log_agent(
            "task_executor_failed",
            {"iteration": iteration, "stage": stage, "tool": tool},
            {"error": visible_summary},
            success=False,
            error=visible_summary,
        )
        if self.runtime.enhanced_ui:
            self.runtime._finish_active_operations(visible_summary)
            self.runtime.enhanced_ui.set_current_task_state(
                title=f"{stage} failed",
                details=(
                    f"Iteration: {iteration}\n"
                    f"Stage: {stage}\n"
                    f"Tool: {tool}\n"
                    f"Reason: {visible_summary}\n"
                    f"Retry attempted: {'yes' if retry_attempted else 'no'}\n"
                    f"Attempts used: {len(retry_history or [])}"
                ),
                status="failed",
            )

    def _failure(
        self,
        iteration: int,
        actions: list[str],
        reason: str,
        failed_tool: str,
        *,
        retry_attempted: bool = False,
        retry_history: list[dict[str, Any]] | None = None,
    ) -> IterationResult:
        self._log_agent(
            "task_executor_failed",
            {"iteration": iteration, "failed_tool": failed_tool},
            {"reason": reason},
            success=False,
            error=reason,
        )
        return IterationResult(
            iteration=iteration,
            validation_passed=False,
            completed_successful_iteration=False,
            applied_actions=actions,
            changed_files=[],
            success=False,
            error=reason,
            failure_stage="Task Executor",
            failed_tool=failed_tool,
            failure_reason=reason,
            retry_attempted=retry_attempted,
            retry_history=retry_history or [],
        )

    def _log_agent(
        self,
        event_type: str,
        input_summary: Any,
        output_summary: Any,
        *,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        logger = getattr(self.runtime, "logger", None)
        if not logger or not hasattr(logger, "log_structured_event"):
            return
        logger.log_structured_event(
            source_type="agent",
            source_name="autonomous_iteration.task_executor",
            phase="task_executor",
            event_type=event_type,
            session_id=getattr(self.runtime, "session_id", None) or "unknown",
            turn_id=1,
            success=success,
            input_summary=input_summary,
            output_summary=output_summary,
            error=error,
        )
