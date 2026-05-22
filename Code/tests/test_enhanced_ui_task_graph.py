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
