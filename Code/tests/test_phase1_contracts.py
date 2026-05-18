from __future__ import annotations

import json
import sys
import importlib.util
from base64 import urlsafe_b64encode
from io import StringIO
from types import SimpleNamespace

import httpx
import pytest
from rich.console import Console

from agent_generator.data_collector import collect_data
from agent_generator.data_processor import process_data
from agent_generator.data_presenter import present_data
from agent_generator.models import DataArtifact, DataArtifactKind, Slot
from agent_generator.pipeline_combiner import combine_pipelines
from agent_generator.runner import _complete_empty_slots
from agent_generator.slot_generator import generate_slots
from core.openpilot_log import OpenPilotLogger
from tools.code_reviewer import code_reviewer_executor
from tools.builtin_tools import register_builtin_tools
from tools.llm_summarizer import llm_summarizer_executor
from tools.web_searcher import _default_http_get, web_searcher_executor
from tools.tool_executor import ToolExecutor
from core.tool_contracts import (
    PermissionLevel,
    ToolDefinition,
    ToolOutputSchema,
)
from tools.tool_selection import ToolSelection
from tools.tool_registry import ToolRegistry


def _registered_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return registry


class FakeCleanupLLM:
    def __init__(
        self,
        payload: dict | str | None = None,
        *,
        fail: bool = False,
        link_selection: str = "NONE",
        keyword_variants: str = "",
        fail_tasks: set[str] | None = None,
    ) -> None:
        self.payload = payload or (
            "## Summary\n"
            "Clean summary\n\n"
            "## Key Points\n"
            "- Useful fact\n\n"
            "## Source Notes\n"
            "- https://example.com/alpha: Primary source\n\n"
            "## Follow-up Queries\n"
            "- openpilot follow up"
        )
        self.fail = fail
        self.link_selection = link_selection
        self.keyword_variants = keyword_variants
        self.fail_tasks = fail_tasks or set()
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        task = request.metadata.get("task")
        if self.fail or task in self.fail_tasks:
            raise RuntimeError("llm unavailable")
        if task == "keyword_generation":
            return SimpleNamespace(parsed_json=None, content=self.keyword_variants)
        if task == "link_selection":
            return SimpleNamespace(parsed_json=None, content=self.link_selection)
        if isinstance(self.payload, dict):
            content = json.dumps(self.payload)
        else:
            content = self.payload
        return SimpleNamespace(
            parsed_json=None,
            content=content,
        )


class FakeStructuredLogger:
    def __init__(self) -> None:
        self.events = []

    def log_structured_event(self, **kwargs) -> None:
        self.events.append(kwargs)


class FakeSummarizerLLM:
    def __init__(self, content: str = "## 最终结果\n整理后的机器学习报告。", *, fail: bool = False) -> None:
        self.content = content
        self.fail = fail
        self.requests = []
        self.model = "fake-summarizer"

    def complete(self, request):
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("summarizer unavailable")
        return SimpleNamespace(
            content=self.content,
            parsed_json=None,
            usage={"total_tokens": 123},
            model=self.model,
        )


class FakeSlotLLM:
    def __init__(self, first_payload: dict, repair_payload: dict | None = None) -> None:
        self.first_payload = first_payload
        self.repair_payload = repair_payload or first_payload
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        task = request.metadata.get("task")
        payload = self.repair_payload if task == "slot_language_repair" else self.first_payload
        return SimpleNamespace(parsed_json=payload, content=json.dumps(payload))


def test_builtin_tools_register_expected_contracts() -> None:
    registry = _registered_registry()

    names = {tool.name for tool in registry.list_all()}
    removed_directory_tool = "directory" + "_lister"

    assert len(names) == 11
    assert {
        "command_executor",
        "embedder",
        "file_reader",
        "file_writer",
        "multi_file_reader",
        "web_searcher",
    }.issubset(names)
    assert removed_directory_tool not in names
    assert "autonomy_tool" not in names
    assert "project_environment_tool" not in names
    assert "memory_context" not in names
    assert "project_state_reader" not in names
    assert "project_improvement_tool" not in names


def test_core_imports_remain_available() -> None:
    from core.openpilot_log import OpenPilotLogger as ImportedLogger
    from autonomous_iteration.intelligent_autopilot import IntelligentAutopilot
    from memory.memory_store import MemoryStore
    from tools.tool_executor import ToolExecutor as ImportedToolExecutor

    assert IntelligentAutopilot is not None
    assert ImportedToolExecutor is ToolExecutor
    assert MemoryStore is not None
    assert ImportedLogger is OpenPilotLogger


def test_slot_generator_prompt_requires_user_language_match(monkeypatch) -> None:
    monkeypatch.setattr("agent_generator.slot_generator.raise_for_missing_socksio", lambda: None)
    payload = {
        "user_language": "zh",
        "slots": [
            {
                "name": "investigation_goal",
                "kind": "task",
                "description": "调查目标",
                "value": "基础概念",
                "required": True,
                "revision_notes": [],
            }
        ],
    }
    fake_llm = FakeSlotLLM(payload)

    generate_slots("帮我调查一下机器学习", llm_client=fake_llm)

    prompt = "\n".join(message.content for message in fake_llm.requests[0].messages)
    assert "user_language" in prompt
    assert "same language as the user task" in prompt
    assert "If the task is Chinese" in prompt
    assert "must be Chinese" in prompt


def test_slot_generator_repairs_language_drift_with_llm(monkeypatch) -> None:
    monkeypatch.setattr("agent_generator.slot_generator.raise_for_missing_socksio", lambda: None)
    first_payload = {
        "user_language": "zh",
        "slots": [
            {
                "name": "investigation_goal",
                "kind": "task",
                "description": "El propósito de la investigación",
                "value": "conceptos básicos",
                "required": True,
                "revision_notes": [],
            },
            {
                "name": "depth",
                "kind": "constraint",
                "description": "Nivel de profundidad deseado",
                "value": "principiante",
                "required": False,
                "revision_notes": [],
            },
        ],
    }
    repair_payload = {
        "user_language": "zh",
        "slots": [
            {
                "name": "investigation_goal",
                "kind": "task",
                "description": "调查目标：了解机器学习的基础概念",
                "value": "基础概念",
                "required": True,
                "revision_notes": [],
            },
            {
                "name": "depth",
                "kind": "constraint",
                "description": "期望的内容深度",
                "value": "初学者",
                "required": False,
                "revision_notes": [],
            },
        ],
    }
    fake_llm = FakeSlotLLM(first_payload, repair_payload)

    slots = generate_slots("帮我调查一下机器学习", llm_client=fake_llm)

    assert [request.metadata["task"] for request in fake_llm.requests] == [
        "slot_generation",
        "slot_language_repair",
    ]
    assert slots[0].description == "调查目标：了解机器学习的基础概念"
    assert slots[0].value == "基础概念"
    assert slots[1].description == "期望的内容深度"
    assert slots[1].value == "初学者"


