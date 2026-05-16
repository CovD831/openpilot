from __future__ import annotations

from execution.intelligent_autopilot import IntelligentAutopilot
from execution.tool_io import ExecutionToolIO
from tools.tool_models import ToolDefinition, ToolInputSchema, ToolOutputSchema
from tools.tool_orchestration_models import ToolSelection


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

    sanitized = helper.sanitize_tool_params(params)

    assert sanitized["content"] == "<300 chars>"
    assert sanitized["content_length"] == 300
    assert sanitized["content_preview"] == "x" * 200
    assert sanitized["code"] == "<11 chars>"
    assert "_llm_client" not in sanitized
    assert sanitized["file_path"] == "app.py"


def test_tool_io_resolves_chained_inputs_for_writer_and_executor() -> None:
    helper = ExecutionToolIO()
    generated = {"code": "print('ok')", "language": "python"}

    writer_params = helper.resolve_chained_inputs(
        "file_writer",
        {"file_path": "app.py"},
        last_output=None,
        last_code_output=generated,
    )
    executor_params = helper.resolve_chained_inputs(
        "code_executor",
        {},
        last_output=None,
        last_code_output=generated,
    )
    placeholder_params = helper.resolve_chained_inputs(
        "file_writer",
        {"content": "before {{code}} after"},
        last_output=None,
        last_code_output=generated,
    )

    assert writer_params["content"] == "print('ok')"
    assert executor_params == {"code": "print('ok')", "language": "python"}
    assert placeholder_params["content"] == "before print('ok') after"


def test_tool_io_resolves_tool_selection_source_step_outputs() -> None:
    helper = ExecutionToolIO()
    selection = ToolSelection(
        step_id="write",
        tool_name="file_writer",
        reason="capability_match",
        input_params={"source_step_id": "generate", "file_path": "app.py"},
    )

    resolved = helper.resolve_selection_inputs(
        selection,
        {"generate": {"code": "print('from step')"}},
    )

    assert resolved.input_params == {
        "file_path": "app.py",
        "content": "print('from step')",
    }
    assert "source_step_id" not in resolved.input_params


def test_intelligent_autopilot_tool_io_proxy_matches_helper(tmp_path) -> None:
    autopilot = IntelligentAutopilot(FakeLLM(), log_file=tmp_path / "autopilot.jsonl")
    helper = ExecutionToolIO()
    tool = ToolDefinition(
        name="demo",
        display_name="Demo",
        description="Demo tool",
        input_schema=[
            ToolInputSchema(name="query", type="string", description="Query", required=True),
        ],
        output_schema=ToolOutputSchema(type="object", description="Demo output"),
    )

    assert autopilot._sanitize_tool_params({"content": "abc"}) == helper.sanitize_tool_params({"content": "abc"})
    assert autopilot._format_tools_for_llm([tool]) == helper.format_tools_for_llm([tool])
    assert autopilot._map_reason_to_enum("best performance") == "best_performance"
    assert autopilot.memory_context_builder is not None
    assert autopilot.iterative_improvement.memory_context_builder is autopilot.memory_context_builder
