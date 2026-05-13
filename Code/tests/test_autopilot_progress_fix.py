import json
import time
from io import StringIO

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel

from agents.iterative_improvement import IterativeImprovementController
from agents.project_evaluator import ProjectEvaluatorAgent
from agents.task_decomposer import TaskDecomposer
from core.instrumented_llm import InstrumentedLLMClient
from core.llm import LLMClient, LLMResponse
from execution.intelligent_autopilot import IntelligentAutopilot
from models.evaluation_models import EvaluationResult, IterationResult
from models.task_models import TaskExecutionResult, TaskStatus
from tools.builtin_tools import register_builtin_tools
from tools.code_reviewer import code_reviewer_executor
from tools.readme_tool import readme_tool_executor
from tools.tool_registry import ToolRegistry
from ui.enhanced_ui import EnhancedUI
from ui.progress_tracker import OperationType, ProgressTracker


class FakeLLM:
    def __init__(self):
        self.calls = []

    def complete(self, request, max_retries=3, use_cache=True):
        self.calls.append(
            {
                "request": request,
                "max_retries": max_retries,
                "use_cache": use_cache,
            }
        )
        if request.response_format == "json_object":
            payload = {
                "task_type": "coding",
                "risk_level": "medium",
                "required_resources": ["llm", "local_file", "code_execution"],
                "expected_deliverables": ["python file"],
                "intent": "create a snake game",
                "confidence": 0.95,
                "reason": "The goal asks to create a game file.",
            }
            return LLMResponse(
                content=json.dumps(payload),
                parsed_json=payload,
                model="fake",
                provider="fake",
            )

        code = "print('snake game ready')\n"
        return LLMResponse(
            content=f"```python\n{code}```",
            parsed_json=None,
            model="fake",
            provider="fake",
        )


class FakeRequest:
    def __init__(self, content: str, response_format: str = "text"):
        self.messages = [FakeMessage(content)]
        self.response_format = response_format


class FakeMessage:
    def __init__(self, content: str):
        self.content = content


class IteratingProjectLLM:
    def __init__(self):
        self.evaluation_calls = 0
        self.code_calls = 0

    def complete(self, request, max_retries=3, use_cache=True):
        prompt = request.messages[0].content if request.messages else ""
        if request.response_format == "json_object" and "Project Evaluator Agent" in prompt:
            self.evaluation_calls += 1
            payload = (
                {
                    "approved": False,
                    "satisfaction_score": 0.55,
                    "summary": "The first version is too minimal.",
                    "issues": ["No controls or scoring were detected."],
                    "improvement_opportunities": ["Add controls and score display."],
                    "recommended_actions": ["Add game loop, controls, scoring, food, and game-over handling."],
                    "next_iteration_goal": "Improve the snake game with controls and scoring.",
                }
                if self.evaluation_calls == 1
                else {
                    "approved": True,
                    "satisfaction_score": 0.92,
                    "summary": "The project now satisfies the game requirements.",
                    "issues": [],
                    "improvement_opportunities": [],
                    "recommended_actions": [],
                    "next_iteration_goal": None,
                }
            )
            return LLMResponse(
                content=json.dumps(payload),
                parsed_json=payload,
                model="fake",
                provider="fake",
            )
        if request.response_format == "json_object":
            payload = {
                "task_type": "coding",
                "risk_level": "medium",
                "required_resources": ["llm", "local_file", "code_execution"],
                "expected_deliverables": ["python file"],
                "intent": "create a snake game",
                "confidence": 0.95,
                "reason": "The goal asks to create a game file.",
            }
            return LLMResponse(
                content=json.dumps(payload),
                parsed_json=payload,
                model="fake",
                provider="fake",
            )

        self.code_calls += 1
        if self.code_calls == 1:
            code = "print('snake game ready')\n"
        else:
            code = """score = 0
snake = [(5, 5)]
food = (7, 7)
game_over = False

def handle_key(key):
    return key in {"up", "down", "left", "right"}

def collision(head):
    return head in snake[1:]

def main():
    global score, game_over
    direction = "right"
    while not game_over:
        handle_key(direction)
        score += 1
        if collision(snake[0]):
            game_over = True
        print(f"Score: {score} Food: {food}")
        break

if __name__ == "__main__":
    main()
"""
        return LLMResponse(
            content=f"```python\n{code}```",
            parsed_json=None,
            model="fake",
            provider="fake",
        )