def test_slot_generator_language_repair_preserves_slot_structure(monkeypatch) -> None:
    monkeypatch.setattr("agent_generator.slot_generator.raise_for_missing_socksio", lambda: None)
    first_payload = {
        "user_language": "zh",
        "slots": [
            {
                "name": "output_format",
                "kind": "format",
                "description": "Formato de salida deseado",
                "value": "resumen",
                "required": False,
                "revision_notes": ["nota previa"],
            }
        ],
    }
    repair_payload = {
        "user_language": "zh",
        "slots": [
            {
                "name": "changed_name",
                "kind": "task",
                "description": "期望的输出格式",
                "value": "摘要",
                "required": True,
                "revision_notes": ["已修复为中文"],
            }
        ],
    }
    fake_llm = FakeSlotLLM(first_payload, repair_payload)

    slots = generate_slots("帮我调查一下机器学习", llm_client=fake_llm)

    assert len(slots) == 1
    assert slots[0].name == "output_format"
    assert str(slots[0].kind) == "format"
    assert slots[0].required is False
    assert slots[0].description == "期望的输出格式"
    assert slots[0].value == "摘要"
    assert slots[0].revision_notes == ["已修复为中文"]


def test_slot_generator_does_not_force_english_task_to_chinese(monkeypatch) -> None:
    monkeypatch.setattr("agent_generator.slot_generator.raise_for_missing_socksio", lambda: None)
    payload = {
        "user_language": "en",
        "slots": [
            {
                "name": "investigation_goal",
                "kind": "task",
                "description": "Purpose of the investigation",
                "value": "basic concepts",
                "required": True,
                "revision_notes": [],
            }
        ],
    }
    fake_llm = FakeSlotLLM(payload)

    slots = generate_slots("Research machine learning", llm_client=fake_llm)

    assert [request.metadata["task"] for request in fake_llm.requests] == ["slot_generation"]
    assert slots[0].description == "Purpose of the investigation"
    assert slots[0].value == "basic concepts"


def test_agent_generator_empty_slot_direct_input_fills_value(monkeypatch) -> None:
    slot = Slot(
        name="focus_area",
        kind="constraint",
        description="重点关注的方向，如算法、应用、工具等",
        value=None,
        required=False,
    )
    prompts = []

    def fake_read_text(prompt: str) -> str:
        prompts.append(prompt)
        return "算法"

    monkeypatch.setattr("agent_generator.runner.read_text", fake_read_text)

    changed = _complete_empty_slots([slot], Console(file=StringIO()), auto_approve=False)

    assert changed is True
    assert slot.value == "算法"
    assert slot.revision_notes == ["Filled during empty-slot completion."]
    assert prompts == ["focus_area (重点关注的方向，如算法、应用、工具等) [Enter to skip]> "]


def test_agent_generator_empty_slot_blank_input_skips(monkeypatch) -> None:
    slot = Slot(
        name="time_range",
        kind="constraint",
        description="时间范围偏好，如经典内容、最近进展等",
        value=None,
        required=False,
    )

    monkeypatch.setattr("agent_generator.runner.read_text", lambda prompt: "")

    changed = _complete_empty_slots([slot], Console(file=StringIO()), auto_approve=False)

    assert changed is True
    assert slot.value is None
    assert slot.revision_notes == ["User chose to keep this slot empty."]


def _sample_collected_web_artifact() -> DataArtifact:
    return DataArtifact(
        id="artifact_collected_web",
        name="Collected web research data",
        kind=DataArtifactKind.COLLECTED,
        content={
            "mode": "web",
            "query": "机器学习 概述",
            "tool_output": {
                "query": "机器学习 概述",
                "provider": "bing_html",
                "effective_query": "机器学习 概述",
                "research_summary": "Clean summary about machine learning.",
                "key_points": ["Useful fact", "Another useful fact"],
                "source_notes": [{"url": "https://example.com/ml", "note": "Primary source"}],
                "results": [
                    {
                        "title": "Machine Learning Guide",
                        "url": "https://example.com/ml",
                        "snippet": "Introductory material.",
                    }
                ],
                "pages": [
                    {
                        "title": "Machine Learning Guide",
                        "url": "https://example.com/ml",
                        "content_excerpt": "Readable page content with useful details.",
                    }
                ],
            },
        },
        source="web_search:机器学习 概述",
        confidence=0.8,
        preview="Web search found 1 result(s).",
    )


def test_llm_summarizer_uses_injected_client_without_real_llm() -> None:
    fake_llm = FakeSummarizerLLM("Injected summary")

    result = llm_summarizer_executor(
        {
            "text": "Collected text",
            "instruction": "Produce the final output.",
            "max_tokens": 321,
            "_llm_client": fake_llm,
        }
    )

    assert result == {"summary": "Injected summary", "tokens_used": 123, "model": "fake-summarizer"}
    request = fake_llm.requests[0]
    assert request.response_format == "text"
    assert request.max_tokens == 321
    assert "Produce the final output." in request.messages[0].content
    assert "Collected text" in request.messages[0].content


def test_data_processor_generates_user_facing_result_with_llm() -> None:
    fake_llm = FakeSummarizerLLM("# 机器学习报告\n这是处理后的报告正文。")
    slots = [
        Slot(name="output_format", kind="format", description="输出形式", value="报告", required=False),
        Slot(name="language_preference", kind="constraint", description="语言", value="中文", required=False),
    ]

    processed_data, pipeline = process_data(
        "帮我调查一下机器学习",
        slots,
        [_sample_collected_web_artifact()],
        llm_client=fake_llm,
    )

    content = processed_data[0].content
    assert processed_data[0].name == "Processed agent result"
    assert content["result_text"] == "# 机器学习报告\n这是处理后的报告正文。"
    assert content["result_format"] == "报告"
    assert content["processing_tool"] == "llm_summarizer"
    assert "Requested output format: 报告" in content["processing_instruction"]
    assert "Clean summary about machine learning" in fake_llm.requests[0].messages[0].content
    assert pipeline.steps[0].strategy == "llm"
    assert "Generated 报告 result" in processed_data[0].preview


