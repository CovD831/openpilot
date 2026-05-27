from __future__ import annotations

import json

from core.openpilot_log import OpenPilotLogger
from core.tool_event_emitter import ToolEventEmitter
from metadata import ToolInputMetadata


class FakeRegistry:
    def get(self, tool_name):
        return None


class FakeUI:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.events = []

    def append_tool_event(self, event) -> None:
        if self.fail:
            raise RuntimeError("ui hook failed")
        self.events.append(event.to_json_dict())


class FakeRuntime:
    def __init__(self, tmp_path, *, ui=None) -> None:
        self.session_id = "session"
        self.logger = OpenPilotLogger(tmp_path / "events.jsonl")
        self.enhanced_ui = ui
        self.tool_registry = FakeRegistry()
        self._project_environments = {
            str(tmp_path): {
                "project_path": str(tmp_path),
                "command_cwd": str(tmp_path),
                "command_env": {"VIRTUAL_ENV": str(tmp_path / ".venv")},
                "python_command": str(tmp_path / ".venv" / "bin" / "python"),
                "pip_command": str(tmp_path / ".venv" / "bin" / "pip"),
            }
        }
        self._last_git_snapshot = {
            "commit_hash": "abc1234",
            "created": True,
        }


def test_tool_event_emitter_builds_context_and_emits_lifecycle_event(tmp_path) -> None:
    ui = FakeUI()
    runtime = FakeRuntime(tmp_path, ui=ui)
    emitter = ToolEventEmitter(runtime)
    input_metadata = ToolInputMetadata.from_mapping("command_executor", {"command": "python main.py", "cwd": str(tmp_path)})

    context = emitter.build_context(
        task_id="task",
        session_id="session",
        step_id="step",
        call_id="task:step",
        tool_name="command_executor",
        input_metadata=input_metadata,
    )
    tool_call = emitter.create_tool_call(
        session_id="session",
        task_id="task",
        step_id="step",
        call_id="task:step",
        tool_name="command_executor",
        input_metadata=input_metadata,
        tool_context=context,
    )
    event = emitter.emit(
        task_id="task",
        tool_call=tool_call,
        event_type="running",
        status="running",
        input_metadata=input_metadata,
        tool_context=context,
    )

    assert event.call_id == "task:step"
    assert event.tool_context is context
    assert event.event_type == "running"
    assert context.cwd == str(tmp_path)
    assert context.python_command.endswith("/.venv/bin/python")
    assert context.git_snapshot["commit_hash"] == "abc1234"
    assert ui.events[0]["call_id"] == "task:step"


def test_tool_event_emitter_tolerates_missing_ui_hook(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path, ui=None)
    emitter = ToolEventEmitter(runtime)
    input_metadata = ToolInputMetadata.from_mapping("file_writer", {"file_path": str(tmp_path / "app.py")})
    context = emitter.build_context(
        task_id="task",
        session_id="session",
        step_id="step",
        call_id="task:step",
        tool_name="file_writer",
        input_metadata=input_metadata,
    )
    tool_call = emitter.create_tool_call(
        session_id="session",
        task_id="task",
        step_id="step",
        call_id="task:step",
        tool_name="file_writer",
        input_metadata=input_metadata,
        tool_context=context,
    )

    event = emitter.emit(task_id="task", tool_call=tool_call, event_type="completed", status="completed")

    assert event.event_type == "completed"


def test_tool_event_emitter_logs_ui_hook_failure_without_raising(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path, ui=FakeUI(fail=True))
    emitter = ToolEventEmitter(runtime)
    input_metadata = ToolInputMetadata.from_mapping("file_writer", {"file_path": str(tmp_path / "app.py")})
    context = emitter.build_context(
        task_id="task",
        session_id="session",
        step_id="step",
        call_id="task:step",
        tool_name="file_writer",
        input_metadata=input_metadata,
    )
    tool_call = emitter.create_tool_call(
        session_id="session",
        task_id="task",
        step_id="step",
        call_id="task:step",
        tool_name="file_writer",
        input_metadata=input_metadata,
        tool_context=context,
    )

    emitter.emit(task_id="task", tool_call=tool_call, event_type="running", status="running")

    entries = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(entry["event_type"] == "tool_event_ui_hook_failed" for entry in entries)
