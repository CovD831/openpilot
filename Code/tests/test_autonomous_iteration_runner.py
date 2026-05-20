from __future__ import annotations

from pathlib import Path

from autonomous_iteration.models import EvaluationResult, IterationResult
from autonomous_iteration.runner import AutonomousIterationRunner
from core.openpilot_log import OpenPilotLogger
from autonomous_iteration.intelligent_autopilot import IntelligentAutopilot
from metadata import FailureMetadata, ResultStatus, ToolExecutionEnvelopeMetadata, ToolInputMetadata, ToolResultMetadata, payload_to_artifact


class FakeIterationAgent:
    def __init__(self) -> None:
        self.callbacks_seen: set[str] = set()

    def run_project_pipeline(self, **kwargs):
        evaluation = EvaluationResult(
            validation_passed=True,
            runnable=True,
            has_blocking_bugs=False,
            summary="ok",
            run_command=kwargs["run_command"],
        )
        state = kwargs["read_project_state"](evaluation, 0)
        result = kwargs["apply_improvement"](1, evaluation, ["Improve app.py"], {"summary": "report"}, False)
        report = kwargs["analyze_improvements"](0, evaluation)
        kwargs["on_progress"]("context_loader", {"context": {"related_memories": [], "related_files": []}, "iteration": 0})
        self.callbacks_seen = {"read_project_state", "apply_improvement", "analyze_improvements", "on_progress"}
        return {
            "success": True,
            "partial_success": False,
            "completed_improvements": 1,
            "required_improvements": 1,
            "completed_iterations": 1,
            "required_iterations": 1,
            "attempts_used": 1,
            "max_iteration_attempts": 2,
            "validation": evaluation,
            "evaluation": evaluation,
            "evaluations": [evaluation],
            "iterations": [result],
            "improvement_report": report,
            "project_state": state,
            "project_states": [state],
            "iteration_goals": [],
            "designed_tasks": [],
            "mind_notes": [],
            "autonomous_iteration": None,
            "failure_stage": None,
            "failed_iteration": None,
            "failed_tool": None,
            "failure_reason": None,
            "retry_attempted": False,
            "retry_history": [],
            "last_successful_iteration": 1,
            "remaining_goals": [],
        }


class FakeAutopilot:
    def __init__(self, tmp_path: Path, environment_success: bool = True) -> None:
        self.enable_iterative_improvement = True
        self.required_successful_improvements = 1
        self.max_iteration_attempts = 2
        self.enhanced_ui = None
        self.session_id = "session"
        self.logger = OpenPilotLogger(tmp_path / "runner.jsonl")
        self.iterative_improvement = FakeIterationAgent()
        self.memory_store = None
        self.progress_events: list[str] = []
        self.environment_success = environment_success

    def _resolve_project_improvement_iterations(self, goal, project_path) -> bool:
        return True

    def _sync_project_environment(self, **kwargs):
        if not self.environment_success:
            return _tool_envelope("project_environment_tool", {"success": False, "error": "env failed"}, kwargs.get("input_metadata"))
        return _tool_envelope("project_environment_tool", {"success": True, "result": {"run_command": "python app.py"}}, kwargs.get("input_metadata"))

    def _handle_iteration_progress(self, event, payload) -> None:
        self.progress_events.append(event)

    def _apply_project_improvement(self, **kwargs) -> IterationResult:
        return IterationResult(
            iteration=kwargs["iteration"],
            validation_passed=True,
            completed_successful_iteration=True,
            applied_actions=kwargs["actions"],
            changed_files=[str(kwargs["project_path"] / "app.py")],
            success=True,
        )

    def _analyze_project_improvements(self, **kwargs) -> dict:
        return {"summary": "Need polish."}

    def _execute_fast_tool(self, **kwargs):
        input_metadata = kwargs["input_metadata"]
        params = input_metadata.to_params() if hasattr(input_metadata, "to_params") else input_metadata
        return _tool_envelope(
            "project_state_reader",
            {
                "success": True,
                "result": {
                "project_path": params["project_path"],
                "written_files": params["written_files"],
            },
            },
            input_metadata,
        )

    def _dashboard_stage_id(self, stage_key):
        return None


def _tool_envelope(tool_name: str, data: dict, input_metadata: ToolInputMetadata | None = None) -> ToolExecutionEnvelopeMetadata:
    success = bool(data.get("success"))
    output_metadata = (
        ToolResultMetadata(tool_name=tool_name, status=ResultStatus.SUCCESS, result=payload_to_artifact(tool_name, data.get("result"), input_metadata))
        if success
        else None
    )
    failure = None if success else FailureMetadata(error_type="ToolError", error_message=str(data.get("error") or f"{tool_name} failed"))
    return ToolExecutionEnvelopeMetadata(
        tool_name=tool_name,
        step_id=tool_name,
        status=ResultStatus.SUCCESS if success else ResultStatus.FAIL,
        success=success,
        input_metadata=input_metadata or ToolInputMetadata(tool_name=tool_name),
        output_metadata=output_metadata,
        failure=failure,
    )


class FakeLLM:
    pass


def test_autonomous_iteration_runner_environment_failure(tmp_path) -> None:
    runner = AutonomousIterationRunner(FakeAutopilot(tmp_path, environment_success=False))

    result = runner.run(
        goal="Improve project",
        project_path=tmp_path,
        written_files=[str(tmp_path / "app.py")],
    )

    assert result["success"] is False
    assert result["failure_stage"] == "Environment Setup"
    assert result["failed_tool"] == "project_environment_tool"
    assert result["validation"].validation_errors == ["env failed"]


def test_autonomous_iteration_runner_success_callbacks_and_shape(tmp_path) -> None:
    autopilot = FakeAutopilot(tmp_path)
    runner = AutonomousIterationRunner(autopilot)

    result = runner.run(
        goal="Improve project",
        project_path=tmp_path,
        written_files=[str(tmp_path / "app.py")],
    )

    assert result["success"] is True
    assert result["validation"].validation_passed is True
    assert result["iterations"][0].success is True
    assert autopilot.iterative_improvement.callbacks_seen == {
        "read_project_state",
        "apply_improvement",
        "analyze_improvements",
        "on_progress",
    }
    assert autopilot.progress_events == ["context_loader"]


def test_intelligent_autopilot_iterative_improvement_proxy_uses_runner(tmp_path) -> None:
    class FakeRunner:
        def run(self, **kwargs):
            return {"success": True, "goal": kwargs["goal"]}

    autopilot = IntelligentAutopilot(FakeLLM(), log_file=tmp_path / "autopilot.jsonl")
    autopilot.autonomous_iteration_runner = FakeRunner()

    result = autopilot._run_iterative_improvement(
        goal="Improve project",
        project_path=tmp_path,
        written_files=[str(tmp_path / "app.py")],
    )

    assert result == {"success": True, "goal": "Improve project"}