def test_data_processor_instruction_follows_non_report_output_format() -> None:
    fake_llm = FakeSummarizerLLM("- 资源 A\n- 资源 B")
    slots = [Slot(name="output_format", kind="format", description="输出形式", value="资源列表", required=False)]

    processed_data, _pipeline = process_data(
        "整理机器学习资源",
        slots,
        [_sample_collected_web_artifact()],
        llm_client=fake_llm,
    )

    instruction = processed_data[0].content["processing_instruction"]
    assert "Requested output format: 资源列表" in instruction
    assert processed_data[0].content["result_format"] == "资源列表"
    assert processed_data[0].content["result_text"] == "- 资源 A\n- 资源 B"


def test_data_processor_falls_back_to_rule_based_result_when_llm_fails() -> None:
    fake_llm = FakeSummarizerLLM(fail=True)
    slots = [Slot(name="output_format", kind="format", description="输出形式", value="摘要", required=False)]

    processed_data, pipeline = process_data(
        "帮我调查一下机器学习",
        slots,
        [_sample_collected_web_artifact()],
        llm_client=fake_llm,
    )

    content = processed_data[0].content
    assert content["processing_tool"] == "rule_based_fallback"
    assert "Clean summary about machine learning." in content["result_text"]
    assert "Useful fact" in content["result_text"]
    assert "LLM processing failed" in content["warnings"][0]
    assert pipeline.steps[0].strategy == "function"


def test_processed_data_preview_displays_result_text() -> None:
    processed_data, _pipeline = process_data(
        "帮我调查一下机器学习",
        [Slot(name="output_format", kind="format", description="输出形式", value="报告", required=False)],
        [_sample_collected_web_artifact()],
        llm_client=FakeSummarizerLLM("# 成品\n这是真正的处理结果。"),
    )

    rendered = StringIO()
    present_data(processed_data, Console(file=rendered, width=120, force_terminal=False))

    text = rendered.getvalue()
    assert "Processed Result" in text
    assert "这是真正的处理结果" in text


def test_pipeline_combiner_embeds_artifacts_and_run_returns_processed_result(tmp_path) -> None:
    processed_data, pipeline = process_data(
        "帮我调查一下机器学习",
        [Slot(name="output_format", kind="format", description="输出形式", value="报告", required=False)],
        [_sample_collected_web_artifact()],
        llm_client=FakeSummarizerLLM("# 成品\n生成 agent 应返回这段。"),
    )
    pipeline.approved = True
    for step in pipeline.steps:
        step.approved = True

    spec = combine_pipelines([pipeline], output_dir=tmp_path, agent_name="demo agent", artifacts=processed_data)

    module_spec = importlib.util.spec_from_file_location("generated_demo_agent", spec.agent_file)
    assert module_spec and module_spec.loader
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    run_output = module.run()

    assert spec.artifacts[0].content["result_text"] == "# 成品\n生成 agent 应返回这段。"
    assert run_output["result"] == "# 成品\n生成 agent 应返回这段。"
    assert run_output["artifacts"][0]["id"] == "artifact_processed_result"


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
    assert result.output["file_type"] == "data"
    assert result.output["truncated"] is False
    assert selection.input_params["encoding"] == "utf-8"
    assert selection.input_params["max_size_mb"] == 10


def test_file_reader_supports_sample_mode(tmp_path) -> None:
    target = tmp_path / "sample.log"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="sample-file",
                tool_name="file_reader",
                reason="capability_match",
                input_params={
                    "file_path": str(target),
                    "read_mode": "sample",
                    "max_lines": 2,
                },
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["content"] == "one\ntwo\n"
    assert result.output["lines_read"] == 2
    assert result.output["total_lines"] == 3
    assert result.output["truncated"] is True
    assert result.output["metadata"]["read_mode"] == "sample"


def test_file_reader_supports_tail_mode(tmp_path) -> None:
    target = tmp_path / "tail.log"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="tail-file",
                tool_name="file_reader",
                reason="capability_match",
                input_params={
                    "file_path": str(target),
                    "read_mode": "tail",
                    "max_lines": 2,
                },
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["content"] == "two\nthree\n"
    assert result.output["lines_read"] == 2
    assert result.output["total_lines"] == 3
    assert result.output["truncated"] is True
    assert result.output["metadata"]["read_mode"] == "tail"


def test_file_reader_adaptive_mode_samples_log_files(tmp_path) -> None:
    target = tmp_path / "events.log"
    target.write_text("first\nsecond\nthird\n", encoding="utf-8")
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="adaptive-file",
                tool_name="file_reader",
                reason="capability_match",
                input_params={
                    "file_path": str(target),
                    "read_mode": "adaptive",
                    "max_lines": 2,
                },
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["file_type"] == "log"
    assert result.output["content"] == "first\nsecond\n"
    assert result.output["truncated"] is True
    assert result.output["metadata"]["read_mode"] == "adaptive"


def test_file_reader_returns_placeholder_for_binary_files(tmp_path) -> None:
    target = tmp_path / "image.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\n")
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="binary-file",
                tool_name="file_reader",
                reason="capability_match",
                input_params={"file_path": str(target)},
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["content"] == "[Binary file - content not displayed]"
    assert result.output["file_type"] == "binary"
    assert result.output["encoding"] == "binary"
    assert result.output["lines_read"] == 0


def test_multi_file_reader_scans_directory_with_glob(tmp_path) -> None:
    first = tmp_path / "alpha完成报告.md"
    second = tmp_path / "beta完成报告.md"
    ignored = tmp_path / "notes.txt"
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")
    ignored.write_text("ignored", encoding="utf-8")

    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="read-matching-files",
                tool_name="multi_file_reader",
                reason="capability_match",
                input_params={
                    "directory_path": str(tmp_path),
                    "pattern": "*完成报告.md",
                },
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["count"] == 2
    assert result.output["files"] == [str(first), str(second)]
    assert "alpha" in result.output["content"]
    assert "beta" in result.output["content"]
    assert "ignored" not in result.output["content"]


