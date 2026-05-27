from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from rich.console import Console

from ui.enhanced_ui import EnhancedUI


def _contains_node(node: dict, node_id: str) -> bool:
    if node.get("id") == node_id:
        return True
    return any(_contains_node(child, node_id) for child in node.get("children") or [])


def _contains_hidden_summary(node: dict) -> bool:
    description = str(node.get("description") or "")
    if node.get("kind") == "summary" or "details hidden" in description:
        return True
    return any(_contains_hidden_summary(child) for child in node.get("children") or [])


def _render_tail(ui: EnhancedUI) -> str:
    console = Console(record=True, width=100)
    console.print(ui.create_task_graph_live_tail())
    return console.export_text(clear=False)


def test_task_graph_live_view_grows_with_full_history() -> None:
    ui = EnhancedUI(Console(record=True, width=100))
    active_tool_id = "iteration_1_tool_18"
    stages = []
    for index in range(24):
        stage_id = f"iteration_1_stage_{index}"
        stages.append(
            {
                "id": stage_id,
                "description": f"Stage {index}",
                "status": "running" if index == 18 else "completed",
                "kind": "agent",
                "children": [
                    {
                        "id": f"iteration_1_tool_{index}",
                        "description": f"tool_{index}",
                        "status": "running" if index == 18 else "completed",
                        "kind": "tool",
                    }
                ],
            }
        )
    tasks = [
        {
            "id": "iteration_1",
            "description": "Iteration 1",
            "status": "running",
            "kind": "iteration",
            "children": stages,
        }
    ]
    full_rows = ui._task_graph_visible_rows(tasks)

    live_tasks = ui._task_graph_live_tasks(tasks, active_tool_id)

    assert live_tasks == tasks
    assert ui._task_graph_visible_rows(live_tasks) == full_rows
    assert ui._task_graph_panel_height(full_rows) == full_rows + 4
    assert _contains_node(live_tasks[0], active_tool_id)
    assert not _contains_hidden_summary(live_tasks[0])


def test_progress_dashboard_drops_current_task_region() -> None:
    ui = EnhancedUI(Console(record=True, width=100))
    ui.set_task_graph_state(
        goal="Long task",
        tasks=[
            {
                "id": "iteration_1",
                "description": "Iteration 1",
                "status": "running",
                "kind": "iteration",
                "children": [
                    {
                        "id": f"iteration_1_stage_{index}",
                        "description": f"Stage {index}",
                        "status": "completed",
                        "kind": "agent",
                    }
                    for index in range(30)
                ],
            }
        ],
        current_task_id="iteration_1",
    )

    layout = ui.create_progress_dashboard()

    assert [child.name for child in layout.children] == ["task_graph"]


def test_append_only_task_graph_has_no_panel_title_or_box() -> None:
    console = Console(record=True, width=100)
    ui = EnhancedUI(console)

    with ui.live_session("Executing: sample"):
        ui.set_task_graph_state(
            goal="Build app",
            tasks=[
                {
                    "id": "iteration_1",
                    "description": "Iteration 1",
                    "status": "running",
                    "kind": "iteration",
                }
            ],
            current_task_id="iteration_1",
        )

    output = console.export_text(clear=False)
    assert "Task Graph" not in output
    assert "Current Task Details" not in output
    assert "╭" not in output
    assert "Build app" in output
    assert "Iteration 1" not in output


def test_append_only_task_graph_keeps_running_nodes_out_of_history() -> None:
    console = Console(record=True, width=100)
    ui = EnhancedUI(console)
    task = {
        "id": "iteration_1",
        "description": "Iteration 1",
        "status": "running",
        "kind": "iteration",
        "children": [
            {
                "id": "iteration_1_execution",
                "description": "Task Executor",
                "status": "pending",
                "kind": "agent",
            }
        ],
    }

    with ui.live_session("Executing: sample"):
        ui.set_task_graph_state(goal="Build app", tasks=[task], current_task_id="iteration_1")
        ui.set_task_graph_state(goal="Build app", tasks=[task], current_task_id="iteration_1")
        changed_task = {
            **task,
            "children": [{**task["children"][0], "status": "running"}],
        }
        ui.set_task_graph_state(goal="Build app", tasks=[changed_task], current_task_id="iteration_1_execution")

    output = console.export_text(clear=False)
    assert "1. Iteration 1" not in output
    assert "Task Executor" not in output


