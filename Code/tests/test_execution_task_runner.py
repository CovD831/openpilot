from __future__ import annotations

from rich.console import Console

from autonomous_iteration.task_models import Task, TaskExecutionContext, TaskExecutionResult, TaskPriority, TaskStatus
from core.openpilot_log import OpenPilotLogger
from autonomous_iteration.task_runner import ExecutionTaskRunner


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
    def __init__(self, tmp_path, *, enhanced: bool = False, fail_order: bool = False) -> None:
        self.console = Console(record=True, width=100)
        self.logger = OpenPilotLogger(tmp_path / "task_runner.jsonl")
        self.session_id = "session"
        self.use_enhanced_ui = enhanced
        self.enhanced_ui = FakeEnhancedUI()
        self.task_decomposer = FakeTaskDecomposer(fail_order=fail_order)
        self.stats = {"tasks_completed": 0, "tasks_failed": 0}
        self.executed: list[str] = []
        self.raise_for: set[str] = set()

    def _execute_task(self, task: Task, context: TaskExecutionContext) -> TaskExecutionResult:
        self.executed.append(task.id)
        if task.id in self.raise_for:
            raise RuntimeError("boom")
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


def test_task_runner_standard_executes_graph_order(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path)
    runtime.task_decomposer = FakeTaskDecomposer(order=["b", "a"])
    runner = ExecutionTaskRunner(runtime)
    tasks = _tasks()

    results = runner.execute_tasks(tasks, "goal")

    assert runtime.executed == ["b", "a"]
    assert [result.status for result in results] == [TaskStatus.COMPLETED, TaskStatus.COMPLETED]
    assert all(task.status == TaskStatus.COMPLETED for task in tasks)
    assert runtime.stats["tasks_completed"] == 2


def test_task_runner_falls_back_to_sequential_order(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path, fail_order=True)
    runner = ExecutionTaskRunner(runtime)
    tasks = _tasks()

    runner.execute_tasks(tasks, "goal")

    assert runtime.executed == ["a", "b"]
    assert "executing sequentially" in runtime.console.export_text()


def test_task_runner_enhanced_converts_task_exception_to_failed_result(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path, enhanced=True)
    runtime.raise_for = {"a"}
    runner = ExecutionTaskRunner(runtime)
    tasks = _tasks()

    results = runner.execute_tasks(tasks, "goal")

    assert results[0].status == TaskStatus.FAILED
    assert "Task execution exception" in results[0].error
    assert tasks[0].status == TaskStatus.FAILED
    assert runtime.enhanced_ui.current_updates[-1]["status"] == "completed"


def test_task_runner_dashboard_items_marks_running_task(tmp_path) -> None:
    runner = ExecutionTaskRunner(FakeRuntime(tmp_path))
    items = runner.dashboard_task_items(_tasks(), running_task_id="a")

    assert items[0]["status"] == "running"
    assert items[1]["status"] == "pending"
