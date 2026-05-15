from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import patch

from openai import OpenAIError

from agents.evaluation_models import EvaluationResult
from core.config import LLMSettings
from core.exceptions import ErrorCategory, LLMProviderError, classify_error
from core.llm import LLMClient, LLMMessage, LLMRequest
from execution.intelligent_autopilot import IntelligentAutopilot
from tools.project_improvement_tool import (
    PROJECT_IMPROVEMENT_TOOL_DEFINITION,
    project_improvement_tool_executor,
)


class RetryLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def log_event(self, event_type, payload, **kwargs) -> None:
        self.events.append((event_type, payload))


class RetryMechanismTest(unittest.TestCase):
    def test_llm_transport_retry_recovers_from_network_error(self) -> None:
        calls = {"count": 0}

        class FakeCompletions:
            def create(self, **payload):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise OpenAIError("Connection error.")
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="ok"), finish_reason="stop")],
                    model="fake-model",
                    usage=None,
                    id="resp_1",
                    created=1,
                )

        class FakeOpenAI:
            def __init__(self, **kwargs) -> None:
                self.chat = SimpleNamespace(completions=FakeCompletions())

        settings = LLMSettings(
            api_key="test-key",
            transport_retries=1,
            retry_initial_delay=0,
            retry_max_delay=0,
        )
        client = LLMClient(settings=settings, enable_cache=False)

        with patch("core.llm.OpenAI", FakeOpenAI):
            response = client.complete(
                LLMRequest(messages=[LLMMessage(role="user", content="hello")]),
                max_retries=1,
            )

        self.assertEqual(response.content, "ok")
        self.assertEqual(calls["count"], 2)
        retry_history = response.raw_response_metadata["transport_retry_history"]
        self.assertEqual([item["status"] for item in retry_history], ["failed", "success"])

    def test_llm_transport_retry_does_not_retry_auth_error(self) -> None:
        calls = {"count": 0}

        class FakeCompletions:
            def create(self, **payload):
                calls["count"] += 1
                raise OpenAIError("401 unauthorized")

        class FakeOpenAI:
            def __init__(self, **kwargs) -> None:
                self.chat = SimpleNamespace(completions=FakeCompletions())

        settings = LLMSettings(
            api_key="test-key",
            transport_retries=2,
            retry_initial_delay=0,
            retry_max_delay=0,
        )
        client = LLMClient(settings=settings, enable_cache=False)

        with patch("core.llm.OpenAI", FakeOpenAI):
            with self.assertRaises(LLMProviderError):
                client.complete(
                    LLMRequest(messages=[LLMMessage(role="user", content="hello")]),
                    max_retries=1,
                )

        self.assertEqual(calls["count"], 1)

    def test_provider_error_preserves_retryable_network_category(self) -> None:
        error = LLMProviderError("ErrorCategory.NETWORK: Connection error.")

        self.assertEqual(classify_error(error), ErrorCategory.NETWORK)

    def test_chat_provider_boundary_is_only_core_llm(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        offenders = []
        for path in (repo_root / "Code" / "src").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "chat.completions.create" in text and path.name != "llm.py":
                offenders.append(path.relative_to(repo_root).as_posix())

        self.assertEqual(offenders, [])

    def test_project_improvement_tool_uses_llm_sized_timeout_without_outer_retry(self) -> None:
        self.assertGreaterEqual(PROJECT_IMPROVEMENT_TOOL_DEFINITION.timeout_seconds, 360)
        self.assertEqual(PROJECT_IMPROVEMENT_TOOL_DEFINITION.max_retries, 0)

    def test_project_improvement_tool_returns_marked_fallback_on_llm_failure(self) -> None:
        class FailingLLM:
            def complete(self, *args, **kwargs):
                raise TimeoutError("provider stalled")

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            main = project / "main.py"
            main.write_text("import tkinter as tk\nroot = tk.Tk()\n", encoding="utf-8")
            result = project_improvement_tool_executor(
                {
                    "project_path": str(project),
                    "goal": "帮我做一个贪吃蛇",
                    "written_files": [str(main)],
                    "validation_result": {"validation_passed": True},
                    "prompt_context": {
                        "product_judgment": {
                            "project_type": "interactive_game",
                            "explicit_terminal_requested": False,
                            "current_runtime": "tkinter_gui",
                            "preferred_runtime": "standalone_gui",
                            "preferred_stack": "pygame",
                        }
                    },
                    "_llm_client": FailingLLM(),
                }
            )

        self.assertEqual(result["source"], "fallback")
        self.assertIn("provider stalled", result["fallback_reason"])
        self.assertIn("pygame", result["next_iteration_goal"].lower())

    def test_project_improvement_prompt_is_hard_cropped(self) -> None:
        captured = {}

        class CapturingLLM:
            def complete(self, request, **kwargs):
                captured["prompt"] = request.messages[0].content
                return SimpleNamespace(
                    parsed_json={
                        "summary": "ok",
                        "improvement_opportunities": ["Improve the GUI"],
                        "recommended_actions": ["Use pygame"],
                        "next_iteration_goal": "Migrate to pygame",
                        "must_implement_next": ["pygame launches"],
                        "blocking_risks": [],
                    },
                    content="{}",
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            main = project / "main.py"
            main.write_text("import tkinter as tk\n" + "x = 1\n" * 3000 + "TAIL_SHOULD_BE_CROPPED\n", encoding="utf-8")
            result = project_improvement_tool_executor(
                {
                    "project_path": str(project),
                    "goal": "帮我做一个贪吃蛇",
                    "written_files": [str(main)],
                    "validation_result": {"validation_passed": True},
                    "_llm_client": CapturingLLM(),
                }
            )

        self.assertEqual(result["source"], "llm")
        self.assertLess(len(captured["prompt"]), 9000)
        self.assertNotIn("TAIL_SHOULD_BE_CROPPED", captured["prompt"])

    def test_product_judgment_detects_tkinter_runtime(self) -> None:
        autopilot = object.__new__(IntelligentAutopilot)
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            main = project / "main.py"
            main.write_text("import tkinter as tk\nroot = tk.Tk()\n", encoding="utf-8")
            judgment = autopilot._infer_product_judgment(
                original_goal="帮我做一个贪吃蛇",
                project_path=project,
                written_files=[str(main)],
            )

        self.assertEqual(judgment["current_runtime"], "tkinter_gui")
        self.assertEqual(judgment["preferred_stack"], "pygame")

    def test_fast_tool_retries_retryable_non_timeout_but_not_timeout(self) -> None:
        autopilot = object.__new__(IntelligentAutopilot)
        autopilot.tool_registry = SimpleNamespace(get=lambda name: SimpleNamespace(max_retries=2))
        autopilot.logger = RetryLogger()
        autopilot.session_id = "test"
        autopilot.enhanced_ui = None
        retryable_error = SimpleNamespace(
            error_type="NetworkError",
            error_message="temporary connection issue",
            retry_recommended=True,
        )
        timeout_error = SimpleNamespace(
            error_type="TimeoutError",
            error_message="Execution exceeded timeout of 300s",
            retry_recommended=True,
        )

        retryable_results = [
            SimpleNamespace(success=False, status="failed", error=retryable_error, output=None, duration_seconds=0.1),
            SimpleNamespace(success=True, status="success", error=None, output={"ok": True}, duration_seconds=0.1),
        ]
        autopilot.tool_executor = SimpleNamespace(execute_single=lambda selection, context=None: retryable_results.pop(0))
        result, history = autopilot._execute_tool_with_fast_retry(SimpleNamespace(tool_name="code_generator", step_id="s1"))

        self.assertTrue(result.success)
        self.assertEqual(len(history), 2)

        timeout_calls = {"count": 0}

        def timeout_once(selection, context=None):
            timeout_calls["count"] += 1
            return SimpleNamespace(success=False, status="timeout", error=timeout_error, output=None, duration_seconds=300)

        autopilot.tool_executor = SimpleNamespace(execute_single=timeout_once)
        result, history = autopilot._execute_tool_with_fast_retry(SimpleNamespace(tool_name="code_generator", step_id="s2"))

        self.assertFalse(result.success)
        self.assertEqual(len(history), 1)
        self.assertEqual(timeout_calls["count"], 1)

    def test_code_generation_pipeline_succeeds_with_surgical_retry(self) -> None:
        autopilot = object.__new__(IntelligentAutopilot)
        autopilot.enhanced_ui = None
        autopilot.logger = RetryLogger()
        autopilot.session_id = "test"

        def execute_attempt(self, *, mode=None, **kwargs):
            if mode in {"full", "compact"}:
                return {
                    "success": False,
                    "status": "timeout",
                    "error_type": "TimeoutError",
                    "error": "Execution exceeded timeout of 300s",
                    "duration_seconds": 300,
                    "step_id": f"{mode}_step",
                }
            return {
                "success": True,
                "status": "success",
                "result": {"code": "print('ok')\n"},
                "duration_seconds": 1,
                "step_id": "surgical_step",
            }

        autopilot._execute_code_generation_for_improvement = MethodType(execute_attempt, autopilot)
        result, history = autopilot._run_code_generation_retry_pipeline(
            task=SimpleNamespace(),
            iteration=1,
            goal="make snake",
            target_file=Path("Snake/main.py"),
            current_code="print('old')\n",
            evaluation=EvaluationResult(validation_passed=True, runnable=True, has_blocking_bugs=False, summary="ok"),
            actions=["Improve resize handling"],
            improvement_report={"must_implement_next": ["Resize handling works"]},
            is_repair=False,
        )

        self.assertTrue(result["success"])
        self.assertEqual([item["mode"] for item in history], ["full", "compact", "surgical"])

    def test_code_generation_pipeline_exhaustion_records_retry_history(self) -> None:
        autopilot = object.__new__(IntelligentAutopilot)
        autopilot.enhanced_ui = None
        autopilot.logger = RetryLogger()
        autopilot.session_id = "test"

        def timeout_attempt(self, *, mode=None, **kwargs):
            return {
                "success": False,
                "status": "timeout",
                "error_type": "TimeoutError",
                "error": "Execution exceeded timeout of 300s",
                "duration_seconds": 300,
                "step_id": f"{mode}_step",
            }

        autopilot._execute_code_generation_for_improvement = MethodType(timeout_attempt, autopilot)
        result, history = autopilot._run_code_generation_retry_pipeline(
            task=SimpleNamespace(),
            iteration=1,
            goal="make snake",
            target_file=Path("Snake/main.py"),
            current_code="print('old')\n",
            evaluation=EvaluationResult(validation_passed=True, runnable=True, has_blocking_bugs=False, summary="ok"),
            actions=["Improve resize handling"],
            improvement_report={"must_implement_next": ["Resize handling works"]},
            is_repair=False,
        )

        self.assertFalse(result["success"])
        self.assertEqual(len(history), 3)
        self.assertTrue(all(item["error_type"] == "TimeoutError" for item in history))

    def test_iteration_failure_result_keeps_retry_history(self) -> None:
        autopilot = object.__new__(IntelligentAutopilot)
        autopilot.enhanced_ui = None
        autopilot.logger = RetryLogger()
        autopilot.session_id = "test"

        def timeout_attempt(self, *, mode=None, **kwargs):
            return {
                "success": False,
                "status": "timeout",
                "error_type": "TimeoutError",
                "error": "Execution exceeded timeout of 300s",
                "duration_seconds": 300,
                "step_id": f"{mode}_step",
            }

        autopilot._execute_code_generation_for_improvement = MethodType(timeout_attempt, autopilot)

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "main.py"
            target.write_text("print('old')\n", encoding="utf-8")
            result = autopilot._apply_project_improvement(
                goal="make snake",
                project_path=Path(tmpdir),
                written_files=[str(target)],
                run_command="python main.py",
                readme_path=Path(tmpdir) / "README.md",
                iteration=1,
                evaluation=EvaluationResult(validation_passed=True, runnable=True, has_blocking_bugs=False, summary="ok"),
                actions=["Improve resize handling"],
                improvement_report={"must_implement_next": ["Resize handling works"]},
                is_repair=False,
            )

        self.assertFalse(result.success)
        self.assertEqual(result.failure_stage, "Task Executor")
        self.assertEqual(result.failed_tool, "code_generator")
        self.assertTrue(result.retry_attempted)
        self.assertEqual([item["mode"] for item in result.retry_history], ["full", "compact", "surgical"])


if __name__ == "__main__":
    unittest.main()
