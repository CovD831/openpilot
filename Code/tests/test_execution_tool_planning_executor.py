from __future__ import annotations

import json
from types import SimpleNamespace

from autonomous_iteration.task_models import Task, TaskExecutionContext, TaskExecutionResult, TaskStatus
from core.openpilot_log import OpenPilotLogger
from core.tool_event_loop import ToolEventLoopRunner
from autonomous_iteration.agents.tool_planning_executor import ToolPlanningTaskExecutor
from autonomous_iteration.intelligent_autopilot import IntelligentAutopilot
from autonomous_iteration.planning_surface import (
    CapabilityExposure,
    CapabilitySourceKind,
    PlanningSurfaceCard,
    PlanningSurfaceCatalog,
    PlanningSurfaceSelector,
    StaticCapabilityCardProvider,
    ToolCapabilityCardProvider,
)
from autonomous_iteration.runtime_controller import EditGuard, FileSelector, RuntimeVerifier, StateUpdater, ToolRouter
from autonomous_iteration.tool_io import ExecutionToolIO
from core.exceptions import ErrorCategory, InvalidLLMResponseError, LLMProviderError
from metadata import AgentPhase, CodeArtifactMetadata, FileArtifactMetadata, ResolutionPlanMetadata, ResultStatus, RuntimeStateMetadata, TaskResultMetadata, TextArtifactMetadata, ToolResultMetadata
from tools.bug_fix_tool import BUG_FIX_TOOL_DEFINITION
from tools.command_tool import COMMAND_EXECUTOR_DEFINITION
from tools.code_generator import CODE_GENERATOR_DEFINITION
from tools.file_reader import FILE_READER_DEFINITION
from tools.file_writer import FILE_WRITER_DEFINITION
from tools.file_delete_tool import FILE_DELETE_TOOL_DEFINITION
from tools.environment_fix_tool import ENVIRONMENT_FIX_TOOL_DEFINITION
from tools.llm_summarizer import LLM_SUMMARIZER_DEFINITION
from tools.multi_file_reader import MULTI_FILE_READER_DEFINITION
from tools.code_editor import CODE_EDITOR_DEFINITION
from tools.code_unit_generator import CODE_UNIT_GENERATOR_DEFINITION
from tools.file_patch_writer import FILE_PATCH_WRITER_DEFINITION
from tools.readme_tool import README_TOOL_DEFINITION
from tools.task_classifier import TASK_CLASSIFIER_DEFINITION
from tools.web_searcher import WEB_SEARCHER_DEFINITION


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


class InvalidJSONLLM:
    def __init__(self) -> None:
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        raise InvalidLLMResponseError("LLM returned invalid JSON after repair attempts.")


class TransportFailureLLM:
    def __init__(self) -> None:
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        raise LLMProviderError("incomplete chunked read", category=ErrorCategory.NETWORK, retryable=True)


