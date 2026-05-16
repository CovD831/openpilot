from __future__ import annotations

from pathlib import Path

from autonomous_iteration.models import EvaluationResult, IterationResult
from autonomous_iteration.runner import AutonomousIterationRunner
from core.openpilot_log import OpenPilotLogger
from execution.intelligent_autopilot import IntelligentAutopilot


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
            return {"success": False, "error": "env failed"}
        return {"success": True, "result": {"run_command": "python app.py"}}

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
        return {
            "success": True,
            "result": {
                "project_path": kwargs["input_params"]["project_path"],
                "written_files": kwargs["input_params"]["written_files"],
            },
        }

    def _dashboard_stage_id(self, stage_key):
        return None


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
