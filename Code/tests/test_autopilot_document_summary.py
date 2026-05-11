import json
import os
import subprocess
import sys
from datetime import datetime
from io import StringIO

from rich.console import Console

from openpilot.builtin_tools import (
    directory_lister_executor,
    multi_file_reader_executor,
    register_builtin_tools,
)
from openpilot.executor_models import ExecutionError, ExecutionResult, ExecutionStatus
from openpilot.llm import LLMResponse
from openpilot.openpilot_log import OpenPilotLogger
from openpilot.planner_models import ExecutionPlan, PlanStep, TaskCard
from openpilot.result_validator import ResultValidator
from openpilot.semantic_analyzer import SemanticAnalyzer
from openpilot.tool_orchestration_models import OrchestrationContext, SelectionReason, ToolOrchestrationPlan, ToolSelection
from openpilot.tool_orchestrator import ToolOrchestrator
from openpilot.tool_registry import ToolRegistry
from openpilot.validation_models import ValidationRule, ValidationSeverity, ValidationType
from openpilot.workflow_executor import WorkflowExecutor
from openpilot.cli import _clear_log_file


class DummyLLMClient:
    def complete(self, request):
        raise AssertionError("LLM should not be called by these unit tests")


class FakeSemanticLLMClient:
    def __init__(self, empty_summaries: int = 0):
        self.empty_summaries = empty_summaries
        self.calls = []

    def complete(self, request):
        self.calls.append(request)
        task = request.metadata.get("semantic_task")
        if task == "goal":
            payload = {
                "task_type": "document_summary",
                "risk_level": "low",
                "required_resources": ["llm", "local_file", "memory"],
                "expected_deliverables": ["completion report summary"],
                "intent": "summarize completion reports",
                "confidence": 0.96,
                "reason": "The user asks to organize completion reports.",
            }
        elif task == "plan_step":
            step_id = request.metadata["step_id"]
            by_step = {
                "step-1": ("list_completion_reports", "file_read", "directory_lister"),
                "step-2": ("read_reports", "file_read", "multi_file_reader"),
                "step-3": ("summarize", "llm_call", "llm_summarizer"),
                "step-4": ("generate_final_report", "llm_call", "llm_summarizer"),
            }
            operation, capability, tool = by_step.get(step_id, ("summarize", "llm_call", "llm_summarizer"))
            payload = {
                "operation_type": operation,
                "capability": capability,
                "preferred_tool": tool,
                "needs_file_write": False,
                "allows_file_mutation": False,
                "source_kind": "previous_output",
                "confidence": 0.94,
                "reason": "Semantic test fixture.",
            }
        else:
            payload = {"summary": "semantic fake response"}
        return LLMResponse(
            content=json.dumps(payload),
            parsed_json=payload,
            model="fake",
            provider="fake",
        )


class ArchiveStepSemanticLLMClient(FakeSemanticLLMClient):
    def complete(self, request):
        if request.metadata.get("semantic_task") == "plan_step" and request.metadata.get("step_id") == "step-4":
            payload = {
                "operation_type": "archive_files",
                "capability": "llm_call",
                "preferred_tool": "llm_summarizer",
                "needs_file_write": False,
                "allows_file_mutation": False,
                "source_kind": "previous_output",
                "confidence": 0.92,
                "reason": "The step requests file organization but the goal did not authorize mutation.",
            }
            return LLMResponse(content=json.dumps(payload), parsed_json=payload, model="fake", provider="fake")
        return super().complete(request)


class ExplicitMutationSemanticLLMClient(FakeSemanticLLMClient):
    def complete(self, request):
        if request.metadata.get("semantic_task") == "plan_step" and request.metadata.get("step_id") == "step-4":
            payload = {
                "operation_type": "archive_files",
                "capability": "file_write",
                "preferred_tool": "unsupported_file_mutation",
                "needs_file_write": True,
                "allows_file_mutation": True,
                "source_kind": "previous_output",
                "confidence": 0.93,
                "reason": "The step explicitly wants to mutate original files.",
            }
            return LLMResponse(content=json.dumps(payload), parsed_json=payload, model="fake", provider="fake")
        return super().complete(request)