def test_autopilot_reuses_enhanced_ui_and_tracker():
    ui = EnhancedUI(Console(file=StringIO()))
    tracker = ProgressTracker(ui)
    autopilot = IntelligentAutopilot(
        llm_client=FakeLLM(),
        console=ui.console,
        use_enhanced_ui=True,
        enhanced_ui=ui,
        tracker=tracker,
    )

    assert autopilot.enhanced_ui is ui
    assert autopilot.tracker is tracker


def test_instrumented_llm_preserves_retry_and_cache_arguments(monkeypatch):
    captured = {}

    def fake_complete(self, request, max_retries=3, use_cache=True):
        captured["max_retries"] = max_retries
        captured["use_cache"] = use_cache
        return LLMResponse(content="ok", model="fake", provider="fake")

    monkeypatch.setattr(LLMClient, "complete", fake_complete)

    client = InstrumentedLLMClient()
    client.complete(object(), max_retries=3, use_cache=True)

    assert captured == {"max_retries": 3, "use_cache": True}


def test_activity_panel_renders_spinner_between_timestamp_and_command():
    console_output = StringIO()
    ui = EnhancedUI(Console(file=console_output, width=120))
    tracker = ProgressTracker(ui)
    op_id = tracker._start_operation(
        OperationType.TOOL_CALL,
        "file_writer",
        {"file_path": "/tmp/demo.py"},
        phase="Executing",
    )
    tracker.append_operation_line(op_id, "file_path: /tmp/demo.py")
    ui.set_active_operations(tracker.get_active_operations())

    ui.console.print(ui.create_activity_panel())
    rendered = console_output.getvalue()

    assert "file_writer" in rendered
    assert any(frame in rendered for frame in ProgressTracker.SPINNER_FRAMES)
    assert rendered.index("[") < rendered.index("file_writer")


def test_active_llm_operation_displays_dim_trace_lines():
    console_output = StringIO()
    ui = EnhancedUI(Console(file=console_output, width=120))
    tracker = ProgressTracker(ui)
    op_id = tracker._start_operation(
        OperationType.LLM_CALL,
        "LLM: fake",
        {"prompt_preview": "public request summary"},
        phase="Waiting for model",
    )
    tracker.append_operation_line(op_id, "Preparing request")
    tracker.append_operation_line(op_id, "Waiting for model response")
    ui.set_active_operations(tracker.get_active_operations())

    ui.console.print(ui.create_activity_panel())
    rendered = console_output.getvalue()

    assert "LLM: fake" in rendered
    assert "Preparing request" in rendered
    assert "Waiting for model response" in rendered


def test_progress_dashboard_has_task_graph_and_current_details():
    console_output = StringIO()
    ui = EnhancedUI(Console(file=console_output, width=120))
    ui.set_task_graph_state(
        goal="Build demo",
        tasks=[
            {"id": "task-1", "description": "Generate code", "status": "running"},
            {"id": "task-2", "description": "Write README", "status": "pending"},
        ],
        current_task_id="task-1",
    )
    ui.set_current_task_state(
        title="Task 1/2",
        details="Generate code",
        status="running",
    )

    ui.console.print(ui.create_progress_dashboard())
    rendered = console_output.getvalue()

    assert "Task Graph" in rendered
    assert "Current Task Details" in rendered
    assert "Generate code" in rendered
    assert "Write README" in rendered


def test_dashboard_refreshes_active_operations_after_static_layout_update():
    console_output = StringIO()
    ui = EnhancedUI(Console(file=console_output, width=120))
    tracker = ProgressTracker(ui)
    legacy_layout = Layout(Panel("legacy static content"))
    ui.update_main_content(legacy_layout)
    op_id = tracker._start_operation(
        OperationType.TOOL_CALL,
        "file_writer",
        {"file_path": "/tmp/demo.py"},
        phase="Executing",
    )
    tracker.append_operation_line(op_id, "file_path: /tmp/demo.py")
    ui.set_active_operations(tracker.get_active_operations())

    ui.console.print(ui._compose_main_content(ui._main_content))
    rendered = console_output.getvalue()

    assert "Task Graph" in rendered
    assert "Current Task Details" in rendered
    assert "file_writer" in rendered
    assert "file_path: /tmp/demo.py" in rendered
    assert any(frame in rendered for frame in ProgressTracker.SPINNER_FRAMES)


