from __future__ import annotations

from autonomous_iteration.models import IterationResult
from ui.iteration_dashboard import IterationDashboardAdapter


class FakeUI:
    def __init__(self) -> None:
        self.task_graph_state = {"tasks": [], "current_task_id": None}
        self.current_states: list[dict] = []
        self.active_operations = ["llm", "tool"]

    def set_task_graph_state(self, **kwargs) -> None:
        self.task_graph_state.update(kwargs)

    def set_current_task_state(self, **kwargs) -> None:
        self.current_states.append(kwargs)

    def set_active_operations(self, operations) -> None:
        self.active_operations = operations


class FakeAutopilot:
    def __init__(self) -> None:
        self.enhanced_ui = FakeUI()
        self.tracker = None
        self.required_successful_improvements = 2
        self._dashboard_iteration_counter = 0
        self._dashboard_current_iteration_id = None


def test_iteration_dashboard_stage_helpers_update_nested_graph() -> None:
    autopilot = FakeAutopilot()
    adapter = IterationDashboardAdapter(autopilot)

    iteration_id = adapter.ensure_dashboard_iteration(1)
    stage_order = [child["description"] for child in autopilot.enhanced_ui.task_graph_state["tasks"][0]["children"]]
    adapter.append_dashboard_stage_child(
        "execution",
        child_id="action_1",
        description="Apply polish",
        kind="task",
        status="running",
    )
    adapter.set_dashboard_task_status(adapter.dashboard_stage_id("execution"), "running")

    tasks = autopilot.enhanced_ui.task_graph_state["tasks"]
    execution_node = next(child for child in tasks[0]["children"] if child["id"] == "iteration_1_execution")

    assert iteration_id == "iteration_1"
    assert stage_order[:7] == [
        "Environment Setup",
        "Read Project State",
        "Context Loader",
        "Goal Maker",
        "Task Designer",
        "Task Decomposer",
        "Task Executor",
    ]
    assert execution_node["status"] == "running"
    assert execution_node["children"][0]["description"] == "Apply polish"


def test_iteration_dashboard_failure_summary_and_finish_operations() -> None:
    autopilot = FakeAutopilot()
    adapter = IterationDashboardAdapter(autopilot)

    message = adapter.format_iteration_failure(
        {
            "completed_improvements": 1,
            "required_improvements": 2,
            "failed_iteration": 2,
            "failure_stage": "Task Executor",
            "failed_tool": "project_improvement_tool",
            "failure_reason": "timeout",
            "retry_attempted": True,
            "retry_history": [{"mode": "compact"}],
            "remaining_goals": ["Improve keyboard flow"],
        }
    )
    adapter.finish_active_operations("timeout")

    assert "Iteration 2" in message
    assert "Task Executor" in message
    assert "retry attempted: yes" in message
    assert autopilot.enhanced_ui.active_operations == []


def test_iteration_dashboard_core_event_sequence_does_not_raise() -> None:
    autopilot = FakeAutopilot()
    adapter = IterationDashboardAdapter(autopilot)

    class Goal:
        title = "Improve polish"
        category = "ux"
        acceptance_criteria = ["Visible status"]

    class Task:
        description = "Update app.py"
        target_files = ["app.py"]

    adapter.handle_iteration_progress(
        "context_loader",
        {"iteration": 1, "context": {"related_memories": [1], "related_files": [1], "environment_context": []}},
    )
    adapter.handle_iteration_progress("goal_maker_started", {"iteration": 1})
    adapter.handle_iteration_progress("goal_maker", {"iteration": 1, "selected_goal": Goal()})
    adapter.handle_iteration_progress("task_designer_started", {"iteration": 1})
    adapter.handle_iteration_progress("task_designer", {"tasks": [Task()]})
    adapter.handle_iteration_progress("decomposition_started", {"iteration": 1, "tasks": [Task()]})
    adapter.handle_iteration_progress("decomposition", {"tasks": [Task()], "difficulty": {"level": "low"}})
    adapter.handle_iteration_progress("iteration_started", {"iteration": 1, "actions": ["Update app.py"]})
    adapter.handle_iteration_progress(
        "iteration_failed",
        {
            "iteration": 1,
            "result": IterationResult(
                iteration=1,
                validation_passed=False,
                completed_successful_iteration=False,
                success=False,
                error="tool failed",
                changed_files=["app.py"],
            ),
            "completed_improvements": 0,
            "required_improvements": 2,
        },
    )

    titles = [state["title"] for state in autopilot.enhanced_ui.current_states]
    assert titles[:5] == [
        "Context Loader",
        "Goal Maker",
        "Goal Maker",
        "Task Designer",
        "Task Designer",
    ]
    assert titles[5:8] == [
        "Task Decomposer",
        "Task Decomposer",
        "Iteration 1",
    ]
    assert titles[-1] == "Iteration 1 failed"