def test_append_only_task_graph_prints_hierarchy_terminal_history() -> None:
    console = Console(record=True, width=100)
    ui = EnhancedUI(console)
    task = {
        "id": "iteration_1",
        "description": "Iteration 1",
        "status": "running",
        "kind": "iteration",
        "children": [
            {
                "id": "iteration_1_environment",
                "description": "Environment Setup",
                "status": "running",
                "kind": "agent",
            }
        ],
    }

    with ui.live_session("Executing: sample"):
        ui.set_task_graph_state(goal="Build app", tasks=[task], current_task_id="iteration_1_environment")
        ui.set_task_graph_state(
            goal="Build app",
            tasks=[
                {
                    **task,
                    "status": "completed",
                    "children": [{**task["children"][0], "status": "completed"}],
                }
            ],
            current_task_id=None,
        )

    output = console.export_text(clear=False)
    assert output.count("1. Iteration 1") == 1
    assert output.count("Environment Setup") == 1
    assert "✓ 1. Iteration 1" in output
    assert "✓ Environment Setup" in output


def test_append_only_task_graph_prints_terminal_state_after_active_pending_parent() -> None:
    console = Console(record=True, width=100)
    ui = EnhancedUI(console)
    task = {
        "id": "iteration_1",
        "description": "Iteration 1",
        "status": "running",
        "kind": "iteration",
        "children": [
            {
                "id": "iteration_1_project_state",
                "description": "Read Project State",
                "status": "pending",
                "kind": "agent",
                "children": [
                    {
                        "id": "iteration_1_project_state_tool",
                        "description": "project_state_reader",
                        "status": "completed",
                        "kind": "tool",
                    }
                ],
            }
        ],
    }

    with ui.live_session("Executing: sample"):
        ui.set_task_graph_state(goal="Build app", tasks=[task], current_task_id="iteration_1_project_state")
        ui.set_task_graph_state(
            goal="Build app",
            tasks=[
                {
                    **task,
                    "children": [{**task["children"][0], "status": "completed"}],
                }
            ],
            current_task_id="iteration_1_project_state",
        )

    output = console.export_text(clear=False)
    assert output.count("Read Project State") == 1
    assert "✓ Read Project State" in output


def test_task_graph_live_tail_renders_running_path_with_spinner() -> None:
    ui = EnhancedUI(Console(record=True, width=100))
    ui._task_graph_spinner_frame = "⠹"
    ui.set_task_graph_state(
        goal="Build app",
        tasks=[
            {
                "id": "iteration_1",
                "description": "Iteration 1",
                "status": "running",
                "kind": "iteration",
                "children": [
                    {
                        "id": "iteration_1_project_state",
                        "description": "Read Project State",
                        "status": "pending",
                        "kind": "agent",
                    }
                ],
            }
        ],
        current_task_id="iteration_1_project_state",
    )

    output = _render_tail(ui)

    assert "⠹ 1. Iteration 1" in output
    assert "⠹ Read Project State" in output