def test_completed_llm_operation_is_removed_from_active_trace():
    console_output = StringIO()
    ui = EnhancedUI(Console(file=console_output, width=120))
    tracker = ProgressTracker(ui)
    with tracker.track_llm_call("fake", "prompt") as op_id:
        tracker.append_operation_line(op_id, "Transient line")

    ui.set_active_operations(tracker.get_active_operations())
    ui.console.print(ui.create_activity_panel())
    rendered = console_output.getvalue()

    assert "Transient line" not in rendered
    assert "fake responded" in rendered


def test_append_operation_line_caps_to_rolling_window():
    ui = EnhancedUI(Console(file=StringIO()))
    ui.max_active_trace_lines = 3
    tracker = ProgressTracker(ui)
    op_id = tracker._start_operation(OperationType.LLM_CALL, "LLM: fake", {})

    for index in range(6):
        tracker.append_operation_line(op_id, f"line {index}")

    op = tracker.operations[op_id]
    assert op.display_lines == ["line 3", "line 4", "line 5"]


def test_update_loop_advances_spinner_frames():
    ui = EnhancedUI(Console(file=StringIO()))
    tracker = ProgressTracker(ui)
    op_id = tracker._start_operation(OperationType.TOOL_CALL, "file_writer", {})
    before = tracker.operations[op_id].spinner_frame

    tracker.start_tracking()
    try:
        time.sleep(0.6)
    finally:
        tracker.stop_tracking()

    after = tracker.operations[op_id].spinner_frame
    assert after != before


def test_instrumented_llm_records_public_trace(monkeypatch):
    ui = EnhancedUI(Console(file=StringIO()))
    tracker = ProgressTracker(ui)

    def fake_complete(self, request, max_retries=3, use_cache=True):
        return LLMResponse(
            content='{"ok": true}',
            parsed_json={"ok": True},
            model="fake",
            provider="fake",
            usage={"total_tokens": 4},
        )

    monkeypatch.setattr(LLMClient, "complete", fake_complete)

    client = InstrumentedLLMClient(tracker=tracker)
    client.complete(FakeRequest("public prompt", response_format="json_object"))

    completed = tracker.get_completed_operations(limit=1)[0]
    trace = "\n".join(completed.display_lines or [])
    assert "Preparing request" in trace
    assert "Waiting for model response" in trace
    assert "Response format: json_object" in trace
    assert "Response parsed" in trace
    assert "hidden" not in trace.lower()


def test_instrumented_llm_records_failed_status_without_hidden_reasoning(monkeypatch):
    ui = EnhancedUI(Console(file=StringIO()))
    tracker = ProgressTracker(ui)

    def fake_complete(self, request, max_retries=3, use_cache=True):
        raise ValueError("invalid json after retry")

    monkeypatch.setattr(LLMClient, "complete", fake_complete)

    client = InstrumentedLLMClient(tracker=tracker)
    try:
        client.complete(FakeRequest("public prompt", response_format="json_object"))
    except ValueError:
        pass

    completed = tracker.get_completed_operations(limit=1)[0]
    trace = "\n".join(completed.display_lines or [])
    assert "retries allowed: 3" in trace
    assert "invalid json after retry" in trace
    assert "chain-of-thought" not in trace.lower()


def test_output_placeholder_is_replaced_with_generated_code():
    autopilot = IntelligentAutopilot(llm_client=FakeLLM())
    params = autopilot._resolve_chained_inputs(
        "file_writer",
        {"file_path": "/tmp/demo.py", "content": "{{code_generator.output}}"},
        last_output=None,
        last_code_output={"code": "print('real code')", "language": "python"},
    )

    assert params["content"] == "print('real code')"


def test_code_reviewer_executor_uses_static_reviewer_contract():
    result = code_reviewer_executor(
        {
            "code": "def main():\n    return 1\n",
            "language": "python",
        }
    )

    assert result["approved"] is True
    assert "issues" in result
    assert "suggestions" in result
    assert "syntax_errors" in result


def test_readme_tool_writes_usage_instructions(tmp_path):
    main_file = tmp_path / "main.py"
    main_file.write_text("print('hello')\n", encoding="utf-8")

    result = readme_tool_executor(
        {
            "project_path": str(tmp_path),
            "project_summary": "A tiny demo app",
            "written_files": [str(main_file)],
            "entry_files": [str(main_file)],
        }
    )

    readme = tmp_path / "README.md"
    content = readme.read_text(encoding="utf-8")
    assert result["file_path"] == str(readme.absolute())
    assert result["run_command"] == "python main.py"
    assert "# " in content
    assert "A tiny demo app" in content
    assert "python main.py" in content
    assert "`main.py`" in content
    assert "{{" not in content


