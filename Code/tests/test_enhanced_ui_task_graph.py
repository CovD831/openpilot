from __future__ import annotations

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
    assert "Iteration 1" in output


def test_append_only_task_graph_prints_only_changed_nodes() -> None:
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
    assert output.count("1. Iteration 1") == 1
    assert output.count("Task Executor") == 1


def test_append_only_task_graph_prints_hierarchy_terminal_transitions() -> None:
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
    assert output.count("1. Iteration 1") == 2
    assert output.count("Environment Setup") == 2
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
    assert output.count("Read Project State") == 2
    assert "✓ Read Project State" in output


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
    assert output.count("1. Iteration 1") == 2


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
    assert output.count("Environment Setup") == 1
    assert output.count("project_environment_tool") == 2
    assert output.index("Environment Setup") < output.index("project_environment_tool")