def test_task_graph_live_tail_clears_when_path_reaches_terminal_state() -> None:
    ui = EnhancedUI(Console(record=True, width=100))
    task = {
        "id": "iteration_1",
        "description": "Iteration 1",
        "status": "running",
        "kind": "iteration",
        "children": [
            {
                "id": "iteration_1_environment",
                "description": "Environment Setup",
                "status": "running",
                "kind": "agent",
            }
        ],
    }
    ui.set_task_graph_state(goal="Build app", tasks=[task], current_task_id="iteration_1_environment")
    assert "Environment Setup" in _render_tail(ui)

    ui.set_task_graph_state(
        tasks=[
            {
                **task,
                "status": "completed",
                "children": [{**task["children"][0], "status": "completed"}],
            }
        ],
        current_task_id=None,
    )

    assert _render_tail(ui).strip() == ""


def test_task_graph_live_tail_uses_progress_tracker_spinner_frame() -> None:
    class ActiveOperation:
        spinner_frame = "⠧"

    ui = EnhancedUI(Console(record=True, width=100))
    ui.set_task_graph_state(
        goal="Build app",
        tasks=[
            {
                "id": "iteration_1",
                "description": "Iteration 1",
                "status": "running",
                "kind": "iteration",
            }
        ],
        current_task_id="iteration_1",
    )

    ui.set_active_operations([ActiveOperation()])

    assert "⠧ 1. Iteration 1" in _render_tail(ui)


def test_task_graph_live_tail_renders_transient_llm_stream() -> None:
    ui = EnhancedUI(Console(record=True, width=100))
    ui.set_task_graph_state(
        goal="Build app",
        tasks=[
            {
                "id": "iteration_1",
                "description": "Iteration 1",
                "status": "running",
                "kind": "iteration",
            }
        ],
        current_task_id="iteration_1",
    )
    ui.set_active_operations(
        [
            SimpleNamespace(
                type=SimpleNamespace(value="llm"),
                name="LLM: fake-model",
                start_time=datetime.now(),
                spinner_frame="⠧",
                phase="Streaming response",
                stream_text="Public visible model output",
                response_preview="",
                tokens_or_chars=27,
            )
        ]
    )

    output = _render_tail(ui)

    assert "⠧ 1. Iteration 1" in output
    assert "LLM: fake-model" in output
    assert "Phase: Streaming response" in output
    assert "Public visible model output" in output


def test_tool_event_live_tail_renders_running_call() -> None:
    ui = EnhancedUI(Console(record=True, width=100))
    ui._task_graph_spinner_frame = "⠹"

    ui.append_tool_event(
        {
            "event_type": "running",
            "status": "running",
            "tool_name": "code_generator",
            "call_id": "task:r1:c1",
            "tool_call": {"reason": "generate implementation"},
        }
    )

    output = _render_tail(ui)
    assert "⠹ Tool: code_generator" in output
    assert "(r1:c1)" in output
    assert "generate implementation" in output


def test_tool_event_completed_enters_history_once_and_leaves_tail() -> None:
    console = Console(record=True, width=100)
    ui = EnhancedUI(console)

    with ui.live_session("Executing: sample"):
        ui.append_tool_event(
            {
                "event_type": "running",
                "status": "running",
                "tool_name": "file_writer",
                "call_id": "call_1",
                "tool_call": {"reason": "write file"},
            }
        )
        assert "file_writer" in _render_tail(ui)
        completed_event = {
            "event_type": "completed",
            "status": "completed",
            "tool_name": "file_writer",
            "call_id": "call_1",
        }
        ui.append_tool_event(completed_event)
        ui.append_tool_event(completed_event)
        assert "file_writer" not in _render_tail(ui)

    output = console.export_text(clear=False)
    assert output.count("Tool completed: file_writer (call_1)") == 1


def test_tool_event_recoverable_error_is_history_not_error_panel() -> None:
    console = Console(record=True, width=100)
    ui = EnhancedUI(console)

    with ui.live_session("Executing: sample"):
        ui.append_tool_event(
            {
                "event_type": "error",
                "status": "error",
                "tool_name": "code_generator",
                "call_id": "call_2",
                "recoverable": True,
                "tool_error": {
                    "recoverable": True,
                    "error_message": "Unsupported language: text",
                    "suggested_recovery": "Use a documentation writer instead.",
                },
            }
        )

    output = console.export_text(clear=False)
    assert "Tool error recovered: code_generator (call_2)" in output
    assert "Use a documentation writer instead." in output
    assert "Tool failed: code_generator (call_2)" not in output


