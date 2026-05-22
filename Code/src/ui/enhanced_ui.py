"""Enhanced UI components with Claude Code-style interface."""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Optional

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.text import Text
from rich.tree import Tree
from rich.align import Align
from rich.box import ROUNDED, HEAVY, DOUBLE
from rich.style import Style


class EnhancedUI:
    """Enhanced UI with Claude Code-style interface and real-time updates."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()
        self.live: Optional[Live] = None
        self.current_layout: Optional[Layout] = None
        self._main_content: Any | None = None
        self.activity_log: list[tuple[str, str, datetime]] = []
        self.active_operations: list[Any] = []
        self.max_log_lines = 10
        self.max_active_trace_lines = 8
        self.spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._task_graph_spinner_index = 0
        self._task_graph_spinner_frame = self.spinner_frames[0]
        self.task_graph_state: dict[str, Any] = {
            "goal": "",
            "stages": [],
            "stage_statuses": {},
            "current_stage": "",
            "tasks": [],
            "current_task_id": None,
        }
        self.current_task_state: dict[str, Any] = {
            "title": "Waiting",
            "details": "",
            "status": "idle",
        }

    def show_banner(self):
        """Display OpenPilot banner."""
        banner = Text()
        banner.append("╔═══════════════════════════════════════════════════════════╗\n", style="bold cyan")
        banner.append("║                                                           ║\n", style="bold cyan")
        banner.append("║              ", style="bold cyan")
        banner.append("🚀 OpenPilot AI Agent System", style="bold white")
        banner.append("              ║\n", style="bold cyan")
        banner.append("║                                                           ║\n", style="bold cyan")
        banner.append("║          ", style="bold cyan")
        banner.append("Intelligent Task Decomposition & Execution", style="dim white")
        banner.append("         ║\n", style="bold cyan")
        banner.append("║                                                           ║\n", style="bold cyan")
        banner.append("╚═══════════════════════════════════════════════════════════╝", style="bold cyan")

        self.console.print(banner)
        self.console.print()

    def show_menu(self, title: str, options: list[tuple[str, str]], selected: int = 0) -> Panel:
        """Create an interactive menu panel."""
        menu_items = []
        for i, (key, description) in enumerate(options):
            if i == selected:
                prefix = "▶ "
                style = "bold cyan on black"
            else:
                prefix = "  "
                style = "white"

            menu_items.append(Text(f"{prefix}{key}: {description}", style=style))

        menu_group = Group(*menu_items)
        return Panel(
            menu_group,
            title=f"[bold cyan]{title}[/bold cyan]",
            border_style="cyan",
            box=ROUNDED,
            padding=(1, 2),
        )

    def create_status_panel(self, status: str, details: str = "") -> Panel:
        """Create a status panel."""
        content = Text()
        content.append("Status: ", style="bold white")

        if "running" in status.lower() or "executing" in status.lower():
            content.append(status, style="bold yellow")
            icon = "⚙️ "
        elif "success" in status.lower() or "complete" in status.lower():
            content.append(status, style="bold green")
            icon = "✅ "
        elif "error" in status.lower() or "failed" in status.lower():
            content.append(status, style="bold red")
            icon = "❌ "
        else:
            content.append(status, style="bold blue")
            icon = "ℹ️ "

        if details:
            content.append(f"\n{details}", style="dim white")

        return Panel(
            content,
            title=f"{icon}[bold]System Status[/bold]",
            border_style="blue",
            box=ROUNDED,
        )

    def create_activity_panel(self) -> Panel:
        """Create activity log panel showing recent actions."""
        return self.create_current_task_panel(title="[bold]Current Task Details[/bold]")

    def create_current_task_panel(self, title: str = "[bold]Current Task Details[/bold]", extra_content: Any | None = None) -> Panel:
        """Create the live current-task panel with active operations and recent history."""
        active_rows = []

        if self.current_task_state:
            task_title = self.current_task_state.get("title") or "Waiting"
            task_status = self.current_task_state.get("status") or "idle"
            task_details = self.current_task_state.get("details") or ""
            header = Text()
            header.append(f"{task_title}", style="bold white")
            header.append(f" · {task_status}", style="dim")
            active_rows.append(header)
            if task_details:
                detail_limit = 9 if self._is_failure_summary_state(task_status, task_details) else 4
                for detail_line in str(task_details).splitlines()[:detail_limit]:
                    active_rows.append(Text(f"    {detail_line}", style="dim"))

        visible_operations = [] if self._is_failure_summary_state(
            self.current_task_state.get("status") or "",
            self.current_task_state.get("details") or "",
        ) else self.active_operations

        for op in visible_operations:
            elapsed = (datetime.now() - op.start_time).total_seconds()
            op_type = op.type.value if hasattr(op.type, "value") else str(op.type)
            if op_type == "llm":
                style = "magenta"
            elif op_type == "tool":
                style = "cyan"
            else:
                style = "yellow"

            line = Text()
            line.append(f"[{op.start_time.strftime('%H:%M:%S')}] ", style="dim")
            line.append(f"{op.spinner_frame or '⠋'} ", style=style)
            line.append(f"{op.name} ", style=style)
            line.append(f"running {elapsed:.1f}s", style="dim")
            if op.phase:
                line.append(f" · {op.phase}", style="dim")
            active_rows.append(line)

            display_lines = op.display_lines or []
            if display_lines:
                for trace_line in display_lines[-self.max_active_trace_lines:]:
                    active_rows.append(Text(f"    {trace_line}", style="dim"))
            if op.response_preview:
                active_rows.append(
                    Text(f"    Response preview: {op.response_preview}", style="dim")
                )
            if getattr(op, "token_usage_text", ""):
                active_rows.append(
                    Text(f"    {op.token_usage_text}", style="dim")
                )
            if op.tokens_or_chars:
                active_rows.append(
                    Text(f"    Response: {op.tokens_or_chars} chars", style="dim")
                )

        if extra_content is not None:
            if active_rows:
                active_rows.append(Text("-" * 28, style="dim"))
            active_rows.append(extra_content)

        log_rows = []
        if active_rows and self.activity_log:
            log_rows.append(Text("-" * 28, style="dim"))

        if not self.activity_log and not active_rows:
            content = Text("No recent activity", style="dim")
        else:
            for action_type, message, timestamp in self.activity_log[-self.max_log_lines:]:
                time_str = timestamp.strftime("%H:%M:%S")

                if action_type == "tool":
                    icon = ">"
                    style = "cyan"
                elif action_type == "llm":
                    icon = "..."
                    style = "magenta"
                elif action_type == "success":
                    icon = "✓"
                    style = "green"
                elif action_type == "error":
                    icon = "✗"
                    style = "red"
                else:
                    icon = "•"
                    style = "white"

                line = Text()
                line.append(f"[{time_str}] ", style="dim")
                line.append(f"{icon} ", style=style)
                line.append(message, style=style)
                log_rows.append(line)

            remaining = max(0, self.max_log_lines - len(active_rows))
            visible_logs = log_rows[-remaining:] if remaining else []
            content = Group(*(active_rows + visible_logs))

        return Panel(
            content,
            title=title,
            border_style="yellow",
            box=ROUNDED,
            height=self.max_log_lines + 4,
        )

    def _is_failure_summary_state(self, status: str, details: str) -> bool:
        """Return true when details should outrank transient operation traces."""
        status_text = (status or "").lower()
        details_text = str(details or "").lower()
        if status_text in {"failed", "warning", "needs improvement", "stopped"}:
            return any(marker in details_text for marker in ("failure", "failed", "reason:", "tool:"))
        return False

    def set_task_graph_state(
        self,
        *,
        goal: str | None = None,
        stages: list[str] | None = None,
        stage_statuses: dict[str, str] | None = None,
        current_stage: str | None = None,
        tasks: list[dict[str, Any]] | None = None,
        current_task_id: str | None = None,
    ) -> None:
        """Update the persistent task graph area."""
        if goal is not None:
            self.task_graph_state["goal"] = goal
        if stages is not None:
            self.task_graph_state["stages"] = stages
        if stage_statuses is not None:
            self.task_graph_state["stage_statuses"] = stage_statuses
        if current_stage is not None:
            self.task_graph_state["current_stage"] = current_stage
        if tasks is not None:
            self.task_graph_state["tasks"] = tasks
        if current_task_id is not None:
            self.task_graph_state["current_task_id"] = current_task_id
        self._refresh_main_content()

    def set_current_task_state(
        self,
        *,
        title: str | None = None,
        details: str | None = None,
        status: str | None = None,
    ) -> None:
        """Update the persistent current task summary."""
        if title is not None:
            self.current_task_state["title"] = title
        if details is not None:
            self.current_task_state["details"] = details
        if status is not None:
            self.current_task_state["status"] = status
        self._refresh_main_content()

    def create_task_graph_state_panel(self) -> Panel:
        """Render the persistent task graph or phase graph."""
        goal = self.task_graph_state.get("goal") or "OpenPilot task"
        tasks = self.task_graph_state.get("tasks") or []
        current_task_id = self.task_graph_state.get("current_task_id")

        if tasks:
            tree = Tree(f"[bold]{goal}[/bold]", guide_style="dim")
            display_tasks = self._task_graph_live_tasks(tasks, current_task_id)
            for index, task in enumerate(display_tasks, 1):
                self._add_task_graph_node(
                    tree,
                    task,
                    current_task_id=current_task_id,
                    index=index,
                    depth=0,
                )
        else:
            stages = self.task_graph_state.get("stages") or [
                "Semantic Analysis",
                "Memory Retrieval",
                "Task Decomposition",
                "Execution",
                "Result Assembly",
            ]
            statuses = self.task_graph_state.get("stage_statuses") or {}
            current_stage = self.task_graph_state.get("current_stage")
            tree = Tree(f"[bold]{goal}[/bold]", guide_style="dim")
            for stage in stages:
                status = statuses.get(stage, "pending")
                if stage == current_stage and status not in {"completed", "failed"}:
                    status = "running"
                style, icon = self._status_style_icon(status, active=stage == current_stage)
                tree.add(f"{icon} [{style}]{stage}[/{style}] [dim]{status}[/dim]")

        visible_rows = self._task_graph_visible_rows(display_tasks) if tasks else len(stages)
        panel_height = self._task_graph_panel_height(visible_rows)

        return Panel(
            tree,
            title="[bold]Task Graph[/bold]",
            border_style="cyan",
            box=ROUNDED,
            height=panel_height,
        )

    def create_progress_dashboard(self, extra_content: Any | None = None) -> Layout:
        """Create the fixed two-region autopilot dashboard."""
        layout = Layout()
        tasks = self.task_graph_state.get("tasks") or []
        stages = self.task_graph_state.get("stages") or []
        current_task_id = self.task_graph_state.get("current_task_id")
        display_tasks = self._task_graph_live_tasks(tasks, current_task_id) if tasks else []
        graph_rows = self._task_graph_visible_rows(display_tasks) if tasks else len(stages or [])
        layout.split_column(
            Layout(
                self.create_task_graph_state_panel(),
                name="task_graph",
                size=self._task_graph_panel_height(graph_rows),
            ),
            Layout(
                self.create_current_task_panel(extra_content=extra_content),
                name="current_task",
            ),
        )
        return layout

    def create_full_task_graph_timeline_panel(self) -> Panel | None:
        """Render the full task graph timeline without live-dashboard height limits."""
        tasks = self.task_graph_state.get("tasks") or []
        if not tasks:
            return None
        goal = self.task_graph_state.get("goal") or "OpenPilot task"
        current_task_id = self.task_graph_state.get("current_task_id")
        tree = Tree(f"[bold]{goal}[/bold]", guide_style="dim")
        for index, task in enumerate(tasks, 1):
            self._add_task_graph_node(
                tree,
                task,
                current_task_id=current_task_id,
                index=index,
                depth=0,
            )
        return Panel(
            tree,
            title="[bold]Full Task Graph Timeline[/bold]",
            border_style="cyan",
            box=ROUNDED,
        )

    def show_full_task_graph_timeline(self) -> None:
        """Print the full task graph timeline into terminal scrollback."""
        panel = self.create_full_task_graph_timeline_panel()
        if panel is not None:
            self.console.print(panel)

    def _add_task_graph_node(
        self,
        parent,
        node: dict[str, Any],
        *,
        current_task_id: str | None,
        index: int,
        depth: int,
    ):
        status = node.get("status", "pending")
        style, icon = self._status_style_icon(status, active=node.get("id") == current_task_id)
        description = node.get("description", "Untitled task")
        label = self._task_graph_node_label(node, description, index=index, depth=depth)
        effort = node.get("effort")
        suffix = f" [dim]({effort})[/dim]" if effort else ""
        branch = parent.add(f"{icon} [{style}]{label}[/{style}]{suffix}")
        for child_index, child in enumerate(node.get("children") or [], 1):
            self._add_task_graph_node(
                branch,
                child,
                current_task_id=current_task_id,
                index=child_index,
                depth=depth + 1,
            )
        return branch

    def _task_graph_node_label(self, node: dict[str, Any], description: str, *, index: int, depth: int) -> str:
        if depth == 0:
            return f"{index}. {description}"
        kind = (node.get("kind") or "").lower()
        prefixes = {
            "tool": f"Tool {index}",
            "goal": f"Goal {index}",
            "task": f"Task {index}",
            "result": "Result",
            "note": "Note",
            "prompt_context": "Prompt Context",
            "rubric": "Rubric",
        }
        prefix = prefixes.get(kind)
        return f"{prefix}: {description}" if prefix else description

    def _task_graph_live_tasks(
        self,
        tasks: list[dict[str, Any]],
        current_task_id: str | None,
    ) -> list[dict[str, Any]]:
        """Return the complete live-dashboard task graph without pruning history."""
        return tasks

    def _task_graph_active_root_id(self, tasks: list[dict[str, Any]], current_task_id: str | None) -> str | None:
        if current_task_id:
            for task in tasks:
                if self._task_graph_contains_node(task, current_task_id):
                    return task.get("id")
        for task in tasks:
            if (task.get("status") or "").lower() in {"running", "in_progress"}:
                return task.get("id")
        return None

    def _task_graph_contains_node(self, node: dict[str, Any], node_id: str) -> bool:
        if node.get("id") == node_id:
            return True
        return any(self._task_graph_contains_node(child, node_id) for child in node.get("children") or [])

    def _task_graph_visible_rows(self, nodes: list[dict[str, Any]]) -> int:
        total = 0
        for node in nodes:
            total += 1
            total += self._task_graph_visible_rows(node.get("children") or [])
        return total

    def _task_graph_live_row_limit(self) -> int:
        return max(8, self._task_graph_panel_height(999) - 4)

    def _task_graph_panel_height(self, visible_rows: int) -> int:
        return max(12, visible_rows + 4)

    def _status_style_icon(self, status: str, active: bool = False) -> tuple[str, str]:
        status = (status or "pending").lower()
        if status in {"completed", "success"}:
            return "green", "✓"
        if status in {"failed", "error"}:
            return "red", "✗"
        if status in {"running", "in_progress"} or active:
            return "yellow", self._task_graph_spinner_frame
        return "dim", "•"

    def log_activity(self, action_type: str, message: str):
        """Add an activity to the log."""
        self.activity_log.append((action_type, message, datetime.now()))
        # Keep only recent entries
        if len(self.activity_log) > 100:
            self.activity_log = self.activity_log[-100:]
        self._refresh_main_content()

    def set_active_operations(self, operations: list[Any]) -> None:
        """Update active operations displayed in the activity panel."""
        self.active_operations = operations
        self._advance_task_graph_spinner()
        self._refresh_main_content()

    def _advance_task_graph_spinner(self) -> None:
        """Keep Task Graph running markers animated even though they are not operations."""
        for op in self.active_operations:
            frame = getattr(op, "spinner_frame", "")
            if frame:
                self._task_graph_spinner_frame = frame
                return
        self._task_graph_spinner_index = (self._task_graph_spinner_index + 1) % len(self.spinner_frames)
        self._task_graph_spinner_frame = self.spinner_frames[self._task_graph_spinner_index]

    @contextmanager
    def live_session(self, title: str = "OpenPilot Session"):
        """Context manager for live updating display."""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=3),
        )

        # Header
        header = Panel(
            Align.center(Text(title, style="bold white")),
            style="bold cyan",
            box=HEAVY,
        )
        layout["header"].update(header)

        # Footer
        footer = Panel(
            Align.center(Text("Press Ctrl+C to interrupt", style="dim")),
            style="dim",
            box=ROUNDED,
        )
        layout["footer"].update(footer)

        self.current_layout = layout

        with Live(layout, console=self.console, refresh_per_second=4, screen=False) as live:
            self.live = live
            try:
                yield self
            finally:
                self.live = None
                self.current_layout = None
                self._main_content = None

    def update_main_content(self, content):
        """Update the main content area."""
        self._main_content = content
        self._refresh_main_content()

    def _refresh_main_content(self):
        """Refresh the remembered main content with current activity."""
        if self.current_layout:
            self.current_layout["main"].update(
                self._compose_main_content(self._main_content)
            )

    def _compose_main_content(self, content):
        return self.create_progress_dashboard(extra_content=content)

    def show_progress_with_activity(
        self,
        task_description: str,
        total_steps: int = 100,
    ):
        """Show progress bar with activity log."""
        if not self.current_layout:
            return None

        # Create progress bar
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=self.console,
        )

        task_id = progress.add_task(task_description, total=total_steps)

        # Combine progress and activity log
        content = Layout()
        content.split_column(
            Layout(Panel(progress, border_style="blue", box=ROUNDED), size=5),
            Layout(self.create_activity_panel()),
        )

        self.update_main_content(content)

        return progress, task_id

    def show_tool_execution(self, tool_name: str, params: dict[str, Any]):
        """Display tool execution in progress."""
        self.log_activity("tool", f"Calling {tool_name}")
        params_preview = []
        for key, value in params.items():
            value_str = str(value)
            if len(value_str) > 80:
                value_str = value_str[:77] + "..."
            params_preview.append(f"{key}: {value_str}")
        self.set_current_task_state(
            title=f"Tool: {tool_name}",
            details="\n".join(params_preview),
            status="running",
        )

    def show_llm_thinking(self, prompt_preview: str, model: str = "gpt-4"):
        """Display LLM thinking process."""
        self.log_activity("llm", f"Thinking with {model}")

    def create_executing_panel(self, task_description: str) -> Panel:
        """Create an executing panel with spinner animation."""
        from rich.spinner import Spinner
        from rich.columns import Columns

        spinner = Spinner("dots", text=task_description, style="bold yellow")

        return Panel(
            spinner,
            title="[bold yellow]⏳ Executing[/bold yellow]",
            border_style="yellow",
            box=ROUNDED,
        )

    def create_task_tree_panel(self, decomposition) -> Panel:
        """Create a panel containing the task decomposition tree."""
        tree = Tree(
            f"[bold]{decomposition.original_task.description}[/bold]",
            guide_style="dim"
        )

        for subtask in decomposition.subtasks:
            priority_color = {
                "critical": "red",
                "high": "yellow",
                "medium": "cyan",
                "low": "dim"
            }.get(subtask.priority.value, "white")

            effort_str = f"{subtask.estimated_effort:.1f}u" if subtask.estimated_effort else "?"

            branch = tree.add(
                f"[{priority_color}]●[/{priority_color}] "
                f"{subtask.description} "
                f"[dim]({effort_str})[/dim]"
            )

            if subtask.dependencies:
                branch.add(f"[dim]Depends on: {len(subtask.dependencies)} task(s)[/dim]")

        return Panel(
            tree,
            title="📋 Task Breakdown",
            border_style="cyan",
            padding=(1, 2)
        )

    def show_task_tree(self, task_graph: dict[str, Any]):
        tree = Tree("📋 [bold cyan]Task Decomposition[/bold cyan]")

        def add_subtasks(parent_node, tasks: list[dict]):
            for task in tasks:
                task_name = task.get("name", "Unnamed task")
                status = task.get("status", "pending")

                if status == "completed":
                    icon = "✅"
                    style = "green"
                elif status == "in_progress":
                    icon = "⚙️"
                    style = "yellow"
                elif status == "failed":
                    icon = "❌"
                    style = "red"
                else:
                    icon = "⏸️"
                    style = "dim"

                node = parent_node.add(f"{icon} [{style}]{task_name}[/{style}]")

                if "subtasks" in task and task["subtasks"]:
                    add_subtasks(node, task["subtasks"])

        if "tasks" in task_graph:
            add_subtasks(tree, task_graph["tasks"])

        return Panel(
            tree,
            title="[bold]Task Structure[/bold]",
            border_style="cyan",
            box=ROUNDED,
        )

    def show_error(self, error_message: str, details: str = ""):
        """Display error message."""
        self.log_activity("error", error_message)

        content = Text()
        content.append("❌ Error\n\n", style="bold red")
        content.append(error_message, style="red")

        if details:
            content.append("\n\nDetails:\n", style="bold white")
            content.append(details, style="dim white")

        panel = Panel(
            content,
            title="[bold red]Error[/bold red]",
            border_style="red",
            box=DOUBLE,
        )

        self.console.print(panel)

    def show_success(self, message: str, details: str = ""):
        """Display success message."""
        self.log_activity("success", message)

        content = Text()
        content.append("✅ Success\n\n", style="bold green")
        content.append(message, style="green")

        if details:
            content.append("\n\n", style="white")
            content.append(details, style="dim white")

        panel = Panel(
            content,
            title="[bold green]Success[/bold green]",
            border_style="green",
            box=ROUNDED,
        )

        self.console.print(panel)

    def prompt_choice(self, question: str, choices: list[str], default: int = 0) -> int:
        """Prompt user to select from choices."""
        self.console.print()
        self.console.print(Panel(
            Text(question, style="bold white"),
            border_style="cyan",
            box=ROUNDED,
        ))

        for i, choice in enumerate(choices):
            prefix = "▶" if i == default else " "
            style = "bold cyan" if i == default else "white"
            self.console.print(f"  {prefix} [{i+1}] {choice}", style=style)

        self.console.print()

        while True:
            try:
                from utils.input_utils import read_text

                response = read_text("Your choice (1-{}, default {}): ".format(
                    len(choices), default + 1
                ))

                if not response.strip():
                    return default

                choice_num = int(response) - 1
                if 0 <= choice_num < len(choices):
                    return choice_num
                else:
                    self.console.print(f"[red]Please enter a number between 1 and {len(choices)}[/red]")
            except ValueError:
                self.console.print("[red]Please enter a valid number[/red]")
            except KeyboardInterrupt:
                self.console.print("\n[yellow]Cancelled[/yellow]")
                return default