def test_readme_tool_infers_pygame_setup(tmp_path):
    main_file = tmp_path / "main.py"
    main_file.write_text("import pygame\nprint('snake')\n", encoding="utf-8")

    result = readme_tool_executor(
        {
            "project_path": str(tmp_path),
            "written_files": [str(main_file)],
            "entry_files": [str(main_file)],
        }
    )

    assert result["setup_commands"] == ["pip install pygame"]
    assert "pip install pygame" in (tmp_path / "README.md").read_text(encoding="utf-8")


def test_builtin_registry_includes_readme_tool():
    registry = ToolRegistry()
    register_builtin_tools(registry)

    assert registry.get("readme_tool") is not None


def test_project_evaluator_approves_complete_snake_project(tmp_path):
    main_file = tmp_path / "main.py"
    main_file.write_text(
        """
score = 0
snake = [(5, 5)]
food = (8, 8)
game_over = False

def handle_key(key):
    return key in {"up", "down", "left", "right"}

def collision(head):
    return head in snake[1:]

def main():
    global score, game_over
    while not game_over:
        handle_key("right")
        score += 1
        if collision(snake[0]):
            game_over = True
        print(f"Score: {score} Food: {food}")
        break

if __name__ == "__main__":
    main()
""",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("## Run\n\n```bash\npython main.py\n```\n", encoding="utf-8")

    result = ProjectEvaluatorAgent(satisfaction_threshold=0.85).evaluate_project(
        goal="做一个贪吃蛇小游戏",
        project_path=tmp_path,
        written_files=[str(main_file)],
        run_command="python main.py",
    )

    assert result.approved is True
    assert result.satisfaction_score >= 0.85


def test_project_evaluator_flags_missing_run_instructions_and_placeholders(tmp_path):
    main_file = tmp_path / "main.py"
    main_file.write_text("{{code_generator.output}}\n", encoding="utf-8")

    result = ProjectEvaluatorAgent(satisfaction_threshold=0.85).evaluate_project(
        goal="做一个贪吃蛇小游戏",
        project_path=tmp_path,
        written_files=[str(main_file)],
    )

    assert result.approved is False
    assert result.satisfaction_score < 0.85
    assert any("placeholder" in issue.lower() for issue in result.issues)
    assert any("run" in issue.lower() for issue in result.issues)


def test_iteration_controller_stops_when_evaluation_is_approved(tmp_path):
    class ApprovedEvaluator:
        def evaluate_project(self, **kwargs):
            return EvaluationResult(
                approved=True,
                satisfaction_score=0.91,
                summary="Approved",
            )

    controller = IterativeImprovementController(ApprovedEvaluator(), max_iterations=2)
    calls = []

    result = controller.run(
        goal="demo",
        project_path=tmp_path,
        written_files=[],
        apply_improvement=lambda iteration, evaluation, actions: calls.append(iteration),
    )

    assert result["approved"] is True
    assert result["iterations"] == []
    assert calls == []


def test_iteration_controller_stops_at_two_rounds(tmp_path):
    class LowEvaluator:
        def evaluate_project(self, **kwargs):
            return EvaluationResult(
                approved=False,
                satisfaction_score=0.4,
                summary="Needs work",
                recommended_actions=["Improve controls", "Improve scoring"],
            )

    controller = IterativeImprovementController(LowEvaluator(), max_iterations=2)

    def apply(iteration, evaluation, actions):
        return IterationResult(
            iteration=iteration,
            before_score=evaluation.satisfaction_score,
            applied_actions=actions,
            changed_files=[str(tmp_path / "main.py")],
            success=True,
        )

    result = controller.run(
        goal="demo",
        project_path=tmp_path,
        written_files=[str(tmp_path / "main.py")],
        apply_improvement=apply,
    )

    assert len(result["iterations"]) == 2


def test_fast_path_writes_non_placeholder_python_file(tmp_path):
    ui = EnhancedUI(Console(file=StringIO()))
    tracker = ProgressTracker(ui)
    autopilot = IntelligentAutopilot(
        llm_client=FakeLLM(),
        console=ui.console,
        use_enhanced_ui=True,
        enhanced_ui=ui,
        tracker=tracker,
    )

    goal = f"在'{tmp_path}'中做一个贪吃蛇"
    try:
        result = autopilot.execute(goal)
    finally:
        tracker.stop_tracking()

    output_file = tmp_path / "main.py"
    readme_file = tmp_path / "README.md"
    assert result["success"] is True
    assert result["fast_path"] is True
    assert output_file.exists()
    assert readme_file.exists()
    assert output_file.read_text(encoding="utf-8") == "print('snake game ready')"
    assert "python main.py" in readme_file.read_text(encoding="utf-8")
    assert "{{code_generator.output}}" not in output_file.read_text(encoding="utf-8")

    activity = "\n".join(message for _, message, _ in ui.activity_log)
    assert "Semantic Analysis" in activity
    assert "Task Decomposition" in activity
    assert "file_writer" in activity
    graph_tasks = {task["id"]: task["status"] for task in ui.task_graph_state["tasks"]}
    assert graph_tasks["fast_code_generator"] == "completed"
    assert graph_tasks["fast_file_writer"] == "completed"
    assert graph_tasks["fast_readme_tool"] == "completed"


def test_fast_path_runs_iterative_project_improvement(tmp_path):
    ui = EnhancedUI(Console(file=StringIO()))
    tracker = ProgressTracker(ui)
    autopilot = IntelligentAutopilot(
        llm_client=IteratingProjectLLM(),
        console=ui.console,
        use_enhanced_ui=True,
        enhanced_ui=ui,
        tracker=tracker,
    )

    goal = f"在'{tmp_path}'中做一个贪吃蛇"
    try:
        result = autopilot.execute(goal)
    finally:
        tracker.stop_tracking()

    output = (tmp_path / "main.py").read_text(encoding="utf-8")
    assert result["success"] is True
    assert result["evaluation"].approved is True
    assert result["evaluation"].satisfaction_score >= 0.85
    assert len(result["iterations"]) == 1
    assert "Score:" in output
    assert "collision" in output
    graph_tasks = {task["id"]: task["status"] for task in ui.task_graph_state["tasks"]}
    assert graph_tasks["evaluation"] == "completed"
    assert graph_tasks["iteration_1"] == "completed"


def test_generic_readme_finalizer_uses_file_writer_outputs(tmp_path):
    output_file = tmp_path / "main.py"
    output_file.write_text("print('ready')\n", encoding="utf-8")
    autopilot = IntelligentAutopilot(llm_client=FakeLLM())
    task_result = TaskExecutionResult(
        task_id="task-1",
        status=TaskStatus.COMPLETED,
        result={
            "tool_calls": [
                {
                    "tool": "file_writer",
                    "params": {"file_path": str(output_file)},
                    "result": {"file_path": str(output_file)},
                    "success": True,
                    "error": None,
                }
            ]
        },
        duration=0.1,
    )

    result = autopilot._finalize_project_readme(f"在'{tmp_path}'中做一个项目", [task_result])

    assert result is not None
    assert result["success"] is True
    assert (tmp_path / "README.md").exists()
    assert "python main.py" in (tmp_path / "README.md").read_text(encoding="utf-8")


def test_generic_readme_finalizer_skips_when_readme_tool_already_ran(tmp_path):
    autopilot = IntelligentAutopilot(llm_client=FakeLLM())
    task_result = TaskExecutionResult(
        task_id="task-1",
        status=TaskStatus.COMPLETED,
        result={
            "tool_calls": [
                {
                    "tool": "readme_tool",
                    "result": {"file_path": str(tmp_path / "README.md")},
                    "success": True,
                    "error": None,
                }
            ]
        },
        duration=0.1,
    )

    result = autopilot._finalize_project_readme(f"在'{tmp_path}'中做一个项目", [task_result])

    assert result is None
    assert not (tmp_path / "README.md").exists()


def test_simple_code_artifact_decomposition_is_capped_to_three_subtasks():
    subtasks = [
        {
            "description": f"Subtask {index}",
            "priority": "medium",
            "estimated_effort": 1.0,
            "dependencies": [],
            "tags": [],
        }
        for index in range(5)
    ]

    class DecomposeLLM:
        def complete(self, request):
            payload = {"rationale": "many tasks", "subtasks": subtasks}
            return LLMResponse(
                content=json.dumps(payload),
                parsed_json=payload,
                model="fake",
                provider="fake",
            )

    result = TaskDecomposer(DecomposeLLM()).decompose("在'/tmp/TestDemo-Snake'中做一个贪吃蛇")

    assert len(result.subtasks) == 3
