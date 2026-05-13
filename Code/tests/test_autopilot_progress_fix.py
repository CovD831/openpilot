import json
import time
from io import StringIO

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel

from agents.task_decomposer import TaskDecomposer
from core.instrumented_llm import InstrumentedLLMClient
from core.llm import LLMClient, LLMResponse
from execution.intelligent_autopilot import IntelligentAutopilot
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
