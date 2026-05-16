from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from rich.console import Console

from execution.task_models import Task, TaskDecompositionResult, TaskExecutionResult, TaskStatus
from core.openpilot_log import OpenPilotLogger
from execution.session_runner import AutopilotSessionRunner


class FakeSemantic:
    task_type = SimpleNamespace(value="coding")
    risk_level = SimpleNamespace(value="low")
    required_resources = []
    confidence = 0.9

    def model_dump(self):
        return {"task_type": "coding", "risk_level": "low"}


class FakeMemoryResult:
    memories = []


class FakeTaskDecomposer:
    def __init__(self) -> None:
        self.decompose_called = False
        self.assemble_called = False

    def decompose(self, task_description, context):
        self.decompose_called = True
        task = Task(id="t1", description="Write app.py")
        return TaskDecompositionResult(
            original_task=Task(id="root", description=task_description),
            subtasks=[task],
            task_graph_summary="summary",
            decomposition_rationale="because",
            estimated_total_effort=1.0,
        )

    def assemble_results(self, original_task, subtasks):
        self.assemble_called = True
        return {"summary": original_task.description, "tasks": len(subtasks)}


class FakeMemoryStore:
    def query(self, query, limit=5):
        return FakeMemoryResult()


class FakeSemanticAnalyzer:
    def analyze_goal(self, goal):
        return FakeSemantic()


class FakeTracker:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start_tracking(self):
        self.started = True

    def stop_tracking(self):
        self.stopped = True

    @contextmanager
    def track_task(self, title, metadata):
        yield


class FakeEnhancedUI:
    def __init__(self) -> None:
        self.graph_updates: list[dict] = []
        self.current_updates: list[dict] = []
        self.activities: list[tuple[str, str]] = []

    def set_task_graph_state(self, **kwargs):
        self.graph_updates.append(kwargs)

    def set_current_task_state(self, **kwargs):
        self.current_updates.append(kwargs)

    def log_activity(self, level, message):
        self.activities.append((level, message))


class FakeRuntime:
    def __init__(self, tmp_path: Path) -> None:
        self.console = Console(record=True, width=100)
        self.logger = OpenPilotLogger(tmp_path / "session_runner.jsonl")
        self.session_id = "session"
        self.stats = {
            "start_time": None,
            "end_time": None,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "success": False,
        }
        self.required_successful_improvements = 2
        self.semantic_analyzer = FakeSemanticAnalyzer()
        self.memory_store = FakeMemoryStore()
        self.task_decomposer = FakeTaskDecomposer()
        self.enhanced_ui = FakeEnhancedUI()
        self.tracker = FakeTracker()
        self.fast_result = None
        self.improvement_result = None
        self.written_files = []
        self.project_path = None

    def _show_start_panel(self, goal):
        self.console.print(f"start {goal}")

    def _show_task_tree(self, decomposition):
        self.console.print("tree")

    def _show_completion_summary(self, decomposition, results):
        self.console.print("summary")

    def _try_simple_code_artifact_fast_path(self, goal, semantic):
        return self.fast_result

    def _dashboard_task_items(self, tasks, running_task_id=None):
        return [{"id": task.id, "status": task.status.value} for task in tasks]

    def _execute_tasks(self, tasks, goal):
        for task in tasks:
            task.mark_completed({"ok": True})
        return [
            TaskExecutionResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                result={"ok": True},
                duration=0.1,
            )
            for task in tasks
        ]

    def _finalize_project_readme(self, goal, results):
        return {"success": True, "result": {"file_path": "README.md"}}

    def _collect_written_files(self, results):
        return self.written_files

    def _infer_project_path_from_files(self, goal, written_files):
        return self.project_path

    def _run_iterative_improvement(self, **kwargs):
        return self.improvement_result

    def _format_iteration_failure(self, improvement_result):
        return improvement_result.get("failure_reason") or "iteration failed"

    def _stop_tracking_if_owned(self):
        self.tracker.stop_tracking()


def test_session_runner_standard_returns_existing_result_shape(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path)
    runtime.stats["start_time"] = runtime.stats["end_time"] = __import__("datetime").datetime.now()
    runner = AutopilotSessionRunner(runtime)

    result = runner.run("Build app", {}, mode="standard")

    assert result["success"] is True
    assert result["goal"] == "Build app"
    assert result["final_result"] == {"summary": "Build app", "tasks": 1}
    assert result["completed_improvements"] == 0
    assert runtime.task_decomposer.decompose_called is True


def test_session_runner_enhanced_returns_existing_result_shape(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("execution.session_runner.time.sleep", lambda seconds: None)
    runtime = FakeRuntime(tmp_path)
    runtime.stats["start_time"] = runtime.stats["end_time"] = __import__("datetime").datetime.now()
    runner = AutopilotSessionRunner(runtime)

    result = runner.run("Build app", {}, mode="enhanced_ui")

    assert result["success"] is True
    assert "final_result" not in result
    assert runtime.tracker.started is True
    assert runtime.tracker.stopped is True
    assert runtime.enhanced_ui.current_updates[-1]["title"] == "Success"


def test_session_runner_fast_path_skips_decomposition(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path)
    runtime.fast_result = {"success": True, "fast": True}
    runner = AutopilotSessionRunner(runtime)

    result = runner.run("print hello", {}, mode="standard")

    assert result == {"success": True, "fast": True}
    assert runtime.task_decomposer.decompose_called is False


def test_session_runner_surfaces_autonomous_iteration_failure(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path)
    runtime.stats["start_time"] = runtime.stats["end_time"] = __import__("datetime").datetime.now()
    runtime.written_files = [str(tmp_path / "app.py")]
    runtime.project_path = tmp_path
    runtime.improvement_result = {
        "success": False,
        "failure_stage": "Task Executor",
        "failed_iteration": 1,
        "failed_tool": "code_generator",
        "failure_reason": "generation failed",
        "retry_attempted": True,
        "retry_history": [{"attempt": "full"}],
        "remaining_goals": ["Fix app"],
    }
    runner = AutopilotSessionRunner(runtime)

    result = runner.run("Build app", {}, mode="standard")

    assert result["success"] is False
    assert result["iteration_error"] == "generation failed"
    assert result["failure_stage"] == "Task Executor"
    assert result["failed_tool"] == "code_generator"
    assert result["retry_history"] == [{"attempt": "full"}]