class SaveStepSemanticLLMClient(FakeSemanticLLMClient):
    def complete(self, request):
        if request.metadata.get("semantic_task") == "plan_step" and request.metadata.get("step_id") == "step-4":
            payload = {
                "operation_type": "write_output_file",
                "capability": "file_write",
                "preferred_tool": "file_writer",
                "needs_file_write": True,
                "allows_file_mutation": False,
                "source_kind": "previous_output",
                "confidence": 0.95,
                "reason": "The step explicitly names an output markdown file.",
            }
            return LLMResponse(content=json.dumps(payload), parsed_json=payload, model="fake", provider="fake")
        return super().complete(request)


class EmptyThenSummaryExecutor:
    def __init__(self):
        self.calls = 0

    def execute_single(self, selection):
        self.calls += 1
        output = {"summary": "" if self.calls == 1 else "non-empty retry summary"}
        result = ExecutionResult(
            execution_id=f"exec-{self.calls}",
            tool_name=selection.tool_name,
            step_id=selection.step_id,
            status=ExecutionStatus.SUCCESS,
            success=True,
            started_at=datetime.now(),
            output=output,
        )
        return result


class AlwaysEmptyExecutor(EmptyThenSummaryExecutor):
    def execute_single(self, selection):
        self.calls += 1
        return ExecutionResult(
            execution_id=f"exec-{self.calls}",
            tool_name=selection.tool_name,
            step_id=selection.step_id,
            status=ExecutionStatus.SUCCESS,
            success=True,
            started_at=datetime.now(),
            output={"summary": ""},
        )


def _semantic_orchestrator(registry: ToolRegistry, client=None) -> ToolOrchestrator:
    return ToolOrchestrator(registry, semantic_analyzer=SemanticAnalyzer(client or FakeSemanticLLMClient()))


def _document_summary_plan(plan_dir: str) -> ExecutionPlan:
    return ExecutionPlan(
        task_card=TaskCard(
            goal=f"\u5e2e\u6211\u751f\u6210'{plan_dir}'\u4e0b\u5b8c\u6210\u62a5\u544a\u7684\u603b\u7ed3",
            task_type="document_summary",
            risk_level="low",
        ),
        steps=[
            PlanStep(
                id="step-1",
                title="\u626b\u63cf\u76ee\u5f55\u83b7\u53d6\u6587\u4ef6\u5217\u8868",
                description=f"\u626b\u63cf {plan_dir} \u76ee\u5f55\u5e76\u627e\u51fa\u5b8c\u6210\u62a5\u544a\u6587\u4ef6",
                risk_level="low",
                expected_output="\u6587\u4ef6\u5217\u8868",
            ),
            PlanStep(
                id="step-2",
                title="\u8bfb\u53d6\u62a5\u544a\u6587\u4ef6\u5185\u5bb9",
                description="\u8bfb\u53d6\u5b8c\u6210\u62a5\u544a\u6587\u4ef6\u5185\u5bb9",
                risk_level="low",
                expected_output="\u62a5\u544a\u5185\u5bb9",
            ),
            PlanStep(
                id="step-3",
                title="\u751f\u6210\u62a5\u544a\u603b\u7ed3",
                description="\u751f\u6210\u5b8c\u6210\u62a5\u544a\u7684\u603b\u7ed3",
                risk_level="low",
                expected_output="\u603b\u7ed3\u6587\u672c",
            ),
        ],
        success_criteria=["summary generated"],
    )


def _document_summary_final_report_plan(plan_dir: str) -> ExecutionPlan:
    plan = _document_summary_plan(plan_dir)
    plan.task_card.goal = f"\u5e2e\u6211\u6574\u7406'{plan_dir}'\u4e0b\u7684\u6240\u6709\u5b8c\u6210\u62a5\u544a"
    plan.steps.append(
        PlanStep(
            id="step-4",
            title="\u751f\u6210\u6700\u7ec8\u6574\u7406\u62a5\u544a",
            description="\u57fa\u4e8e\u6bcf\u4e2a\u62a5\u544a\u6458\u8981\u751f\u6210\u6700\u7ec8\u6574\u7406\u62a5\u544a",
            risk_level="low",
            expected_output="\u6700\u7ec8\u6574\u7406\u62a5\u544a",
        )
    )
    return plan


