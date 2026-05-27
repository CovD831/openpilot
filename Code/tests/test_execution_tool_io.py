from __future__ import annotations

from types import SimpleNamespace

from autonomous_iteration.intelligent_autopilot import IntelligentAutopilot
from autonomous_iteration.task_models import Task, TaskPriority
from autonomous_iteration.tool_io import ExecutionToolIO
from core.tool_contracts import ToolDefinition
from metadata import CodeArtifactMetadata, ResultStatus, ToolContractMetadata, ToolInputMetadata, ToolResultMetadata
from tools.tool_selection import ToolSelection


class FakeLLM:
    def __init__(self, content: str = "```python\nprint('ok')\n```") -> None:
        self.content = content
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return SimpleNamespace(content=self.content)


class FakeUI:
    def __init__(self) -> None:
        self.events = []

    def append_tool_event(self, event) -> None:
        self.events.append(event.to_json_dict() if hasattr(event, "to_json_dict") else event)

    def set_current_task_state(self, **_kwargs) -> None:
        return None


def test_tool_io_sanitizes_large_payloads_without_private_params() -> None:
    helper = ExecutionToolIO()
    params = {
        "content": "x" * 300,
        "code": "print('ok')",
        "task_description": "build app",
        "_llm_client": object(),
        "file_path": "app.py",
    }

    sanitized = helper.sanitize_tool_metadata(ToolInputMetadata.from_mapping("demo", params))

    assert sanitized["content"] == "<300 chars>"
    assert sanitized["content_length"] == 300
    assert sanitized["content_preview"] == "x" * 200
    assert sanitized["code"] == "<11 chars>"
    assert "_llm_client" not in sanitized
    assert sanitized["file_path"] == "app.py"


def test_tool_io_resolves_chained_metadata_for_writer_and_executor() -> None:
    helper = ExecutionToolIO()
    generated = ToolResultMetadata(
        tool_name="code_generator",
        status=ResultStatus.SUCCESS,
        result=CodeArtifactMetadata(code="print('ok')", language="python"),
    )

    writer_metadata = helper.resolve_chained_metadata(
        "file_writer",
        ToolInputMetadata.from_mapping("file_writer", {"file_path": "app.py"}),
        last_output=None,
        last_code_output=generated,
    )
    executor_metadata = helper.resolve_chained_metadata(
        "code_executor",
        ToolInputMetadata.from_mapping("code_executor", {}),
        last_output=None,
        last_code_output=generated,
    )

    assert writer_metadata.content == "print('ok')"
    assert executor_metadata.code == "print('ok')"
    assert executor_metadata.language == "python"


def test_tool_io_resolves_tool_selection_dependency_outputs() -> None:
    helper = ExecutionToolIO()
    selection = ToolSelection(
        step_id="write",
        tool_name="file_writer",
        reason="capability_match",
        input_metadata=ToolInputMetadata.from_mapping("file_writer", {"file_path": "app.py"}),
        depends_on=["generate"],
    )

    resolved = helper.resolve_selection_metadata(
        selection,
        {
            "generate": ToolResultMetadata(
                tool_name="code_generator",
                status=ResultStatus.SUCCESS,
                result=CodeArtifactMetadata(code="print('from step')", language="python"),
            )
        },
    )

    assert resolved.input_metadata.file_path == "app.py"
    assert resolved.input_metadata.content == "print('from step')"


def test_intelligent_autopilot_tool_io_proxy_matches_helper(tmp_path) -> None:
    autopilot = IntelligentAutopilot(FakeLLM(), log_file=tmp_path / "autopilot.jsonl")
    helper = ExecutionToolIO()
    tool = ToolDefinition(
        name="demo",
        display_name="Demo",
        description="Demo tool",
        contract_metadata=ToolContractMetadata(
            tool_name="demo",
            input_metadata_type="ToolInputMetadata",
            output_metadata_type="ToolResultMetadata",
            required_input_fields=["query"],
        ),
    )

    assert autopilot._sanitize_tool_metadata({"content": "abc"}) == helper.sanitize_tool_metadata({"content": "abc"})
    assert autopilot._format_tools_for_llm([tool]) == helper.format_tools_for_llm([tool])
    assert autopilot._map_reason_to_enum("best performance") == "best_performance"
    assert autopilot.memory_context_builder is not None
    assert autopilot.iterative_improvement.memory_context_builder is autopilot.memory_context_builder


def test_contextual_code_generator_executor_accepts_tool_input_metadata(tmp_path) -> None:
    llm = FakeLLM()
    autopilot = IntelligentAutopilot(llm, log_file=tmp_path / "autopilot.jsonl")
    executor = autopilot.tool_registry.get_executor("code_generator")

    result = executor(
        ToolInputMetadata.from_mapping(
            "code_generator",
            {"task_description": "write hello world", "language": "python"},
        )
    )

    assert isinstance(result, ToolResultMetadata)
    assert isinstance(result.result, CodeArtifactMetadata)
    assert "print('ok')" in result.result.code
    assert llm.requests


def test_fast_tool_code_generator_uses_metadata_without_mapping_error(tmp_path) -> None:
    autopilot = IntelligentAutopilot(FakeLLM(), log_file=tmp_path / "autopilot.jsonl")
    autopilot.enhanced_ui = FakeUI()
    task = Task(id="task", description="Generate hello world", priority=TaskPriority.HIGH)

    result = autopilot._execute_fast_tool(
        task=task,
        step_id="test_code_generator",
        tool_name="code_generator",
        input_metadata=ToolInputMetadata.from_mapping(
            "code_generator",
            {"task_description": "write hello world", "language": "python"},
        ),
    )

    assert result.success is True
    assert isinstance(result.output, CodeArtifactMetadata)
    assert "print('ok')" in result.output.code
    assert result.call_id == "task:test_code_generator"
    assert result.tool_context.call_id == "task:test_code_generator"
    assert [event.event_type for event in result.tool_events] == ["pending", "running", "completed"]
    assert [event["event_type"] for event in autopilot.enhanced_ui.events] == ["pending", "running", "completed"]


def test_fast_tool_failure_emits_error_event_with_recoverable_flag(tmp_path) -> None:
    autopilot = IntelligentAutopilot(FakeLLM(), log_file=tmp_path / "autopilot.jsonl")
    autopilot.enhanced_ui = FakeUI()
    task = Task(id="task", description="Run missing tool", priority=TaskPriority.HIGH)

    result = autopilot._execute_fast_tool(
        task=task,
        step_id="missing_step",
        tool_name="missing_tool",
        input_metadata=ToolInputMetadata.from_mapping("missing_tool", {}),
    )

    assert result.success is False
    assert result.call_id == "task:missing_step"
    assert [event.event_type for event in result.tool_events] == ["pending", "running", "error"]
    assert result.tool_events[-1].recoverable == bool(result.failure.recoverable)
    assert autopilot.enhanced_ui.events[-1]["event_type"] == "error"
