from __future__ import annotations

import json
from types import SimpleNamespace

from autonomous_iteration.task_models import Task, TaskExecutionContext, TaskExecutionResult, TaskStatus
from core.openpilot_log import OpenPilotLogger
from autonomous_iteration.agents.tool_planning_executor import ToolPlanningTaskExecutor
from autonomous_iteration.intelligent_autopilot import IntelligentAutopilot
from autonomous_iteration.runtime_controller import EditGuard, FileSelector, RuntimeVerifier, StateUpdater, ToolRouter
from autonomous_iteration.tool_io import ExecutionToolIO
from metadata import AgentPhase, CodeArtifactMetadata, FileArtifactMetadata, ResultStatus, RuntimeStateMetadata, TaskResultMetadata, TextArtifactMetadata, ToolResultMetadata
from tools.multi_file_reader import MULTI_FILE_READER_DEFINITION


class FakeLLM:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.requests = []
        self._index = 0

    def complete(self, request):
        self.requests.append(request)
        payload = self.payload
        if isinstance(payload, list):
            payload = payload[min(self._index, len(payload) - 1)]
            self._index += 1
        if isinstance(payload, str):
            return SimpleNamespace(parsed_json=None, content=payload)
        return SimpleNamespace(parsed_json=payload, content=json.dumps(payload))


class FakeToolRegistry:
    def get(self, tool_name):
        if tool_name == "multi_file_reader":
            return MULTI_FILE_READER_DEFINITION
        return None

    def get_executor(self, tool_name):
        if tool_name in {"code_generator", "file_writer", "command_executor", "multi_file_reader"}:
            return lambda *_args, **_kwargs: None
        return None

    def list_all(self):
        return []


class FakeToolExecutor:
    def __init__(self) -> None:
        self.selections = []

    def execute_single(self, selection, context=None):
        self.selections.append(selection)
        if selection.tool_name == "code_generator":
            return SimpleNamespace(
                success=True,
                output_metadata=ToolResultMetadata(
                    tool_name="code_generator",
                    status=ResultStatus.SUCCESS,
                    result=CodeArtifactMetadata(code="print('ok')", language="python"),
                ),
                error=None,
                execution_time_ms=10,
            )
        if selection.tool_name == "file_writer":
            payload = selection.input_metadata.to_params()
            return SimpleNamespace(
                success=True,
                output_metadata=ToolResultMetadata(
                    tool_name="file_writer",
                    status=ResultStatus.SUCCESS,
                    result=FileArtifactMetadata(file_path=payload["file_path"], content=payload["content"]),
                ),
                error=None,
                execution_time_ms=5,
            )
        if selection.tool_name == "command_executor":
            payload = selection.input_metadata.to_params()
            return SimpleNamespace(
                success=True,
                output_metadata=ToolResultMetadata(
                    tool_name="command_executor",
                    status=ResultStatus.SUCCESS,
                    result=TextArtifactMetadata(content="command ok", attributes=payload),
                ),
                error=None,
                execution_time_ms=5,
            )
        if selection.tool_name == "multi_file_reader":
            payload = selection.input_metadata.to_params()
            return SimpleNamespace(
                success=True,
                output_metadata=ToolResultMetadata(
                    tool_name="multi_file_reader",
                    status=ResultStatus.SUCCESS,
                    result=FileArtifactMetadata(
                        file_path=str(payload.get("directory_path") or ""),
                        files=list(payload.get("file_paths") or []),
                        content="combined",
                    ),
                ),
                error=None,
                execution_time_ms=5,
            )
        return SimpleNamespace(
            success=False,
            output_metadata=None,
            error=SimpleNamespace(error_type="UnknownTool", error_message="unknown tool", recoverable=True),
            execution_time_ms=1,
        )


class InvalidMultiFileReaderExecutor(FakeToolExecutor):
    def execute_single(self, selection, context=None):
        if selection.tool_name == "multi_file_reader":
            self.selections.append(selection)
            return SimpleNamespace(
                success=False,
                output_metadata=None,
                error=SimpleNamespace(
                    error_type="ValueError",
                    error_message="multi_file_reader requires file_paths or directory_path",
                    recoverable=False,
                ),
                execution_time_ms=1,
            )
        return super().execute_single(selection, context)


