from __future__ import annotations

import importlib
import json
import sys

import pytest

from autonomous_iteration.models import EvaluationResult
from autonomous_iteration.agents.iteration_agent import AutonomousIterationAgent
from autonomous_iteration.agents.project_evaluator import ProjectEvaluatorAgent
from core.openpilot_log import OpenPilotLogger
from execution.agents.orchestrator import AgentOrchestrator
from execution.agents.task_decomposer import TaskDecomposer
from execution.intelligent_autopilot import IntelligentAutopilot
from execution.task_models import TaskDecompositionResult


class FakeLLM:
    pass


class PassingEvaluator:
    llm_client = None

    def evaluate_project(self, **kwargs):
        return EvaluationResult(
            validation_passed=True,
            runnable=True,
            has_blocking_bugs=False,
            summary="ok",
            run_command="python app.py",
        )


def test_module_owned_paths_replace_global_agents_package() -> None:
    sys.modules.pop("agents", None)
    sys.modules.pop(".".join(["agents", "task_models"]), None)

    assert importlib.import_module("execution.task_models").TaskDecompositionResult is TaskDecompositionResult
    assert importlib.import_module("autonomous_iteration.models").EvaluationResult is EvaluationResult
    assert importlib.import_module("execution.agents.task_decomposer").TaskDecomposer is TaskDecomposer
    assert importlib.import_module("execution.agents.orchestrator").AgentOrchestrator is AgentOrchestrator
    assert importlib.import_module("autonomous_iteration.agents.project_evaluator").ProjectEvaluatorAgent is ProjectEvaluatorAgent
    assert importlib.import_module("autonomous_iteration.agents.iteration_agent").AutonomousIterationAgent is AutonomousIterationAgent

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("agents")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(".".join(["agents", "task_models"]))


def test_intelligent_autopilot_constructs_module_owned_agents(tmp_path) -> None:
    autopilot = IntelligentAutopilot(FakeLLM(), log_file=tmp_path / "autopilot.jsonl")

    assert isinstance(autopilot.task_decomposer, TaskDecomposer)
    assert isinstance(autopilot.orchestrator, AgentOrchestrator)
    assert isinstance(autopilot.project_evaluator, ProjectEvaluatorAgent)
    assert isinstance(autopilot.iterative_improvement, AutonomousIterationAgent)


def test_module_owned_agents_emit_structured_agent_logs(tmp_path) -> None:
    log_file = tmp_path / "agents.jsonl"
    logger = OpenPilotLogger(log_file)

    decomposer = TaskDecomposer(FakeLLM(), logger=logger, session_id_getter=lambda: "session")
    result = decomposer.decompose("Build a tiny script", context={"goal": "demo"})
    assert isinstance(result, TaskDecompositionResult)

    evaluator = ProjectEvaluatorAgent(logger=logger, session_id_getter=lambda: "session")
    missing = evaluator.evaluate_project(
        goal="Validate missing files",
        project_path=tmp_path,
        written_files=[str(tmp_path / "missing.py")],
    )
    assert missing.validation_passed is False

    agent = AutonomousIterationAgent(
        PassingEvaluator(),
        required_successful_improvements=0,
        max_iteration_attempts=1,
        logger=logger,
    )
    iteration_result = agent.run_project_pipeline(
        goal="No-op",
        project_path=tmp_path,
        written_files=[],
        apply_improvement=lambda *args, **kwargs: None,
    )
    assert iteration_result["success"] is True

    payloads = [
        json.loads(line)["payload"]
        for line in log_file.read_text(encoding="utf-8").splitlines()
    ]
    agent_sources = {
        payload["source_name"]
        for payload in payloads
        if payload.get("source_type") == "agent"
    }
    assert "execution.agents.task_decomposer" in agent_sources
    assert "autonomous_iteration.agents.project_evaluator" in agent_sources
    assert "autonomous_iteration.agents.iteration_agent" in agent_sources
