from __future__ import annotations

from autonomous_iteration.intelligent_autopilot import IntelligentAutopilot
from autonomous_iteration.tool_io import ExecutionToolIO
from core.tool_contracts import ToolDefinition
from metadata import ResultStatus, ToolContractMetadata, ToolInputMetadata, ToolResultMetadata
from tools.tool_selection import ToolSelection


class FakeLLM:
    pass


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
        result={"kind": "code_artifact", "code": "print('ok')", "language": "python"},
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
                result={"kind": "code_artifact", "code": "print('from step')", "language": "python"},
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