class FakeRuntime:
    def __init__(self, tmp_path, payload) -> None:
        self.session_id = "session"
        self.logger = OpenPilotLogger(tmp_path / "tool_planning.jsonl")
        self.llm_client = FakeLLM(payload)
        self.tool_registry = FakeToolRegistry()
        self.tool_executor = FakeToolExecutor()
        self.enhanced_ui = None
        self.tool_io = ExecutionToolIO(self.logger, lambda: self.session_id)
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
            "kind": "git_snapshot",
            "project_path": str(tmp_path),
            "commit_hash": "abc1234",
            "created": True,
        }

    def _format_tools_for_llm(self, tools):
        return "No tools"

    def _resolve_chained_metadata(self, tool_name, input_metadata, last_output, last_code_output):
        return self.tool_io.resolve_chained_metadata(tool_name, input_metadata, last_output, last_code_output)

    def _map_reason_to_enum(self, reason_text):
        return self.tool_io.map_reason_to_enum(reason_text)

    def _sanitize_tool_metadata(self, input_metadata):
        return self.tool_io.sanitize_tool_metadata(input_metadata)

    def _environment_for_tool_input(self, input_metadata):
        return next(iter(self._project_environments.values()))

    def _apply_project_command_context(self, tool_name, input_metadata):
        if tool_name != "command_executor":
            return input_metadata
        environment = self._environment_for_tool_input(input_metadata)
        return input_metadata.model_copy(
            update={
                "cwd": environment["command_cwd"],
                "env": environment["command_env"],
            }
        )


class FakeUI:
    def __init__(self) -> None:
        self.events = []

    def append_tool_event(self, event) -> None:
        self.events.append(event.to_json_dict() if hasattr(event, "to_json_dict") else event)

    def set_current_task_state(self, **_kwargs) -> None:
        return None


class BrokenEventHookUI(FakeUI):
    def append_tool_event(self, event) -> None:
        raise RuntimeError("ui hook failed")


def _context(task: Task) -> TaskExecutionContext:
    return TaskExecutionContext(task=task, parent_context={"goal": "build app"}, shared_state={}, execution_history=[])


