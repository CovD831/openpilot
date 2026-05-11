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
        self.activity_log: list[tuple[str, str, datetime]] = []
        self.max_log_lines = 10

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
        if not self.activity_log:
            content = Text("No recent activity", style="dim")
        else:
            lines = []
            for action_type, message, timestamp in self.activity_log[-self.max_log_lines:]:
                time_str = timestamp.strftime("%H:%M:%S")

                if action_type == "tool":
                    icon = "🔧"
                    style = "cyan"
                elif action_type == "llm":
                    icon = "🤔"
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
                lines.append(line)

            content = Group(*lines)

        return Panel(
            content,
            title="[bold]📋 Activity Log[/bold]",
            border_style="yellow",
            box=ROUNDED,
            height=self.max_log_lines + 4,
        )

    def log_activity(self, action_type: str, message: str):
        """Add an activity to the log."""
        self.activity_log.append((action_type, message, datetime.now()))
        # Keep only recent entries
        if len(self.activity_log) > 100:
            self.activity_log = self.activity_log[-100:]

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

    def update_main_content(self, content):
        """Update the main content area."""
        if self.current_layout:
            self.current_layout["main"].update(content)

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

        # Create tool info panel
        tool_info = Table.grid(padding=(0, 2))
        tool_info.add_column(style="bold cyan")
        tool_info.add_column(style="white")

        tool_info.add_row("Tool:", tool_name)
        for key, value in params.items():
            value_str = str(value)
            if len(value_str) > 50:
                value_str = value_str[:47] + "..."
            tool_info.add_row(f"{key}:", value_str)

        panel = Panel(
            tool_info,
            title="[bold]🔧 Tool Execution[/bold]",
            border_style="cyan",
            box=ROUNDED,
        )

        if self.current_layout:
            content = Layout()
            content.split_column(
                Layout(panel, size=len(params) + 6),
                Layout(self.create_activity_panel()),
            )
            self.update_main_content(content)

    def show_llm_thinking(self, prompt_preview: str, model: str = "gpt-4"):
        """Display LLM thinking process."""
        self.log_activity("llm", f"Thinking with {model}")

        # Truncate prompt for display
        if len(prompt_preview) > 200:
            prompt_preview = prompt_preview[:197] + "..."

        thinking_panel = Panel(
            Group(
                Text(f"Model: {model}", style="bold magenta"),
                Text(""),
                Text("Prompt:", style="dim"),
                Text(prompt_preview, style="white"),
                Text(""),
                Text("⏳ Waiting for response...", style="yellow"),
            ),
            title="[bold]🤔 LLM Thinking[/bold]",
            border_style="magenta",
            box=ROUNDED,
        )

        if self.current_layout:
            content = Layout()
            content.split_column(
                Layout(thinking_panel, size=12),
                Layout(self.create_activity_panel()),
            )
            self.update_main_content(content)

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
                response = self.console.input("[bold cyan]Your choice[/bold cyan] (1-{}, default {}): ".format(
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
