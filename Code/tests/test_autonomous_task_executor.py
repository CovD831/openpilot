from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from autonomous_iteration.models import EvaluationResult, IterationResult
from autonomous_iteration.improvement_context import ImprovementContextHelper
from autonomous_iteration.task_models import TaskExecutionResult, TaskStatus
from autonomous_iteration.task_executor import AutonomousTaskExecutor
from core.openpilot_log import OpenPilotLogger
from autonomous_iteration.intelligent_autopilot import IntelligentAutopilot
from metadata import (
    FailureMetadata,
    FileArtifactMetadata,
    ResultStatus,
    TaskResultMetadata,
    TextArtifactMetadata,
    ToolExecutionEnvelopeMetadata,
    ToolInputMetadata,
    ToolResultMetadata,
    payload_to_artifact,
)


class FakeRuntime:
    def __init__(self, tmp_path: Path, *, code_results: list[dict] | None = None) -> None:
        self.tmp_path = tmp_path
        self.enhanced_ui = None
        self.session_id = "session"
        self.logger = OpenPilotLogger(tmp_path / "task_executor.jsonl")
        self.calls: list[dict] = []
        self.code_results = list(code_results or [])
        self.environment_success = True
        self.review_result = {"success": True, "result": {"approved": True}}
        self.review_results: list[dict] = []
        self.readme_result = {"success": True, "result": {"file_path": str(tmp_path / "README.md")}}
        self.write_result = {"success": True, "result": {"file_path": str(tmp_path / "app.py")}}
        self._project_improvement_actions: list[str] = []
        self.improvement_context = ImprovementContextHelper(
            environment_context_getter=lambda path: {"run_command": "python app.py"} if path else {},
            logger=self.logger,
            session_id_getter=lambda: self.session_id,
        )

    def _select_iteration_target_file(self, written_files, actions):
        return self.improvement_context.select_iteration_target_file(written_files, actions)

    def _dashboard_stage_id(self, stage_key):
        return None

    def _set_dashboard_task_status(self, task_id, status):
        return None

    def _short_dashboard_text(self, value, limit=140):
        text = " ".join(str(value or "").split())
        return text if len(text) <= limit else text[: limit - 3] + "..."

    def _build_prompt_context(self, **kwargs):
        return self.improvement_context.build_prompt_context(**kwargs)

    def _prompt_context_layer_summary(self, prompt_context):
        return self.improvement_context.prompt_context_layer_summary(prompt_context)

    def _readme_environment_context(self, environment_payload):
        return {"dependencies": ", ".join(environment_payload.get("detected_packages", []))}

    def _sync_project_environment(self, **kwargs):
        self.calls.append({"tool": "project_environment_tool", **kwargs})
        if not self.environment_success:
            return _tool_envelope("project_environment_tool", {"success": False, "error": "env failed"}, kwargs.get("input_metadata"))
        return _tool_envelope(
            "project_environment_tool",
            {
                "success": True,
                "result": {
                "run_command": "python app.py",
                "setup_commands": ["python -m venv .venv"],
                "detected_packages": ["rich"],
            },
            },
            kwargs.get("input_metadata"),
        )

    def _execute_fast_tool(self, **kwargs):
        self.calls.append(kwargs)
        tool_name = kwargs["tool_name"]
        if tool_name == "code_generator":
            if self.code_results:
                return _tool_envelope(tool_name, self.code_results.pop(0), kwargs.get("input_metadata"))
            return _tool_envelope(tool_name, {"success": True, "result": {"code": "print('improved')\n"}, "status": "completed"}, kwargs.get("input_metadata"))
        if tool_name == "file_writer":
            return _tool_envelope(tool_name, self.write_result, kwargs.get("input_metadata"))
        if tool_name == "code_reviewer":
            if self.review_results:
                return _tool_envelope(tool_name, self.review_results.pop(0), kwargs.get("input_metadata"))
            return _tool_envelope(tool_name, self.review_result, kwargs.get("input_metadata"))
        if tool_name == "readme_tool":
            return _tool_envelope(tool_name, self.readme_result, kwargs.get("input_metadata"))
        raise AssertionError(f"unexpected tool {tool_name}")


