from __future__ import annotations

import json
import sys

from core.openpilot_log import OpenPilotLogger
from tools.builtin_tools import register_builtin_tools
from tools.tool_executor import ToolExecutor
from tools.tool_models import (
    PermissionLevel,
    ToolDefinition,
    ToolOutputSchema,
)
from tools.tool_orchestration_models import ToolSelection
from tools.tool_registry import ToolRegistry


def _registered_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return registry


def test_builtin_tools_register_expected_contracts() -> None:
    registry = _registered_registry()

    names = {tool.name for tool in registry.list_all()}

    assert len(names) == 16
    assert {
        "command_executor",
        "embedder",
        "memory_context",
        "file_reader",
        "file_writer",
        "directory_lister",
        "multi_file_reader",
        "project_environment_tool",
        "project_state_reader",
        "project_improvement_tool",
        "autonomy_tool",
    }.issubset(names)


def test_core_imports_remain_available() -> None:
    from core.openpilot_log import OpenPilotLogger as ImportedLogger
    from execution.intelligent_autopilot import IntelligentAutopilot
    from memory.memory_store import MemoryStore
    from tools.tool_executor import ToolExecutor as ImportedToolExecutor

    assert IntelligentAutopilot is not None
    assert ImportedToolExecutor is ToolExecutor
    assert MemoryStore is not None
    assert ImportedLogger is OpenPilotLogger


def test_config_check_cli_returns_success() -> None:
    from ui.cli import main

    assert main(["config", "check"]) == 0


def test_tool_executor_rejects_missing_required_input() -> None:
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="read-file",
                tool_name="file_reader",
                reason="capability_match",
                input_params={},
            )
        )
    finally:
        executor.shutdown()

    assert not result.success
    assert result.error is not None
    assert result.error.error_type == "InvalidInput"
    assert "file_path" in result.error.error_message
    assert result.error.recoverable
    assert result.error.retry_recommended
    assert result.metadata["failure_mode"] == "invalid_input"
    assert "required parameters" in result.metadata["recovery_strategy"]


def test_tool_executor_reads_file_and_applies_defaults(tmp_path) -> None:
    target = tmp_path / "hello.txt"
    target.write_text("hello openpilot", encoding="utf-8")
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    selection = ToolSelection(
        step_id="read-file",
        tool_name="file_reader",
        reason="capability_match",
        input_params={"file_path": str(target)},
    )
    try:
        result = executor.execute_single(selection)
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["content"] == "hello openpilot"
    assert result.output["encoding"] == "utf-8"
    assert selection.input_params["encoding"] == "utf-8"
    assert selection.input_params["max_size_mb"] == 10


def test_tool_executor_records_output_schema_warnings() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="partial_output_tool",
            display_name="Partial Output Tool",
            description="Returns an incomplete object to exercise warnings",
            permission_level=PermissionLevel.LOW,
            input_schema=[],
            output_schema=ToolOutputSchema(
                type="object",
                description="Expected output",
                properties={
                    "present": {"type": "string"},
                    "missing": {"type": "integer"},
                },
            ),
            audit_required=False,
        ),
        lambda params: {"present": "yes"},
    )
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="partial-output",
                tool_name="partial_output_tool",
                reason="capability_match",
                input_params={},
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.metadata["validation_warnings"] == [
        "Output for partial_output_tool is missing declared property: missing"
    ]


def test_command_executor_defaults_to_dry_run(tmp_path) -> None:
    target = tmp_path / "should_not_exist.txt"
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="dry-run-command",
                tool_name="command_executor",
                reason="capability_match",
                input_params={"command": f"touch {target}"},
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["stdout"].startswith("[DRY RUN]")
    assert result.output["exit_code"] == 0
    assert result.output["risk_assessment"]["risk_level"] == "medium"
    assert not target.exists()


def test_command_executor_automatic_runs_low_risk_command() -> None:
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="automatic-command",
                tool_name="command_executor",
                reason="capability_match",
                input_params={
                    "command": f"{sys.executable} -c \"print('ok')\"",
                    "mode": "automatic",
                    "timeout": 10,
                },
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["success"]
    assert result.output["stdout"].strip() == "ok"
    assert result.output["stderr"] == ""
    assert result.output["exit_code"] == 0


def test_embedder_uses_injected_service_without_network() -> None:
    class FakeEmbeddingService:
        provider = "fake"
        model = "fake-embedding"

        def embed_text(self, text: str, use_cache: bool = True) -> list[float]:
            assert text == "hello semantic world"
            assert use_cache is False
            return [0.1, 0.2, 0.3]

    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="embed-query",
                tool_name="embedder",
                reason="capability_match",
                input_params={
                    "query": "hello semantic world",
                    "use_cache": False,
                    "_embedding_service": FakeEmbeddingService(),
                },
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output == {
        "embedding": [0.1, 0.2, 0.3],
        "dimension": 3,
        "model": "fake-embedding",
        "provider": "fake",
        "cached": False,
    }


def test_logger_writes_legacy_and_structured_jsonl(tmp_path) -> None:
    log_file = tmp_path / "openpilot.jsonl"
    logger = OpenPilotLogger(log_file)

    logger.log_event(
        "legacy_event",
        {"message": "ok"},
        session_id="session-1",
        turn_id=1,
    )
    logger.log_structured_event(
        source_type="tool",
        source_name="file_reader",
        phase="pre_execution",
        event_type="structured_event",
        session_id="session-1",
        turn_id=2,
        success=True,
        duration_ms=3,
        input_summary={"file_path": "demo.txt"},
        output_summary={"size_bytes": 4},
        metadata={"contract": "phase1"},
    )

    events = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
    ]

    assert [event["event_type"] for event in events] == [
        "legacy_event",
        "structured_event",
    ]
    assert events[0]["payload"] == {"message": "ok"}
    assert events[1]["payload"]["source_type"] == "tool"
    assert events[1]["payload"]["source_name"] == "file_reader"
    assert events[1]["payload"]["metadata"] == {"contract": "phase1"}