def test_tool_planning_executor_success_and_chained_file_writer(tmp_path) -> None:
    task = Task(id="task", description="Generate and write app")
    runtime = FakeRuntime(
        tmp_path,
        {
            "decision_needs": [
                {
                    "need_type": "code_generation",
                    "question": "generate code",
                    "attributes": {"task_description": "make app"},
                },
                {
                    "need_type": "file_write",
                    "question": "write file",
                    "target_path": "app.py",
                },
            ]
        },
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    assert result.result_metadata.result.attributes["all_tools_succeeded"] is True
    assert result.result_metadata.result.attributes["tool_results"][1]["input_metadata"]["content"] == "print('ok')"
    assert result.result_metadata.result.attributes["tool_results"][1]["tool_context"]["git_snapshot"]["commit_hash"] == "abc1234"
    assert runtime.tool_executor.selections[1].input_metadata.to_params() == {"file_path": "app.py", "content": "print('ok')"}
    payloads = [
        json.loads(line)["payload"]
        for line in (tmp_path / "tool_planning.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(payload.get("source_type") == "agent" for payload in payloads)
    assert any(payload.get("source_name") == "autonomous_iteration.agents.tool_planning_executor" for payload in payloads)


def test_tool_event_loop_recovers_from_text_language_code_generator(tmp_path) -> None:
    task = Task(id="task", description="Design personal assistant")
    runtime = FakeRuntime(
        tmp_path,
        [
            {
                "decision_needs": [
                    {
                        "need_type": "code_generation",
                        "question": "write design prose",
                        "attributes": {"task_description": "outline design", "language": "text"},
                    }
                ]
            },
            {
                "decision_needs": [
                    {
                        "need_type": "file_write",
                        "question": "write design note",
                        "target_path": "DESIGN.md",
                        "attributes": {"content": "# Design\n"},
                    }
                ]
            },
        ],
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    attrs = result.result_metadata.result.attributes
    assert attrs["all_tools_succeeded"] is True
    assert len(runtime.llm_client.requests) == 2
    assert attrs["tool_results"][0]["success"] is False
    assert attrs["tool_results"][0]["error"].startswith("Unsupported language")
    assert attrs["tool_results"][1]["tool"] == "file_writer"
    loop = attrs["tool_loop"]
    assert loop["recoverable_errors"][0]["error_type"] == "UnsupportedLanguage"
    assert any(event["event_type"] == "error" for event in loop["events"])


def test_tool_event_loop_emits_lifecycle_events_to_ui_hook(tmp_path) -> None:
    task = Task(id="task", description="Generate and write app")
    runtime = FakeRuntime(
        tmp_path,
        {
            "decision_needs": [
                {
                    "need_type": "code_generation",
                    "question": "generate code",
                    "attributes": {"task_description": "make app"},
                },
                {
                    "need_type": "file_write",
                    "question": "write file",
                    "target_path": "app.py",
                },
            ]
        },
    )
    runtime.enhanced_ui = FakeUI()
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    ui_events = runtime.enhanced_ui.events
    assert [event["event_type"] for event in ui_events[:3]] == ["pending", "running", "completed"]
    assert ui_events[0]["call_id"] == "task:r1:c1"
    assert ui_events[0]["tool_context"]["call_id"] == "task:r1:c1"
    assert any(event["tool_name"] == "file_writer" and event["event_type"] == "completed" for event in ui_events)


def test_tool_event_loop_emits_recoverable_error_to_ui_hook(tmp_path) -> None:
    task = Task(id="task", description="Design personal assistant")
    runtime = FakeRuntime(
        tmp_path,
        [
            {
                "decision_needs": [
                    {
                        "need_type": "code_generation",
                        "question": "write design prose",
                        "attributes": {"task_description": "outline design", "language": "text"},
                    }
                ]
            },
            {
                "decision_needs": [
                    {
                        "need_type": "file_write",
                        "question": "write design note",
                        "target_path": "DESIGN.md",
                        "attributes": {"content": "# Design\n"},
                    }
                ]
            },
        ],
    )
    runtime.enhanced_ui = FakeUI()
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    error_events = [event for event in runtime.enhanced_ui.events if event["event_type"] == "error"]
    assert error_events
    assert error_events[0]["tool_name"] == "code_generator"
    assert error_events[0]["recoverable"] is True
    assert error_events[0]["tool_error"]["error_type"] == "UnsupportedLanguage"


def test_tool_event_loop_ui_hook_failure_does_not_fail_task(tmp_path) -> None:
    task = Task(id="task", description="Generate app")
    runtime = FakeRuntime(
        tmp_path,
        {
            "decision_needs": [
                {
                    "need_type": "code_generation",
                    "question": "generate code",
                    "attributes": {"task_description": "make app"},
                }
            ]
        },
    )
    runtime.enhanced_ui = BrokenEventHookUI()
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    entries = [
        json.loads(line)
        for line in (tmp_path / "tool_planning.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(entry.get("event_type") == "tool_event_ui_hook_failed" for entry in entries)


def test_tool_event_loop_normalizes_command_executor_execute_mode(tmp_path) -> None:
    task = Task(id="task", description="Run command")
    runtime = FakeRuntime(
        tmp_path,
        {
            "decision_needs": [
                {
                    "need_type": "command_check",
                    "question": "run command",
                    "command": "python main.py",
                    "attributes": {"mode": "execute"},
                }
            ]
        },
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    assert runtime.tool_executor.selections[0].input_metadata.mode == "automatic"
    assert runtime.tool_executor.selections[0].input_metadata.cwd == str(tmp_path)
    assert runtime.tool_executor.selections[0].input_metadata.env["VIRTUAL_ENV"] == str(tmp_path / ".venv")
    loop = result.result_metadata.result.attributes["tool_loop"]
    assert loop["tool_contexts"][0]["cwd"] == str(tmp_path)
    assert loop["tool_contexts"][0]["python_command"].endswith("/.venv/bin/python")


def test_tool_planning_executor_routes_decision_needs_through_tool_router(tmp_path) -> None:
    task = Task(id="task", description="Run tests")
    runtime = FakeRuntime(
        tmp_path,
        {
            "decision_needs": [
                {
                    "need_type": "command_check",
                    "question": "verify generated project",
                    "command": "pytest",
                    "attributes": {"mode": "automatic"},
                }
            ]
        },
    )
    state = RuntimeStateMetadata(goal="build app")
    runtime.runtime_controller = SimpleNamespace(
        state=state,
        router=ToolRouter(runtime.tool_registry),
        edit_guard=EditGuard(),
        file_selector=FileSelector(),
        state_updater=StateUpdater(),
        verifier=RuntimeVerifier(),
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    assert runtime.tool_executor.selections[0].tool_name == "command_executor"
    assert runtime.tool_executor.selections[0].input_metadata.command == "pytest"
    assert state.tool_history[0]["tool_name"] == "command_executor"


def test_tool_planning_executor_rejects_old_tool_calls_protocol(tmp_path) -> None:
    task = Task(id="task", description="Use available tools")
    runtime = FakeRuntime(
        tmp_path,
        {"tool_calls": [{"tool_name": "file_writer", "reason": "write output", "input_metadata": {"file_path": "note.md"}}]},
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.FAILED
    assert result.error == "LLM generated empty decision_needs plan"


def test_tool_event_loop_missing_required_field_is_recoverable(tmp_path) -> None:
    task = Task(id="task", description="Generate code")
    runtime = FakeRuntime(
        tmp_path,
        [
            {
                "decision_needs": [
                    {
                        "need_type": "file_write",
                        "question": "write generated code",
                        "target_path": "app.py",
                    }
                ]
            },
            {
                "decision_needs": [
                    {
                        "need_type": "file_write",
                        "question": "write generated code",
                        "target_path": "app.py",
                        "attributes": {"content": "print('ok')"},
                    }
                ]
            },
        ],
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    loop = result.result_metadata.result.attributes["tool_loop"]
    assert loop["recoverable_errors"][0]["error_type"] == "MissingRequiredInput"


def test_tool_router_blocks_incomplete_directory_need_before_tool_call(tmp_path) -> None:
    task = Task(id="task", description="Validate files")
    state = RuntimeStateMetadata(goal="validate files")
    runtime = FakeRuntime(
        tmp_path,
        {
            "decision_needs": [
                {
                    "need_type": "project_structure",
                    "question": "read project files",
                    "attributes": {"pattern": "*.py"},
                }
            ]
        },
    )
    runtime.runtime_controller = SimpleNamespace(
        state=state,
        router=ToolRouter(runtime.tool_registry),
        edit_guard=EditGuard(),
        file_selector=FileSelector(),
        state_updater=StateUpdater(),
        verifier=RuntimeVerifier(),
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.FAILED
    assert result.error == "LLM generated empty decision_needs plan"
    assert state.unknowns == ["read project files"]


def test_tool_event_loop_execution_value_error_can_recover(tmp_path) -> None:
    task = Task(id="task", description="Validate files")
    runtime = FakeRuntime(
        tmp_path,
        [
            {
                "decision_needs": [
                    {
                        "need_type": "project_structure",
                        "question": "read project files",
                        "target_path": str(tmp_path),
                    }
                ]
            },
            {
                "decision_needs": [
                    {
                        "need_type": "file_write",
                        "question": "record validation",
                        "target_path": "validation.md",
                        "attributes": {"content": "ok"},
                    }
                ]
            },
        ],
    )
    runtime.tool_executor = InvalidMultiFileReaderExecutor()
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    loop = result.result_metadata.result.attributes["tool_loop"]
    assert loop["recoverable_errors"][0]["error_type"] == "ValueError"
    assert loop["recoverable_errors"][0]["recoverable"] is True
    assert runtime.tool_executor.selections[-1].tool_name == "file_writer"


def test_tool_event_loop_auto_verifies_file_writer_when_runtime_state_is_active(tmp_path) -> None:
    task = Task(id="task", description="Generate and write app")
    runtime = FakeRuntime(
        tmp_path,
        {
            "decision_needs": [
                {
                    "need_type": "file_write",
                    "question": "write app file",
                    "target_path": "app.py",
                    "attributes": {"content": "print('ok')"},
                }
            ]
        },
    )
    state = RuntimeStateMetadata(goal="build app", phase=AgentPhase.EXECUTE)
    runtime.runtime_controller = SimpleNamespace(
        state=state,
        edit_guard=EditGuard(),
        file_selector=FileSelector(),
        state_updater=StateUpdater(),
        verifier=RuntimeVerifier(),
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    assert [selection.tool_name for selection in runtime.tool_executor.selections] == ["file_writer", "command_executor"]
    assert runtime.tool_executor.selections[1].input_metadata.command == "pytest"
    attrs = result.result_metadata.result.attributes
    assert attrs["tool_results"][-1]["tool"] == "command_executor"
    assert state.verification_status == "passed"
    assert state.phase == AgentPhase.SUMMARIZE


def test_tool_event_loop_guards_mutating_command_executor(tmp_path) -> None:
    task = Task(id="task", description="Create project directory")
    runtime = FakeRuntime(
        tmp_path,
        {
            "decision_needs": [
                {
                    "need_type": "command_check",
                    "question": "create directory",
                    "command": "mkdir generated",
                    "attributes": {"mode": "automatic"},
                }
            ]
        },
    )
    state = RuntimeStateMetadata(goal="create project", phase=AgentPhase.EXECUTE)
    runtime.runtime_controller = SimpleNamespace(
        state=state,
        edit_guard=EditGuard(),
        file_selector=FileSelector(),
        state_updater=StateUpdater(),
        verifier=RuntimeVerifier(),
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    assert [selection.tool_name for selection in runtime.tool_executor.selections] == ["command_executor", "command_executor"]
    assert runtime.tool_executor.selections[1].input_metadata.command == "pytest"
    assert state.planned_edits
    assert state.planned_edits[0].target_files == [str(tmp_path)]
    assert any(event.get("event_type") == "edit_guard" and event.get("approved") for event in state.tool_history)
    assert state.verification_status == "passed"
    assert state.phase == AgentPhase.SUMMARIZE


def test_tool_prompt_describes_required_any_of_contract(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})

    prompt = runtime.tool_io.format_tools_for_llm([MULTI_FILE_READER_DEFINITION])

    assert "one of: file_paths or directory_path [required]" in prompt


def test_tool_planning_executor_invalid_or_empty_plan_returns_failed_result(tmp_path) -> None:
    task = Task(id="task", description="Do impossible thing")
    executor = ToolPlanningTaskExecutor(FakeRuntime(tmp_path, {"decision_needs": []}))

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.FAILED
    assert result.error == "LLM generated empty decision_needs plan"


def test_tool_planning_executor_bad_json_returns_failed_result(tmp_path) -> None:
    task = Task(id="task", description="Do impossible thing")
    executor = ToolPlanningTaskExecutor(FakeRuntime(tmp_path, "{bad-json"))

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.FAILED
    assert "Failed to parse LLM response as JSON" in result.error


def test_intelligent_autopilot_execute_task_proxy_uses_tool_planning_agent(tmp_path) -> None:
    class FakeAgent:
        def execute_task(self, task, context):
            return TaskExecutionResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                result_metadata=TaskResultMetadata(
                    task_id=task.id,
                    status=ResultStatus.SUCCESS,
                    result=TextArtifactMetadata(content="proxied", attributes={"proxied": True}),
                ),
                duration=0.0,
            )

    class MinimalLLM:
        pass

    autopilot = IntelligentAutopilot(MinimalLLM(), log_file=tmp_path / "autopilot.jsonl")
    autopilot.tool_planning_task_executor = FakeAgent()
    task = Task(id="task", description="Proxy task")

    result = autopilot._execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    assert result.result_metadata.result.get("proxied") is True
