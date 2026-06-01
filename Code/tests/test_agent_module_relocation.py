from __future__ import annotations

import importlib
import json
import sys

import pytest

from autonomous_iteration.models import EvaluationResult
from autonomous_iteration.agents.iteration_agent import AutonomousIterationAgent
from autonomous_iteration.agents.project_evaluator import ProjectEvaluatorAgent
from core.openpilot_log import OpenPilotLogger
from autonomous_iteration.agents.execution_orchestrator import AgentOrchestrator
from autonomous_iteration.agents.execution_task_decomposer import TaskDecomposer
from autonomous_iteration.intelligent_autopilot import IntelligentAutopilot
from autonomous_iteration.task_models import TaskDecompositionResult


class FakeLLM:
    pass


class FakeDecompositionLLM:
    def complete(self, _request):
        return type(
            "Response",
            (),
            {
                "parsed_json": {
                    "rationale": "demo",
                    "subtasks": [
                        {
                            "description": "Plan the assistant features and outline file layout.",
                            "priority": "high",
                            "estimated_effort": 0.5,
                            "dependencies": [],
                            "tags": [],
                        },
                        {
                            "description": "Implement the assistant script in '/tmp/assistant'.",
                            "priority": "high",
                            "estimated_effort": 2.0,
                            "dependencies": [0],
                            "tags": [],
                        },
                        {
                            "description": "Validate the script by running basic tests.",
                            "priority": "medium",
                            "estimated_effort": 0.5,
                            "dependencies": [1],
                            "tags": [],
                        },
                    ],
                },
                "content": "",
            },
        )()


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

    assert importlib.import_module("autonomous_iteration.task_models").TaskDecompositionResult is TaskDecompositionResult
    assert importlib.import_module("autonomous_iteration.models").EvaluationResult is EvaluationResult
    assert importlib.import_module("autonomous_iteration.agents.execution_task_decomposer").TaskDecomposer is TaskDecomposer
    assert importlib.import_module("autonomous_iteration.agents.execution_orchestrator").AgentOrchestrator is AgentOrchestrator
    assert importlib.import_module("autonomous_iteration.agents.project_evaluator").ProjectEvaluatorAgent is ProjectEvaluatorAgent
    assert importlib.import_module("autonomous_iteration.agents.iteration_agent").AutonomousIterationAgent is AutonomousIterationAgent

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("agents")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(".".join(["agents", "task_models"]))
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("execution")


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
    assert "autonomous_iteration.agents.execution_task_decomposer" in agent_sources
    assert "autonomous_iteration.agents.project_evaluator" in agent_sources
    assert "autonomous_iteration.agents.iteration_agent" in agent_sources


def test_simple_code_artifact_decomposition_skips_planning_only_subtasks() -> None:
    decomposer = TaskDecomposer(FakeDecompositionLLM())

    result = decomposer.decompose("帮我在'/tmp/assistant'中做一个个人数字助手")

    descriptions = [task.description for task in result.subtasks]
    assert descriptions == [
        "Implement the assistant script in '/tmp/assistant'.",
        "Validate the script by running basic tests.",
    ]
    assert result.subtasks[0].dependencies == []
    assert result.subtasks[1].dependencies == [result.subtasks[0].id]


def test_simple_code_artifact_compaction_skips_chinese_planning_only_subtasks() -> None:
    decomposer = TaskDecomposer(FakeLLM())
    subtasks = [
        {
            "description": "设计个人数字助手的功能并规划文件结构。",
            "dependencies": [],
        },
        {
            "description": "在指定目录中实现个人数字助手脚本。",
            "dependencies": [0],
        },
        {
            "description": "运行脚本并验证基本命令。",
            "dependencies": [1],
        },
    ]

    assert decomposer._is_simple_code_artifact("帮我在'/tmp/assistant'中做一个个人数字助手")
    compact = decomposer._compact_simple_code_subtasks(subtasks)

    assert [subtask["description"] for subtask in compact] == [
        "在指定目录中实现个人数字助手脚本。",
        "运行脚本并验证基本命令。",
    ]
    assert compact[0]["dependencies"] == []
    assert compact[1]["dependencies"] == [0]


def test_planning_subtask_does_not_treat_implementation_approach_as_execution() -> None:
    decomposer = TaskDecomposer(FakeLLM())

    assert decomposer._is_planning_subtask(
        "Define requirements and design the assistant, then choose a suitable implementation approach."
    )