def test_tool_event_terminal_error_enters_history_once() -> None:
    console = Console(record=True, width=100)
    ui = EnhancedUI(console)
    failed_event = {
        "event_type": "error",
        "status": "error",
        "tool_name": "file_writer",
        "call_id": "call_3",
        "recoverable": False,
        "tool_error": {
            "recoverable": False,
            "error_message": "Permission denied",
        },
    }

    with ui.live_session("Executing: sample"):
        ui.append_tool_event(failed_event)
        ui.append_tool_event(failed_event)

    output = console.export_text(clear=False)
    assert output.count("Tool failed: file_writer (call_3)") == 1


def test_task_graph_live_tail_clears_llm_stream_after_operation_finishes() -> None:
    ui = EnhancedUI(Console(record=True, width=100))
    ui.set_task_graph_state(
        goal="Build app",
        tasks=[
            {
                "id": "iteration_1",
                "description": "Iteration 1",
                "status": "running",
                "kind": "iteration",
            }
        ],
        current_task_id="iteration_1",
    )
    ui.set_active_operations(
        [
            SimpleNamespace(
                type=SimpleNamespace(value="llm"),
                name="LLM: fake-model",
                start_time=datetime.now(),
                spinner_frame="⠧",
                phase="Streaming response",
                stream_text="Temporary stream text",
                response_preview="",
                tokens_or_chars=21,
            )
        ]
    )
    assert "Temporary stream text" in _render_tail(ui)

    ui.set_active_operations([])

    output = _render_tail(ui)
    assert "Temporary stream text" not in output
    assert "1. Iteration 1" in output


def test_llm_stream_text_does_not_enter_append_only_history() -> None:
    console = Console(record=True, width=100)
    ui = EnhancedUI(console)

    with ui.live_session("Executing: sample"):
        ui.set_task_graph_state(
            goal="Build app",
            tasks=[
                {
                    "id": "iteration_1",
                    "description": "Iteration 1",
                    "status": "running",
                    "kind": "iteration",
                }
            ],
            current_task_id="iteration_1",
        )
        ui.set_active_operations(
            [
                SimpleNamespace(
                    type=SimpleNamespace(value="llm"),
                    name="LLM: fake-model",
                    start_time=datetime.now(),
                    spinner_frame="⠧",
                    phase="Streaming response",
                    stream_text="Do not keep this stream",
                    response_preview="",
                    tokens_or_chars=23,
                )
            ]
        )
        ui.set_active_operations([])

    output = console.export_text(clear=False)
    assert "Do not keep this stream" not in output


def test_transient_operation_session_preserves_task_graph_state_and_history() -> None:
    console = Console(record=True, width=100)
    ui = EnhancedUI(console)
    tasks = [
        {
            "id": "iteration_1",
            "description": "Iteration 1",
            "status": "completed",
            "kind": "iteration",
        }
    ]
    ui.set_task_graph_state(goal="Build app", tasks=tasks, current_task_id=None)
    ui._append_task_graph_seen = {"iteration_1": ("completed", "1. Iteration 1", "")}

    with ui.transient_operation_session():
        ui.set_active_operations(
            [
                SimpleNamespace(
                    type=SimpleNamespace(value="llm"),
                    name="LLM: fake-model",
                    start_time=datetime.now(),
                    spinner_frame="⠧",
                    phase="Streaming response",
                    stream_text="Temporary stream",
                    response_preview="",
                    tokens_or_chars=16,
                )
            ]
        )

    assert ui.task_graph_state["tasks"] == tasks
    assert ui._append_task_graph_seen == {"iteration_1": ("completed", "1. Iteration 1", "")}
    assert ui.active_operations == []