def test_code_reviewer_rejects_non_pygame_when_pygame_is_product_fit() -> None:
    result = code_reviewer_executor(
        {
            "code": "print('hi')\n",
            "language": "python",
            "prompt_context": {
                "product_judgment": {
                    "preferred_stack": "pygame",
                }
            },
        }
    )

    assert result["approved"] is False
    assert any("standalone pygame GUI" in item for item in result["warnings"])
    assert any("standalone pygame GUI" in item for item in result["suggestions"])


def test_code_reviewer_rejects_curses_when_pygame_is_product_fit() -> None:
    result = code_reviewer_executor(
        {
            "code": "import curses\n\ndef main(stdscr):\n    pass\n",
            "language": "python",
            "prompt_context": {
                "product_judgment": {
                    "preferred_stack": "pygame",
                }
            },
        }
    )

    assert result["approved"] is False
    assert any("terminal/curses to pygame" in item for item in result["warnings"])
    assert any("terminal/curses to pygame" in item for item in result["suggestions"])


def test_code_reviewer_allows_pygame_code_without_product_fit_warning() -> None:
    result = code_reviewer_executor(
        {
            "code": "import pygame\npygame.init()\n",
            "language": "python",
            "prompt_context": {
                "product_judgment": {
                    "preferred_stack": "pygame",
                }
            },
        }
    )

    assert not any("Product-fit rubric not satisfied" in item for item in result["warnings"])
    assert not any("Product-fit rubric not satisfied" in item for item in result["suggestions"])


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


def test_web_searcher_requires_query() -> None:
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="search-missing-query",
                tool_name="web_searcher",
                reason="capability_match",
                input_params={},
            )
        )
    finally:
        executor.shutdown()

    assert not result.success
    assert result.error is not None
    assert result.error.error_type == "InvalidInput"
    assert "query" in result.error.error_message


def test_web_searcher_parses_google_html_without_network() -> None:
    html = """
    <html>
      <body>
        <a href="/url?q=https%3A%2F%2Fexample.com%2Falpha&amp;sa=U">Alpha Result</a>
        <a href="/search?q=openpilot">Google internal link</a>
        <a href="/url?q=https%3A%2F%2Fdocs.example.org%2Fbeta&amp;sa=U">Beta Result</a>
      </body>
    </html>
    """

    def fake_http_get(url: str, timeout: int) -> str:
        assert "google.com/search" in url
        assert "q=openpilot+research" in url
        assert timeout == 7
        return html

    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="search-web",
                tool_name="web_searcher",
                reason="capability_match",
                input_params={
                    "query": "openpilot research",
                    "max_results": 1,
                    "max_pages": 0,
                    "timeout": 7,
                    "llm_cleanup": False,
                    "_http_get": fake_http_get,
                },
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["provider"] == "google_html"
    assert result.output["effective_query"] == "openpilot research"
    assert result.output["count"] == 1
    assert result.output["llm_cleanup"] is False
    assert result.output["results"][0] == {
        "rank": 1,
        "title": "Alpha Result",
        "url": "https://example.com/alpha",
        "snippet": "",
        "source_domain": "example.com",
    }
    assert result.output["search_attempts"][0]["provider"] == "google_html"
    assert result.output["warnings"] == []


def test_web_searcher_parses_google_url_parameter_without_network() -> None:
    html = """
    <html><body>
      <a href="/url?url=https%3A%2F%2Fexample.com%2Furl-param&amp;sa=U">URL Param Result</a>
    </body></html>
    """

    result = web_searcher_executor(
        {
            "query": "openpilot",
            "max_pages": 0,
            "llm_cleanup": False,
            "max_search_attempts": 1,
            "_http_get": lambda url, timeout: html,
        }
    )

    assert result["count"] == 1
    assert result["results"][0]["url"] == "https://example.com/url-param"


def test_web_searcher_parses_bing_ck_redirect_without_google_base() -> None:
    target = "https://example.com/bing-article"
    encoded = urlsafe_b64encode(target.encode("utf-8")).decode("ascii").rstrip("=")
    html = f"""
    <ol>
      <li class="b_algo">
        <h2><a href="/ck/a?u=a1{encoded}&amp;ntb=1">Bing Redirect Result</a></h2>
        <p>Bing snippet.</p>
      </li>
    </ol>
    """

    def fake_http_get(url: str, timeout: int) -> str:
        if "google.com/search" in url:
            return "<html><body>No Google results</body></html>"
        if "bing.com/search" in url:
            return html
        raise AssertionError(f"unexpected url: {url}")

    result = web_searcher_executor(
        {
            "query": "openpilot",
            "max_pages": 0,
            "llm_cleanup": False,
            "max_search_attempts": 2,
            "_http_get": fake_http_get,
        }
    )

    assert result["provider"] == "bing_html"
    assert result["count"] == 1
    assert result["results"][0]["url"] == target
    assert "google.com/ck" not in result["results"][0]["url"]


def test_web_searcher_empty_results_return_warning_without_failure() -> None:
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="search-empty",
                tool_name="web_searcher",
                reason="capability_match",
                input_params={
                    "query": "nothing",
                    "llm_cleanup": False,
                    "_http_get": lambda url, timeout: "<html><body>No results</body></html>",
                },
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["count"] == 0
    assert result.output["results"] == []
    assert result.output["search_attempts"]
    assert all(attempt["status"] == "empty" for attempt in result.output["search_attempts"])
    assert result.output["warnings"]


def test_web_searcher_continues_from_empty_google_to_bing_without_network() -> None:
    bing_html = """
    <ol>
      <li class="b_algo">
        <h2><a href="https://example.com/bing-result">Bing Result</a></h2>
        <p>Bing snippet with useful details.</p>
      </li>
    </ol>
    """

    def fake_http_get(url: str, timeout: int) -> str:
        if "google.com/search" in url:
            return "<html><body>No Google results</body></html>"
        if "bing.com/search" in url:
            return bing_html
        raise AssertionError(f"unexpected url: {url}")

    result = web_searcher_executor(
        {
            "query": "openpilot research",
            "max_pages": 0,
            "llm_cleanup": False,
            "max_search_attempts": 2,
            "_http_get": fake_http_get,
        }
    )

    assert result["provider"] == "bing_html"
    assert result["effective_query"] == "openpilot research"
    assert [attempt["status"] for attempt in result["search_attempts"]] == ["empty", "success"]
    assert result["results"][0]["url"] == "https://example.com/bing-result"


