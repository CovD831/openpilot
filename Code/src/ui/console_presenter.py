"""Console presentation helpers for the autopilot execution shell."""

from __future__ import annotations

from typing import Any, Callable

from rich.console import Console
from rich.panel import Panel
from rich.tree import Tree

from core.openpilot_log import OpenPilotLogger


class ConsolePresenter:
    """Render standard console views without touching execution state."""

    def __init__(
        self,
        console: Console,
        *,
        auto_approve_getter: Callable[[], bool] | None = None,
        stats_getter: Callable[[], dict[str, Any]] | None = None,
        logger: OpenPilotLogger | None = None,
        session_id_getter: Callable[[], str | None] | None = None,
    ) -> None:
        self.console = console
        self.auto_approve_getter = auto_approve_getter or (lambda: True)
        self.stats_getter = stats_getter or (lambda: {})
        self.logger = logger
        self.session_id_getter = session_id_getter or (lambda: None)

    def show_start_panel(self, goal: str) -> None:
        """Show the execution start panel."""
        panel = Panel(
            f"[bold cyan]Goal:[/bold cyan] {goal}\n\n"
            f"[dim]Mode: Intelligent Autopilot (Dynamic Task Decomposition)[/dim]\n"
            f"[dim]Auto-approve: {'Yes' if self.auto_approve_getter() else 'No'}[/dim]",
            title="[bold green]🚀 Intelligent Autopilot Activated[/bold green]",
            border_style="green",
        )
        self.console.print(panel)
        self.console.print()
        self._log("start_panel_rendered", input_summary={"goal": goal}, success=True)

    def show_task_tree(self, decomposition: Any) -> None:
        """Show task decomposition as a console tree."""
        tree = Tree(
            f"[bold]{decomposition.original_task.description}[/bold]",
            guide_style="dim",
        )

        for subtask in decomposition.subtasks:
            priority = subtask.priority.value if hasattr(subtask.priority, "value") else str(subtask.priority)
            priority_color = {
                "critical": "red",
                "high": "yellow",
                "medium": "cyan",
                "low": "dim",
            }.get(priority, "white")

            effort_str = f"{subtask.estimated_effort:.1f}u" if subtask.estimated_effort else "?"
            branch = tree.add(
                f"[{priority_color}]●[/{priority_color}] "
                f"{subtask.description} "
                f"[dim]({effort_str})[/dim]"
            )

            if subtask.dependencies:
                branch.add(f"[dim]Depends on: {len(subtask.dependencies)} task(s)[/dim]")

        self.console.print(tree)
        self.console.print()
        self._log(
            "task_tree_rendered",
            input_summary={"subtasks": len(decomposition.subtasks)},
            success=True,
        )

    def show_completion_summary(self, decomposition: Any, results: list[Any]) -> None:
        """Show the final execution summary."""
        stats = self.stats_getter()
        start_time = stats.get("start_time")
        end_time = stats.get("end_time")
        duration = (end_time - start_time).total_seconds() if start_time and end_time else 0.0

        self.console.print()
        self.console.print("━" * 80)

        if stats.get("success"):
            self.console.print("[bold green]✨ Autopilot mission completed successfully![/bold green]")
        else:
            self.console.print("[bold yellow]⚠ Autopilot mission completed with errors[/bold yellow]")

        self.console.print("━" * 80)
        self.console.print()
        self.console.print(f"[cyan]Total duration:[/cyan] {duration:.1f}s")
        self.console.print(f"[cyan]Tasks completed:[/cyan] {stats.get('tasks_completed', 0)}/{len(decomposition.subtasks)}")

        if stats.get("tasks_failed", 0) > 0:
            self.console.print(f"[yellow]Tasks failed:[/yellow] {stats['tasks_failed']}")

        if decomposition.subtasks:
            success_rate = stats.get("tasks_completed", 0) / len(decomposition.subtasks) * 100
            self.console.print(f"[cyan]Success rate:[/cyan] {success_rate:.0f}%")

        self.console.print()
        self._log(
            "completion_summary_rendered",
            input_summary={"results": len(results), "subtasks": len(decomposition.subtasks)},
            output_summary={"success": stats.get("success")},
            success=True,
        )

    def build_task_graph_for_ui(self, decomposition: Any) -> dict[str, Any]:
        """Build task graph structure for enhanced UI display."""
        tasks = []

        for subtask in decomposition.subtasks:
            task_dict = {
                "name": subtask.description,
                "status": subtask.status.value if hasattr(subtask.status, "value") else str(subtask.status),
                "priority": subtask.priority.value if hasattr(subtask.priority, "value") else str(subtask.priority),
                "estimated_effort": subtask.estimated_effort,
            }

            if subtask.dependencies:
                task_dict["dependencies"] = len(subtask.dependencies)

            tasks.append(task_dict)

        graph = {
            "original_task": decomposition.original_task.description,
            "tasks": tasks,
            "total_effort": decomposition.estimated_total_effort,
        }
        self._log(
            "task_graph_built",
            input_summary={"subtasks": len(decomposition.subtasks)},
            output_summary={"tasks": len(tasks)},
            success=True,
        )
        return graph

    def _log(
        self,
        event_type: str,
        *,
        success: bool | None = None,
        input_summary: Any | None = None,
        output_summary: Any | None = None,
        error: str | None = None,
    ) -> None:
        if not self.logger:
            return
        self.logger.log_structured_event(
            source_type="function",
            source_name="ui.console_presenter",
            phase="presentation",
            event_type=event_type,
            session_id=self.session_id_getter() or "unknown",
            turn_id=1,
            success=success,
            input_summary=input_summary,
            output_summary=output_summary,
            error=error,
        )
