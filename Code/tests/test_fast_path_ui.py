from __future__ import annotations

import io
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace

from agents.evaluation_models import EvaluationResult
from execution.intelligent_autopilot import IntelligentAutopilot
from rich.console import Console
from ui.enhanced_ui import EnhancedUI


FAST_TASK_IDS = {"fast_code_generator", "fast_file_writer", "fast_readme_tool"}
ITERATION_TASK_IDS = {
    "project_state",
    "goal_maker",
    "task_designer",
    "decomposition",
    "execution",
    "evaluation",
    "mind_system",
}


class FakeEnhancedUI:
    def __init__(self) -> None:
        self.graph_updates: list[dict] = []
        self.current_task_updates: list[dict] = []
        self.task_graph_state = {"tasks": [], "current_task_id": None}

    def set_task_graph_state(self, **kwargs) -> None:
        self.graph_updates.append(kwargs)
        if "tasks" in kwargs:
            self.task_graph_state["tasks"] = kwargs["tasks"]
        if "current_task_id" in kwargs:
            self.task_graph_state["current_task_id"] = kwargs["current_task_id"]

    def set_current_task_state(self, **kwargs) -> None:
        self.current_task_updates.append(kwargs)

    def update_main_content(self, content) -> None:
        pass

    def create_status_panel(self, status: str, details: str = "") -> dict[str, str]:
        return {"status": status, "details": details}

    def log_activity(self, action_type: str, message: str) -> None:
        pass


class FakeLogger:
    def log_event(self, *args, **kwargs) -> None:
        pass


