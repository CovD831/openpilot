"""Task execution loop adapter for IntelligentAutopilot."""

from __future__ import annotations

from typing import Any

from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from autonomous_iteration.task_models import Task, TaskExecutionContext, TaskExecutionResult, TaskStatus


class ExecutionTaskRunner:
    """Run decomposed tasks while preserving the existing autopilot runtime API."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def execute_tasks(self, tasks: list[Task], goal: str = "") -> list[TaskExecutionResult]:
        """Execute tasks using the runtime task graph and selected UI mode."""
        self._log(
            "task_runner_started",
            input_summary={"total_tasks": len(tasks), "goal": goal},
            success=None,
        )
        task_graph = self.runtime.task_decomposer.build_task_graph(tasks)

        try:
            execution_order = self.runtime.task_decomposer.get_execution_order(task_graph)
        except ValueError:
            if self.runtime.use_enhanced_ui:
                self.runtime.enhanced_ui.log_activity(
                    "error",
                    "Cannot determine execution order, executing sequentially",
                )
            else:
                self.runtime.console.print(
                    "[yellow]⚠ Cannot determine execution order (cyclic dependencies?), executing sequentially[/yellow]"
                )
            execution_order = [t.id for t in tasks]

        if self.runtime.use_enhanced_ui:
            results = self.execute_tasks_enhanced_ui(tasks, execution_order, goal)
        else:
            results = self.execute_tasks_standard(tasks, execution_order, goal)

        self._log(
            "task_runner_completed",
            output_summary={
                "results": len(results),
                "completed": len([r for r in results if r.status == TaskStatus.COMPLETED]),
                "failed": len([r for r in results if r.status == TaskStatus.FAILED]),
            },
            success=all(r.status == TaskStatus.COMPLETED for r in results),
        )
        return results

    def dashboard_task_items(
        self,
        tasks: list[Task],
        running_task_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Convert task models into UI dashboard rows."""
        items = []
        for task in tasks:
            status = task.status.value if hasattr(task.status, "value") else str(task.status)
            if running_task_id and task.id == running_task_id and status == "pending":
                status = "running"
            items.append({
                "id": task.id,
                "description": task.description,
                "status": status,
                "effort": f"{task.estimated_effort:.1f}u" if task.estimated_effort else "",
            })
        return items

    def execute_tasks_enhanced_ui(
        self,
        tasks: list[Task],
        execution_order: list[str],
        goal: str,
    ) -> list[TaskExecutionResult]:
        """Execute tasks with enhanced UI updates."""
        runtime = self.runtime
        results = []

        runtime.logger.log_event(
            "task_execution_started",
            {
                "total_tasks": len(tasks),
                "execution_order": execution_order,
                "goal": goal,
            },
            session_id=runtime.session_id or "unknown",
            turn_id=1,
        )
        self._log(
            "enhanced_task_execution_started",
            input_summary={"total_tasks": len(tasks), "execution_order": execution_order},
            success=None,
        )

        for i, task_id in enumerate(execution_order, 1):
            task = next((t for t in tasks if t.id == task_id), None)
            if not task:
                runtime.logger.log_event(
                    "task_not_found",
                    {"task_id": task_id, "index": i},
                    session_id=runtime.session_id or "unknown",
                    turn_id=1,
                )
                continue

            runtime.logger.log_event(
                "task_execution_start",
                {
                    "task_id": task.id,
                    "task_index": i,
                    "description": task.description,
                    "priority": task.priority.value if hasattr(task.priority, "value") else str(task.priority),
                },
                session_id=runtime.session_id or "unknown",
                turn_id=1,
            )

            completed_count = len([r for r in results if r.status == TaskStatus.COMPLETED])
            failed_count = len([r for r in results if r.status == TaskStatus.FAILED])
            status_detail = (
                f"{task.description}\n\n"
                f"Completed: {completed_count}\n"
                f"Failed: {failed_count}\n"
                f"Remaining: {len(tasks) - i}"
            )

            runtime.enhanced_ui.set_task_graph_state(
                tasks=self.dashboard_task_items(tasks, running_task_id=task.id),
                current_task_id=task.id,
            )
            runtime.enhanced_ui.set_current_task_state(
                title=f"Task {i}/{len(tasks)}",
                details=status_detail,
                status="running",
            )

            task_context = TaskExecutionContext(
                task=task,
                parent_context={"goal": goal, "session_id": runtime.session_id},
                shared_state={},
                execution_history=[],
            )

            try:
                result = runtime._execute_task(task, task_context)
                results.append(result)

                runtime.logger.log_event(
                    "task_execution_complete",
                    {
                        "task_id": task.id,
                        "task_index": i,
                        "status": result.status.value if hasattr(result.status, "value") else str(result.status),
                        "success": result.status == TaskStatus.COMPLETED,
                        "error": result.error,
                        "duration": result.duration,
                        "result_summary": str(result.result)[:200] if result.result else None,
                    },
                    session_id=runtime.session_id or "unknown",
                    turn_id=1,
                )

                if result.status == TaskStatus.COMPLETED:
                    task.mark_completed(result.result)
                    runtime.enhanced_ui.set_task_graph_state(
                        tasks=self.dashboard_task_items(tasks),
                        current_task_id=task.id,
                    )
                    runtime.enhanced_ui.set_current_task_state(
                        title=f"Task {i}/{len(tasks)}",
                        details=task.description,
                        status="completed",
                    )
                    runtime.enhanced_ui.log_activity(
                        "success",
                        f"✓ Task {i}: {task.description[:50]}... ({result.duration:.1f}s)",
                    )
                else:
                    task.mark_failed(result.error or "Unknown error")
                    runtime.enhanced_ui.set_task_graph_state(
                        tasks=self.dashboard_task_items(tasks),
                        current_task_id=task.id,
                    )
                    runtime.enhanced_ui.set_current_task_state(
                        title=f"Task {i}/{len(tasks)}",
                        details=result.error or "Unknown error",
                        status="failed",
                    )
                    runtime.enhanced_ui.log_activity("error", f"✗ Task {i} failed: {result.error}")
                    runtime.logger.log_event(
                        "task_execution_failed",
                        {
                            "task_id": task.id,
                            "task_index": i,
                            "description": task.description,
                            "error": result.error,
                            "result": result.result,
                        },
                        session_id=runtime.session_id or "unknown",
                        turn_id=1,
                    )

                if task.status == TaskStatus.PENDING:
                    runtime.logger.log_event(
                        "task_status_update_failed",
                        {
                            "task_id": task.id,
                            "task_index": i,
                            "result_status": result.status.value if hasattr(result.status, "value") else str(result.status),
                            "task_status": task.status.value if hasattr(task.status, "value") else str(task.status),
                        },
                        session_id=runtime.session_id or "unknown",
                        turn_id=1,
                    )
                    if result.status == TaskStatus.COMPLETED:
                        task.status = TaskStatus.COMPLETED
                        task.result = result.result
                    else:
                        task.status = TaskStatus.FAILED
                        task.error = result.error

            except Exception as exc:
                error_msg = f"Task execution exception: {str(exc)}"
                runtime.enhanced_ui.log_activity("error", f"✗ Task {i} exception: {str(exc)}")
                runtime.logger.log_event(
                    "task_execution_exception",
                    {
                        "task_id": task.id,
                        "task_index": i,
                        "description": task.description,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                    session_id=runtime.session_id or "unknown",
                    turn_id=1,
                )

                result = TaskExecutionResult(
                    task_id=task.id,
                    status=TaskStatus.FAILED,
                    error=error_msg,
                    duration=0.0,
                    metadata={},
                )
                results.append(result)
                task.mark_failed(error_msg)
                runtime.enhanced_ui.set_task_graph_state(
                    tasks=self.dashboard_task_items(tasks),
                    current_task_id=task.id,
                )
                runtime.enhanced_ui.set_current_task_state(
                    title=f"Task {i}/{len(tasks)}",
                    details=error_msg,
                    status="failed",
                )

        completed = len([r for r in results if r.status == TaskStatus.COMPLETED])
        failed = len([r for r in results if r.status == TaskStatus.FAILED])
        runtime.logger.log_event(
            "task_execution_summary",
            {
                "total": len(results),
                "completed": completed,
                "failed": failed,
                "task_statuses": [
                    {
                        "id": t.id,
                        "description": t.description[:50],
                        "status": t.status.value if hasattr(t.status, "value") else str(t.status),
                    }
                    for t in tasks
                ],
            },
            session_id=runtime.session_id or "unknown",
            turn_id=1,
        )
        self._log(
            "enhanced_task_execution_completed",
            output_summary={"completed": completed, "failed": failed},
            success=failed == 0,
        )

        return results

    def execute_tasks_standard(
        self,
        tasks: list[Task],
        execution_order: list[str],
        goal: str,
    ) -> list[TaskExecutionResult]:
        """Execute tasks with standard console output."""
        runtime = self.runtime
        results = []
        self._log(
            "standard_task_execution_started",
            input_summary={"total_tasks": len(tasks), "execution_order": execution_order},
            success=None,
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=runtime.console,
        ) as progress:
            task_progress = progress.add_task("Executing tasks...", total=len(tasks))

            for i, task_id in enumerate(execution_order, 1):
                task = next((t for t in tasks if t.id == task_id), None)
                if not task:
                    continue

                progress.update(
                    task_progress,
                    description=f"[{i}/{len(tasks)}] {task.description[:50]}...",
                )

                task_context = TaskExecutionContext(
                    task=task,
                    parent_context={"goal": goal, "session_id": runtime.session_id},
                    shared_state={},
                    execution_history=[],
                )

                try:
                    result = runtime._execute_task(task, task_context)
                except Exception as exc:
                    result = TaskExecutionResult(
                        task_id=task.id,
                        status=TaskStatus.FAILED,
                        error=f"Task execution exception: {str(exc)}",
                        duration=0.0,
                        metadata={},
                    )
                results.append(result)

                if result.status == TaskStatus.COMPLETED:
                    task.mark_completed(result.result)
                    runtime.stats["tasks_completed"] += 1
                    status_icon = "✓"
                    status_color = "green"
                else:
                    task.mark_failed(result.error or "Unknown error")
                    runtime.stats["tasks_failed"] += 1
                    status_icon = "✗"
                    status_color = "red"

                runtime.console.print(
                    f"  [{status_color}]{status_icon}[/{status_color}] "
                    f"Task {i}: {task.description[:60]} "
                    f"({result.duration:.1f}s)"
                )

                if result.error:
                    runtime.console.print(f"    [red]Error: {result.error}[/red]")

                progress.advance(task_progress)

        self._log(
            "standard_task_execution_completed",
            output_summary={
                "results": len(results),
                "completed": len([r for r in results if r.status == TaskStatus.COMPLETED]),
                "failed": len([r for r in results if r.status == TaskStatus.FAILED]),
            },
            success=all(r.status == TaskStatus.COMPLETED for r in results),
        )
        return results

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
            source_name="autonomous_iteration.task_runner",
            phase="task_execution",
            event_type=event_type,
            session_id=getattr(self.runtime, "session_id", None) or "unknown",
            turn_id=1,
            success=success,
            input_summary=input_summary,
            output_summary=output_summary,
            error=error,
        )