def test_transient_operation_session_only_clears_llm_operations() -> None:
    ui = EnhancedUI(Console(record=True, width=100))
    tool_operation = SimpleNamespace(
        type=SimpleNamespace(value="tool"),
        name="Tool: file_writer",
        start_time=datetime.now(),
        spinner_frame="⠧",
    )
    llm_operation = SimpleNamespace(
        type=SimpleNamespace(value="llm"),
        name="LLM: fake-model",
        start_time=datetime.now(),
        spinner_frame="⠧",
    )

    with ui.transient_operation_session():
        ui.set_active_operations([tool_operation, llm_operation])

    assert ui.active_operations == [tool_operation]


def test_append_only_task_graph_reset_reprints_goal_and_new_tree() -> None:
    console = Console(record=True, width=100)
    ui = EnhancedUI(console)

    with ui.live_session("Executing: sample"):
        ui.set_task_graph_state(
            goal="First goal",
            tasks=[
                {
                    "id": "iteration_1",
                    "description": "Iteration 1",
                    "status": "running",
                    "kind": "iteration",
                }
            ],
        )
        ui.set_task_graph_state(goal="Second goal", tasks=[], current_task_id=None)
        ui.set_task_graph_state(
            tasks=[
                {
                    "id": "iteration_1",
                    "description": "Iteration 1",
                    "status": "running",
                    "kind": "iteration",
                }
            ],
            current_task_id="iteration_1",
        )

    output = console.export_text(clear=False)
    assert "First goal" in output
    assert "Second goal" in output
    assert "1. Iteration 1" not in output


def test_append_only_task_graph_skips_generic_phase_graph() -> None:
    console = Console(record=True, width=100)
    ui = EnhancedUI(console)

    with ui.live_session("Executing: sample"):
        ui.set_task_graph_state(
            goal="Build app",
            stages=["Semantic Analysis", "Memory Retrieval", "Iteration 1"],
            stage_statuses={
                "Semantic Analysis": "completed",
                "Memory Retrieval": "running",
                "Iteration 1": "pending",
            },
            current_stage="Memory Retrieval",
            tasks=[],
        )

    output = console.export_text(clear=False)
    assert "Build app" not in output
    assert "Semantic Analysis" not in output
    assert "Memory Retrieval" not in output
    assert "1. Iteration 1" not in output


def test_append_only_task_graph_prints_terminal_tool_once_with_parent_context() -> None:
    console = Console(record=True, width=100)
    ui = EnhancedUI(console)
    task = {
        "id": "iteration_1",
        "description": "Iteration 1",
        "status": "running",
        "kind": "iteration",
        "children": [
            {
                "id": "iteration_1_environment",
                "description": "Environment Setup",
                "status": "pending",
                "kind": "agent",
                "children": [
                    {
                        "id": "iteration_1_environment_tool",
                        "description": "project_environment_tool",
                        "status": "running",
                        "kind": "tool",
                    }
                ],
            }
        ],
    }

    with ui.live_session("Executing: sample"):
        ui.set_task_graph_state(goal="Build app", tasks=[task], current_task_id="iteration_1_environment_tool")
        completed_task = {
            **task,
            "children": [
                {
                    **task["children"][0],
                    "children": [{**task["children"][0]["children"][0], "status": "completed"}],
                }
            ],
        }
        ui.set_task_graph_state(goal="Build app", tasks=[completed_task], current_task_id="iteration_1_environment")
        failed_task = {
            **completed_task,
            "children": [
                {
                    **completed_task["children"][0],
                    "children": [{**completed_task["children"][0]["children"][0], "status": "failed"}],
                }
            ],
        }
        ui.set_task_graph_state(goal="Build app", tasks=[failed_task], current_task_id="iteration_1_environment_tool")

    output = console.export_text(clear=False)
    assert "Environment Setup" not in output
    assert output.count("project_environment_tool") == 2