def test_chinese_document_summary_orchestration_uses_specific_tools(tmp_path):
    registry = ToolRegistry()
    register_builtin_tools(registry)
    orchestrator = _semantic_orchestrator(registry)

    result = orchestrator.create_orchestration_plan(
        _document_summary_plan(str(tmp_path)),
        OrchestrationContext(task_type="document_summary", prefer_parallel=False, use_memory=False),
    )

    assert result.success is True
    selections = result.plan.tool_selections
    assert [selection.tool_name for selection in selections] == [
        "directory_lister",
        "multi_file_reader",
        "llm_summarizer",
    ]
    assert selections[0].input_params["directory_path"] == str(tmp_path)
    assert selections[1].input_params["source_step_id"] == "step-1"
    assert selections[2].input_params["source_step_id"] == "step-2"


def test_goal_understanding_uses_llm_semantic_classification(tmp_path):
    client = FakeSemanticLLMClient()
    workflow = WorkflowExecutor(client, console=Console(file=open(os.devnull, "w")))
    workflow.logger = OpenPilotLogger(tmp_path / "openpilot.jsonl")
    workflow.workflow_session_id = "test-session"

    task_card = workflow._stage_1_goal_understanding(
        "\u5e2e\u6211\u6574\u7406 Plan \u4e2d\u6240\u6709\u5b8c\u6210\u62a5\u544a"
    )

    assert task_card.task_type.value == "document_summary"
    assert task_card.risk_level.value == "low"
    assert any(call.metadata.get("semantic_task") == "goal" for call in client.calls)
    events = [
        json.loads(line)
        for line in (tmp_path / "openpilot.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["event_type"] == "semantic_goal_analysis"


def test_final_report_generation_uses_llm_not_file_writer(tmp_path):
    registry = ToolRegistry()
    register_builtin_tools(registry)
    orchestrator = _semantic_orchestrator(registry)

    result = orchestrator.create_orchestration_plan(
        _document_summary_final_report_plan(str(tmp_path)),
        OrchestrationContext(task_type="document_summary", prefer_parallel=False, use_memory=False),
    )

    assert result.success is True
    selections = result.plan.tool_selections
    assert [selection.tool_name for selection in selections] == [
        "directory_lister",
        "multi_file_reader",
        "llm_summarizer",
        "llm_summarizer",
    ]
    assert selections[3].input_params["source_step_id"] == "step-3"
    assert "file_path" not in selections[3].input_params


def test_explicit_save_step_uses_file_writer_with_previous_content(tmp_path):
    plan = _document_summary_final_report_plan(str(tmp_path))
    plan.steps[-1] = PlanStep(
        id="step-4",
        title="\u4fdd\u5b58\u5230 final.md",
        description="\u5c06\u6700\u7ec8\u6574\u7406\u62a5\u544a\u4fdd\u5b58\u5230 final.md",
        risk_level="medium",
        expected_output="\u5199\u5165 final.md",
    )
    registry = ToolRegistry()
    register_builtin_tools(registry)
    orchestrator = ToolOrchestrator(registry, semantic_analyzer=SemanticAnalyzer(SaveStepSemanticLLMClient()))

    result = orchestrator.create_orchestration_plan(
        plan,
        OrchestrationContext(task_type="document_summary", prefer_parallel=False, use_memory=False),
    )

    assert result.success is True
    final_selection = result.plan.tool_selections[-1]
    assert final_selection.tool_name == "file_writer"
    assert final_selection.input_params["file_path"] == "final.md"
    assert final_selection.input_params["source_step_id"] == "step-3"


def test_archive_step_without_mutation_permission_becomes_llm_recommendation(tmp_path):
    registry = ToolRegistry()
    register_builtin_tools(registry)
    orchestrator = ToolOrchestrator(registry, semantic_analyzer=SemanticAnalyzer(ArchiveStepSemanticLLMClient()))

    result = orchestrator.create_orchestration_plan(
        _document_summary_final_report_plan(str(tmp_path)),
        OrchestrationContext(task_type="document_summary", prefer_parallel=False, use_memory=False),
    )

    assert result.success is True
    final_selection = result.plan.tool_selections[-1]
    assert final_selection.step_id == "step-4"
    assert final_selection.tool_name == "llm_summarizer"
    assert final_selection.input_params["source_step_id"] == "step-3"
    assert "file_path" not in final_selection.input_params
    assert orchestrator.last_semantic_analyses[-1]["allows_file_mutation"] is False


def test_explicit_file_mutation_is_reported_unsupported(tmp_path):
    registry = ToolRegistry()
    register_builtin_tools(registry)
    orchestrator = ToolOrchestrator(registry, semantic_analyzer=SemanticAnalyzer(ExplicitMutationSemanticLLMClient()))

    result = orchestrator.create_orchestration_plan(
        _document_summary_final_report_plan(str(tmp_path)),
        OrchestrationContext(task_type="document_summary", prefer_parallel=False, use_memory=False),
    )

    assert result.success is True
    assert [selection.step_id for selection in result.plan.tool_selections] == ["step-1", "step-2", "step-3"]
    assert result.warnings
    assert "safe move/rename tool" in result.warnings[0]


def test_multi_file_reader_output_feeds_llm_text(tmp_path):
    first = tmp_path / "OP-01-\u5b8c\u6210\u62a5\u544a.md"
    second = tmp_path / "OP-02-\u5b8c\u6210\u62a5\u544a.md"
    first.write_text("# OP-01\n\nDone A", encoding="utf-8")
    second.write_text("# OP-02\n\nDone B", encoding="utf-8")

    listed = directory_lister_executor(
        {"directory_path": str(tmp_path), "pattern": "*\u5b8c\u6210\u62a5\u544a*.md"}
    )
    read = multi_file_reader_executor({"file_paths": listed["files"]})

    workflow = WorkflowExecutor(DummyLLMClient(), console=Console(file=open(os.devnull, "w")))
    selection = ToolSelection(
        step_id="step-3",
        tool_name="llm_summarizer",
        reason=SelectionReason.CAPABILITY_MATCH,
        confidence=0.9,
        input_params={"source_step_id": "step-2"},
    )

    resolved = workflow._resolve_selection_inputs(selection, {"step-2": read})

    assert "text" in resolved.input_params
    assert "Done A" in resolved.input_params["text"]
    assert "Done B" in resolved.input_params["text"]
    assert "source_step_id" not in resolved.input_params


def test_workflow_failure_status_and_log_payload(tmp_path):
    workflow = WorkflowExecutor(DummyLLMClient(), console=Console(file=open(os.devnull, "w")))
    workflow.logger = OpenPilotLogger(tmp_path / "openpilot.jsonl")
    workflow.stats["start_time"] = datetime.now()

    result = ExecutionResult(
        execution_id="exec-1",
        tool_name="file_reader",
        step_id="step-1",
        status=ExecutionStatus.FAILED,
        success=False,
        started_at=datetime.now(),
    )
    result.mark_failed(
        ExecutionError(
            error_type="KeyError",
            error_message="'file_path'",
            recoverable=False,
            retry_recommended=False,
        )
    )
    result.metadata["input_keys"] = []
    validation = ResultValidator().validate_execution_result(result)
    plan = ExecutionPlan(
        task_card=TaskCard(goal="test", task_type="document_summary", risk_level="low"),
        steps=[
            PlanStep(
                id="step-1",
                title="read",
                description="read",
                risk_level="low",
                expected_output="content",
            )
        ],
    )

    workflow._stage_8_logging(plan.task_card, plan, [result], [validation], [])

    payload = json.loads((tmp_path / "openpilot.jsonl").read_text(encoding="utf-8").splitlines()[-1])["payload"]
    assert workflow._workflow_success([result], [validation]) is False
    assert payload["success"] is False
    assert payload["step_results"][0]["error"]["type"] == "KeyError"
    assert payload["step_results"][0]["input_keys"] == []


def test_workflow_log_includes_planned_steps_tool_selections_and_input_resolution(tmp_path):
    workflow = WorkflowExecutor(DummyLLMClient(), console=Console(file=open(os.devnull, "w")))
    workflow.logger = OpenPilotLogger(tmp_path / "openpilot.jsonl")
    workflow.stats["start_time"] = datetime.now()
    plan = _document_summary_plan(str(tmp_path))
    selection = ToolSelection(
        step_id="step-2",
        tool_name="llm_summarizer",
        reason=SelectionReason.CAPABILITY_MATCH,
        confidence=0.9,
        input_params={"file_path": str(tmp_path)},
    )
    workflow._last_orchestration_plan = ToolOrchestrationPlan(
        plan_id="plan-1",
        goal=plan.task_card.goal,
        tool_selections=[selection],
    )
    result = workflow._create_missing_input_result(
        selection,
        {
            "original_input_keys": ["file_path"],
            "resolved_input_keys": ["file_path"],
            "source_step_id": None,
            "source_available": False,
            "source_output_summary": None,
            "missing_required_inputs": ["text"],
            "unresolved_input_chain": True,
        },
    )
    result.metadata["input_keys"] = ["file_path"]
    result.metadata["input_resolution"] = {
        "original_input_keys": ["file_path"],
        "resolved_input_keys": ["file_path"],
        "source_step_id": None,
        "source_available": False,
        "source_output_summary": None,
        "missing_required_inputs": ["text"],
        "unresolved_input_chain": True,
    }
    validation = ResultValidator().validate_execution_result(result)

    workflow._stage_8_logging(plan.task_card, plan, [result], [validation], [])

    payload = json.loads((tmp_path / "openpilot.jsonl").read_text(encoding="utf-8").splitlines()[-1])["payload"]
    assert payload["planned_steps"][0]["title"]
    assert payload["tool_selections"][0]["tool"] == "llm_summarizer"
    assert payload["tool_selections"][0]["input_keys"] == ["file_path"]
    assert payload["step_results"][0]["input_resolution"]["missing_required_inputs"] == ["text"]
    assert payload["step_results"][0]["input_resolution"]["unresolved_input_chain"] is True


def test_missing_llm_text_precheck_logs_tool_execution_result(tmp_path):
    workflow = WorkflowExecutor(DummyLLMClient(), console=Console(file=open(os.devnull, "w")))
    workflow.logger = OpenPilotLogger(tmp_path / "openpilot.jsonl")
    selection = ToolSelection(
        step_id="step-2",
        tool_name="llm_summarizer",
        reason=SelectionReason.CAPABILITY_MATCH,
        confidence=0.9,
        input_params={"file_path": str(tmp_path)},
    )
    orchestration_plan = ToolOrchestrationPlan(
        plan_id="plan-1",
        goal="test",
        tool_selections=[selection],
    )

    results = workflow._stage_5_execution(orchestration_plan)

    assert results[0].success is False
    assert results[0].error.error_type == "MissingRequiredInput"
    assert results[0].metadata["input_resolution"]["missing_required_inputs"] == ["text"]
    payloads = [
        json.loads(line)
        for line in (tmp_path / "openpilot.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    event = payloads[-1]
    assert event["event_type"] == "tool_execution_result"
    assert event["payload"]["error"]["type"] == "MissingRequiredInput"
    assert event["payload"]["input_resolution"]["missing_required_inputs"] == ["text"]


def test_missing_source_output_is_visible_in_input_resolution(tmp_path):
    workflow = WorkflowExecutor(DummyLLMClient(), console=Console(file=open(os.devnull, "w")))
    selection = ToolSelection(
        step_id="step-3",
        tool_name="llm_summarizer",
        reason=SelectionReason.CAPABILITY_MATCH,
        confidence=0.9,
        input_params={"source_step_id": "step-2"},
    )

    resolved, input_resolution = workflow._resolve_selection_with_diagnostics(selection, {})

    assert "text" not in resolved.input_params
    assert input_resolution["source_step_id"] == "step-2"
    assert input_resolution["source_available"] is False
    assert input_resolution["missing_required_inputs"] == ["text"]
    assert input_resolution["unresolved_input_chain"] is True


def test_workflow_executor_accepts_openpilot_log_file(tmp_path):
    log_file = tmp_path / "openpilot.jsonl"
    workflow = WorkflowExecutor(
        DummyLLMClient(),
        console=Console(file=open(os.devnull, "w")),
        log_file=log_file,
    )

    workflow.logger.log_event("probe", {"ok": True}, session_id="test", turn_id=1)

    assert log_file.exists()
    assert json.loads(log_file.read_text(encoding="utf-8").splitlines()[-1])["event_type"] == "probe"
    assert not (tmp_path / "workflow.jsonl").exists()


def test_run_startup_log_clear_truncates_selected_log(tmp_path):
    log_file = tmp_path / "openpilot.jsonl"
    log_file.write_text("old event\n", encoding="utf-8")

    _clear_log_file(log_file)

    assert log_file.read_text(encoding="utf-8") == ""


def test_llm_summary_body_not_printed_to_console(monkeypatch):
    output = StringIO()
    workflow = WorkflowExecutor(DummyLLMClient(), console=Console(file=output))
    workflow.logger = OpenPilotLogger(os.devnull)
    selection = ToolSelection(
        step_id="step-1",
        tool_name="llm_summarizer",
        reason=SelectionReason.CAPABILITY_MATCH,
        confidence=0.9,
        input_params={"text": "source text"},
    )
    orchestration_plan = ToolOrchestrationPlan(
        plan_id="plan-1",
        goal="test",
        tool_selections=[selection],
    )
    result = ExecutionResult(
        execution_id="exec-1",
        tool_name="llm_summarizer",
        step_id="step-1",
        status=ExecutionStatus.SUCCESS,
        success=True,
        started_at=datetime.now(),
        output={"summary": "SHOULD_NOT_BE_PRINTED"},
    )
    monkeypatch.setattr(workflow.executor, "execute_single", lambda _selection: result)

    workflow._stage_5_execution(orchestration_plan)

    assert "SHOULD_NOT_BE_PRINTED" not in output.getvalue()


def test_empty_llm_summary_retries_once_and_uses_retry_output(tmp_path):
    workflow = WorkflowExecutor(DummyLLMClient(), console=Console(file=open(os.devnull, "w")))
    workflow.logger = OpenPilotLogger(tmp_path / "openpilot.jsonl")
    workflow.workflow_session_id = "test-session"
    workflow.executor = EmptyThenSummaryExecutor()
    selection = ToolSelection(
        step_id="step-3",
        tool_name="llm_summarizer",
        reason=SelectionReason.CAPABILITY_MATCH,
        confidence=0.9,
        input_params={"text": "source text"},
    )
    orchestration_plan = ToolOrchestrationPlan(
        plan_id="plan-1",
        goal="test",
        tool_selections=[selection],
    )

    results = workflow._stage_5_execution(orchestration_plan)

    assert workflow.executor.calls == 2
    assert results[0].success is True
    assert results[0].output["summary"] == "non-empty retry summary"
    events = [
        json.loads(line)
        for line in (tmp_path / "openpilot.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(event["event_type"] == "empty_output_retry" for event in events)


def test_repeated_empty_llm_summary_fails_as_empty_output(tmp_path):
    workflow = WorkflowExecutor(DummyLLMClient(), console=Console(file=open(os.devnull, "w")))
    workflow.logger = OpenPilotLogger(tmp_path / "openpilot.jsonl")
    workflow.executor = AlwaysEmptyExecutor()
    selection = ToolSelection(
        step_id="step-3",
        tool_name="llm_summarizer",
        reason=SelectionReason.CAPABILITY_MATCH,
        confidence=0.9,
        input_params={"text": "source text"},
    )
    orchestration_plan = ToolOrchestrationPlan(
        plan_id="plan-1",
        goal="test",
        tool_selections=[selection],
    )

    results = workflow._stage_5_execution(orchestration_plan)

    assert workflow.executor.calls == 2
    assert results[0].success is False
    assert results[0].error.error_type == "EmptyLLMOutput"


def test_validation_rule_schema_alias_has_no_import_warning():
    completed = subprocess.run(
        [
            sys.executable,
            "-W",
            "error::UserWarning",
            "-c",
            "from openpilot.validation_models import ValidationRule",
        ],
        check=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        text=True,
    )
    assert completed.returncode == 0

    rule = ValidationRule(
        rule_id="schema-rule",
        name="schema rule",
        validation_type=ValidationType.SCHEMA,
        severity=ValidationSeverity.ERROR,
        schema={"type": "object"},
        description="validates schema",
    )
    assert rule.json_schema == {"type": "object"}
    assert rule.schema == {"type": "object"}
