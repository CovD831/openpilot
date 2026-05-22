from __future__ import annotations

import json

from autonomous_iteration.models import DesignedImprovementTask
from autonomous_iteration.agents.context_loader import (
    DEFAULT_AUTONOMOUS_ITERATION_SYSTEM_PROMPT,
    ContextLoaderAgent,
)
from autonomous_iteration.agents.goal_maker import GoalMakerAgent
from autonomous_iteration.agents.task_decomposer import TaskDecomposerAgent
from autonomous_iteration.agents.task_designer import TaskDesignerAgent
from autonomous_iteration.pipeline import AutonomousIterationPipeline
from core.openpilot_log import OpenPilotLogger
from memory.agents.context_manager import ContextManagerAgent
from memory.agents.memory_vault_agent import MemoryVaultAgent
from memory.agents.project_manager_agent import ProjectManagerAgent
from memory.agents.virtual_environment_manager import VirtualEnvironmentManager
from memory.memory_models import MemoryRecord, MemoryType
from memory.memory_store import MemoryStore
from tools.task_classifier import task_classifier_executor
from metadata import TaskRouteMetadata, ToolInputMetadata
from tools.builtin_tools import register_builtin_tools
from tools.tool_executor import ToolExecutor
from tools.tool_selection import ToolSelection
from tools.tool_registry import ToolRegistry


def test_memory_agent_facades_import_and_context_rules() -> None:
    manager = ContextManagerAgent(max_agent_chars=40)
    user_text = "用户原话必须保持：不要改写 spacing   和标点。"
    agent_text = "agent-output-" * 20

    manager.add_user_message(user_text)
    manager.add_agent_message(agent_text)
    context = manager.output_context()

    assert context["messages"][0]["content"] == user_text
    assert context["messages"][1]["attributes"]["compressed"] is True
    assert context["messages"][1]["content"].startswith("[COMPRESSED AGENT HISTORY]")


def test_memory_vault_agent_remind_and_confidence_without_graph(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.save(
        MemoryRecord(
            id="pref-1",
            memory_type=MemoryType.PROJECT,
            content="User prefers robust modular agents.",
            tags=["agents"],
            confidence=0.9,
        )
    )
    agent = MemoryVaultAgent(memory_store=store)

    reminders = agent.remind("robust agents")
    confidence, answer = agent.confidence_evaluate("robust agents")

    assert reminders[0]["id"] == "pref-1"
    assert confidence > 0
    assert "robust modular agents" in answer


def test_project_manager_agent_sketch_shape(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("def main():\n    return 'instruction aligned'\n", encoding="utf-8")
    agent = ProjectManagerAgent(root_path=project)

    result = agent.update(project)
    sketch = json.loads((project / "sketch.json").read_text(encoding="utf-8"))

    assert result["file_count"] == 1
    assert "main.py" in sketch["files"]
    assert sketch["files"]["main.py"]["function_description"]
    assert sketch["files"]["main.py"]["semantic_info"]["kind"] == "keyword_fallback"
    assert agent.search("instruction aligned")[0]["name"] == "main.py"


def test_virtual_environment_manager_returns_context_without_creating_env(tmp_path) -> None:
    (tmp_path / "requirements.txt").write_text("rich\npydantic>=2\n", encoding="utf-8")
    manager = VirtualEnvironmentManager(tmp_path)

    context = manager.get_environment_context()

    assert context["env_name"] == ".venv"
    assert "python -m venv .venv" in context["setup_commands"]
    assert any("install rich pydantic>=2" in command for command in context["setup_commands"])
    assert not (tmp_path / ".venv").exists()


def test_autonomous_iteration_pipeline_stage_order_and_decomposition() -> None:
    captured_kwargs = {}

    class Builder:
        def build(self, query, **kwargs):
            captured_kwargs.update(kwargs)
            return {
                "query": query,
                "system_prompt": kwargs.get("system_prompt", ""),
                "prompt_text": f"## System Prompt\n{kwargs.get('system_prompt', '')}",
            }

    events = []
    pipeline = AutonomousIterationPipeline(
        context_loader=ContextLoaderAgent(memory_context_builder=Builder()),
        goal_maker=GoalMakerAgent(lambda *args: ["goal"]),
        task_designer=TaskDesignerAgent(lambda *args: ["task"]),
        task_decomposer=TaskDecomposerAgent(
            lambda tasks: [task.description for task in tasks],
            lambda tasks: {
                "level": "high" if max(len(task.target_files) for task in tasks) > 1 else "low",
                "score": max(len(task.target_files) for task in tasks),
            },
            easy_threshold=1,
            max_depth=3,
        ),
    )
    task = DesignedImprovementTask(
        id="task",
        goal_id="goal",
        description="Update files",
        target_files=["a.py", "b.py"],
        acceptance_criteria=["works"],
        risk_notes=["risk"],
    )

    events.append("Context Loader")
    context = pipeline.load_context("goal", ".", 0)
    events.append("Project Diagnosis")
    events.append("Goal Maker")
    goals = pipeline.make_goals({}, {}, {}, 0)
    events.append("Task Designer")
    tasks = pipeline.design_tasks({}, goals[0], {}, 0)
    events.append("Task Decomposer")
    decomposition = pipeline.decompose_tasks([task], context)

    assert events == pipeline.stage_names[:5]
    assert context["system_prompt"] == DEFAULT_AUTONOMOUS_ITERATION_SYSTEM_PROMPT
    assert captured_kwargs["system_prompt"] == DEFAULT_AUTONOMOUS_ITERATION_SYSTEM_PROMPT
    assert tasks == ["task"]
    assert decomposition["depth"] == 1
    assert decomposition["difficulty"]["level"] == "low"
    assert len(decomposition["subtasks"]) == 2


def test_tool_executor_structured_logs_include_source_type(tmp_path) -> None:
    log_file = tmp_path / "tools.jsonl"
    logger = OpenPilotLogger(log_file)
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry, logger=logger)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="read-missing",
                tool_name="file_reader",
                reason="capability_match",
                input_metadata={},
            )
        )
    finally:
        executor.shutdown()

    assert not result.success
    events = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
    ]
    payloads = [event["payload"] for event in events]
    assert {payload["source_type"] for payload in payloads} == {"tool"}
    assert payloads[-1]["source_name"] == "file_reader"
    assert payloads[-1]["phase"] == "tool_execution"
    assert payloads[-1]["success"] is False


