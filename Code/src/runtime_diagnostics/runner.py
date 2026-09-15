"""Task-pool runner for real-task-driven diagnostics."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
import uuid

from pydantic import BaseModel, Field

from autonomous_iteration.pi_task_runner import PiTaskRunner
from metadata import TaskAdmissionGrant, TaskApprovalGrant
from runtime_diagnostics.raw_task import RawTaskInput
from runtime_diagnostics.recorder import DiagnosticRecorder
from runtime_diagnostics.task_pool import load_raw_tasks


ExecutorFn = Callable[[str, dict[str, Any]], dict[str, Any]]


class TaskPoolRunResult(BaseModel):
    run_id: str
    execution_run_id: str | None = None
    task_id: str
    source: str
    success: bool
    started_at: str
    finished_at: str
    error: str | None = None
    result_summary: dict[str, Any] = Field(default_factory=dict)


class RuntimeTaskPoolRunner:
    """Run a list of RawTaskInput tasks through a provided executor."""

    def __init__(self, executor: ExecutorFn, *, recorder: DiagnosticRecorder | None = None):
        self.executor = executor
        self.recorder = recorder or DiagnosticRecorder()

    def run_path(self, path: str | Path) -> list[TaskPoolRunResult]:
        return self.run_tasks(load_raw_tasks(path))

    def run_tasks(self, tasks: list[RawTaskInput]) -> list[TaskPoolRunResult]:
        results: list[TaskPoolRunResult] = []
        for task in tasks:
            results.append(self.run_task(task))
        return results

    def run_task(self, task: RawTaskInput) -> TaskPoolRunResult:
        started_at = datetime.now(UTC).isoformat()
        runtime_session_id = uuid.uuid4().hex
        run = self.recorder.start_run(
            task.task_id,
            source=task.source,
            raw_input=task.raw_input,
            session_id=runtime_session_id,
        )
        context = {
            "task_id": task.task_id,
            "run_id": run.run_id,
            "session_id": runtime_session_id,
            "source": task.source,
            "attachments": task.attachments,
            "tags": task.tags,
            **task.context,
        }
        self.recorder.record_run(
            {
                "event": "task_pool_item_started",
                "task_id": task.task_id,
                "run_id": run.run_id,
                "session_id": runtime_session_id,
                "source": task.source,
                "tags": task.tags,
                "started_at": started_at,
            }
        )
        try:
            result = self.executor(task.raw_input, context)
            success = bool(result.get("success")) if isinstance(result, dict) else bool(result)
            execution_run_id = (
                str(result.get("run_id") or "").strip()
                if isinstance(result, dict)
                else ""
            )
            result_summary = _result_summary(result)
            run_result = TaskPoolRunResult(
                run_id=run.run_id,
                execution_run_id=execution_run_id or None,
                task_id=task.task_id,
                source=task.source,
                success=success,
                started_at=started_at,
                finished_at=datetime.now(UTC).isoformat(),
                result_summary=result_summary,
                error=None if success else str(result.get("error") or result.get("failure_reason") or "task failed") if isinstance(result, dict) else None,
            )
        except Exception as exc:
            run_result = TaskPoolRunResult(
                run_id=run.run_id,
                execution_run_id=None,
                task_id=task.task_id,
                source=task.source,
                success=False,
                started_at=started_at,
                finished_at=datetime.now(UTC).isoformat(),
                error=str(exc),
                result_summary={},
            )
        self.recorder.record_run(
            {
                "event": "task_pool_item_finished",
                "task_id": task.task_id,
                "run_id": run.run_id,
                "execution_run_id": run_result.execution_run_id,
                "session_id": runtime_session_id,
                "source": task.source,
                "success": run_result.success,
                "error": run_result.error,
                "result_summary": run_result.result_summary,
                "started_at": run_result.started_at,
                "finished_at": run_result.finished_at,
            }
        )
        return run_result


def build_pi_executor(*, runner: PiTaskRunner | None = None) -> ExecutorFn:
    """Build a diagnostics executor that uses the same typed Pi boundary as the CLI.

    Raw task-pool text is not authority. Callers must attach the immutable
    ``TaskAdmissionGrant`` produced by task admission and, for mutations, the
    matching ``TaskApprovalGrant`` and conversation identity.
    """
    pi_runner = runner or PiTaskRunner()

    def _execute(goal: str, context: dict[str, Any]) -> dict[str, Any]:
        admission = context.get("task_admission")
        if not isinstance(admission, TaskAdmissionGrant):
            raise TypeError("Pi diagnostics execution requires a validated TaskAdmissionGrant")
        supplied_task_id = str(context.get("task_id") or "").strip()
        if supplied_task_id and supplied_task_id != admission.task_id:
            raise ValueError("Pi diagnostics task identity does not match TaskAdmissionGrant")
        supplied_project_path = str(context.get("project_path") or "").strip()
        if supplied_project_path and (
            Path(supplied_project_path).expanduser().resolve(strict=False)
            != Path(admission.project_root).expanduser().resolve(strict=False)
        ):
            raise ValueError("Pi diagnostics project identity does not match TaskAdmissionGrant")
        approval = context.get("task_approval")
        if approval is not None and not isinstance(approval, TaskApprovalGrant):
            raise TypeError("Pi diagnostics execution requires a validated TaskApprovalGrant")
        conversation_id = str(
            context.get("conversation_id") or context.get("session_id") or ""
        ).strip()
        return pi_runner.run(
            goal,
            admission,
            approval=approval,
            source=str(context.get("source") or "runtime_diagnostics"),
            conversation_id=conversation_id,
        )

    return _execute


def _result_summary(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"success": bool(result)}
    summary: dict[str, Any] = {"success": bool(result.get("success"))}
    for key in ("goal", "failure_stage", "failed_tool", "failure_reason"):
        value = result.get(key)
        if value not in (None, "", [], {}):
            summary[key] = value
    runtime_report = result.get("runtime_report")
    if isinstance(runtime_report, dict):
        for key in ("phase", "verification_status", "completion_reason"):
            value = runtime_report.get(key)
            if value not in (None, "", [], {}):
                summary[f"runtime_report.{key}"] = value
    return summary
