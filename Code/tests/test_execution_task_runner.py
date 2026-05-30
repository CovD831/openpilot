from __future__ import annotations

from rich.console import Console

from autonomous_iteration.intelligent_autopilot import IntelligentAutopilot
from autonomous_iteration.task_models import Task, TaskExecutionContext, TaskExecutionResult, TaskPriority, TaskStatus
from core.openpilot_log import OpenPilotLogger
from metadata import FailureMetadata, ResultStatus, TaskResultMetadata


class FakeTaskDecomposer:
    def __init__(self, *, fail_order: bool = False, order: list[str] | None = None) -> None:
        self.fail_order = fail_order
        self.order = order

    def build_task_graph(self, tasks):
        return {"tasks": tasks}

    def get_execution_order(self, task_graph):
        if self.fail_order:
            raise ValueError("cycle")
        return self.order or [task.id for task in task_graph["tasks"]]


class FakeEnhancedUI:
    def __init__(self) -> None:
        self.activities: list[tuple[str, str]] = []
        self.graph_updates: list[dict] = []
        self.current_updates: list[dict] = []

    def log_activity(self, level, message):
        self.activities.append((level, message))

    def set_task_graph_state(self, **kwargs):
        self.graph_updates.append(kwargs)

    def set_current_task_state(self, **kwargs):
        self.current_updates.append(kwargs)


class FakeRuntime:
    _dashboard_task_items = IntelligentAutopilot._dashboard_task_items
    _execute_tasks_enhanced_ui = IntelligentAutopilot._execute_tasks_enhanced_ui
    _execute_tasks_standard = IntelligentAutopilot._execute_tasks_standard
    _log_task_execution_event = IntelligentAutopilot._log_task_execution_event
    _implicit_dependencies_for_task = IntelligentAutopilot._implicit_dependencies_for_task
    _blocking_dependency = IntelligentAutopilot._blocking_dependency
    _blocked_task_result = IntelligentAutopilot._blocked_task_result
    _execution_history_payload = IntelligentAutopilot._execution_history_payload

    def __init__(self, tmp_path, *, enhanced: bool = False, fail_order: bool = False) -> None:
        self.console = Console(record=True, width=100)
        self.logger = OpenPilotLogger(tmp_path / "runtime_task_execution.jsonl")
        self.session_id = "session"
        self.use_enhanced_ui = enhanced
        self.enhanced_ui = FakeEnhancedUI()
        self.task_decomposer = FakeTaskDecomposer(fail_order=fail_order)
        self.stats = {"tasks_completed": 0, "tasks_failed": 0}
        self.executed: list[str] = []
        self.raise_for: set[str] = set()
        self.fail_for: set[str] = set()

    def _execute_task(self, task: Task, context: TaskExecutionContext) -> TaskExecutionResult:
        self.executed.append(task.id)
        if task.id in self.raise_for:
            raise RuntimeError("boom")
        if task.id in self.fail_for:
            failure = FailureMetadata(
                error_type="DecisionNeedValidationError",
                error_message="Decision need schema validation failed",
                details={"failed_tool": "tool_planning_executor", "failure_stage": "Tool Planning"},
            )
            return TaskExecutionResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error=failure.error_message,
                result_metadata=TaskResultMetadata(task_id=task.id, status=ResultStatus.FAIL, failure=failure),
                duration=0.1,
            )
        return TaskExecutionResult(
            task_id=task.id,
            status=TaskStatus.COMPLETED,
            result={"ok": task.description},
            duration=0.1,
        )


def _tasks() -> list[Task]:
    return [
        Task(id="a", description="First task", priority=TaskPriority.HIGH, estimated_effort=1.0),
        Task(id="b", description="Second task", priority=TaskPriority.MEDIUM, estimated_effort=1.0),
    ]


def test_runtime_standard_task_execution_uses_graph_order(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path)
    runtime.task_decomposer = FakeTaskDecomposer(order=["b", "a"])
    tasks = _tasks()

    results = IntelligentAutopilot._execute_tasks(runtime, tasks, "goal")

    assert runtime.executed == ["b", "a"]
    assert [result.status for result in results] == [TaskStatus.COMPLETED, TaskStatus.COMPLETED]
    assert all(task.status == TaskStatus.COMPLETED for task in tasks)
    assert runtime.stats["tasks_completed"] == 2


def test_runtime_task_execution_falls_back_to_sequential_order(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path, fail_order=True)
    tasks = _tasks()

    IntelligentAutopilot._execute_tasks(runtime, tasks, "goal")

    assert runtime.executed == ["a", "b"]
    assert "executing sequentially" in runtime.console.export_text()


def test_runtime_enhanced_task_execution_converts_task_exception_to_failed_result(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path, enhanced=True)
    runtime.raise_for = {"a"}
    tasks = _tasks()

    results = IntelligentAutopilot._execute_tasks(runtime, tasks, "goal")

    assert results[0].status == TaskStatus.FAILED
    assert "Task execution exception" in results[0].error
    assert tasks[0].status == TaskStatus.FAILED
    assert runtime.enhanced_ui.current_updates[-1]["status"] == "completed"


def test_runtime_enhanced_task_execution_preserves_failed_result_metadata(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path, enhanced=True)
    runtime.fail_for = {"a"}
    tasks = _tasks()

    results = IntelligentAutopilot._execute_tasks(runtime, tasks, "goal")

    assert results[0].status == TaskStatus.FAILED
    assert tasks[0].status == TaskStatus.FAILED
    assert tasks[0].result.failure.details["failed_tool"] == "tool_planning_executor"


def test_runtime_blocks_dependency_after_failed_previous_task(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path, enhanced=True)
    runtime.fail_for = {"a"}
    tasks = [
        Task(id="a", description="Clarify requirements", priority=TaskPriority.HIGH),
        Task(
            id="b",
            description="Create project based on subtask 0 requirements",
            priority=TaskPriority.MEDIUM,
        ),
    ]

    results = IntelligentAutopilot._execute_tasks(runtime, tasks, "goal")

    assert runtime.executed == ["a"]
    assert [result.status for result in results] == [TaskStatus.FAILED, TaskStatus.FAILED]
    assert tasks[1].status == TaskStatus.BLOCKED
    assert "Blocked because task a failed" in results[1].error


def test_runtime_dashboard_items_marks_running_task(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path)
    items = IntelligentAutopilot._dashboard_task_items(runtime, _tasks(), running_task_id="a")

    assert items[0]["status"] == "running"
    assert items[1]["status"] == "pending"