def test_iteration_stage_started_events_show_running_agent() -> None:
    autopilot = FakeAutopilot()
    adapter = IterationDashboardAdapter(autopilot)

    adapter.ensure_dashboard_iteration(1)
    adapter.handle_iteration_progress("decomposition_started", {"iteration": 1})

    children = autopilot.enhanced_ui.task_graph_state["tasks"][0]["children"]
    by_description = {child["description"]: child for child in children}

    assert by_description["Task Decomposer"]["status"] == "running"
    assert autopilot.enhanced_ui.task_graph_state["current_task_id"] == "iteration_1_decomposition"
    assert autopilot.enhanced_ui.current_states[-1] == {
        "title": "Task Decomposer",
        "details": "Breaking task into executable subtasks",
        "status": "running",
    }


def test_running_tool_becomes_current_task_id() -> None:
    autopilot = FakeAutopilot()
    adapter = IterationDashboardAdapter(autopilot)

    adapter.ensure_dashboard_iteration(1)
    adapter.set_dashboard_tool_status(
        parent_task_id=adapter.dashboard_stage_id("execution"),
        tool_id="iteration_1_code_generator",
        tool_name="code_generator",
        status="running",
    )

    assert autopilot.enhanced_ui.task_graph_state["current_task_id"] == "iteration_1_code_generator"

    adapter.set_dashboard_tool_status(
        parent_task_id=adapter.dashboard_stage_id("execution"),
        tool_id="iteration_1_code_generator",
        tool_name="code_generator",
        status="completed",
    )

    assert autopilot.enhanced_ui.task_graph_state["current_task_id"] == "iteration_1_execution"


def test_modification_evaluation_started_marks_evaluator_running() -> None:
    autopilot = FakeAutopilot()
    adapter = IterationDashboardAdapter(autopilot)

    adapter.ensure_dashboard_iteration(1)
    adapter.handle_iteration_progress("iteration_started", {"iteration": 1, "actions": ["Update app.py"]})
    adapter.handle_iteration_progress("modification_evaluation_started", {"iteration": 1})

    children = autopilot.enhanced_ui.task_graph_state["tasks"][0]["children"]
    by_description = {child["description"]: child for child in children}

    assert by_description["Task Executor"]["status"] == "completed"
    assert by_description["Modification Evaluator"]["status"] == "running"
    assert autopilot.enhanced_ui.task_graph_state["current_task_id"] == "iteration_1_evaluation"
    assert autopilot.enhanced_ui.current_states[-1]["title"] == "Modification Evaluator"
    assert autopilot.enhanced_ui.current_states[-1]["status"] == "running"


def test_iteration_started_completes_missing_pre_execution_stages() -> None:
    autopilot = FakeAutopilot()
    adapter = IterationDashboardAdapter(autopilot)

    adapter.ensure_dashboard_iteration(1)
    adapter.handle_iteration_progress(
        "iteration_started",
        {"iteration": 1, "actions": ["Fix the runtime error reported by the smoke test."]},
    )

    children = autopilot.enhanced_ui.task_graph_state["tasks"][0]["children"]
    by_description = {child["description"]: child for child in children}

    assert by_description["Goal Maker"]["status"] == "completed"
    assert by_description["Task Designer"]["status"] == "completed"
    assert by_description["Task Decomposer"]["status"] == "completed"
    assert by_description["Task Executor"]["status"] == "running"
    assert by_description["Goal Maker"]["children"][0]["description"] == "Repair path prepared"