def test_task_classifier_routes_direct_project_work_to_autonomous_iteration() -> None:
    result = task_classifier_executor(ToolInputMetadata.from_mapping("task_classifier", {"task": "帮我在项目里做一个贪吃蛇"}))

    assert isinstance(result.result, TaskRouteMetadata)
    assert result["route"] == "autonomous_iteration"
    assert result["confidence"] >= 0.8


def test_task_classifier_routes_reusable_agent_requests_to_agent_generator() -> None:
    result = task_classifier_executor(ToolInputMetadata.from_mapping("task_classifier", {"task": "生成一个可复用的研究报告 agent"}))

    assert isinstance(result.result, TaskRouteMetadata)
    assert result["route"] == "agent_generator"
    assert result["confidence"] >= 0.8


def test_task_classifier_routes_knowledge_work_to_agent_generator() -> None:
    tasks = [
        "帮我调查一下机器学习",
        "帮我研究一下新能源汽车出海市场",
        "整理一下这些资料并生成报告",
        "解释一下 transformer 的核心思想",
    ]

    for task in tasks:
        result = task_classifier_executor(ToolInputMetadata.from_mapping("task_classifier", {"task": task}))
        assert result["route"] == "agent_generator", task
        assert "knowledge work" in result["reason"]


def test_task_classifier_execution_intent_overrides_knowledge_work() -> None:
    tasks = [
        "帮我在项目里实现机器学习模块",
        "修复 web_searcher.py 里的 bug",
        "在 /tmp/demo 创建一个 Python 项目",
        "研究 web_searcher.py 为什么失败并修复",
    ]

    for task in tasks:
        result = task_classifier_executor(ToolInputMetadata.from_mapping("task_classifier", {"task": task}))
        assert result["route"] == "autonomous_iteration", task


def test_task_classifier_defaults_ambiguous_tasks_to_autonomous_iteration() -> None:
    result = task_classifier_executor(ToolInputMetadata.from_mapping("task_classifier", {"task": "分析一下这个任务"}))

    assert result["route"] == "autonomous_iteration"


def test_command_registry_hides_removed_agent_and_autopilot_commands() -> None:
    from ui.commands import get_all_command_names, get_command_registry

    names = get_all_command_names()
    help_text = get_command_registry().format_help()

    assert "/agent" not in names
    assert "/autopilot" not in names
    assert "/agent" not in help_text
    assert "/autopilot" not in help_text
    assert "task classifier" in help_text.lower()


def test_execute_goal_interactive_routes_with_task_classifier(monkeypatch) -> None:
    from ui import enhanced_cli

    calls = []

    class Console:
        def print(self, *args, **kwargs):
            pass

    class UI:
        console = Console()

    runtime_options = enhanced_cli.OpenPilotRuntimeOptions()

    def fake_agent(task, ui, llm_client=None, logger=None):
        calls.append(("agent", task))
        return "agent-result"

    def fake_autopilot(goal, ui, tracker, llm_client, logger, runtime_options):
        calls.append(("autopilot", goal))
        return "autopilot-result"

    monkeypatch.setattr(enhanced_cli, "_execute_agent_generator", fake_agent)
    monkeypatch.setattr(enhanced_cli, "_execute_autopilot", fake_autopilot)

    assert (
        enhanced_cli._execute_goal_interactive(
            "生成一个可复用的研究报告 agent",
            UI(),
            tracker=None,
            llm_client=None,
            logger=None,
            runtime_options=runtime_options,
        )
        == "agent-result"
    )
    assert calls[-1] == ("agent", "生成一个可复用的研究报告 agent")

    assert (
        enhanced_cli._execute_goal_interactive(
            "帮我做一个项目",
            UI(),
            tracker=None,
            llm_client=None,
            logger=None,
            runtime_options=runtime_options,
        )
        == "autopilot-result"
    )
    assert calls[-1] == ("autopilot", "帮我做一个项目")
    assert calls == [("agent", "生成一个可复用的研究报告 agent"), ("autopilot", "帮我做一个项目")]