def test_web_searcher_builds_short_query_variants_from_long_slot_query() -> None:
    seen_search_urls = []
    html = '<a href="/url?q=https%3A%2F%2Fexample.com%2Fml&amp;sa=U">ML Result</a>'

    def fake_http_get(url: str, timeout: int) -> str:
        seen_search_urls.append(url)
        if "google.com/search" in url:
            return html
        raise AssertionError(f"unexpected url: {url}")

    result = web_searcher_executor(
        {
            "query": "帮我调研一下机器学习 subject: 机器学习 depth: overview output_format: report language: 中文 time_focus: latest",
            "max_pages": 0,
            "llm_cleanup": False,
            "max_search_attempts": 1,
            "_http_get": fake_http_get,
        }
    )

    assert result["effective_query"].startswith("机器学习")
    assert "subject:" not in result["effective_query"]
    assert "subject%3A" not in seen_search_urls[0]
    assert "机器学习" in result["effective_query"]


def test_web_searcher_tries_next_query_variant_until_success() -> None:
    google_html = '<a href="/url?q=https%3A%2F%2Fexample.com%2Fml&amp;sa=U">Machine Learning</a>'

    def fake_http_get(url: str, timeout: int) -> str:
        if "q=%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0" in url and "overview" not in url and "%E6%A6%82%E8%BF%B0" not in url:
            return google_html
        return "<html><body>No results for first variant</body></html>"

    result = web_searcher_executor(
        {
            "query": "subject: 机器学习 depth: overview",
            "max_pages": 0,
            "llm_cleanup": False,
            "max_search_attempts": 3,
            "_http_get": fake_http_get,
        }
    )

    assert result["count"] == 1
    assert result["effective_query"] == "机器学习"
    assert [attempt["status"] for attempt in result["search_attempts"]] == ["empty", "empty", "success"]


def test_web_searcher_llm_keyword_generation_failure_uses_local_variants() -> None:
    html = '<a href="/url?q=https%3A%2F%2Fexample.com%2Fml&amp;sa=U">ML Result</a>'

    def fake_http_get(url: str, timeout: int) -> str:
        if "google.com/search" in url:
            return html
        raise AssertionError(f"unexpected url: {url}")

    fake_llm = FakeCleanupLLM(fail_tasks={"keyword_generation"})
    result = web_searcher_executor(
        {
            "query": "subject: 机器学习 depth: overview",
            "max_pages": 0,
            "llm_cleanup": False,
            "max_search_attempts": 1,
            "_http_get": fake_http_get,
            "_llm_client": fake_llm,
        }
    )

    assert result["count"] == 1
    assert any("LLM keyword generation failed" in warning for warning in result["warnings"])
    assert [request.metadata["task"] for request in fake_llm.requests] == ["keyword_generation"]


def test_web_searcher_default_http_get_uses_httpx_env_proxy_and_redirects(monkeypatch) -> None:
    calls = {}

    class FakeResponse:
        text = "<html>ok</html>"

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            calls["client_kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, url: str):
            calls["url"] = url
            return FakeResponse()

    monkeypatch.setattr("tools.web_searcher._load_dotenv_for_proxy", lambda: calls.setdefault("dotenv", True))
    monkeypatch.setattr("tools.web_searcher.httpx.Client", FakeClient)

    html = _default_http_get("https://example.com/search", 7)

    assert html == "<html>ok</html>"
    assert calls["dotenv"] is True
    assert calls["url"] == "https://example.com/search"
    assert calls["client_kwargs"]["timeout"] == 7
    assert calls["client_kwargs"]["trust_env"] is True
    assert calls["client_kwargs"]["follow_redirects"] is True


def test_web_searcher_network_errors_include_sanitized_proxy_diagnostics(monkeypatch) -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)

    def fake_http_get(url: str, timeout: int) -> str:
        raise httpx.ReadError("SSL: UNEXPECTED_EOF_WHILE_READING via https://proxy.example/secret")

    result = web_searcher_executor(
        {
            "query": "openpilot",
            "max_pages": 0,
            "llm_cleanup": False,
            "max_search_attempts": 1,
            "_http_get": fake_http_get,
        }
    )

    assert result["count"] == 0
    assert result["search_attempts"][0]["status"] == "network_error"
    assert "Network/proxy failure" in result["search_attempts"][0]["error"]
    assert "[redacted-url]" in result["search_attempts"][0]["error"]
    assert "proxy.example" not in json.dumps(result, ensure_ascii=False)
    assert result["network_diagnostics"]["proxy_env_vars"] == []
    assert any("No HTTP_PROXY/HTTPS_PROXY/ALL_PROXY" in warning for warning in result["warnings"])


def test_web_searcher_blocked_search_page_is_diagnosed() -> None:
    def fake_http_get(url: str, timeout: int) -> str:
        return "<html><title>CAPTCHA</title><body>Please enable JavaScript to continue</body></html>"

    result = web_searcher_executor(
        {
            "query": "openpilot",
            "max_pages": 0,
            "llm_cleanup": False,
            "max_search_attempts": 1,
            "_http_get": fake_http_get,
        }
    )

    assert result["count"] == 0
    assert result["search_attempts"][0]["status"] == "blocked"
    assert "challenge" in result["search_attempts"][0]["error"].lower()
    assert any("status=blocked" in warning for warning in result["warnings"])


def test_web_searcher_http_status_blocked_is_diagnosed() -> None:
    request = httpx.Request("GET", "https://www.google.com/search?q=openpilot")
    response = httpx.Response(429, request=request)

    def fake_http_get(url: str, timeout: int) -> str:
        raise httpx.HTTPStatusError("too many requests", request=request, response=response)

    result = web_searcher_executor(
        {
            "query": "openpilot",
            "max_pages": 0,
            "llm_cleanup": False,
            "max_search_attempts": 1,
            "_http_get": fake_http_get,
        }
    )

    assert result["count"] == 0
    assert result["search_attempts"][0]["status"] == "blocked"
    assert "HTTP 429" in result["search_attempts"][0]["error"]