class FastPathUITest(unittest.TestCase):
    def test_fast_path_does_not_add_generation_steps_to_task_graph(self) -> None:
        autopilot = object.__new__(IntelligentAutopilot)
        ui = FakeEnhancedUI()
        target_file = Path("/Users/yanning/Projects/openpilot/Snake/main.py")

        autopilot.enhanced_ui = ui
        autopilot.console = SimpleNamespace(print=lambda *args, **kwargs: None)
        autopilot.logger = FakeLogger()
        autopilot.session_id = "test-session"
        autopilot.stats = {}
        autopilot.required_successful_improvements = 2

        autopilot._simple_code_artifact_target = MethodType(
            lambda self, goal, semantic: target_file,
            autopilot,
        )
        autopilot._stop_tracking_if_owned = MethodType(lambda self: None, autopilot)

        tool_results = {
            "code_generator": {
                "tool": "code_generator",
                "result": {"code": "print('snake')\n"},
                "success": True,
                "error": None,
            },
            "file_writer": {
                "tool": "file_writer",
                "result": {"file_path": str(target_file)},
                "success": True,
                "error": None,
            },
            "readme_tool": {
                "tool": "readme_tool",
                "result": {"file_path": str(target_file.parent / "README.md")},
                "success": True,
                "error": None,
            },
        }

        def execute_fast_tool(self, *, tool_name, **kwargs):
            return tool_results[tool_name]

        def run_iterative_improvement(self, **kwargs):
            self._reset_iteration_dashboard("make snake")
            self._ensure_dashboard_iteration()
            return {
                "success": True,
                "validation": EvaluationResult(
                    validation_passed=True,
                    runnable=True,
                    has_blocking_bugs=False,
                    summary="ok",
                ),
                "evaluation": None,
                "completed_improvements": 0,
                "required_improvements": 2,
                "completed_iterations": 0,
                "required_iterations": 2,
                "improvement_report": {},
                "iterations": [],
                "partial_success": False,
                "remaining_goals": [],
            }

        autopilot._execute_fast_tool = MethodType(execute_fast_tool, autopilot)
        autopilot._run_iterative_improvement = MethodType(run_iterative_improvement, autopilot)

        result = autopilot._try_simple_code_artifact_fast_path("make snake", SimpleNamespace())

        self.assertTrue(result["success"])
        all_task_ids = {
            task.get("id")
            for update in ui.graph_updates
            for task in update.get("tasks", [])
        }
        current_task_ids = {
            update.get("current_task_id")
            for update in ui.graph_updates
            if update.get("current_task_id")
        }

        self.assertFalse(FAST_TASK_IDS & all_task_ids)
        self.assertFalse(FAST_TASK_IDS & current_task_ids)
        self.assertIn("iteration_1", all_task_ids)
        self.assertFalse(ITERATION_TASK_IDS & all_task_ids)

    def test_fast_path_fails_when_iteration_fails_even_if_validation_passed(self) -> None:
        autopilot = object.__new__(IntelligentAutopilot)
        ui = FakeEnhancedUI()
        target_file = Path("/Users/yanning/Projects/openpilot/Snake/main.py")

        autopilot.enhanced_ui = ui
        autopilot.console = SimpleNamespace(print=lambda *args, **kwargs: None)
        autopilot.logger = FakeLogger()
        autopilot.session_id = "test-session"
        autopilot.stats = {}
        autopilot.required_successful_improvements = 2

        autopilot._simple_code_artifact_target = MethodType(
            lambda self, goal, semantic: target_file,
            autopilot,
        )
        autopilot._stop_tracking_if_owned = MethodType(lambda self: None, autopilot)

        tool_results = {
            "code_generator": {
                "tool": "code_generator",
                "result": {"code": "print('snake')\n"},
                "success": True,
                "error": None,
            },
            "file_writer": {
                "tool": "file_writer",
                "result": {"file_path": str(target_file)},
                "success": True,
                "error": None,
            },
            "readme_tool": {
                "tool": "readme_tool",
                "result": {"file_path": str(target_file.parent / "README.md")},
                "success": True,
                "error": None,
            },
        }

        def execute_fast_tool(self, *, tool_name, **kwargs):
            return tool_results[tool_name]

        def run_iterative_improvement(self, **kwargs):
            return {
                "success": False,
                "partial_success": True,
                "validation": EvaluationResult(
                    validation_passed=True,
                    runnable=True,
                    has_blocking_bugs=False,
                    summary="base project still runs",
                ),
                "evaluation": None,
                "completed_improvements": 0,
                "required_improvements": 2,
                "completed_iterations": 0,
                "required_iterations": 2,
                "improvement_report": {},
                "iterations": [],
                "failure_stage": "Task Executor",
                "failed_iteration": 1,
                "failed_tool": "code_generator",
                "failure_reason": "code_generator timed out after 300s",
                "retry_attempted": True,
                "remaining_goals": ["Refactor restart"],
            }

        autopilot._execute_fast_tool = MethodType(execute_fast_tool, autopilot)
        autopilot._run_iterative_improvement = MethodType(run_iterative_improvement, autopilot)

        result = autopilot._try_simple_code_artifact_fast_path("make snake", SimpleNamespace())

        self.assertFalse(result["success"])
        self.assertTrue(result["partial_success"])
        self.assertIn("code_generator timed out", result["iteration_error"])
        self.assertEqual(result["failure_stage"], "Task Executor")

    def test_tool_children_are_nested_under_agent_task(self) -> None:
        autopilot = object.__new__(IntelligentAutopilot)
        ui = FakeEnhancedUI()
        autopilot.enhanced_ui = ui

        autopilot._append_dashboard_tasks(
            [
                {"id": "execution", "description": "Task Executor", "status": "running"},
                {"id": "evaluation", "description": "Modification Evaluator", "status": "pending"},
            ],
            current_task_id="execution",
        )
        autopilot._set_dashboard_tool_status(
            parent_task_id="execution",
            tool_id="iteration_1_code_generator",
            tool_name="code_generator",
            status="running",
        )
        autopilot._set_dashboard_tool_status(
            parent_task_id="execution",
            tool_id="iteration_1_code_generator",
            tool_name="code_generator",
            status="completed",
        )
        autopilot._set_dashboard_task_status("execution", "completed")

        execution = next(task for task in ui.task_graph_state["tasks"] if task["id"] == "execution")
        evaluation = next(task for task in ui.task_graph_state["tasks"] if task["id"] == "evaluation")

        self.assertEqual(
            execution["children"],
            [
                {
                    "id": "iteration_1_code_generator",
                    "description": "code_generator",
                    "status": "completed",
                    "kind": "tool",
                }
            ],
        )
        self.assertNotIn("children", evaluation)

    def test_iteration_timeline_preserves_history_and_debug_children(self) -> None:
        autopilot = object.__new__(IntelligentAutopilot)
        ui = FakeEnhancedUI()
        autopilot.enhanced_ui = ui
        autopilot.required_successful_improvements = 2
        autopilot.max_iteration_attempts = 4
        autopilot.tracker = None

        autopilot._reset_iteration_dashboard("make snake")

        state = SimpleNamespace(
            written_files=["Snake/main.py"],
            safe_target_files=["Snake/main.py"],
            memory_records=[],
        )
        goal = SimpleNamespace(
            title="Add score feedback",
            category="feature",
            acceptance_criteria=["Score is visible", "Game can restart"],
        )
        designed_task = SimpleNamespace(
            description="Implement scoring and restart flow",
            target_files=["Snake/main.py"],
        )
        evaluation = EvaluationResult(
            validation_passed=True,
            runnable=True,
            has_blocking_bugs=False,
            summary="Game runs with scoring.",
        )
        result = SimpleNamespace(
            success=True,
            completed_successful_iteration=True,
        )

        autopilot._handle_iteration_progress("project_state", {"state": state, "iteration": 0})
        autopilot._handle_iteration_progress(
            "improvement_report",
            {
                "completed_improvements": 0,
                "required_improvements": 2,
                "report": {"next_iteration_goal": "Add score feedback"},
            },
        )
        autopilot._handle_iteration_progress(
            "goal_maker",
            {"selected_goal": goal, "goals": [goal], "iteration": 0},
        )
        autopilot._handle_iteration_progress(
            "task_designer",
            {"tasks": [designed_task], "selected_goal": goal, "iteration": 0},
        )
        autopilot._handle_iteration_progress("decomposition", {"tasks": [designed_task], "iteration": 0})
        autopilot._handle_iteration_progress(
            "iteration_started",
            {
                "iteration": 1,
                "completed_improvements": 0,
                "required_improvements": 2,
                "actions": ["Implement scoring and restart flow"],
            },
        )
        autopilot._set_dashboard_tool_status(
            parent_task_id=autopilot._dashboard_stage_id("execution"),
            tool_id="iteration_1_code_generator",
            tool_name="code_generator",
            status="completed",
        )
        autopilot._set_dashboard_tool_status(
            parent_task_id=autopilot._dashboard_stage_id("execution"),
            tool_id="iteration_1_file_writer",
            tool_name="file_writer",
            status="completed",
        )
        autopilot._handle_iteration_progress(
            "modification_evaluation",
            {"iteration": 1, "evaluation": evaluation, "result": result, "tasks": [designed_task]},
        )
        autopilot._handle_iteration_progress("mind_system", {"iteration": 1, "note": "Iteration 1 completed: score flow"})
        autopilot._handle_iteration_progress(
            "iteration_completed",
            {"iteration": 1, "evaluation": evaluation, "result": result},
        )

        autopilot._handle_iteration_progress("project_state", {"state": state, "iteration": 1})

        roots = ui.task_graph_state["tasks"]
        self.assertEqual([root["id"] for root in roots], ["iteration_1", "iteration_2"])

        first_iteration = roots[0]
        first_children_by_id = {child["id"]: child for child in first_iteration["children"]}
        goal_maker = first_children_by_id["iteration_1_goal_maker"]
        task_designer = first_children_by_id["iteration_1_task_designer"]
        execution = first_children_by_id["iteration_1_execution"]
        evaluation_node = first_children_by_id["iteration_1_evaluation"]
        mind_system = first_children_by_id["iteration_1_mind_system"]

        self.assertTrue(any(child["kind"] == "goal" for child in goal_maker["children"]))
        self.assertTrue(any(child["kind"] == "task" for child in task_designer["children"]))
        tool_children = [child for child in execution["children"] if child["kind"] == "tool"]
        self.assertEqual([child["description"] for child in tool_children], ["code_generator", "file_writer"])
        action_children = [child for child in execution["children"] if child["kind"] == "task"]
        self.assertTrue(action_children)
        self.assertTrue(all(child["status"] == "completed" for child in action_children))
        self.assertTrue(any(child["kind"] == "result" for child in evaluation_node["children"]))
        self.assertTrue(any(child["kind"] == "note" for child in mind_system["children"]))
        self.assertEqual(first_iteration["status"], "completed")
        self.assertEqual(roots[1]["status"], "running")

    def test_three_iteration_timeline_renders_live_summary_and_full_details(self) -> None:
        console = Console(width=180, record=True, force_terminal=True, color_system=None, file=io.StringIO())
        ui = EnhancedUI(console)
        tasks = [
            {
                "id": f"iteration_{index}",
                "description": f"Iteration {index}",
                "status": "completed",
                "kind": "iteration",
                "children": [
                    {
                        "id": f"iteration_{index}_goal_maker",
                        "description": "Goal Maker",
                        "status": "completed",
                        "kind": "agent",
                        "children": [
                            {
                                "id": f"iteration_{index}_goal",
                                "description": f"Goal {index} selected",
                                "status": "completed",
                                "kind": "goal",
                            }
                        ],
                    },
                    {
                        "id": f"iteration_{index}_task_designer",
                        "description": "Task Designer",
                        "status": "completed",
                        "kind": "agent",
                        "children": [
                            {
                                "id": f"iteration_{index}_task",
                                "description": f"Task {index} designed",
                                "status": "completed",
                                "kind": "task",
                            }
                        ],
                    },
                    {
                        "id": f"iteration_{index}_execution",
                        "description": "Task Executor",
                        "status": "completed",
                        "kind": "agent",
                        "children": [
                            {
                                "id": f"iteration_{index}_code_generator",
                                "description": "code_generator",
                                "status": "completed",
                                "kind": "tool",
                            }
                        ],
                    },
                    {
                        "id": f"iteration_{index}_evaluation",
                        "description": "Modification Evaluator",
                        "status": "completed",
                        "kind": "agent",
                        "children": [
                            {
                                "id": f"iteration_{index}_result",
                                "description": f"Iteration {index} accepted",
                                "status": "completed",
                                "kind": "result",
                            }
                        ],
                    },
                    {
                        "id": f"iteration_{index}_mind_system",
                        "description": "Mind System",
                        "status": "completed",
                        "kind": "agent",
                        "children": [
                            {
                                "id": f"iteration_{index}_note",
                                "description": f"Iteration {index} memory note",
                                "status": "completed",
                                "kind": "note",
                            }
                        ],
                    },
                ],
            }
            for index in range(1, 4)
        ]
        ui.set_task_graph_state(goal="make snake", tasks=tasks, current_task_id="iteration_3")

        self.assertEqual([task["id"] for task in ui.task_graph_state["tasks"]], ["iteration_1", "iteration_2", "iteration_3"])

        console.print(ui.create_task_graph_state_panel())
        live_text = console.export_text(clear=True)
        self.assertIn("1. Iteration 1", live_text)
        self.assertIn("2. Iteration 2", live_text)
        self.assertIn("3. Iteration 3", live_text)
        self.assertIn("details hidden; full timeline printed below", live_text)

        console.print(ui.create_full_task_graph_timeline_panel())
        full_text = console.export_text()
        self.assertIn("Tool 1: code_generator", full_text)
        self.assertIn("Goal 1: Goal 1 selected", full_text)
        self.assertIn("Task 1: Task 1 designed", full_text)
        self.assertIn("Result: Iteration 1 accepted", full_text)
        self.assertIn("Note: Iteration 1 memory note", full_text)

    def test_running_execution_children_are_failed_when_iteration_fails(self) -> None:
        autopilot = object.__new__(IntelligentAutopilot)
        ui = FakeEnhancedUI()
        autopilot.enhanced_ui = ui
        autopilot.required_successful_improvements = 2
        autopilot.max_iteration_attempts = 4
        autopilot.tracker = None

        autopilot._reset_iteration_dashboard("make snake")
        autopilot._handle_iteration_progress(
            "iteration_started",
            {
                "iteration": 1,
                "completed_improvements": 0,
                "required_improvements": 2,
                "actions": ["Implement pause"],
            },
        )
        autopilot._set_dashboard_tool_status(
            parent_task_id=autopilot._dashboard_stage_id("execution"),
            tool_id="iteration_1_code_generator",
            tool_name="code_generator",
            status="running",
        )
        result = SimpleNamespace(
            error="timeout",
            failure_reason="timeout",
            failed_tool="code_generator",
            changed_files=[],
            retry_attempted=False,
        )

        autopilot._handle_iteration_progress(
            "iteration_failed",
            {
                "iteration": 1,
                "result": result,
                "failure_stage": "Task Executor",
                "failed_tool": "code_generator",
                "failure_reason": "timeout",
            },
        )

        iteration = ui.task_graph_state["tasks"][0]
        execution = next(child for child in iteration["children"] if child["id"] == "iteration_1_execution")
        self.assertEqual(execution["status"], "failed")
        self.assertTrue(execution["children"])
        self.assertTrue(all(child["status"] == "failed" for child in execution["children"]))

    def test_compact_retry_prompt_is_shorter_and_omits_large_report_json(self) -> None:
        autopilot = object.__new__(IntelligentAutopilot)
        evaluation = EvaluationResult(
            validation_passed=True,
            runnable=True,
            has_blocking_bugs=False,
            summary="ok",
            validation_errors=[],
            warnings=["interactive smoke test skipped"],
        )
        current_code = "\n".join(
            [
                "def main(stdscr):",
                "    while True:",
                "        key = stdscr.getch()",
                "        if key == ord('r'):",
                "            return main(stdscr)",
                "        draw()",
            ]
            * 120
        )
        report = {
            "summary": "functional but restart is recursive",
            "improvement_opportunities": ["replace recursion"],
            "recommended_actions": ["use an outer loop"],
            "must_implement_next": ["Restart uses a loop", "No recursive main call"],
            "selected_goal": {"title": "Refactor restart", "rationale": "x" * 1200},
            "designed_tasks": [{"description": "y" * 1200, "acceptance_criteria": ["z" * 400]}],
        }

        full_prompt = autopilot._build_project_improvement_prompt(
            goal="make snake",
            target_file=Path("Snake/main.py"),
            current_code=current_code,
            evaluation=evaluation,
            actions=["Replace recursive restart with an iterative loop"],
            improvement_report=report,
            is_repair=False,
            simplified=False,
        )
        compact_prompt = autopilot._build_project_improvement_prompt(
            goal="make snake",
            target_file=Path("Snake/main.py"),
            current_code=current_code,
            evaluation=evaluation,
            actions=["Replace recursive restart with an iterative loop"],
            improvement_report=report,
            is_repair=False,
            simplified=True,
        )

        self.assertLess(len(compact_prompt), len(full_prompt))
        self.assertNotIn("Designed tasks:", compact_prompt)
        self.assertNotIn("Selected goal:", compact_prompt)
        self.assertLessEqual(len(compact_prompt), 3000)

    def test_iteration_code_generation_uses_default_timeout(self) -> None:
        autopilot = object.__new__(IntelligentAutopilot)
        autopilot._dashboard_current_iteration_id = "iteration_1"
        captured = {}

        def execute_fast_tool(self, **kwargs):
            captured.update(kwargs)
            return {"success": True}

        autopilot._execute_fast_tool = MethodType(execute_fast_tool, autopilot)

        autopilot._execute_code_generation_for_improvement(
            task=SimpleNamespace(),
            iteration=1,
            target_file=Path("Snake/main.py"),
            improvement_prompt="improve",
            simplified=False,
        )

        self.assertNotEqual(captured.get("timeout_override"), 120)
        self.assertNotIn("timeout_override", captured)


if __name__ == "__main__":
    unittest.main()