class FakeToolRegistry:
    def get(self, tool_name):
        if tool_name == "file_reader":
            return FILE_READER_DEFINITION
        if tool_name == "multi_file_reader":
            return MULTI_FILE_READER_DEFINITION
        if tool_name == "command_executor":
            return COMMAND_EXECUTOR_DEFINITION
        if tool_name == "code_generator":
            return CODE_GENERATOR_DEFINITION
        if tool_name == "code_unit_generator":
            return CODE_UNIT_GENERATOR_DEFINITION
        if tool_name == "code_editor":
            return CODE_EDITOR_DEFINITION
        if tool_name == "file_writer":
            return FILE_WRITER_DEFINITION
        if tool_name == "file_patch_writer":
            return FILE_PATCH_WRITER_DEFINITION
        if tool_name == "readme_tool":
            return README_TOOL_DEFINITION
        if tool_name == "web_searcher":
            return WEB_SEARCHER_DEFINITION
        if tool_name == "bug_fix_tool":
            return BUG_FIX_TOOL_DEFINITION
        if tool_name == "environment_fix_tool":
            return ENVIRONMENT_FIX_TOOL_DEFINITION
        if tool_name == "file_delete_tool":
            return FILE_DELETE_TOOL_DEFINITION
        return None

    def get_executor(self, tool_name):
        if tool_name in {
            "code_generator",
            "code_unit_generator",
            "code_editor",
            "file_writer",
            "file_patch_writer",
            "command_executor",
            "code_executor",
            "file_reader",
            "multi_file_reader",
        }:
            return lambda *_args, **_kwargs: None
        return None

    def list_all(self):
        return [
            FILE_READER_DEFINITION,
            MULTI_FILE_READER_DEFINITION,
            COMMAND_EXECUTOR_DEFINITION,
            WEB_SEARCHER_DEFINITION,
            CODE_GENERATOR_DEFINITION,
            CODE_UNIT_GENERATOR_DEFINITION,
            CODE_EDITOR_DEFINITION,
            FILE_WRITER_DEFINITION,
            FILE_PATCH_WRITER_DEFINITION,
            README_TOOL_DEFINITION,
            FILE_DELETE_TOOL_DEFINITION,
            BUG_FIX_TOOL_DEFINITION,
            ENVIRONMENT_FIX_TOOL_DEFINITION,
            LLM_SUMMARIZER_DEFINITION,
            TASK_CLASSIFIER_DEFINITION,
        ]


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
        if selection.tool_name == "code_unit_generator":
            return SimpleNamespace(
                success=True,
                output_metadata=ToolResultMetadata(
                    tool_name="code_unit_generator",
                    status=ResultStatus.SUCCESS,
                    result=CodeArtifactMetadata(
                        code="def added():\n    return 2",
                        language="python",
                        attributes={"operation_kind": "add_symbol", "symbol_name": "added"},
                    ),
                ),
                error=None,
                execution_time_ms=10,
            )
        if selection.tool_name == "code_editor":
            return SimpleNamespace(
                success=True,
                output_metadata=ToolResultMetadata(
                    tool_name="code_editor",
                    status=ResultStatus.SUCCESS,
                    result=CodeArtifactMetadata(
                        code="def change():\n    return 2",
                        language="python",
                        attributes={
                            "operation_kind": "modify_symbol",
                            "symbol_name": "change",
                            "line_start": 1,
                            "line_end": 2,
                            "patch": {
                                "operation_kind": "modify_symbol",
                                "replacement_text": "def change():\n    return 2",
                                "line_start": 1,
                                "line_end": 2,
                            },
                        },
                    ),
                ),
                error=None,
                execution_time_ms=10,
            )
        if selection.tool_name == "file_patch_writer":
            payload = selection.input_metadata.to_params()
            return SimpleNamespace(
                success=True,
                output_metadata=ToolResultMetadata(
                    tool_name="file_patch_writer",
                    status=ResultStatus.SUCCESS,
                    result=FileArtifactMetadata(file_path=payload["file_path"], attributes={"changed_ranges": [{"line_start": 1, "line_end": 2}]}),
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
        if selection.tool_name == "code_executor":
            payload = selection.input_metadata.to_params()
            return SimpleNamespace(
                success=True,
                output_metadata=ToolResultMetadata(
                    tool_name="code_executor",
                    status=ResultStatus.SUCCESS,
                    result=TextArtifactMetadata(content="code ok", attributes=payload),
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
        if selection.tool_name == "file_reader":
            payload = selection.input_metadata.to_params()
            return SimpleNamespace(
                success=True,
                output_metadata=ToolResultMetadata(
                    tool_name="file_reader",
                    status=ResultStatus.SUCCESS,
                    result=FileArtifactMetadata(
                        file_path=str(payload.get("file_path") or ""),
                        content="file content",
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


class AssistantCodeToolExecutor(FakeToolExecutor):
    def execute_single(self, selection, context=None):
        if selection.tool_name == "code_generator":
            self.selections.append(selection)
            return SimpleNamespace(
                success=True,
                output_metadata=ToolResultMetadata(
                    tool_name="code_generator",
                    status=ResultStatus.SUCCESS,
                    result=CodeArtifactMetadata(
                        code='"""OpenPilot Assistant main file."""\n\n\ndef main():\n    print("ok")\n',
                        language="python",
                    ),
                ),
                error=None,
                execution_time_ms=10,
            )
        return super().execute_single(selection, context)


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


class TimeoutThenSuccessExecutor(FakeToolExecutor):
    def __init__(self) -> None:
        super().__init__()
        self._timed_out = False

    def execute_single(self, selection, context=None):
        if selection.tool_name == "code_generator" and not self._timed_out:
            self._timed_out = True
            self.selections.append(selection)
            return SimpleNamespace(
                success=False,
                output_metadata=None,
                error=SimpleNamespace(
                    error_type="LLMTimeoutError",
                    error_message="provider read operation timed out",
                    recoverable=True,
                    retry_recommended=True,
                ),
                execution_time_ms=1,
            )
        return super().execute_single(selection, context)


class TimeoutUntilLocalFallbackExecutor(FakeToolExecutor):
    def execute_single(self, selection, context=None):
        if selection.tool_name == "code_generator":
            self.selections.append(selection)
            prompt_context = selection.input_metadata.prompt_context
            if not prompt_context.get("local_fallback_after_provider_failure"):
                return SimpleNamespace(
                    success=False,
                    output_metadata=None,
                    error=SimpleNamespace(
                        error_type="LLMTimeoutError",
                        error_message="provider read operation timed out",
                        recoverable=True,
                        retry_recommended=True,
                    ),
                    execution_time_ms=1,
                )
            return SimpleNamespace(
                success=True,
                output_metadata=ToolResultMetadata(
                    tool_name="code_generator",
                    status=ResultStatus.SUCCESS,
                    result=CodeArtifactMetadata(
                        code="print('local fallback')",
                        language="python",
                        attributes={"generation_mode": "local_fallback"},
                    ),
                ),
                error=None,
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

    def _format_planning_surface(self, tools, **kwargs):
        return self.tool_io.format_planning_surface(tools, **kwargs)

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
    assert runtime.tool_executor.selections[1].input_metadata.to_params() == {
        "file_path": "app.py",
        "content": "print('ok')",
        "operation_kind": "create_file",
    }
    payloads = [
        json.loads(line)["payload"]
        for line in (tmp_path / "tool_planning.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(payload.get("source_type") == "agent" for payload in payloads)
    assert any(payload.get("source_name") == "autonomous_iteration.agents.tool_planning_executor" for payload in payloads)


def test_tool_planning_reroutes_generated_python_away_from_requirements(tmp_path) -> None:
    task = Task(id="task", description="Create assistant core")
    runtime = FakeRuntime(
        tmp_path,
        {
            "decision_needs": [
                {
                    "need_type": "code_generation",
                    "question": "generate assistant",
                    "attributes": {"task_description": "Create the main assistant Python file"},
                },
                {
                    "need_type": "file_write",
                    "question": "write generated assistant",
                    "target_path": str(tmp_path / "requirements.txt"),
                },
            ]
        },
    )
    runtime.tool_executor = AssistantCodeToolExecutor()
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    writer_input = runtime.tool_executor.selections[1].input_metadata
    assert writer_input.file_path == str(tmp_path / "assistant.py")
    assert writer_input.content.startswith('"""OpenPilot Assistant')
    assert result.result_metadata.result.attributes["all_tools_succeeded"] is True


def test_tool_planning_defaults_missing_question_and_normalizes_readme_path(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path, {})
    executor = ToolPlanningTaskExecutor(runtime)

    tool_requests = executor._parse_decision_needs(
        SimpleNamespace(
            parsed_json={
                "decision_needs": [
                    {
                        "need_type": "readme_generation",
                        "target_path": str(tmp_path / "README.md"),
                        "attributes": {"content": "# Usage\n"},
                    }
                ]
            },
            content="",
        )
    )

    assert tool_requests[0]["tool_name"] == "readme_tool"
    assert tool_requests[0]["reason"] == f"readme_generation: {tmp_path / 'README.md'}"
    assert tool_requests[0]["input_metadata"]["project_path"] == str(tmp_path)


def test_tool_planning_moves_tool_input_fields_for_bug_fix_need(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path, {})
    executor = ToolPlanningTaskExecutor(runtime)

    tool_requests = executor._parse_decision_needs(
        SimpleNamespace(
            parsed_json={
                "decision_needs": [
                    {
                        "need_type": "bug_fix_tool",
                        "question": "Fix the failing assistant test.",
                        "command": "python test_assistant.py",
                        "file_paths": ["assistant.py", "test_assistant.py"],
                        "timeout": 30,
                        "max_iterations": 5,
                    }
                ]
            },
            content="",
        )
    )

    assert tool_requests[0]["tool_name"] == "bug_fix_tool"
    assert tool_requests[0]["input_metadata"]["file_paths"] == ["assistant.py", "test_assistant.py"]
    assert tool_requests[0]["input_metadata"]["max_iterations"] == 5
    assert tool_requests[0]["timeout_override"] == 30


def test_tool_planning_executor_chains_code_unit_to_patch_writer(tmp_path) -> None:
    task = Task(id="task", description="Add helper to app")
    runtime = FakeRuntime(
        tmp_path,
        {
            "decision_needs": [
                {
                    "need_type": "code_unit_generate",
                    "question": "generate helper function",
                    "target_path": "app.py",
                    "operation_kind": "add_symbol",
                    "symbol_name": "added",
                    "symbol_type": "function",
                    "attributes": {"task_description": "add helper"},
                },
                {
                    "need_type": "file_write",
                    "question": "insert helper function",
                    "target_path": "app.py",
                    "operation_kind": "add_symbol",
                },
            ]
        },
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    assert [selection.tool_name for selection in runtime.tool_executor.selections] == [
        "code_unit_generator",
        "file_patch_writer",
    ]
    patch_input = runtime.tool_executor.selections[1].input_metadata.to_params()
    assert patch_input["generated_unit"] == "def added():\n    return 2"
    assert patch_input["operation_kind"] == "add_symbol"


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
    assert result.error is None
    attrs = result.result_metadata.result.attributes
    assert attrs["all_tools_succeeded"] is True
    assert len(runtime.llm_client.requests) == 2
    assert attrs["tool_results"][0]["success"] is False
    assert attrs["tool_results"][0]["error"].startswith("Unsupported language")
    assert attrs["tool_results"][1]["tool"] == "file_writer"
    loop = attrs["tool_loop"]
    assert loop["recoverable_errors"][0]["error_type"] == "UnsupportedLanguage"
    assert any(event["event_type"] == "error" for event in loop["events"])


def test_tool_event_loop_retries_recoverable_code_generator_timeout(tmp_path) -> None:
    task = Task(id="task", description="Generate app")
    decision = {
        "decision_needs": [
            {
                "need_type": "code_generation",
                "question": "generate app",
                "attributes": {"task_description": "make app", "language": "python"},
            },
            {
                "need_type": "file_write",
                "question": "write app",
                "target_path": str(tmp_path / "app.py"),
            },
        ]
    }
    runtime = FakeRuntime(tmp_path, [decision, decision])
    runtime.tool_executor = TimeoutThenSuccessExecutor()
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    assert [selection.tool_name for selection in runtime.tool_executor.selections] == [
        "code_generator",
        "code_generator",
        "file_writer",
    ]
    assert len(runtime.llm_client.requests) == 1
    loop = result.result_metadata.result.attributes["tool_loop"]
    assert loop["recoverable_errors"][0]["error_type"] == "LLMTimeoutError"
    assert "bounded request" in loop["recoverable_errors"][0]["suggested_recovery"]
    entries = [
        json.loads(line)
        for line in (tmp_path / "tool_planning.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(entry["event_type"] == "tool_loop_direct_retry_scheduled" for entry in entries)


def test_tool_event_loop_uses_local_code_fallback_after_repeated_provider_timeout(tmp_path) -> None:
    task = Task(id="task", description="Generate app")
    decision = {
        "decision_needs": [
            {
                "need_type": "code_generation",
                "question": "generate app",
                "attributes": {"task_description": "make app", "language": "python"},
            },
            {
                "need_type": "file_write",
                "question": "write app",
                "target_path": str(tmp_path / "app.py"),
            },
        ]
    }
    runtime = FakeRuntime(tmp_path, decision)
    runtime.tool_executor = TimeoutUntilLocalFallbackExecutor()
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    assert [selection.tool_name for selection in runtime.tool_executor.selections] == [
        "code_generator",
        "code_generator",
        "code_generator",
        "file_writer",
    ]
    fallback_selection = runtime.tool_executor.selections[2]
    assert fallback_selection.input_metadata.prompt_context["local_fallback_after_provider_failure"] is True
    writer_selection = runtime.tool_executor.selections[3]
    assert writer_selection.input_metadata.content == "print('local fallback')"
    assert len(runtime.llm_client.requests) == 1
    entries = [
        json.loads(line)
        for line in (tmp_path / "tool_planning.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(entry["event_type"] == "tool_loop_local_fallback_scheduled" for entry in entries)


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


def test_tool_planning_executor_normalizes_top_level_code_need_fields(tmp_path) -> None:
    task = Task(id="task", description="Validate generated assistant")
    runtime = FakeRuntime(
        tmp_path,
        {
            "decision_needs": [
                {
                    "need_type": "code_execution",
                    "question": "run generated smoke test",
                    "code": "print('assistant ok')",
                    "language": "python",
                    "timeout": 5,
                }
            ]
        },
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    assert runtime.tool_executor.selections[0].tool_name == "code_executor"
    assert runtime.tool_executor.selections[0].input_metadata.code == "print('assistant ok')"
    assert runtime.tool_executor.selections[0].timeout_override == 5
    entries = [
        json.loads(line)
        for line in (tmp_path / "tool_planning.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(entry["event_type"] == "decision_need_normalized" and entry["level"] == "DEBUG" for entry in entries)


def test_tool_planning_executor_normalizes_top_level_file_write_content(tmp_path) -> None:
    task = Task(id="task", description="Write generated file")
    runtime = FakeRuntime(
        tmp_path,
        {
            "decision_needs": [
                {
                    "need_type": "file_write",
                    "question": "write generated file",
                    "target_path": "assistant.py",
                    "content": "print('assistant ok')",
                    "overwrite": True,
                }
            ]
        },
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    assert runtime.tool_executor.selections[0].tool_name == "file_writer"
    assert runtime.tool_executor.selections[0].input_metadata.content == "print('assistant ok')"
    assert runtime.tool_executor.selections[0].input_metadata.overwrite is True


def test_tool_planning_executor_normalizes_null_candidate_paths(tmp_path) -> None:
    task = Task(id="task", description="Generate assistant")
    runtime = FakeRuntime(
        tmp_path,
        {
            "decision_needs": [
                {
                    "need_type": "code_generation",
                    "question": "Generate the Python assistant code",
                    "target_path": None,
                    "candidate_paths": None,
                    "query": None,
                    "command": None,
                    "risk_level": "low",
                    "attributes": {"language": "python", "task_description": "print hello"},
                }
            ]
        },
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    assert runtime.tool_executor.selections[0].tool_name == "code_generator"
    entries = [
        json.loads(line)
        for line in (tmp_path / "tool_planning.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        entry["event_type"] == "decision_need_normalized"
        and "candidate_paths:null_to_default" in entry["payload"]["output_summary"]["normalized_fields"]
        for entry in entries
    )


def test_tool_planning_executor_schema_error_is_structured_and_logged(tmp_path) -> None:
    task = Task(id="task", description="Validate generated assistant")
    runtime = FakeRuntime(
        tmp_path,
        {
            "decision_needs": [
                {
                    "need_type": "code_execution",
                    "question": "run generated smoke test",
                    "surprise": "not a tool field",
                }
            ]
        },
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.FAILED
    assert result.result_metadata.failure.error_type == "DecisionNeedValidationError"
    assert result.result_metadata.failure.details["failed_tool"] == "tool_planning_executor"
    assert "surprise" in result.result_metadata.failure.details["invalid_fields"]
    entries = [
        json.loads(line)
        for line in (tmp_path / "tool_planning.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(entry["event_type"] == "decision_need_schema_error" and entry["level"] == "ERROR" for entry in entries)


def test_tool_planning_executor_rejects_old_tool_calls_protocol(tmp_path) -> None:
    task = Task(id="task", description="Use available tools")
    runtime = FakeRuntime(
        tmp_path,
        {"tool_calls": [{"tool_name": "file_writer", "reason": "write output", "input_metadata": {"file_path": "note.md"}}]},
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.FAILED
    assert result.error == "Tool planning requires decomposition after empty decision_needs plan"
    assert result.result_metadata.failure.error_type == "DecisionNeedResolutionError"
    assert result.result_metadata.failure.details["problem_signal"]["category"] == "tool_contract"
    assert result.result_metadata.failure.details["resolution_plan"]["strategy"] == "direct_retry"
    assert len(runtime.llm_client.requests) == 2


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
    assert result.error == "Tool planning requires decomposition after empty decision_needs plan"
    assert result.result_metadata.failure.details["problem_signal"]["category"] == "tool_contract"
    assert "read project files" in state.unknowns


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


def test_directory_discovery_plan_does_not_send_directory_to_file_reader(tmp_path) -> None:
    task = Task(id="task", description="Document and test project")
    (tmp_path / "main.py").write_text("print('ok')", encoding="utf-8")
    runtime = FakeRuntime(
        tmp_path,
        {
            "decision_needs": [
                {
                    "need_type": "command_check",
                    "question": "What files and directories exist in the project folder?",
                    "command": f"ls -la {tmp_path}",
                    "attributes": {"mode": "automatic"},
                },
                {
                    "need_type": "file_read",
                    "question": "If there are existing Python files, read them to understand the current assistant code.",
                    "target_path": str(tmp_path),
                },
            ]
        },
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    assert [selection.tool_name for selection in runtime.tool_executor.selections] == [
        "command_executor",
        "multi_file_reader",
    ]
    assert runtime.tool_executor.selections[1].input_metadata.directory_path == str(tmp_path)
    assert runtime.tool_executor.selections[1].input_metadata.pattern == "*"


def test_tool_event_loop_reports_file_reader_directory_contract_error(tmp_path) -> None:
    task = Task(id="task", description="Read a project directory incorrectly")
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    executor = ToolPlanningTaskExecutor(runtime)
    executor._parse_decision_needs = lambda _response: [  # type: ignore[method-assign]
        {
            "tool_name": "file_reader",
            "reason": "read directory",
            "input_metadata": {"file_path": str(tmp_path)},
        }
    ]

    result = ToolEventLoopRunner(executor, max_steps=1).run(task, "prompt")

    assert result.success is False
    assert result.tool_results[0]["tool"] == "file_reader"
    assert result.tool_results[0]["call_id"] == "task:r1:c1"
    assert "expected a file path" in result.tool_results[0]["error"]
    assert "multi_file_reader" in result.tool_results[0]["suggested_recovery"]
    assert result.loop_metadata.final_error is not None
    assert result.loop_metadata.final_error.details["tool_name"] == "file_reader"
    assert result.loop_metadata.final_error.details["call_id"] == "task:r1:c1"


def test_tool_event_loop_reports_invented_intermediate_file_with_recovery(tmp_path) -> None:
    task = Task(id="task", description="Read hallucinated subtask plan")
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    executor = ToolPlanningTaskExecutor(runtime)
    invented_path = tmp_path / "results" / "openpilot" / "subtask_0.md"
    executor._parse_decision_needs = lambda _response: [  # type: ignore[method-assign]
        {
            "tool_name": "file_reader",
            "reason": "read invented plan",
            "input_metadata": {"file_path": str(invented_path)},
        }
    ]

    result = ToolEventLoopRunner(executor, max_steps=1).run(task, "prompt")

    assert result.success is False
    assert result.tool_results[0]["tool"] == "file_reader"
    assert "File not found" in result.tool_results[0]["error"]
    assert "shared execution history" in result.tool_results[0]["suggested_recovery"]
    assert result.loop_metadata.final_error is not None
    assert result.loop_metadata.final_error.details["error_type"] == "InventedIntermediateFile"


def test_tool_event_loop_rejects_generated_placeholder_file_content(tmp_path) -> None:
    task = Task(id="task", description="Write placeholder")
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    executor = ToolPlanningTaskExecutor(runtime)
    executor._parse_decision_needs = lambda _response: [  # type: ignore[method-assign]
        {
            "tool_name": "file_writer",
            "reason": "write placeholder",
            "input_metadata": {
                "file_path": str(tmp_path / "assistant.py"),
                "content": "PLACEHOLDER - will be replaced with actual generated code",
            },
        }
    ]

    result = ToolEventLoopRunner(executor, max_steps=1).run(task, "prompt")

    assert result.success is False
    assert result.tool_results[0]["tool"] == "file_writer"
    assert "generated placeholder" in result.tool_results[0]["error"]
    assert "Regenerate real content" in result.tool_results[0]["suggested_recovery"]
    assert result.loop_metadata.recoverable_errors[0].error_type == "GeneratedPlaceholderContent"


def test_tool_event_loop_rejects_chinese_placeholder_file_content(tmp_path) -> None:
    task = Task(id="task", description="Write placeholder")
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    executor = ToolPlanningTaskExecutor(runtime)
    executor._parse_decision_needs = lambda _response: [  # type: ignore[method-assign]
        {
            "tool_name": "file_writer",
            "reason": "write placeholder",
            "input_metadata": {
                "file_path": str(tmp_path / "assistant.py"),
                "content": "# 代码将由code_generation生成后填充，此处占位",
            },
        }
    ]

    result = ToolEventLoopRunner(executor, max_steps=1).run(task, "prompt")

    assert result.success is False
    assert result.tool_results[0]["tool"] == "file_writer"
    assert "generated placeholder" in result.tool_results[0]["error"]


def test_tool_event_loop_allows_config_placeholder_inside_substantive_code(tmp_path) -> None:
    task = Task(id="task", description="Write generated app")
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    executor = ToolPlanningTaskExecutor(runtime)
    content = "API_KEY = 'YOUR_API_KEY_PLACEHOLDER'\n\ndef main():\n    print('ok')\n"
    executor._parse_decision_needs = lambda _response: [  # type: ignore[method-assign]
        {
            "tool_name": "file_writer",
            "reason": "write implementation",
            "input_metadata": {
                "file_path": str(tmp_path / "assistant.py"),
                "content": content,
            },
        }
    ]

    result = ToolEventLoopRunner(executor, max_steps=1).run(task, "prompt")

    assert result.success is True
    assert result.tool_results[0]["success"] is True


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
    assert "app.py --help" in runtime.tool_executor.selections[1].input_metadata.command
    assert runtime.tool_executor.selections[1].input_metadata.timeout == 5
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
    assert result.error == "Tool planning requires decomposition after empty decision_needs plan"
    assert result.result_metadata.failure.error_type == "DecisionNeedResolutionError"
    assert result.result_metadata.failure.details["problem_signal"]["category"] == "planning_gap"
    assert result.result_metadata.failure.details["difficulty_assessment"]["level"] in {"simple", "moderate"}


def test_tool_planning_executor_read_only_empty_plan_with_evidence_summarizes(tmp_path) -> None:
    task = Task(
        id="task",
        description="请梳理 CLI 入口到主执行运行时的核心链路",
        kind="codebase_understanding",
        tags=["analysis"],
    )
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    state = RuntimeStateMetadata(goal=task.description, phase=AgentPhase.UNDERSTAND_PROJECT)
    state.add_fact("Observed CLI entrypoint in Code/src/ui/enhanced_cli.py")
    state.add_candidate_file("Code/src/ui/enhanced_cli.py", "file_read evidence")
    runtime.runtime_controller = SimpleNamespace(
        state=state,
        router=ToolRouter(runtime.tool_registry),
        edit_guard=EditGuard(),
        file_selector=FileSelector(),
        state_updater=StateUpdater(),
        verifier=RuntimeVerifier(),
    )
    context = TaskExecutionContext(
        task=task,
        parent_context={"goal": task.description, "project_path": str(tmp_path)},
        shared_state={},
        execution_history=[],
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, context)

    assert result.status == TaskStatus.COMPLETED
    assert runtime.tool_executor.selections == []
    assert state.phase == AgentPhase.SUMMARIZE
    assert state.completion_reason == "read-only analysis has enough evidence to synthesize"


def test_tool_planning_executor_read_only_empty_plan_without_evidence_still_fails(tmp_path) -> None:
    task = Task(
        id="task",
        description="请梳理 CLI 入口到主执行运行时的核心链路",
        kind="codebase_understanding",
        tags=["analysis"],
    )
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    runtime.runtime_controller = SimpleNamespace(
        state=RuntimeStateMetadata(goal=task.description, phase=AgentPhase.UNDERSTAND_PROJECT),
        router=ToolRouter(runtime.tool_registry),
        edit_guard=EditGuard(),
        file_selector=FileSelector(),
        state_updater=StateUpdater(),
        verifier=RuntimeVerifier(),
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.FAILED
    assert result.error == "Tool planning requires decomposition after empty decision_needs plan"


def test_tool_planning_fallback_state_inherits_context_project_path(tmp_path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    task = Task(id="task", description="Inspect project structure", kind="codebase_understanding", tags=["analysis"])
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    controller = SimpleNamespace(
        state=None,
        router=ToolRouter(runtime.tool_registry),
        edit_guard=EditGuard(),
        file_selector=FileSelector(),
        state_updater=StateUpdater(),
        verifier=RuntimeVerifier(),
    )
    runtime.runtime_controller = controller
    executor = ToolPlanningTaskExecutor(runtime)
    executor._active_task = task
    executor._active_task_id = task.id
    executor._active_task_description = task.description
    executor._active_goal = task.description
    executor._active_context = TaskExecutionContext(
        task=task,
        parent_context={"goal": task.description, "project_path": str(project_dir)},
        shared_state={},
        execution_history=[],
    )

    requests = executor._route_decision_needs(
        {
            "decision_needs": [
                {
                    "need_type": "project_structure",
                    "question": "Inspect the repository root",
                }
            ]
        }
    )

    assert requests
    assert controller.state is not None
    assert f"Project path: {project_dir.resolve(strict=False)}" in controller.state.known_facts
    assert str(project_dir.resolve(strict=False)) in controller.state.candidate_files
    assert requests[0]["input_metadata"]["project_path"] == str(project_dir.resolve(strict=False))


def test_tool_planning_executor_empty_plan_retry_can_recover(tmp_path) -> None:
    task = Task(id="task", description="Do impossible thing")
    runtime = FakeRuntime(
        tmp_path,
        [
            {"decision_needs": []},
            {
                "decision_needs": [
                    {
                        "need_type": "command_check",
                        "question": "run smoke validation",
                        "command": "python -m compileall .",
                    }
                ]
            },
        ],
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    assert len(runtime.llm_client.requests) == 2
    assert [selection.tool_name for selection in runtime.tool_executor.selections] == ["command_executor"]
    entries = [
        json.loads(line)
        for line in (tmp_path / "tool_planning.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(entry["event_type"] == "problem_resolution_planned" for entry in entries)
    assert any(entry["event_type"] == "decision_need_empty_plan_retry_recovered" for entry in entries)


def test_tool_planning_executor_falls_back_for_unroutable_actionable_plan(tmp_path) -> None:
    package = tmp_path / "assistant"
    package.mkdir()
    target_file = package / "core.py"
    target_file.write_text(
        "class Assistant:\n"
        "    def respond(self, text):\n"
        "        return text\n",
        encoding="utf-8",
    )
    task = Task(id="task", description="Implement core assistant logic and command parsing loop")
    runtime = FakeRuntime(
        tmp_path,
        {
            "decision_needs": [
                {
                    "need_type": "assistant_logic",
                    "question": "decide how to implement the assistant core",
                }
            ]
        },
    )
    executor = ToolPlanningTaskExecutor(runtime)
    context = TaskExecutionContext(
        task=task,
        parent_context={"goal": f"build app in '{tmp_path}'"},
        shared_state={},
        execution_history=[],
    )

    result = executor.execute_task(task, context)

    assert result.status == TaskStatus.COMPLETED
    selections = runtime.tool_executor.selections
    assert [selection.tool_name for selection in selections] == [
        "code_generator",
        "file_writer",
        "command_executor",
    ]
    writer_input = selections[1].input_metadata.to_params()
    assert writer_input["file_path"] == str(target_file)
    assert writer_input["operation_kind"] == "file_replace"
    assert writer_input["content"] == "print('ok')"
    entries = [
        json.loads(line)
        for line in (tmp_path / "tool_planning.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(entry["event_type"] == "decision_need_fallback_plan" for entry in entries)


def test_tool_planning_executor_falls_back_after_invalid_json_repair_exhaustion(tmp_path) -> None:
    task = Task(id="task", description="Implement app.py and validate it")
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    runtime.llm_client = InvalidJSONLLM()
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    assert [selection.tool_name for selection in runtime.tool_executor.selections] == [
        "code_generator",
        "file_writer",
        "command_executor",
    ]
    entries = [
        json.loads(line)
        for line in (tmp_path / "tool_planning.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    fallback_entries = [entry for entry in entries if entry["event_type"] == "decision_need_fallback_plan"]
    assert fallback_entries
    assert "invalid JSON" in fallback_entries[0]["payload"]["input_summary"]["reason"]


def test_tool_planning_executor_falls_back_after_transport_failure(tmp_path) -> None:
    task = Task(id="task", description="Implement app.py with README documentation")
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    runtime.llm_client = TransportFailureLLM()
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    assert [selection.tool_name for selection in runtime.tool_executor.selections] == [
        "code_generator",
        "file_writer",
        "command_executor",
    ]


def test_tool_planning_executor_validation_fallback_does_not_regenerate_code(tmp_path) -> None:
    task = Task(id="task", description="Test: validate the generated app")
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    runtime.llm_client = TransportFailureLLM()
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    assert [selection.tool_name for selection in runtime.tool_executor.selections] == ["command_executor"]
    command = runtime.tool_executor.selections[0].input_metadata.command
    assert command == f"python -m compileall {tmp_path}"


def test_tool_planning_executor_validation_fallback_prefers_runtime_command(tmp_path) -> None:
    task = Task(id="task", description="Validate generated assistant")
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    runtime._project_environments[str(tmp_path)]["run_command"] = "python app.py --smoke"
    executor = ToolPlanningTaskExecutor(runtime)
    context = TaskExecutionContext(
        task=task,
        parent_context={"goal": "build app", "project_path": str(tmp_path), "run_command": "python app.py --smoke"},
        shared_state={},
        execution_history=[],
    )

    result = executor.execute_task(task, context)

    assert result.status == TaskStatus.COMPLETED
    assert [selection.tool_name for selection in runtime.tool_executor.selections] == [
        "command_executor",
        "command_executor",
    ]
    assert runtime.tool_executor.selections[0].input_metadata.command == "python app.py --smoke"
    assert runtime.tool_executor.selections[1].input_metadata.command == f"python -m compileall {tmp_path}"


def test_tool_planning_executor_inherits_project_root_for_hallucinated_workspace_need(tmp_path) -> None:
    task = Task(id="task", description="Inspect the current project root")
    runtime = FakeRuntime(tmp_path, {})
    executor = ToolPlanningTaskExecutor(runtime)
    executor._active_context = TaskExecutionContext(
        task=task,
        parent_context={"goal": "analyze runtime", "cwd": str(tmp_path)},
        shared_state={},
        execution_history=[],
    )

    tool_requests = executor._parse_decision_needs(
        SimpleNamespace(
            parsed_json={
                "decision_needs": [
                    {
                        "need_type": "project_structure",
                        "question": "inspect current project structure",
                        "target_path": "/workspace/openpilot",
                    }
                ]
            },
            content="",
        )
    )

    assert tool_requests[0]["tool_name"] == "multi_file_reader"
    assert tool_requests[0]["input_metadata"]["directory_path"] == str(tmp_path)
    assert tool_requests[0]["input_metadata"]["project_path"] == str(tmp_path)
    assert tool_requests[0]["input_metadata"]["pattern"] == "sketch.json"


def test_tool_planning_executor_bad_json_returns_failed_result(tmp_path) -> None:
    task = Task(id="task", description="Do impossible thing")
    executor = ToolPlanningTaskExecutor(FakeRuntime(tmp_path, "{bad-json"))

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.FAILED
    assert "Failed to parse LLM response as JSON" in result.error


def test_tool_planning_prompt_uses_history_and_forbids_invented_subtask_files(tmp_path) -> None:
    task = Task(id="task", description="Create project based on subtask 0 requirements")
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    executor = ToolPlanningTaskExecutor(runtime)
    context = TaskExecutionContext(
        task=task,
        parent_context={"goal": "build app"},
        shared_state={},
        execution_history=[
            {
                "task_id": "previous",
                "description": "Clarify requirements",
                "status": "completed",
                "result_summary": "Use a small Python CLI app.",
            }
        ],
    )

    planning_surface = executor._planning_surface_for_prompt(task.description, "build app", context=context)
    prompt = executor._build_tool_plan_prompt(task.description, "build app", planning_surface, context)

    assert "Previous Task Results" in prompt
    assert "Use a small Python CLI app" in prompt
    assert "Need Catalog" in prompt
    assert "Core Capability Cards" in prompt
    assert "Deferred Capability Cards" in prompt
    assert "Never invent or read intermediate files such as subtask_0.md" in prompt
    assert "Do not emit null" in prompt
    assert "Available Tools" not in prompt
    assert "Input metadata:" not in prompt
    assert '"symbol_name": "optional' not in prompt


def test_tool_planning_surface_for_read_only_task_uses_only_core_cards(tmp_path) -> None:
    task = Task(id="task", description="梳理 CLI 入口到主执行运行时的核心链路")
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    executor = ToolPlanningTaskExecutor(runtime)

    planning_surface = executor._planning_surface_for_prompt(task.description, "analyze runtime flow", context=_context(task))

    assert "File evidence" in planning_surface
    assert "Project structure evidence" in planning_surface
    assert "Command validation" in planning_surface
    assert "External research" in planning_surface
    assert "New file generation" not in planning_surface
    assert "Existing code modification" not in planning_surface
    assert "Documentation delivery" not in planning_surface
    assert "Guarded deletion" not in planning_surface
    assert "Runtime or environment repair" not in planning_surface
    assert "llm_summarizer" not in planning_surface
    assert "task_classifier" not in planning_surface


def test_tool_plan_prompt_includes_read_only_notice_for_analysis_task(tmp_path) -> None:
    task = Task(id="task", description="梳理 CLI 入口到主执行运行时的核心链路", tags=["readonly", "understanding"])
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    executor = ToolPlanningTaskExecutor(runtime)
    context = _context(task)

    planning_surface = executor._planning_surface_for_prompt(task.description, "analyze runtime flow", context=context)
    prompt = executor._build_tool_plan_prompt(task.description, "analyze runtime flow", planning_surface, context)

    assert "Read-only task mode" in prompt
    assert "Do not emit file_write, file_delete, code generation, bug_fix, repair, or mutating command needs." in prompt
    assert "Prefer file_read, project_structure, and safe validation evidence." in prompt


def test_tool_planning_surface_adds_deferred_cards_for_create_and_docs_tasks(tmp_path) -> None:
    task = Task(id="task", description="Implement app.py with README documentation")
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    executor = ToolPlanningTaskExecutor(runtime)

    planning_surface = executor._planning_surface_for_prompt(task.description, "build app", context=_context(task))

    assert "New file generation" in planning_surface
    assert "Documentation delivery" in planning_surface
    assert "Existing code modification" not in planning_surface


def test_tool_planning_surface_adds_repair_card_for_runtime_failure_tasks(tmp_path) -> None:
    task = Task(id="task", description="Repair runtime import failure and broken venv startup")
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    executor = ToolPlanningTaskExecutor(runtime)

    planning_surface = executor._planning_surface_for_prompt(task.description, "restore startup", context=_context(task))

    assert "Runtime or environment repair" in planning_surface
    assert '"need_type":"bug_fix"' in planning_surface


def test_planning_surface_catalog_merges_tool_and_future_skill_providers() -> None:
    skill_card = PlanningSurfaceCard(
        card_id="skill_test_development",
        title="Test-development skill",
        source_kind=CapabilitySourceKind.SKILL_FUTURE,
        exposure=CapabilityExposure.DEFERRED,
        need_types=("project_structure", "command_check"),
        summary="Use a future skill procedure for test-development investigation.",
        required_fields_hint="task goal and project path",
        example_need={"need_type": "project_structure", "target_path": "/abs/path/project"},
        trigger_terms=("test development", "测试开发"),
        backing_refs=("skill:test_development",),
    )

    catalog = PlanningSurfaceCatalog.from_providers(
        [
            ToolCapabilityCardProvider([FILE_READER_DEFINITION, MULTI_FILE_READER_DEFINITION]),
            StaticCapabilityCardProvider([skill_card]),
        ]
    )
    selection = PlanningSurfaceSelector().select(
        catalog,
        task_description="改进测试开发流程，先做 test development investigation",
        goal="improve agent testing",
    )

    assert catalog.get("file_evidence") is not None
    assert catalog.get("skill_test_development") is skill_card
    assert selection.deferred_cards == (skill_card,)
    assert "Test-development skill" in selection.render()


def test_tool_planning_surface_accepts_runtime_future_skill_provider(tmp_path) -> None:
    skill_card = PlanningSurfaceCard(
        card_id="skill_bug_investigation",
        title="Bug investigation skill",
        source_kind="skill_future",
        exposure="deferred",
        need_types=("file_read", "project_structure", "command_check"),
        summary="Use a future skill procedure to find root causes before fixes.",
        required_fields_hint="problem statement and evidence scope",
        example_need={"need_type": "project_structure", "target_path": "/abs/path/project"},
        trigger_terms=("root cause", "本质问题"),
        backing_refs=("skill:bug_investigation",),
    )
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    runtime.planning_surface_providers = [StaticCapabilityCardProvider([skill_card])]
    task = Task(id="task", description="分析 bug 的 root cause，不要只修表象")
    executor = ToolPlanningTaskExecutor(runtime)

    planning_surface = executor._planning_surface_for_prompt(task.description, "find 本质问题", context=_context(task))

    assert "Bug investigation skill" in planning_surface
    assert "skill:bug_investigation" not in planning_surface
    assert "Input metadata:" not in planning_surface


def test_tool_planning_retry_prompt_uses_incremental_capability_surface(tmp_path) -> None:
    task = Task(id="task", description="Modify the existing CLI entrypoint to fix command parsing")
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    executor = ToolPlanningTaskExecutor(runtime)
    executor._active_task_description = task.description
    executor._active_goal = "fix CLI"
    executor._active_context = _context(task)
    signal = executor._problem_signal_for_empty_plan({"decision_needs": []})

    prompt = executor._empty_plan_retry_prompt(
        {"decision_needs": []},
        signal,
        executor._assess_problem_difficulty(signal, executor._judge_problem(signal)),
        ResolutionPlanMetadata(strategy="direct_retry", max_attempts=2, acceptance_check="recover"),
    )

    assert "Planning Surface" in prompt
    assert "Existing code modification" in prompt
    assert "Available Tools" not in prompt
    assert "Input metadata:" not in prompt


def test_tool_planning_prompt_budget_is_significantly_smaller_than_legacy_full_tool_prompt(tmp_path) -> None:
    runtime = IntelligentAutopilot(FakeLLM({"decision_needs": []}), log_file=tmp_path / "autopilot.jsonl")
    executor = runtime.tool_planning_task_executor
    task = Task(id="task", description="请梳理从 CLI 入口到主执行运行时的核心链路，并指出关键模块之间的关系。")
    context = TaskExecutionContext(task=task, parent_context={"goal": "analyze runtime"}, shared_state={}, execution_history=[])
    tools = runtime.tool_registry.list_all()
    tools_description = runtime.tool_io.format_tools_for_llm(tools)
    planning_surface = executor._planning_surface_for_prompt(task.description, "analyze runtime", context=context)

    legacy_prompt = f"""You are an AI assistant that selects and sequences tools to accomplish tasks.

Task: {task.description}
Overall Goal: analyze runtime
Previous Task Results:
No previous task results.

Available Tools:
{tools_description}

Generate a JSON plan with decision_needs. The runtime ToolRouter is the only component
allowed to map needs to concrete tools using budget, risk, and permission checks.

Output ONLY valid JSON in this format:
{{
  "decision_needs": [
    {{
      "need_type": "code_file_create",
      "question": "create the main project file",
      "target_path": "/absolute/path/to/file.py",
      "operation_kind": "create_file",
      "attributes": {{"language": "python"}}
    }}
  ]
}}

Allowed need_type values:
file_read, project_structure, web_search, command_check, file_write, file_delete, code_file_create,
directory_generate, code_unit_generate, code_symbol_modify, code_patch, code_generation,
code_execution, readme_generation.

Optional fields may include: target_path, operation_kind, target_scope, symbol_name,
symbol_type, insertion_hint, patch_mode, candidate_paths, query, command, risk_level,
attributes. Omit unknown or unavailable optional fields. Do not emit null.

Important:
- Previous task outputs are provided above in Previous Task Results. Use that shared history directly.
- Never invent or read intermediate files such as subtask_0.md, subtask_1.md, requirements.md, or plan.md unless they appear in previous tool outputs or the user explicitly requested them.
- If previous task results are absent or failed, infer sensible defaults from the original goal instead of reading a made-up plan file.
- For project creation, use directory_generate/code_file_create/file_write directly and create the needed files in the target directory.
- Always distinguish create_file, add_symbol, modify_symbol, and code_patch before selecting needs.
- For new code files or generated project files, emit code_file_create or directory_generate, then file_write with operation_kind create_file.
- For adding a function/class to an existing file, emit file_read, then code_unit_generate with operation_kind add_symbol, then file_write with operation_kind add_symbol so ToolRouter uses file_patch_writer.
- For modifying an existing function/class, emit file_read, then code_symbol_modify or code_patch with operation_kind modify_symbol, then file_write with operation_kind modify_symbol so ToolRouter uses file_patch_writer.
- For deleting an existing file, emit file_read or project_structure first for evidence, then file_delete with operation_kind delete_file so ToolRouter uses file_delete_tool.
- Do not plan code_generator + file_writer for edits to existing functions/classes.
- code_generator only supports executable code languages: python, shell, bash. Never use language "text"
- For design, outline, planning, or prose-only tasks, either return planning metadata through an appropriate text/documentation tool or write Markdown/text with file_writer/readme_tool
- For completed project/code deliveries, emit a readme_generation need after file_write to create README.md with run instructions
- Autopilot will run hard validation and autonomous-iteration improvement analysis after project delivery
- Provide actual values for all parameters, do not use null or placeholders
- If you need to pass output from one tool to another, generate the content directly in the first tool
- For command_executor, input_metadata.mode must be one of: dry_run, interactive, automatic
- For project commands, use mode "automatic" and do not use source/activate/cd/export; OpenPilot injects the target cwd and virtual environment from metadata
"""
    new_prompt = executor._build_tool_plan_prompt(task.description, "analyze runtime", planning_surface, context)

    assert len(new_prompt) <= len(legacy_prompt) * 0.55
    assert "Input metadata:" not in new_prompt
    assert "Available Tools" not in new_prompt
    assert "Need Catalog" in new_prompt
    assert "Do not invent nested directories or filenames under that root without evidence." in new_prompt


def test_tool_planning_prompt_includes_current_project_context(tmp_path) -> None:
    runtime = FakeRuntime(tmp_path, {"decision_needs": []})
    executor = ToolPlanningTaskExecutor(runtime)
    task = Task(id="task", description="Analyze the CLI runtime flow")
    context = TaskExecutionContext(
        task=task,
        parent_context={"goal": "analyze runtime", "cwd": str(tmp_path)},
        shared_state={},
        execution_history=[],
    )

    prompt = executor._build_tool_plan_prompt(
        task.description,
        "analyze runtime",
        executor._planning_surface_for_prompt(task.description, "analyze runtime", context=context),
        context,
    )

    assert f"Project root: {tmp_path}" in prompt


def test_intelligent_autopilot_normalizes_execution_context_and_propagates_parent_context(tmp_path, monkeypatch) -> None:
    autopilot = IntelligentAutopilot(FakeLLM({"decision_needs": []}), log_file=tmp_path / "autopilot.jsonl")
    monkeypatch.chdir(tmp_path)

    normalized = autopilot._normalize_execution_context({})

    assert normalized["cwd"] == str(tmp_path.resolve())
    autopilot.session_id = "session"
    autopilot._current_execution_context = {**normalized, "run_command": "pytest"}

    parent_context = autopilot._task_parent_context("analyze runtime")

    assert parent_context["goal"] == "analyze runtime"
    assert parent_context["cwd"] == str(tmp_path.resolve())
    assert parent_context["run_command"] == "pytest"


def test_intelligent_autopilot_execution_history_payload_carries_observed_paths(tmp_path) -> None:
    autopilot = IntelligentAutopilot(FakeLLM({"decision_needs": []}), log_file=tmp_path / "autopilot.jsonl")
    task = Task(id="task", description="Inspect CLI files")
    result = TaskExecutionResult(
        task_id=task.id,
        status=TaskStatus.COMPLETED,
        result_metadata=TaskResultMetadata(
            task_id=task.id,
            status=ResultStatus.SUCCESS,
            result=TextArtifactMetadata(
                content="completed",
                attributes={
                    "final_output": {
                        "files": [str(tmp_path / "src" / "ui" / "cli.py")],
                        "content": f"# Source: {tmp_path / 'src' / 'ui' / 'cli.py'}",
                    },
                    "tool_results": [
                        {
                            "tool_name": "multi_file_reader",
                            "input_metadata": {"directory_path": str(tmp_path), "project_path": str(tmp_path)},
                            "output": {
                                "files": [str(tmp_path / "pyproject.toml")],
                                "sketch_files": [str(tmp_path / "sketch.json")],
                            },
                        }
                    ],
                    "all_tools_succeeded": True,
                },
            ),
        ),
    )

    history = autopilot._execution_history_payload([task], [result])

    assert history[0]["observed_paths"]
    assert str(tmp_path / "src" / "ui" / "cli.py") in history[0]["observed_paths"]
    assert str(tmp_path / "pyproject.toml") in history[0]["observed_paths"]
    assert history[0]["result_summary"]["all_tools_succeeded"] is True


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
