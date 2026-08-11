from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

from autonomous_iteration.models import IterationResult
from autonomous_iteration.intelligent_autopilot import IntelligentAutopilot
from metadata import (
    EnvironmentOperation,
    EnvironmentReadiness,
    EnvironmentSyncMetadata,
    ProjectStackPresetMetadata,
)
from ui import enhanced_cli


def test_success_details_explain_each_accepted_iteration() -> None:
    details = enhanced_cli._format_success_details(
        {
            "completed_improvements": 1,
            "required_improvements": 1,
            "iterations": [
                IterationResult(
                    iteration=1,
                    validation_passed=True,
                    completed_successful_iteration=True,
                    applied_actions=["Add a visible score display."],
                    changed_files=["/project/snake_game.py"],
                    success=True,
                )
            ],
        },
        delivery_environment=SimpleNamespace(
            project_path="/project",
            run_command=".venv/bin/python snake_game.py",
        ),
    )

    assert "代码优化: 1/1" in details
    assert "第 1 轮: Add a visible score display." in details
    assert "修改文件: snake_game.py" in details
    assert "验证: 通过" in details
    assert "运行: cd /project && .venv/bin/python snake_game.py" in details


def test_success_details_unwrap_checkpointed_session_result() -> None:
    details = enhanced_cli._format_success_details(
        {
            "success": True,
            "session_result": {
                "completed_improvements": 1,
                "required_improvements": 1,
                "iterations": [
                    {
                        "iteration": 1,
                        "validation_passed": True,
                        "applied_actions": ["Add a start screen."],
                        "changed_files": ["/project/snake_game.py"],
                    }
                ],
            },
        }
    )

    assert "代码优化: 1/1" in details
    assert "第 1 轮: Add a start screen." in details
    assert "修改文件: snake_game.py" in details


def test_confirmed_interactive_handoff_launches_through_autopilot(monkeypatch) -> None:
    environment = SimpleNamespace(
        project_path="/project",
        command_cwd="/project",
        run_command=".venv/bin/python snake_game.py",
    )
    calls: list[tuple[object, bool]] = []

    class FakeAutopilot:
        def project_delivery_environment(self, _result):
            return environment

        def launch_interactive_application(self, selected, *, user_confirmed):
            calls.append((selected, user_confirmed))
            return SimpleNamespace(
                success=True,
                output=SimpleNamespace(get=lambda key, default=None: 4321 if key == "process_id" else default),
            )

    class FakeUI:
        def __init__(self) -> None:
            self.console = SimpleNamespace(print=lambda *args, **kwargs: None)
            self.successes: list[tuple[str, str]] = []
            self.errors: list[tuple[str, str]] = []

        def show_success(self, title, details="") -> None:
            self.successes.append((str(title), str(details)))

        def show_error(self, title, details="") -> None:
            self.errors.append((str(title), str(details)))

    monkeypatch.setattr("ui.question_ui.QuestionUI.ask_confirm", lambda *args, **kwargs: True)
    ui = FakeUI()

    launch = enhanced_cli._offer_interactive_application_launch(
        FakeAutopilot(),
        {"success": True},
        ui,
    )

    assert launch is not None
    assert calls == [(environment, True)]
    assert ui.errors == []
    assert ui.successes[-1] == ("应用已启动", "PID: 4321\n关闭应用窗口即可结束进程。")


def _interactive_environment(project: Path) -> EnvironmentSyncMetadata:
    return EnvironmentSyncMetadata(
        operation=EnvironmentOperation.SETUP,
        readiness=EnvironmentReadiness.READY,
        environment_id="env:test",
        project_path=str(project),
        python_executable="/usr/bin/python3",
        command_cwd=str(project),
        run_command=".venv/bin/python snake_game.py",
        stack_preset=ProjectStackPresetMetadata(
            project_path=str(project),
            delivery_surface="interactive_runtime",
        ),
    )


def test_project_delivery_environment_reuses_ready_typed_environment(tmp_path) -> None:
    environment = _interactive_environment(tmp_path)
    autopilot = object.__new__(IntelligentAutopilot)
    autopilot._collect_written_files = lambda _results: [str(tmp_path / "snake_game.py")]
    autopilot._infer_project_path_from_files = lambda _goal, _files: tmp_path
    autopilot._project_environment_context = lambda _path: environment.to_json_dict()

    selected = autopilot.project_delivery_environment(
        {"success": True, "goal": "build a game", "results": []}
    )

    assert selected == environment


def test_project_delivery_environment_unwraps_checkpointed_session_result(tmp_path) -> None:
    environment = _interactive_environment(tmp_path)
    target = tmp_path / "snake_game.py"
    autopilot = object.__new__(IntelligentAutopilot)
    autopilot._collect_written_files = lambda results: [str(target)] if results else []
    autopilot._infer_project_path_from_files = lambda _goal, _files: tmp_path
    autopilot._project_environment_context = lambda _path: environment.to_json_dict()

    selected = autopilot.project_delivery_environment(
        {
            "success": True,
            "session_result": {
                "success": True,
                "goal": "build a game",
                "results": [object()],
            },
        }
    )

    assert selected == environment


def test_project_delivery_environment_rejects_nested_result_without_explicit_success(tmp_path) -> None:
    autopilot = object.__new__(IntelligentAutopilot)

    selected = autopilot.project_delivery_environment(
        {
            "success": True,
            "session_result": {"goal": "build a game", "results": [object()]},
        }
    )

    assert selected is None


def test_interactive_launch_passes_typed_user_confirmation_as_runtime_only_handle(tmp_path) -> None:
    environment = _interactive_environment(tmp_path)
    autopilot = object.__new__(IntelligentAutopilot)
    captured = {}

    def execute_fast_tool(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(success=True)

    autopilot._execute_fast_tool = execute_fast_tool

    result = autopilot.launch_interactive_application(
        environment,
        user_confirmed=True,
    )

    metadata = captured["input_metadata"]
    execution_context = metadata.runtime_handles["_tool_execution_context"]
    assert result.success is True
    assert metadata.mode == "interactive"
    assert "user_confirmed" not in metadata.to_json_dict()
    assert execution_context.user_confirmed is True
    assert execution_context.input_metadata.runtime_handles == {}


def test_interactive_launch_rejects_truthy_non_boolean_confirmation(tmp_path) -> None:
    autopilot = object.__new__(IntelligentAutopilot)

    with pytest.raises(PermissionError, match="explicit user confirmation"):
        autopilot.launch_interactive_application(
            _interactive_environment(tmp_path),
            user_confirmed="yes",
        )