def test_web_searcher_fallback_extracts_external_search_links() -> None:
    html = """
    <html><body>
      <div class="unexpected_result_shape">
        <a href="https://www.bing.com/search?q=openpilot">Internal search</a>
        <a href="https://example.com/article">Useful Article</a>
        <a href="/url?q=https%3A%2F%2Fexample.org%2Fguide&amp;sa=U">Useful Guide</a>
      </div>
    </body></html>
    """

    def fake_http_get(url: str, timeout: int) -> str:
        return html

    result = web_searcher_executor(
        {
            "query": "openpilot",
            "max_results": 2,
            "max_pages": 0,
            "llm_cleanup": False,
            "max_search_attempts": 1,
            "_http_get": fake_http_get,
        }
    )

    assert result["count"] == 2
    assert result["search_attempts"][0]["status"] == "success"
    assert [item["url"] for item in result["results"]] == [
        "https://example.com/article",
        "https://example.org/guide",
    ]


def test_web_searcher_network_errors_are_reported_without_failure() -> None:
    def failing_http_get(url: str, timeout: int) -> str:
        raise OSError("network down")

    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="search-network-failure",
                tool_name="web_searcher",
                reason="capability_match",
                input_params={
                    "query": "openpilot",
                    "_http_get": failing_http_get,
                },
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["count"] == 0
    assert result.output["results"] == []
    assert result.output["search_attempts"]
    assert all(attempt["status"] == "network_error" for attempt in result.output["search_attempts"])
    assert any("network down" in warning for warning in result.output["warnings"])


def test_web_searcher_fetches_pages_and_cleans_with_llm_without_network() -> None:
    search_html = """
    <a href="/url?q=https%3A%2F%2Fexample.com%2Falpha&amp;sa=U">Alpha Result</a>
    <a href="/url?q=https%3A%2F%2Fexample.org%2Fbeta&amp;sa=U">Beta Result</a>
    """
    pages = {
        "https://example.com/alpha": """
        <html><head><title>Alpha Page</title><script>ignore()</script></head>
        <body><nav>menu</nav><main><h1>Alpha heading</h1>
        <p>Alpha useful paragraph with enough detail for extraction.</p>
        <p>Alpha useful paragraph with enough detail for extraction.</p></main></body></html>
        """,
        "https://example.org/beta": """
        <html><head><title>Beta Page</title></head>
        <body><article><p>Beta useful paragraph with distinct research details.</p></article></body></html>
        """,
    }

    def fake_http_get(url: str, timeout: int) -> str:
        if "google.com/search" in url or "bing.com/search" in url:
            return search_html
        return pages[url]

    fake_llm = FakeCleanupLLM()
    result = web_searcher_executor(
        {
            "query": "openpilot research",
            "max_results": 2,
            "max_pages": 2,
            "max_page_chars": 500,
            "_http_get": fake_http_get,
            "_llm_client": fake_llm,
        }
    )

    assert result["llm_cleanup"] is True
    assert [request.metadata["task"] for request in fake_llm.requests] == ["keyword_generation", "cleanup"]
    assert fake_llm.requests[-1].response_format == "text"
    assert len(result["pages"]) == 2
    assert result["pages"][0]["title"] == "Alpha Page"
    assert result["pages"][0]["fetch_success"] is True
    assert result["pages"][0]["fetch_depth"] == 0
    assert result["pages"][0]["parent_url"] is None
    assert result["pages"][0]["selected_by_llm"] is False
    assert "menu" not in result["pages"][0]["content_excerpt"]
    assert "Alpha useful paragraph" in result["pages"][0]["content_excerpt"]
    assert "Clean summary" in result["research_summary"]
    assert result["key_points"] == ["Useful fact"]
    assert result["source_notes"] == [{"url": "https://example.com/alpha", "note": "Primary source"}]
    assert result["follow_up_queries"] == ["openpilot follow up"]


def test_web_searcher_max_pages_zero_skips_page_fetch_and_cleanup() -> None:
    html = '<a href="/url?q=https%3A%2F%2Fexample.com%2Fa&amp;sa=U">A</a>'

    def fake_http_get(url: str, timeout: int) -> str:
        assert "google.com/search" in url
        return html

    fake_llm = FakeCleanupLLM()
    result = web_searcher_executor(
        {
            "query": "openpilot",
            "max_pages": 0,
            "_http_get": fake_http_get,
            "_llm_client": fake_llm,
        }
    )

    assert result["count"] == 1
    assert result["pages"] == []
    assert result["llm_cleanup"] is False
    assert [request.metadata["task"] for request in fake_llm.requests] == ["keyword_generation"]


def test_web_searcher_llm_cleanup_false_skips_llm() -> None:
    html = '<a href="/url?q=https%3A%2F%2Fexample.com%2Fa&amp;sa=U">A</a>'

    def fake_http_get(url: str, timeout: int) -> str:
        if "google.com/search" in url or "bing.com/search" in url:
            return html
        return "<html><body><p>Readable page content with useful details.</p></body></html>"

    fake_llm = FakeCleanupLLM()
    result = web_searcher_executor(
        {
            "query": "openpilot",
            "llm_cleanup": False,
            "_http_get": fake_http_get,
            "_llm_client": fake_llm,
        }
    )

    assert result["pages"][0]["fetch_success"] is True
    assert result["llm_cleanup"] is False
    assert result["research_summary"] == ""
    assert result["key_points"] == []
    assert [request.metadata["task"] for request in fake_llm.requests] == ["keyword_generation"]


def test_web_searcher_page_fetch_failure_is_nonfatal() -> None:
    html = '<a href="/url?q=https%3A%2F%2Fexample.com%2Fa&amp;sa=U">A</a>'

    def fake_http_get(url: str, timeout: int) -> str:
        if "google.com/search" in url or "bing.com/search" in url:
            return html
        raise OSError("page down")

    result = web_searcher_executor(
        {
            "query": "openpilot",
            "llm_cleanup": False,
            "_http_get": fake_http_get,
        }
    )

    assert result["pages"][0]["fetch_success"] is False
    assert result["pages"][0]["error"] == "page down"
    assert any("Failed to fetch https://example.com/a" in warning for warning in result["warnings"])


