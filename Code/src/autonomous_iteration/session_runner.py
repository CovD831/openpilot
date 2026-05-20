"""Autopilot session orchestration extracted from IntelligentAutopilot."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from autonomous_iteration.task_models import TaskStatus


class AutopilotSessionRunner:
    """Run a full autopilot session in standard or enhanced UI mode."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def run(self, goal: str, context: dict[str, Any], mode: str = "standard") -> dict[str, Any]:
        """Run the full execution shell."""
        self._log(
            "session_started",
            input_summary={"goal": goal, "mode": mode},
            success=None,
        )
        if mode == "enhanced_ui":
            return self._run_enhanced_ui(goal, context)
        if mode == "standard":
            return self._run_standard(goal, context)
        raise ValueError(f"Unsupported autopilot session mode: {mode}")

    def _run_enhanced_ui(self, goal: str, context: dict[str, Any]) -> dict[str, Any]:
        runtime = self.runtime
        runtime.tracker.start_tracking()
        stages = [
            "Semantic Analysis",
            "Memory Retrieval",
            "Task Decomposition",
            "Execution",
            "Evaluation",
            "Iteration 1",
            "Iteration 2",
            "Result Assembly",
        ]
        stage_statuses = {stage: "pending" for stage in stages}
        runtime.enhanced_ui.set_task_graph_state(
            goal=goal,
            stages=stages,
            stage_statuses=stage_statuses,
            current_stage="Semantic Analysis",
            tasks=[],
        )
        runtime.enhanced_ui.set_current_task_state(
            title="Semantic Analysis",
            details=f"Goal: {goal[:120]}",
            status="running",
        )

        try:
            stage_statuses["Semantic Analysis"] = "running"
            runtime.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                current_stage="Semantic Analysis",
            )
            with runtime.tracker.track_task("Semantic Analysis", {"goal": goal}):
                semantic = runtime.semantic_analyzer.analyze_goal(goal)

            stage_statuses["Semantic Analysis"] = "completed"
            runtime.enhanced_ui.set_task_graph_state(stage_statuses=stage_statuses)
            runtime.enhanced_ui.log_activity("success", f"Analysis complete: {semantic.task_type.value}")
            runtime.enhanced_ui.set_current_task_state(
                title="Semantic Analysis",
                details=(
                    f"Task Type: {semantic.task_type.value}\n"
                    f"Risk Level: {semantic.risk_level.value}\n"
                    f"Required Resources: {len(semantic.required_resources)}"
                ),
                status="completed",
            )
            time.sleep(1.5)

            stage_statuses["Memory Retrieval"] = "running"
            runtime.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                current_stage="Memory Retrieval",
            )
            runtime.enhanced_ui.set_current_task_state(
                title="Memory Retrieval",
                details="Searching for relevant past experiences",
                status="running",
            )
            with runtime.tracker.track_task("Memory Retrieval", {"query": goal}):
                memories = runtime.memory_store.query(goal, limit=5)

            stage_statuses["Memory Retrieval"] = "completed"
            runtime.enhanced_ui.set_task_graph_state(stage_statuses=stage_statuses)
            if memories.memories:
                runtime.enhanced_ui.log_activity("success", f"Found {len(memories.memories)} relevant memories")
                memory_info = f"Found {len(memories.memories)} relevant memories:\n\n"
                for i, mem in enumerate(memories.memories[:3], 1):
                    memory_info += f"{i}. [{mem.memory_type.value}] {mem.content[:60]}...\n"
                runtime.enhanced_ui.set_current_task_state(
                    title="Memory Retrieval",
                    details=memory_info,
                    status="completed",
                )
                time.sleep(1.5)
            else:
                runtime.enhanced_ui.log_activity("info", "No relevant memories found")
                runtime.enhanced_ui.set_current_task_state(
                    title="Memory Retrieval",
                    details="No relevant memories found",
                    status="completed",
                )

            self._enrich_context(context, goal, semantic, memories)
            fast_result = runtime._try_simple_code_artifact_fast_path(goal, semantic)
            if fast_result is not None:
                self._log("session_fast_path_completed", output_summary={"mode": "enhanced_ui"}, success=True)
                return fast_result

            stage_statuses["Task Decomposition"] = "running"
            runtime.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                current_stage="Task Decomposition",
            )
            runtime.enhanced_ui.set_current_task_state(
                title="Task Decomposition",
                details="Breaking down task into executable subtasks",
                status="running",
            )
            with runtime.tracker.track_task("Task Decomposition", {"goal": goal}):
                decomposition = runtime.task_decomposer.decompose(
                    task_description=goal,
                    context=context,
                )

            stage_statuses["Task Decomposition"] = "completed"
            runtime.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                tasks=runtime._dashboard_task_items(decomposition.subtasks),
            )
            runtime.enhanced_ui.log_activity("success", f"Created {len(decomposition.subtasks)} subtasks")

            breakdown_info = f"Created {len(decomposition.subtasks)} subtasks:\n\n"
            for i, subtask in enumerate(decomposition.subtasks[:5], 1):
                breakdown_info += f"{i}. {subtask.description[:70]}...\n"
            if len(decomposition.subtasks) > 5:
                breakdown_info += f"\n... and {len(decomposition.subtasks) - 5} more tasks"
            runtime.enhanced_ui.set_current_task_state(
                title="Task Decomposition",
                details=breakdown_info,
                status="completed",
            )
            time.sleep(2.0)
            time.sleep(3.0)

            stage_statuses["Execution"] = "running"
            runtime.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                current_stage="Execution",
                tasks=runtime._dashboard_task_items(decomposition.subtasks),
            )
            runtime.enhanced_ui.set_current_task_state(
                title="Execution",
                details=f"Running {len(decomposition.subtasks)} tasks",
                status="running",
            )

            results = runtime._execute_tasks(decomposition.subtasks, goal)
            all_tasks_completed = all(t.status == TaskStatus.COMPLETED for t in decomposition.subtasks)
            stage_statuses["Execution"] = "completed" if all_tasks_completed else "failed"
            runtime.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                tasks=runtime._dashboard_task_items(decomposition.subtasks),
            )
            readme_result, written_files, project_path, improvement_result = self._finalize_project_outputs(
                goal,
                results,
                all_tasks_completed,
            )

            stage_statuses["Result Assembly"] = "running"
            runtime.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                current_stage="Result Assembly",
            )
            runtime.enhanced_ui.set_current_task_state(
                title="Result Assembly",
                details="Assembling final result",
                status="running",
            )
            with runtime.tracker.track_task("Result Assembly", {}):
                runtime.task_decomposer.assemble_results(
                    decomposition.original_task,
                    decomposition.subtasks,
                )
            stage_statuses["Result Assembly"] = "completed"
            runtime.enhanced_ui.set_task_graph_state(stage_statuses=stage_statuses)

            success, iteration_error_msg = self._update_stats(decomposition, improvement_result)
            runtime._stop_tracking_if_owned()
            self._set_enhanced_completion_state(success, readme_result, improvement_result, iteration_error_msg)

            result = self._build_result(
                goal=goal,
                semantic=semantic,
                decomposition=decomposition,
                results=results,
                readme_result=readme_result,
                improvement_result=improvement_result,
                iteration_error_msg=iteration_error_msg,
                success=success,
                include_final_result=False,
            )
            self._log(
                "session_completed",
                output_summary={"mode": "enhanced_ui", "success": success, "project_path": str(project_path) if project_path else None},
                success=success,
            )
            return result

        except Exception as exc:
            runtime.tracker.stop_tracking()
            runtime.enhanced_ui.set_current_task_state(
                title="Error",
                details=f"Execution failed: {str(exc)}",
                status="failed",
            )
            self._log("session_failed", success=False, error=str(exc))
            raise

    def _run_standard(self, goal: str, context: dict[str, Any]) -> dict[str, Any]:
        runtime = self.runtime
        try:
            runtime._show_start_panel(goal)

            runtime.console.print("[bold cyan]🧠 Analyzing goal...[/bold cyan]")
            semantic = runtime.semantic_analyzer.analyze_goal(goal)
            runtime.console.print(f"  • Task type: [cyan]{semantic.task_type.value}[/cyan]")
            runtime.console.print(
                f"  • Risk level: [{'red' if semantic.risk_level.value == 'high' else 'yellow' if semantic.risk_level.value == 'medium' else 'green'}]{semantic.risk_level.value}[/]"
            )
            runtime.console.print(f"  • Confidence: {semantic.confidence:.2f}")
            runtime.console.print()

            runtime.console.print("[bold cyan]🧠 Retrieving memories...[/bold cyan]")
            memories = runtime.memory_store.query(goal, limit=5)
            if memories.memories:
                runtime.console.print(f"  • Found {len(memories.memories)} relevant memories")
                for mem in memories.memories[:3]:
                    runtime.console.print(f"    - [{mem.memory_type.value}] {mem.content[:60]}...")
            else:
                runtime.console.print("  • No relevant memories found")
            runtime.console.print()

            self._enrich_context(context, goal, semantic, memories)
            fast_result = runtime._try_simple_code_artifact_fast_path(goal, semantic)
            if fast_result is not None:
                self._log("session_fast_path_completed", output_summary={"mode": "standard"}, success=True)
                return fast_result

            runtime.console.print("[bold cyan]🔍 Decomposing task...[/bold cyan]")
            decomposition = runtime.task_decomposer.decompose(
                task_description=goal,
                context=context,
            )

            runtime.console.print(f"  • Original task: {decomposition.original_task.description}")
            runtime.console.print(f"  • Subtasks: {len(decomposition.subtasks)}")
            runtime.console.print(f"  • Estimated effort: {decomposition.estimated_total_effort:.1f} units")
            runtime.console.print()
            runtime._show_task_tree(decomposition)

            runtime.logger.log_event(
                "task_decomposition",
                {
                    "goal": goal,
                    "original_task_id": decomposition.original_task.id,
                    "subtask_count": len(decomposition.subtasks),
                    "estimated_effort": decomposition.estimated_total_effort,
                    "rationale": decomposition.decomposition_rationale,
                },
                session_id=runtime.session_id,
                turn_id=1,
            )

            runtime.console.print("[bold cyan]⚡ Executing tasks...[/bold cyan]")
            results = runtime._execute_tasks(decomposition.subtasks, goal)
            all_tasks_completed = all(t.status == TaskStatus.COMPLETED for t in decomposition.subtasks)
            readme_result, written_files, project_path, improvement_result = self._finalize_project_outputs(
                goal,
                results,
                all_tasks_completed,
            )

            runtime.console.print()
            runtime.console.print("[bold cyan]📦 Assembling results...[/bold cyan]")
            final_result = runtime.task_decomposer.assemble_results(
                decomposition.original_task,
                decomposition.subtasks,
            )

            success, iteration_error_msg = self._update_stats(decomposition, improvement_result)
            runtime._show_completion_summary(decomposition, results)
            if iteration_error_msg:
                runtime.console.print(f"[yellow]Autonomous iteration warning:[/yellow] {iteration_error_msg}")

            result = self._build_result(
                goal=goal,
                semantic=semantic,
                decomposition=decomposition,
                results=results,
                readme_result=readme_result,
                improvement_result=improvement_result,
                iteration_error_msg=iteration_error_msg,
                success=success,
                include_final_result=True,
                final_result=final_result,
            )
            self._log(
                "session_completed",
                output_summary={"mode": "standard", "success": success, "project_path": str(project_path) if project_path else None},
                success=success,
            )
            return result

        except Exception as exc:
            runtime.console.print(f"\n[bold red]❌ Execution failed: {exc}[/bold red]")
            runtime.stats["success"] = False
            runtime.stats["end_time"] = datetime.now()
            runtime.logger.log_event(
                "autopilot_failed",
                {
                    "goal": goal,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                session_id=runtime.session_id or "unknown",
                turn_id=1,
            )
            self._log("session_failed", success=False, error=str(exc))
            raise

    def _enrich_context(self, context: dict[str, Any], goal: str, semantic: Any, memories: Any) -> None:
        context["semantic_analysis"] = semantic.model_dump()
        context["memories"] = [m.model_dump() for m in memories.memories]
        context["goal"] = goal

    def _finalize_project_outputs(
        self,
        goal: str,
        results: list[Any],
        all_tasks_completed: bool,
    ) -> tuple[Any, list[str], Any, dict[str, Any] | None]:
        runtime = self.runtime
        readme_result = runtime._finalize_project_readme(goal, results) if all_tasks_completed else None
        written_files = runtime._collect_written_files(results)
        project_path = runtime._infer_project_path_from_files(goal, written_files) if written_files else None
        improvement_result = (
            runtime._run_iterative_improvement(
                goal=goal,
                project_path=project_path,
                written_files=written_files,
                readme_path=(
                    readme_result.output.get("file_path")
                    if readme_result and getattr(readme_result, "output", None) is not None
                    else None
                ),
            )
            if all_tasks_completed and project_path and written_files
            else None
        )
        return readme_result, written_files, project_path, improvement_result

    def _update_stats(self, decomposition: Any, improvement_result: dict[str, Any] | None) -> tuple[bool, str | None]:
        runtime = self.runtime
        success = all(t.status == TaskStatus.COMPLETED for t in decomposition.subtasks)
        iteration_error_msg = None
        if improvement_result is not None and not improvement_result.get("success", False):
            iteration_error_msg = runtime._format_iteration_failure(improvement_result)
            success = False
        runtime.stats["success"] = success
        runtime.stats["tasks_completed"] = len([t for t in decomposition.subtasks if t.status == TaskStatus.COMPLETED])
        runtime.stats["tasks_failed"] = len([t for t in decomposition.subtasks if t.status == TaskStatus.FAILED])
        runtime.stats["end_time"] = datetime.now()
        return success, iteration_error_msg

    def _set_enhanced_completion_state(
        self,
        success: bool,
        readme_result: Any,
        improvement_result: dict[str, Any] | None,
        iteration_error_msg: str | None,
    ) -> None:
        runtime = self.runtime
        if success:
            success_details = f"Goal completed successfully!\n\nCompleted {runtime.stats['tasks_completed']} tasks"
            if readme_result:
                if readme_result.success and readme_result.output is not None:
                    success_details += f"\nREADME: {readme_result.output.get('file_path')}"
                elif readme_result.error_message:
                    success_details += f"\nREADME generation failed: {readme_result.error_message}"
            if improvement_result and improvement_result.get("validation"):
                success_details += (
                    f"\nImprovements applied: {improvement_result.get('completed_improvements', 0)}/"
                    f"{improvement_result.get('required_improvements', runtime.required_successful_improvements)}"
                )
                if iteration_error_msg:
                    success_details += f"\nIteration warning: {iteration_error_msg}"
            runtime.enhanced_ui.set_current_task_state(
                title="Success",
                details=success_details,
                status="completed",
            )
        else:
            failure_details = (
                f"Goal execution failed\n\nCompleted: {runtime.stats['tasks_completed']}, "
                f"Failed: {runtime.stats['tasks_failed']}"
            )
            if iteration_error_msg:
                failure_details = (
                    f"Iteration warning: {iteration_error_msg}\n"
                    f"Completed: {runtime.stats['tasks_completed']}, Failed: {runtime.stats['tasks_failed']}"
                )
            runtime.enhanced_ui.set_current_task_state(
                title="Failed",
                details=failure_details,
                status="failed",
            )

    def _build_result(
        self,
        *,
        goal: str,
        semantic: Any,
        decomposition: Any,
        results: list[Any],
        readme_result: Any,
        improvement_result: dict[str, Any] | None,
        iteration_error_msg: str | None,
        success: bool,
        include_final_result: bool,
        final_result: Any | None = None,
    ) -> dict[str, Any]:
        runtime = self.runtime
        result = {
            "success": success,
            "goal": goal,
            "semantic_analysis": semantic,
            "decomposition": decomposition,
            "results": results,
            "readme": readme_result,
            "validation": improvement_result.get("validation") if improvement_result else None,
            "evaluation": improvement_result.get("evaluation") if improvement_result else None,
            "completed_improvements": improvement_result.get("completed_improvements", 0) if improvement_result else 0,
            "required_improvements": improvement_result.get("required_improvements", runtime.required_successful_improvements) if improvement_result else runtime.required_successful_improvements,
            "completed_iterations": improvement_result.get("completed_iterations", 0) if improvement_result else 0,
            "required_iterations": improvement_result.get("required_iterations", runtime.required_successful_improvements) if improvement_result else runtime.required_successful_improvements,
            "improvement_report": improvement_result.get("improvement_report", {}) if improvement_result else {},
            "iterations": improvement_result.get("iterations", []) if improvement_result else [],
            "partial_success": improvement_result.get("partial_success", False) if improvement_result else False,
            "iteration_error": iteration_error_msg,
            "failure_stage": improvement_result.get("failure_stage") if improvement_result else None,
            "failed_iteration": improvement_result.get("failed_iteration") if improvement_result else None,
            "failed_tool": improvement_result.get("failed_tool") if improvement_result else None,
            "failure_reason": improvement_result.get("failure_reason") if improvement_result else None,
            "retry_attempted": improvement_result.get("retry_attempted", False) if improvement_result else False,
            "retry_history": improvement_result.get("retry_history", []) if improvement_result else [],
            "remaining_goals": improvement_result.get("remaining_goals", []) if improvement_result else [],
            "stats": runtime.stats,
        }
        if include_final_result:
            result["final_result"] = final_result
        return result

    def _log(
        self,
        event_type: str,
        *,
        success: bool | None = None,
        input_summary: Any | None = None,
        output_summary: Any | None = None,
        error: str | None = None,
    ) -> None:
        logger = getattr(self.runtime, "logger", None)
        if not logger:
            return
        logger.log_structured_event(
            source_type="module",
            source_name="autonomous_iteration.session_runner",
            phase="session_execution",
            event_type=event_type,
            session_id=getattr(self.runtime, "session_id", None) or "unknown",
            turn_id=1,
            success=success,
            input_summary=input_summary,
            output_summary=output_summary,
            error=error,
        )
