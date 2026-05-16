from __future__ import annotations

from pathlib import Path

from autonomous_iteration.models import EvaluationResult, IterationResult
from autonomous_iteration.agents.iteration_agent import AutonomousIterationAgent


class FakeEvaluator:
    llm_client = None

    def evaluate_project(self, **kwargs) -> EvaluationResult:
        return EvaluationResult(
            validation_passed=True,
            runnable=True,
            has_blocking_bugs=False,
            summary="Project validation passed.",
            improvement_opportunities=["Improve visible polish."],
            recommended_actions=["Add a visible polish improvement."],
            next_iteration_goal="Add visible polish.",
            run_command=kwargs.get("run_command", ""),
        )


class FakeMemoryContextBuilder:
    def build(
        self,
        query: str,
        *,
        project_path,
        include_environment: bool,
        limit: int,
        system_prompt: str = "",
    ) -> dict:
        return {
            "query": query,
            "project_path": str(project_path),
            "system_prompt": system_prompt,
            "dialog_context": [{"role": "user", "content": "原始用户需求"}],
            "related_memories": [{"id": "memory-1", "content": "Prefer visible polish."}],
            "related_files": [{"path": str(Path(project_path) / "app.py")}],
            "environment_context": [{"content": "Python environment ready."}],
            "prompt_text": f"## System Prompt\n{system_prompt}\n\n## Dialog Context\nUSER: 原始用户需求",
        }


def _project_state(project_path: Path) -> dict:
    return {
        "project_path": str(project_path),
        "goal": "Improve project",
        "written_files": [str(project_path / "app.py")],
        "file_summaries": [],
        "readme_summary": "",
        "run_command": "",
        "memory_records": [],
        "validation_context": {},
        "safe_target_files": [str(project_path / "app.py")],
    }


def test_autonomous_iteration_events_and_memory_context(tmp_path) -> None:
    events: list[str] = []
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("print('hello')\n", encoding="utf-8")
    agent = AutonomousIterationAgent(
        FakeEvaluator(),
        required_successful_improvements=1,
        max_iteration_attempts=2,
        memory_context_builder=FakeMemoryContextBuilder(),
    )

    def apply_improvement(iteration, evaluation, actions, improvement_report, is_repair):
        assert improvement_report["task_difficulty"]["level"] in {"low", "medium", "high"}
        return IterationResult(
            iteration=iteration,
            validation_passed=False,
            completed_successful_iteration=False,
            applied_actions=actions,
            changed_files=[str(project / "app.py")],
            success=True,
        )

    result = agent.run_project_pipeline(
        goal="Improve project",
        project_path=project,
        written_files=[str(project / "app.py")],
        apply_improvement=apply_improvement,
        analyze_improvements=lambda completed, evaluation: {
            "summary": "Need polish.",
            "next_iteration_goal": "Add visible polish.",
            "recommended_actions": ["Add visible polish."],
        },
        read_project_state=lambda evaluation, iteration: _project_state(project),
        on_progress=lambda event, payload: events.append(event),
    )

    assert result["success"]
    assert result["project_state"].memory_context["system_prompt"]
    assert result["project_state"].memory_context["prompt_text"].startswith("## System Prompt")
    assert result["project_state"].memory_context["related_memories"][0]["id"] == "memory-1"
    assert "context_loader" in events
    assert events.index("context_loader") < events.index("goal_maker")
    assert events.index("goal_maker") < events.index("task_designer")
    assert events.index("task_designer") < events.index("decomposition")
    assert events.index("decomposition") < events.index("iteration_started")


def test_autonomous_iteration_task_executor_failure_stage_remains_compatible(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    agent = AutonomousIterationAgent(
        FakeEvaluator(),
        required_successful_improvements=1,
        max_iteration_attempts=2,
        memory_context_builder=FakeMemoryContextBuilder(),
    )

    def apply_improvement(iteration, evaluation, actions, improvement_report, is_repair):
        raise RuntimeError("tool crashed")

    result = agent.run_project_pipeline(
        goal="Improve project",
        project_path=project,
        written_files=[],
        apply_improvement=apply_improvement,
        analyze_improvements=lambda completed, evaluation: {
            "summary": "Need polish.",
            "next_iteration_goal": "Add visible polish.",
            "recommended_actions": ["Add visible polish."],
        },
        read_project_state=lambda evaluation, iteration: _project_state(project),
    )

    assert not result["success"]
    assert result["failure_stage"] == "Task Executor"
    assert result["failed_iteration"] == 1
    assert "tool crashed" in result["failure_reason"]
