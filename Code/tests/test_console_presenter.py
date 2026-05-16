from __future__ import annotations

from datetime import datetime, timedelta

from rich.console import Console

from execution.task_models import Task, TaskDecompositionResult, TaskPriority, TaskStatus
from core.openpilot_log import OpenPilotLogger
from execution.console_presenter import ConsolePresenter


def _decomposition() -> TaskDecompositionResult:
    original = Task(id="root", description="Build a small app")
    subtasks = [
        Task(id="t1", description="Write app.py", priority=TaskPriority.HIGH, estimated_effort=1.5),
        Task(
            id="t2",
            description="Document usage",
            priority=TaskPriority.MEDIUM,
            dependencies=["t1"],
            estimated_effort=0.5,
            status=TaskStatus.COMPLETED,
        ),
    ]
    return TaskDecompositionResult(
        original_task=original,
        subtasks=subtasks,
        task_graph_summary="summary",
        decomposition_rationale="because",
        estimated_total_effort=2.0,
    )


def test_console_presenter_renders_standard_views(tmp_path) -> None:
    console = Console(record=True, width=100)
    stats = {
        "start_time": datetime.now() - timedelta(seconds=3),
        "end_time": datetime.now(),
        "success": True,
        "tasks_completed": 2,
        "tasks_failed": 0,
    }
    presenter = ConsolePresenter(
        console,
        auto_approve_getter=lambda: False,
        stats_getter=lambda: stats,
        logger=OpenPilotLogger(tmp_path / "presenter.jsonl"),
        session_id_getter=lambda: "session",
    )
    decomposition = _decomposition()

    presenter.show_start_panel("Build a small app")
    presenter.show_task_tree(decomposition)
    presenter.show_completion_summary(decomposition, [])

    output = console.export_text()
    assert "Build a small app" in output
    assert "Write app.py" in output
    assert "Autopilot mission completed successfully" in output


def test_console_presenter_builds_task_graph_for_ui() -> None:
    console = Console(record=True)
    presenter = ConsolePresenter(console)

    graph = presenter.build_task_graph_for_ui(_decomposition())

    assert graph["original_task"] == "Build a small app"
    assert graph["total_effort"] == 2.0
    assert graph["tasks"][0]["name"] == "Write app.py"
    assert graph["tasks"][1]["dependencies"] == 1