def test_web_searcher_follows_llm_selected_page_links_without_network() -> None:
    search_html = '<a href="/url?q=https%3A%2F%2Fexample.com%2Fa&amp;sa=U">A</a>'
    pages = {
        "https://example.com/a": """
        <html><head><title>A</title></head><body>
        <main><p>Readable page content with useful details.</p>
        <a href="/detail">Official detail</a>
        <a href="mailto:test@example.com">Email</a>
        <a href="javascript:void(0)">Script</a>
        <a href="#comments">Comments</a>
        <a href="https://ads.example.net/ad">Ad</a>
        </main></body></html>
        """,
        "https://example.com/detail": """
        <html><head><title>Detail</title></head>
        <body><article><p>Deeper official detail with enough useful research content.</p></article></body></html>
        """,
    }

    def fake_http_get(url: str, timeout: int) -> str:
        if "google.com/search" in url or "bing.com/search" in url:
            return search_html
        return pages[url]

    fake_llm = FakeCleanupLLM(link_selection="L1 | adds official details")
    result = web_searcher_executor(
        {
            "query": "openpilot",
            "max_pages": 1,
            "llm_cleanup": False,
            "_http_get": fake_http_get,
            "_llm_client": fake_llm,
        }
    )

    assert [request.metadata["task"] for request in fake_llm.requests] == ["keyword_generation", "link_selection"]
    assert fake_llm.requests[1].response_format == "text"
    assert len(result["pages"]) == 2
    assert result["pages"][1]["url"] == "https://example.com/detail"
    assert result["pages"][1]["fetch_depth"] == 1
    assert result["pages"][1]["parent_url"] == "https://example.com/a"
    assert result["pages"][1]["selected_by_llm"] is True
    assert result["pages"][1]["selection_reason"] == "adds official details"


def test_web_searcher_default_redirect_depth_stops_after_one_layer() -> None:
    search_html = '<a href="/url?q=https%3A%2F%2Fexample.com%2Fa&amp;sa=U">A</a>'
    pages = {
        "https://example.com/a": """
        <html><body><p>Readable page content with useful details.</p>
        <a href="/detail">Detail</a></body></html>
        """,
        "https://example.com/detail": """
        <html><body><p>Second layer content with useful details.</p>
        <a href="/third">Third layer</a></body></html>
        """,
        "https://example.com/third": "<html><body><p>Third layer should not be fetched by default.</p></body></html>",
    }

    def fake_http_get(url: str, timeout: int) -> str:
        if "google.com/search" in url or "bing.com/search" in url:
            return search_html
        return pages[url]

    fake_llm = FakeCleanupLLM(link_selection="L1 | useful next page")
    result = web_searcher_executor(
        {
            "query": "openpilot",
            "max_pages": 1,
            "llm_cleanup": False,
            "_http_get": fake_http_get,
            "_llm_client": fake_llm,
        }
    )

    assert [page["url"] for page in result["pages"]] == [
        "https://example.com/a",
        "https://example.com/detail",
    ]
    assert [request.metadata["task"] for request in fake_llm.requests] == ["keyword_generation", "link_selection"]


def test_web_searcher_redirect_selection_failure_is_nonfatal() -> None:
    search_html = '<a href="/url?q=https%3A%2F%2Fexample.com%2Fa&amp;sa=U">A</a>'

    def fake_http_get(url: str, timeout: int) -> str:
        if "google.com/search" in url or "bing.com/search" in url:
            return search_html
        return """
        <html><body><p>Readable page content with useful details.</p>
        <a href="/detail">Detail</a></body></html>
        """

    fake_llm = FakeCleanupLLM(fail_tasks={"link_selection"})
    result = web_searcher_executor(
        {
            "query": "openpilot",
            "max_pages": 1,
            "llm_cleanup": False,
            "_http_get": fake_http_get,
            "_llm_client": fake_llm,
        }
    )

    assert len(result["pages"]) == 1
    assert any("LLM redirect selection failed" in warning for warning in result["warnings"])


def test_web_searcher_can_disable_redirect_following() -> None:
    search_html = '<a href="/url?q=https%3A%2F%2Fexample.com%2Fa&amp;sa=U">A</a>'

    def fake_http_get(url: str, timeout: int) -> str:
        if "google.com/search" in url or "bing.com/search" in url:
            return search_html
        return """
        <html><body><p>Readable page content with useful details.</p>
        <a href="/detail">Detail</a></body></html>
        """

    fake_llm = FakeCleanupLLM(link_selection="L1 | would be useful")
    disabled = web_searcher_executor(
        {
            "query": "openpilot",
            "max_pages": 1,
            "llm_cleanup": False,
            "follow_redirects": False,
            "_http_get": fake_http_get,
            "_llm_client": fake_llm,
        }
    )
    depth_zero = web_searcher_executor(
        {
            "query": "openpilot",
            "max_pages": 1,
            "llm_cleanup": False,
            "max_redirect_depth": 0,
            "_http_get": fake_http_get,
            "_llm_client": fake_llm,
        }
    )

    assert len(disabled["pages"]) == 1
    assert len(depth_zero["pages"]) == 1
    assert [request.metadata["task"] for request in fake_llm.requests] == ["keyword_generation", "keyword_generation"]


def test_web_searcher_llm_cleanup_failure_is_reported() -> None:
    html = '<a href="/url?q=https%3A%2F%2Fexample.com%2Fa&amp;sa=U">A</a>'

    def fake_http_get(url: str, timeout: int) -> str:
        if "google.com/search" in url or "bing.com/search" in url:
            return html
        return "<html><body><p>Readable page content with useful details.</p></body></html>"

    try:
        web_searcher_executor(
            {
                "query": "openpilot",
                "_http_get": fake_http_get,
                "_llm_client": FakeCleanupLLM(fail=True),
            }
        )
    except RuntimeError as exc:
        assert "LLM cleanup failed" in str(exc)
    else:
        raise AssertionError("Expected LLM cleanup failure")


def test_web_searcher_cleanup_failure_can_return_raw_for_agent_generator() -> None:
    html = '<a href="/url?q=https%3A%2F%2Fexample.com%2Fa&amp;sa=U">A</a>'

    def fake_http_get(url: str, timeout: int) -> str:
        if "google.com/search" in url or "bing.com/search" in url:
            return html
        return "<html><body><p>Readable page content with useful details.</p></body></html>"

    fake_llm = FakeCleanupLLM(fail=True)
    result = web_searcher_executor(
        {
            "query": "openpilot",
            "_http_get": fake_http_get,
            "_llm_client": fake_llm,
            "_cleanup_failure_policy": "return_raw",
        }
    )

    assert result["llm_cleanup"] is False
    assert result["research_summary"] == ""
    assert result["key_points"] == []
    assert result["llm_cleanup_error"]
    assert any("LLM cleanup failed" in warning for warning in result["warnings"])
    assert [request.metadata["task"] for request in fake_llm.requests] == ["keyword_generation", "cleanup"]


