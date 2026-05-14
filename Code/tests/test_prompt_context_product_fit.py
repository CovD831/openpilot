import tempfile
import unittest
from pathlib import Path
from types import MethodType

from agents.evaluation_models import DesignedImprovementTask, EvaluationResult, IterationResult
from agents.iterative_improvement import AutonomousIterationAgent
from agents.task_models import Task, TaskPriority
from execution.code_generator import CodeGenerator
from execution.code_models import CodeGenerationRequest, CodeLanguage
from execution.intelligent_autopilot import IntelligentAutopilot
from tools.project_improvement_tool import project_improvement_tool_executor


class PromptContextProductFitTests(unittest.TestCase):
    def test_project_improvement_prefers_pygame_for_default_snake(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            main = project / "main.py"
            main.write_text("import curses\n\ndef main(stdscr):\n    pass\n", encoding="utf-8")

            report = project_improvement_tool_executor(
                {
                    "project_path": str(project),
                    "goal": "帮我写一个贪吃蛇",
                    "written_files": [str(main)],
                    "validation_result": {"validation_passed": True},
                }
            )

        report_text = str(report).lower()
        self.assertIn("pygame", report_text)
        self.assertIn("standalone", report_text)
        self.assertIn("next_iteration_goal", report)

    def test_project_improvement_respects_explicit_terminal_goal(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            main = project / "main.py"
            main.write_text("import curses\n\ndef main(stdscr):\n    pass\n", encoding="utf-8")

            report = project_improvement_tool_executor(
                {
                    "project_path": str(project),
                    "goal": "帮我在终端用 curses 写一个贪吃蛇",
                    "written_files": [str(main)],
                    "validation_result": {"validation_passed": True},
                }
            )

        self.assertNotIn("pygame", str(report.get("next_iteration_goal", "")).lower())

    def test_code_generator_prompt_nests_context_and_tool_requirements(self):
        request = CodeGenerationRequest(
            request_id="req_test",
            task_description="Migrate the snake game to pygame.",
            language=CodeLanguage.PYTHON,
            prompt_context={
                "original_goal": "写一个贪吃蛇",
                "product_judgment": {
                    "preferred_runtime": "standalone_gui",
                    "preferred_stack": "pygame",
                    "current_runtime": "terminal_curses",
                },
                "quality_rubric": ["Prefer pygame GUI over terminal/curses for default snake."],
                "tool_task": "Generate a pygame replacement.",
            },
        )

        prompt = CodeGenerator()._build_prompt(request)

        self.assertIn("PROMPT CONTEXT JSON", prompt)
        self.assertIn("Prefer pygame GUI over terminal/curses", prompt)
        self.assertIn("TOOL OUTPUT REQUIREMENTS", prompt)
        self.assertIn("full replacement source code", prompt)

    def test_iteration_code_generation_passes_prompt_context_to_tool(self):
        autopilot = IntelligentAutopilot.__new__(IntelligentAutopilot)
        autopilot.enhanced_ui = None
        captured = {}

        def fake_execute_fast_tool(self, **kwargs):
            captured.update(kwargs)
            return {"success": True, "result": {"code": "print('ok')"}}

        autopilot._execute_fast_tool = MethodType(fake_execute_fast_tool, autopilot)
        autopilot._dashboard_stage_id = MethodType(lambda self, key: None, autopilot)

        prompt_context = {
            "original_goal": "写一个贪吃蛇",
            "product_judgment": {"preferred_stack": "pygame"},
            "quality_rubric": ["Product fit matters."],
            "tool_task": "Generate pygame game.",
        }
        task = Task(id="task", description="Improve", priority=TaskPriority.HIGH)
        autopilot._execute_code_generation_for_improvement(
            task=task,
            iteration=1,
            target_file=Path("/tmp/main.py"),
            improvement_prompt="Generate pygame game.",
            simplified=False,
            mode="full",
            prompt_context=prompt_context,
        )

        self.assertEqual(captured["tool_name"], "code_generator")
        self.assertEqual(captured["input_params"]["prompt_context"], prompt_context)
        self.assertEqual(captured["input_params"]["task_description"], "Generate pygame game.")

    def test_modification_evaluator_rejects_terminal_polish_when_pygame_is_preferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            main = Path(tmp) / "main.py"
            main.write_text("import curses\n\ndef main(stdscr):\n    stdscr.getmaxyx()\n", encoding="utf-8")
            agent = AutonomousIterationAgent(evaluator=object())
            evaluation = EvaluationResult(
                validation_passed=True,
                runnable=True,
                has_blocking_bugs=False,
                summary="Project validation passed.",
            )
            result = IterationResult(
                iteration=1,
                validation_passed=True,
                completed_successful_iteration=False,
                applied_actions=["Handle terminal resize."],
                changed_files=[str(main)],
                success=True,
            )
            tasks = [
                DesignedImprovementTask(
                    id="task_1",
                    goal_id="goal_1",
                    description="Handle terminal resize during curses gameplay.",
                    target_files=[str(main)],
                    acceptance_criteria=["Terminal resize does not crash."],
                )
            ]
            report = {
                "prompt_context": {
                    "product_judgment": {
                        "preferred_runtime": "standalone_gui",
                        "preferred_stack": "pygame",
                        "current_runtime": "terminal_curses",
                    }
                }
            }

            accepted = agent._evaluate_modification(evaluation, result, tasks, False, report)

        self.assertFalse(accepted)
        self.assertIn("Product-fit rubric not satisfied", result.failure_reason)


if __name__ == "__main__":
    unittest.main()
