from __future__ import annotations

import json
from types import SimpleNamespace

from execution.task_models import Task, TaskExecutionContext, TaskExecutionResult, TaskStatus
from core.openpilot_log import OpenPilotLogger
from execution.agents.tool_planning_executor import ToolPlanningTaskExecutor
from execution.intelligent_autopilot import IntelligentAutopilot
from execution.tool_io import ExecutionToolIO


class FakeLLM:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        if isinstance(self.payload, str):
            return SimpleNamespace(parsed_json=None, content=self.payload)
        return SimpleNamespace(parsed_json=self.payload, content=json.dumps(self.payload))


class FakeToolRegistry:
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
                output={"code": "print('ok')", "language": "python"},
                error=None,
                execution_time_ms=10,
            )
        if selection.tool_name == "file_writer":
            return SimpleNamespace(
                success=True,
                output={"file_path": selection.input_params["file_path"], "content": selection.input_params["content"]},
                error=None,
                execution_time_ms=5,
            )
        return SimpleNamespace(success=False, output=None, error=SimpleNamespace(error_message="unknown tool"), execution_time_ms=1)


class FakeRuntime:
    def __init__(self, tmp_path, payload) -> None:
        self.session_id = "session"
        self.logger = OpenPilotLogger(tmp_path / "tool_planning.jsonl")
        self.llm_client = FakeLLM(payload)
        self.tool_registry = FakeToolRegistry()
        self.tool_executor = FakeToolExecutor()
        self.enhanced_ui = None
        self.tool_io = ExecutionToolIO(self.logger, lambda: self.session_id)

    def _format_tools_for_llm(self, tools):
        return "No tools"

    def _resolve_chained_inputs(self, tool_name, input_params, last_output, last_code_output):
        return self.tool_io.resolve_chained_inputs(tool_name, input_params, last_output, last_code_output)

    def _map_reason_to_enum(self, reason_text):
        return self.tool_io.map_reason_to_enum(reason_text)

    def _sanitize_tool_params(self, params):
        return self.tool_io.sanitize_tool_params(params)


def _context(task: Task) -> TaskExecutionContext:
    return TaskExecutionContext(task=task, parent_context={"goal": "build app"}, shared_state={}, execution_history=[])


def test_tool_planning_executor_success_and_chained_file_writer(tmp_path) -> None:
    task = Task(id="task", description="Generate and write app")
    runtime = FakeRuntime(
        tmp_path,
        {
            "tool_calls": [
                {"tool_name": "code_generator", "reason": "generate code", "input_params": {"task_description": "make app"}},
                {"tool_name": "file_writer", "reason": "write file", "input_params": {"file_path": "app.py"}},
            ]
        },
    )
    executor = ToolPlanningTaskExecutor(runtime)

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    assert result.result["all_tools_succeeded"] is True
    assert result.result["tool_calls"][1]["params"]["content"] == "print('ok')"
    assert runtime.tool_executor.selections[1].input_params == {"file_path": "app.py", "content": "print('ok')"}
    payloads = [
        json.loads(line)["payload"]
        for line in (tmp_path / "tool_planning.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(payload.get("source_type") == "agent" for payload in payloads)
    assert any(payload.get("source_name") == "execution.agents.tool_planning_executor" for payload in payloads)


def test_tool_planning_executor_invalid_or_empty_plan_returns_failed_result(tmp_path) -> None:
    task = Task(id="task", description="Do impossible thing")
    executor = ToolPlanningTaskExecutor(FakeRuntime(tmp_path, {"tool_calls": []}))

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.FAILED
    assert result.error == "LLM generated empty tool plan"


def test_tool_planning_executor_bad_json_returns_failed_result(tmp_path) -> None:
    task = Task(id="task", description="Do impossible thing")
    executor = ToolPlanningTaskExecutor(FakeRuntime(tmp_path, "{bad-json"))

    result = executor.execute_task(task, _context(task))

    assert result.status == TaskStatus.FAILED
    assert "Failed to parse LLM response as JSON" in result.error


def test_intelligent_autopilot_execute_task_proxy_uses_tool_planning_agent(tmp_path) -> None:
    class FakeAgent:
        def execute_task(self, task, context):
            return TaskExecutionResult(task_id=task.id, status=TaskStatus.COMPLETED, result={"proxied": True}, duration=0.0)

    class MinimalLLM:
        pass

    autopilot = IntelligentAutopilot(MinimalLLM(), log_file=tmp_path / "autopilot.jsonl")
    autopilot.tool_planning_task_executor = FakeAgent()
    task = Task(id="task", description="Proxy task")

    result = autopilot._execute_task(task, _context(task))

    assert result.status == TaskStatus.COMPLETED
    assert result.result == {"proxied": True}