def _tool_envelope(tool_name: str, data: dict, input_metadata: ToolInputMetadata | None = None) -> ToolExecutionEnvelopeMetadata:
    success = bool(data.get("success"))
    result_payload = data.get("result")
    output_metadata = (
        ToolResultMetadata(tool_name=tool_name, status=ResultStatus.SUCCESS, result=payload_to_artifact(tool_name, result_payload, input_metadata))
        if success
        else None
    )
    failure = None if success else FailureMetadata(error_type=str(data.get("error_type") or "ToolError"), error_message=str(data.get("error") or f"{tool_name} failed"))
    return ToolExecutionEnvelopeMetadata(
        tool_name=tool_name,
        step_id=str(data.get("step_id") or tool_name),
        status=ResultStatus.SUCCESS if success else (ResultStatus.TIMEOUT if str(data.get("status")) == "timeout" else ResultStatus.FAIL),
        success=success,
        input_metadata=input_metadata or ToolInputMetadata(tool_name=tool_name),
        output_metadata=output_metadata,
        failure=failure,
        timeout_override=data.get("timeout_override"),
    )


def test_runtime_applies_project_command_context_to_command_metadata(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    runtime = object.__new__(IntelligentAutopilot)
    runtime._project_environments = {
        str(project.resolve()): {
            "project_path": str(project),
            "command_cwd": str(project),
            "command_env": {"VIRTUAL_ENV": str(project / ".venv"), "PATH": f"{project / '.venv' / 'bin'}:/usr/bin"},
            "python_command": str(project / ".venv" / "bin" / "python"),
            "pip_command": str(project / ".venv" / "bin" / "pip"),
        }
    }

    metadata = ToolInputMetadata.from_mapping(
        "command_executor",
        {
            "command": "python main.py",
            "cwd": str(project),
            "env": {"PYGAME_HIDE_SUPPORT_PROMPT": "1", "PATH": "/usr/bin"},
        },
    )

    updated = runtime._apply_project_command_context("command_executor", metadata)

    assert updated.cwd == str(project)
    assert updated.command == shlex.join([str(project / ".venv" / "bin" / "python"), "main.py"])
    assert updated.env["VIRTUAL_ENV"] == str(project / ".venv")
    assert updated.env["PATH"].startswith(str(project / ".venv" / "bin"))
    assert updated.env["PYGAME_HIDE_SUPPORT_PROMPT"] == "1"


def test_collect_written_files_reads_typed_tool_result_metadata(tmp_path) -> None:
    runtime = object.__new__(IntelligentAutopilot)
    output = FileArtifactMetadata(file_path=str(tmp_path / "app.py"))
    result = TaskExecutionResult(
        task_id="task",
        status=TaskStatus.COMPLETED,
        result_metadata=TaskResultMetadata(
            task_id="task",
            status=ResultStatus.SUCCESS,
            result=TextArtifactMetadata(
                content="completed",
                attributes={
                    "tool_calls": [
                        {
                            "tool": "file_writer",
                            "success": True,
                            "result": output,
                            "input_metadata": {"file_path": str(tmp_path / "fallback.py")},
                        }
                    ]
                },
            ),
        ),
    )

    assert runtime._collect_written_files([result]) == [str(tmp_path / "app.py")]


def test_collect_written_files_falls_back_to_input_metadata_file_path(tmp_path) -> None:
    runtime = object.__new__(IntelligentAutopilot)
    result = TaskExecutionResult(
        task_id="task",
        status=TaskStatus.COMPLETED,
        result_metadata=TaskResultMetadata(
            task_id="task",
            status=ResultStatus.SUCCESS,
            result=TextArtifactMetadata(
                content="completed",
                attributes={
                    "tool_calls": [
                        {
                            "tool": "file_writer",
                            "success": True,
                            "result": {},
                            "input_metadata": {"file_path": str(tmp_path / "fallback.py")},
                        }
                    ]
                },
            ),
        ),
    )

    assert runtime._collect_written_files([result]) == [str(tmp_path / "fallback.py")]


class FakeLLM:
    pass


def _evaluation() -> EvaluationResult:
    return EvaluationResult(
        validation_passed=True,
        runnable=True,
        has_blocking_bugs=False,
        summary="ok",
    )


def test_autonomous_task_executor_success_path_and_logs(tmp_path) -> None:
    app = tmp_path / "app.py"
    app.write_text("print('old')\n", encoding="utf-8")
    runtime = FakeRuntime(tmp_path)
    executor = AutonomousTaskExecutor(runtime)

    result = executor.execute_improvement(
        goal="Improve project",
        project_path=tmp_path,
        written_files=[str(app)],
        run_command="",
        readme_path=tmp_path / "README.md",
        iteration=1,
        evaluation=_evaluation(),
        actions=["Improve app.py"],
        improvement_report={"summary": "report"},
        is_repair=False,
    )

    assert result.success is True
    assert result.failed_tool is None
    assert [call["tool_name"] if "tool_name" in call else call["tool"] for call in runtime.calls] == [
        "code_generator",
        "file_writer",
        "project_environment_tool",
        "code_reviewer",
        "readme_tool",
    ]
    events = [json.loads(line) for line in (tmp_path / "task_executor.jsonl").read_text(encoding="utf-8").splitlines()]
    payloads = [event["payload"] for event in events]
    assert any(payload["source_type"] == "agent" and payload["source_name"] == "autonomous_iteration.task_executor" for payload in payloads)


def test_autonomous_task_executor_routes_readme_task_to_documentation_writer(tmp_path) -> None:
    app = tmp_path / "app.py"
    readme = tmp_path / "README.md"
    app.write_text("print('old')\n", encoding="utf-8")
    readme.write_text("# Game\n", encoding="utf-8")
    runtime = FakeRuntime(tmp_path)

    result = AutonomousTaskExecutor(runtime).execute_improvement(
        goal="Improve project",
        project_path=tmp_path,
        written_files=[str(app), str(readme)],
        run_command="",
        readme_path=readme,
        iteration=1,
        evaluation=_evaluation(),
        actions=["在README.md中添加完整的控制键说明和游戏规则简介"],
        improvement_report={
            "summary": "report",
            "must_implement_next": ["README包含完整的控制键说明"],
            "designed_tasks": [
                {
                    "description": "在README.md中添加完整的控制键说明和游戏规则简介",
                    "target_files": [str(readme)],
                    "acceptance_criteria": ["README包含完整的控制键说明"],
                }
            ],
        },
        is_repair=False,
    )

    assert result.success is True
    tool_names = [call["tool_name"] if "tool_name" in call else call["tool"] for call in runtime.calls]
    assert tool_names == ["file_writer"]
    assert runtime.calls[0]["input_metadata"].file_path == str(readme)


def test_autonomous_task_executor_retries_full_compact_surgical_on_timeout(tmp_path) -> None:
    app = tmp_path / "app.py"
    app.write_text("print('old')\n", encoding="utf-8")
    runtime = FakeRuntime(
        tmp_path,
        code_results=[
            {"success": False, "error": "timeout", "error_type": "timeout", "status": "timeout", "timeout_override": 1},
            {"success": False, "error": "timeout", "error_type": "timeout", "status": "timeout", "timeout_override": 1},
            {"success": True, "result": {"code": "print('surgical')\n"}, "status": "completed"},
        ],
    )

    result = AutonomousTaskExecutor(runtime).execute_improvement(
        goal="Improve project",
        project_path=tmp_path,
        written_files=[str(app)],
        run_command="",
        readme_path=tmp_path / "README.md",
        iteration=2,
        evaluation=_evaluation(),
        actions=["Improve app.py"],
        improvement_report={},
        is_repair=False,
    )

    assert result.success is True
    assert [item["mode"] for item in result.retry_history] == ["full", "compact", "surgical"]
    assert result.retry_attempted is True


def test_autonomous_task_executor_retries_product_intent_reviewer_rejection(tmp_path) -> None:
    app = tmp_path / "app.py"
    app.write_text("print('old')\n", encoding="utf-8")
    runtime = FakeRuntime(
        tmp_path,
        code_results=[
            {"success": True, "result": {"code": "import curses\n\ndef main(stdscr):\n    pass\n"}, "status": "completed"},
            {"success": True, "result": {"code": "import pygame\npygame.init()\n"}, "status": "completed"},
        ],
    )
    runtime.review_results = [
        {
            "success": True,
            "result": {
                "approved": False,
                "warnings": ["Product intent drift: standalone GUI intent was replaced by terminal-only interaction."],
                "suggestions": ["Regenerate while preserving product intent."],
                "rejection_categories": ["product_intent_drift"],
            },
        },
        {"success": True, "result": {"approved": True, "warnings": [], "suggestions": [], "rejection_categories": []}},
    ]

    result = AutonomousTaskExecutor(runtime).execute_improvement(
        goal="Build an interactive visual game",
        project_path=tmp_path,
        written_files=[str(app)],
        run_command="",
        readme_path=tmp_path / "README.md",
        iteration=1,
        evaluation=_evaluation(),
        actions=["Fix runtime issue without changing product intent."],
        improvement_report={},
        is_repair=True,
    )

    assert result.success is True
    assert result.retry_attempted is True
    assert any(item["mode"] == "product_intent_retry" for item in result.retry_history)
    code_retry_calls = [
        call for call in runtime.calls
        if call.get("tool_name") == "code_generator" and call["input_metadata"].prompt_context.get("reviewer_rejection")
    ]
    assert code_retry_calls


@pytest.mark.parametrize(
    ("setup", "failed_tool", "reason_part"),
    [
        (lambda runtime, app: app.unlink(), "task_file_resolver", "No related project file"),
        (lambda runtime, app: runtime.code_results.append({"success": True, "result": {"code": app.read_text(encoding="utf-8")}}), "code_generator", "did not change"),
        (lambda runtime, app: runtime.code_results.append({"success": True, "result": {"code": "def broken(:\n"}}), "code_generator", "syntax error"),
        (lambda runtime, app: setattr(runtime, "write_result", {"success": False, "error": "write failed"}), "file_writer", "write failed"),
        (lambda runtime, app: setattr(runtime, "review_result", {"success": True, "result": {"approved": False, "suggestions": ["not good"]}}), "code_reviewer", "not good"),
        (lambda runtime, app: setattr(runtime, "readme_result", {"success": False, "error": "readme failed"}), "readme_tool", "readme failed"),
    ],
)
def test_autonomous_task_executor_failure_semantics(tmp_path, setup, failed_tool, reason_part) -> None:
    app = tmp_path / "app.py"
    app.write_text("print('old')\n", encoding="utf-8")
    runtime = FakeRuntime(tmp_path)
    setup(runtime, app)

    result = AutonomousTaskExecutor(runtime).execute_improvement(
        goal="Improve project",
        project_path=tmp_path,
        written_files=[str(app)],
        run_command="",
        readme_path=tmp_path / "README.md",
        iteration=1,
        evaluation=_evaluation(),
        actions=["Improve app.py"],
        improvement_report={},
        is_repair=False,
    )

    assert result.success is False
    assert result.failure_stage == "Task Executor"
    assert result.failed_tool == failed_tool
    assert reason_part in (result.failure_reason or "")


def test_autonomous_task_executor_environment_failure_stage(tmp_path) -> None:
    app = tmp_path / "app.py"
    app.write_text("print('old')\n", encoding="utf-8")
    runtime = FakeRuntime(tmp_path)
    runtime.environment_success = False

    result = AutonomousTaskExecutor(runtime).execute_improvement(
        goal="Improve project",
        project_path=tmp_path,
        written_files=[str(app)],
        run_command="",
        readme_path=tmp_path / "README.md",
        iteration=1,
        evaluation=_evaluation(),
        actions=["Improve app.py"],
        improvement_report={},
        is_repair=False,
    )

    assert result.success is False
    assert result.failure_stage == "Environment Setup"
    assert result.failed_tool == "project_environment_tool"
    assert "env failed" in (result.failure_reason or "")


def test_autonomous_task_executor_resolver_failure_for_missing_target(tmp_path) -> None:
    target = tmp_path / "missing.py"
    runtime = FakeRuntime(tmp_path)

    result = AutonomousTaskExecutor(runtime).execute_improvement(
        goal="Improve project",
        project_path=tmp_path,
        written_files=[str(target)],
        run_command="",
        readme_path=tmp_path / "README.md",
        iteration=1,
        evaluation=_evaluation(),
        actions=["Improve missing.py"],
        improvement_report={},
        is_repair=False,
    )

    assert result.success is False
    assert result.failed_tool == "task_file_resolver"
    assert "No related project file" in (result.failure_reason or "")


def test_intelligent_autopilot_apply_project_improvement_proxy_uses_task_executor(tmp_path) -> None:
    class FakeExecutor:
        def execute_improvement(self, **kwargs):
            return IterationResult(
                iteration=kwargs["iteration"],
                validation_passed=True,
                completed_successful_iteration=False,
                applied_actions=kwargs["actions"],
                changed_files=[],
                success=True,
            )

    autopilot = IntelligentAutopilot(FakeLLM(), log_file=tmp_path / "autopilot.jsonl")
    autopilot.autonomous_task_executor = FakeExecutor()

    result = autopilot._apply_project_improvement(
        goal="Improve project",
        project_path=tmp_path,
        written_files=[str(tmp_path / "app.py")],
        run_command="",
        readme_path=tmp_path / "README.md",
        iteration=3,
        evaluation=_evaluation(),
        actions=["Improve app.py"],
        improvement_report={},
    )

    assert result.success is True
    assert result.iteration == 3