def test_web_searcher_search_failure_returns_attempt_diagnostics_with_cleanup_fallback_policy() -> None:
    def failing_http_get(url: str, timeout: int) -> str:
        raise OSError("network down")

    result = web_searcher_executor(
        {
            "query": "openpilot",
            "_http_get": failing_http_get,
            "_cleanup_failure_policy": "return_raw",
        }
    )

    assert result["count"] == 0
    assert result["search_attempts"]
    assert all(attempt["status"] == "network_error" for attempt in result["search_attempts"])
    assert any("No search results found" in warning for warning in result["warnings"])


def test_agent_generator_collect_data_raises_on_unusable_network_search(monkeypatch) -> None:
    def fake_web_searcher(params):
        return {
            "query": params["query"],
            "provider": "bing_html",
            "effective_query": "",
            "search_attempts": [
                {
                    "provider": "google_html",
                    "query": params["query"],
                    "result_count": 0,
                    "status": "network_error",
                    "error": "SSL EOF. Network/proxy failure while contacting Google/Bing.",
                },
                {
                    "provider": "bing_html",
                    "query": params["query"],
                    "result_count": 0,
                    "status": "blocked",
                    "error": "Search provider returned HTTP 429",
                },
            ],
            "network_diagnostics": {
                "proxy_env_vars": [],
                "proxy_env_detected": False,
                "http_client": "httpx",
                "trust_env": True,
                "follow_redirects": True,
                "dotenv_loaded": False,
            },
            "results": [],
            "count": 0,
            "pages": [],
            "llm_cleanup": False,
            "research_summary": "",
            "key_points": [],
            "source_notes": [],
            "follow_up_queries": [],
            "warnings": [],
        }

    monkeypatch.setattr("agent_generator.data_collector.web_searcher_executor", fake_web_searcher)
    slots = [Slot(name="topic", kind="constraint", description="topic", value="machine learning", required=False)]

    with pytest.raises(RuntimeError) as exc_info:
        collect_data("research machine learning", slots, llm_client=None)

    message = str(exc_info.value)
    assert "network, proxy" in message
    assert "No HTTP_PROXY/HTTPS_PROXY/ALL_PROXY" in message
    assert "google_html" in message
    assert "bing_html" in message


def test_agent_generator_collect_data_keeps_true_empty_search_artifact(monkeypatch) -> None:
    def fake_web_searcher(params):
        return {
            "query": params["query"],
            "provider": "bing_html",
            "effective_query": "",
            "search_attempts": [
                {
                    "provider": "google_html",
                    "query": params["query"],
                    "result_count": 0,
                    "status": "empty",
                    "error": "No search results parsed from provider response",
                }
            ],
            "network_diagnostics": {"proxy_env_vars": [], "proxy_env_detected": False},
            "results": [],
            "count": 0,
            "pages": [],
            "llm_cleanup": False,
            "research_summary": "",
            "key_points": [],
            "source_notes": [],
            "follow_up_queries": [],
            "warnings": ["No search results found after trying Google/Bing query variants."],
        }

    monkeypatch.setattr("agent_generator.data_collector.web_searcher_executor", fake_web_searcher)
    slots = [Slot(name="topic", kind="constraint", description="topic", value="unlikely topic", required=False)]

    artifacts, _pipeline = collect_data("research unlikely topic", slots, llm_client=None)

    assert len(artifacts) == 1
    assert artifacts[0].confidence == 0.45
    assert artifacts[0].content["tool_output"]["search_attempts"][0]["status"] == "empty"


def test_agent_generator_collect_data_returns_web_artifact_when_cleanup_fails(monkeypatch) -> None:
    def fake_web_searcher(params):
        assert params["_cleanup_failure_policy"] == "return_raw"
        return {
            "query": params["query"],
            "provider": "google_html",
            "results": [
                {
                    "rank": 1,
                    "title": "A",
                    "url": "https://example.com/a",
                    "snippet": "A snippet",
                    "source_domain": "example.com",
                }
            ],
            "count": 1,
            "pages": [
                {
                    "url": "https://example.com/a",
                    "title": "A",
                    "source_domain": "example.com",
                    "content_excerpt": "Readable page content with useful details.",
                    "content_chars": 42,
                    "fetch_success": True,
                    "error": None,
                }
            ],
            "llm_cleanup": False,
            "research_summary": "",
            "key_points": [],
            "source_notes": [],
            "follow_up_queries": [],
            "warnings": [
                "LLM cleanup failed, so Agent Generator continued with raw web search results. "
                "Reason: LLM cleanup failed: Failed to parse JSON (attempt 3/3)."
            ],
            "llm_cleanup_error": "LLM cleanup failed: Failed to parse JSON (attempt 3/3)",
        }

    monkeypatch.setattr("agent_generator.data_collector.web_searcher_executor", fake_web_searcher)
    logger = FakeStructuredLogger()
    slots = [Slot(name="topic", kind="constraint", description="topic", value="machine learning", required=False)]

    artifacts, pipeline = collect_data("research machine learning", slots, llm_client=FakeCleanupLLM(), logger=logger)

    assert len(artifacts) == 1
    output = artifacts[0].content["tool_output"]
    assert output["llm_cleanup"] is False
    assert output["results"][0]["url"] == "https://example.com/a"
    step_params = pipeline.steps[0].parameters
    assert step_params["llm_cleanup_requested"] is True
    assert step_params["llm_cleanup_executed"] is False
    assert "LLM cleanup failed" in step_params["cleanup_fallback_warning"]
    assert step_params["produced_artifact_ids"] == [artifacts[0].id]

    rendered = StringIO()
    present_data(artifacts, Console(file=rendered, width=120, force_terminal=False))
    text = rendered.getvalue()
    assert "LLM cleanup failed" in text
    assert "https://example.com/a" in text
    assert "Readable page content" in text

    assert any(event["source_type"] == "agent_generator" for event in logger.events)
    assert any(event["event_type"] == "warning" and event["phase"] == "web_cleanup" for event in logger.events)
    assert "_llm_client" not in json.dumps(logger.events, default=str)


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
