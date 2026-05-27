"""Enhanced UI components with Claude Code-style interface."""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime
from textwrap import wrap
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


_UNSET = object()


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
        self.max_llm_stream_lines = 8
        self.max_llm_stream_chars = 1200
        self.spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._task_graph_spinner_index = 0
        self._task_graph_spinner_frame = self.spinner_frames[0]
        self._append_task_graph_enabled = False
        self._append_task_graph_seen: dict[str, tuple[str, str, str]] = {}
        self._append_task_graph_goal: str | None = None
        self._tool_event_states: dict[str, dict[str, Any]] = {}
        self._tool_event_history_seen: set[str] = set()
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
        current_task_id: str | None | object = _UNSET,
    ) -> None:
        """Update the persistent task graph area."""
        previous_goal = self.task_graph_state.get("goal") or ""
        reset_append_graph = False
        if goal is not None:
            self.task_graph_state["goal"] = goal
            reset_append_graph = goal != previous_goal
        if stages is not None:
            self.task_graph_state["stages"] = stages
        if stage_statuses is not None:
            self.task_graph_state["stage_statuses"] = stage_statuses
        if current_stage is not None:
            self.task_graph_state["current_stage"] = current_stage
        if tasks is not None:
            self.task_graph_state["tasks"] = tasks
            reset_append_graph = reset_append_graph or not tasks
        if current_task_id is not _UNSET:
            self.task_graph_state["current_task_id"] = current_task_id
        if self._append_task_graph_enabled:
            if reset_append_graph:
                self._reset_append_task_graph()
            self._emit_task_graph_updates()
            self._refresh_task_graph_tail()
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
        if not self._append_task_graph_enabled:
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
        """Create the task graph dashboard without a current-task region."""
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
        )
        return layout

    def create_full_task_graph_timeline_panel(self) -> Tree | None:
        """Render the full task graph timeline without a surrounding panel."""
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
        return tree

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

    def _reset_append_task_graph(self) -> None:
        self._append_task_graph_seen = {}
        self._append_task_graph_goal = None
        self._tool_event_states = {}
        self._tool_event_history_seen = set()

    def append_tool_event(self, event: Any) -> None:
        """Consume a tool lifecycle event for append/live UI rendering."""
        payload = self._tool_event_payload(event)
        call_id = str(payload.get("call_id") or "")
        if not call_id:
            return

        event_type = str(payload.get("event_type") or payload.get("status") or "").lower()
        status = str(payload.get("status") or event_type or "pending").lower()
        if event_type in {"completed", "error"} or status in {"completed", "success", "failed", "error"}:
            if self._append_task_graph_enabled:
                self._emit_tool_event_terminal_history(payload)
            self._tool_event_states.pop(call_id, None)
        else:
            self._tool_event_states[call_id] = payload
        self._refresh_task_graph_tail()

    def _tool_event_payload(self, event: Any) -> dict[str, Any]:
        if hasattr(event, "to_json_dict"):
            payload = event.to_json_dict()
        elif hasattr(event, "model_dump"):
            payload = event.model_dump(mode="json", exclude_none=True)
        elif isinstance(event, dict):
            payload = dict(event)
        else:
            payload = {
                key: value
                for key, value in vars(event).items()
                if not key.startswith("_")
            }
        return payload if isinstance(payload, dict) else {}

    def _tool_event_nested(self, payload: dict[str, Any], key: str) -> dict[str, Any]:
        value = payload.get(key)
        if isinstance(value, dict):
            return value
        if hasattr(value, "to_json_dict"):
            nested = value.to_json_dict()
            return nested if isinstance(nested, dict) else {}
        if hasattr(value, "model_dump"):
            nested = value.model_dump(mode="json", exclude_none=True)
            return nested if isinstance(nested, dict) else {}
        return {}

    def _tool_event_reason(self, payload: dict[str, Any]) -> str:
        tool_call = self._tool_event_nested(payload, "tool_call")
        tool_error = self._tool_event_nested(payload, "tool_error")
        failure = self._tool_event_nested(payload, "failure")
        return str(
            tool_error.get("suggested_recovery")
            or tool_error.get("error_message")
            or failure.get("error_message")
            or tool_call.get("reason")
            or payload.get("reason")
            or ""
        )

    def _tool_event_recoverable(self, payload: dict[str, Any]) -> bool:
        tool_error = self._tool_event_nested(payload, "tool_error")
        if "recoverable" in tool_error:
            return bool(tool_error.get("recoverable"))
        return bool(payload.get("recoverable", True))

    def _emit_tool_event_terminal_history(self, payload: dict[str, Any]) -> None:
        call_id = str(payload.get("call_id") or "")
        tool_name = str(payload.get("tool_name") or "unknown")
        event_type = str(payload.get("event_type") or payload.get("status") or "").lower()
        status = str(payload.get("status") or event_type or "").lower()
        if event_type == "completed" or status in {"completed", "success"}:
            kind = "completed"
            icon = "✓"
            style = "green"
            message = "Tool completed"
        elif event_type == "error" or status in {"failed", "error"}:
            if self._tool_event_recoverable(payload):
                kind = "recoverable_error"
                icon = "!"
                style = "yellow"
                message = "Tool error recovered"
            else:
                kind = "terminal_error"
                icon = "✗"
                style = "red"
                message = "Tool failed"
        else:
            return
        signature = f"{call_id}:{kind}"
        if signature in self._tool_event_history_seen:
            return
        self._tool_event_history_seen.add(signature)

        line = Text()
        line.append(f"{icon} ", style=style)
        line.append(f"{message}: {tool_name} ({call_id})", style=style)
        reason = self._tool_event_reason(payload)
        if reason:
            line.append(f" - {self._shorten_inline(reason, 120)}", style="dim")
        self.console.print(line)

    def _shorten_inline(self, value: str, limit: int) -> str:
        text = " ".join(str(value).split())
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)].rstrip() + "..."

    def _emit_task_graph_updates(self) -> None:
        tasks = self.task_graph_state.get("tasks") or []
        if not tasks:
            return

        goal = self.task_graph_state.get("goal") or "OpenPilot task"
        if self._append_task_graph_goal != goal:
            self.console.print(Text(goal, style="bold"))
            self._append_task_graph_goal = goal

        for index, task in enumerate(tasks, 1):
            self._emit_task_graph_node_update(task, index=index, depth=0)

    def _emit_task_graph_node_update(
        self,
        node: dict[str, Any],
        *,
        index: int,
        depth: int,
    ) -> None:
        node_id = str(node.get("id") or f"{depth}:{index}:{node.get('description', '')}")
        status = str(node.get("status") or "pending")
        description = str(node.get("description") or "Untitled task")
        label = self._task_graph_node_label(node, description, index=index, depth=depth)
        signature = (status, label, str(node.get("effort") or ""))
        previous = self._append_task_graph_seen.get(node_id)
        children = node.get("children") or []
        emit_node = self._should_emit_append_task_graph_node(node, previous)
        if emit_node and previous != signature:
            style, icon = self._status_style_icon(status)
            indent = "  " * depth
            effort = node.get("effort")
            suffix = f" ({effort})" if effort else ""
            line = Text()
            line.append(indent, style="dim")
            line.append(f"{icon} ", style=style)
            line.append(label, style=style)
            if suffix:
                line.append(suffix, style="dim")
            self.console.print(line)
            self._append_task_graph_seen[node_id] = signature
        elif previous is not None and previous != signature:
            self._append_task_graph_seen[node_id] = signature
        for child_index, child in enumerate(children, 1):
            self._emit_task_graph_node_update(
                child,
                index=child_index,
                depth=depth + 1,
            )

    def _should_emit_append_task_graph_node(
        self,
        node: dict[str, Any],
        previous: tuple[str, str, str] | None,
    ) -> bool:
        status = str(node.get("status") or "pending").lower()
        if status not in {"completed", "success", "failed", "error"}:
            return False
        return previous is None or previous[0].lower() != status

    def create_task_graph_live_tail(self) -> Group | Text:
        """Render the current Task Graph path plus transient tool/LLM stream text."""
        path = self._task_graph_running_path()
        rows: list[Text] = []

        if path:
            current_task_id = self.task_graph_state.get("current_task_id")
            for depth, (node, index) in enumerate(path):
                status = str(node.get("status") or "pending")
                active = node.get("id") == current_task_id or depth == len(path) - 1
                style, icon = self._status_style_icon(status, active=active)
                label = self._task_graph_node_label(
                    node,
                    str(node.get("description") or "Untitled task"),
                    index=index,
                    depth=depth,
                )
                line = Text()
                line.append("  " * depth, style="dim")
                line.append(f"{icon} ", style=style)
                line.append(label, style=style)
                rows.append(line)

        tool_rows = self._tool_event_live_rows()
        if tool_rows:
            if rows:
                rows.append(Text(""))
            rows.extend(tool_rows)

        llm_rows = self._llm_stream_live_rows()
        if llm_rows:
            if rows:
                rows.append(Text(""))
            rows.extend(llm_rows)

        if not rows:
            return Text("")
        return Group(*rows)

    def _tool_event_live_rows(self) -> list[Text]:
        active_events = [
            payload for payload in self._tool_event_states.values()
            if str(payload.get("status") or payload.get("event_type") or "").lower()
            in {"pending", "running", "in_progress"}
        ]
        if not active_events:
            return []
        payload = active_events[-1]
        call_id = str(payload.get("call_id") or "")
        tool_name = str(payload.get("tool_name") or "unknown")
        status = str(payload.get("status") or payload.get("event_type") or "pending").lower()
        short_call_id = self._short_tool_call_id(call_id)
        icon = self._task_graph_spinner_frame if status in {"running", "in_progress"} else "•"
        style = "yellow" if status in {"running", "in_progress"} else "dim"

        rows: list[Text] = []
        header = Text()
        header.append(f"{icon} ", style=style)
        header.append(f"Tool: {tool_name} ", style=style)
        header.append(f"({short_call_id}) ", style="dim")
        header.append(status, style="dim")
        rows.append(header)
        reason = self._tool_event_reason(payload)
        if reason:
            rows.append(Text(f"  Reason: {self._shorten_inline(reason, 140)}", style="dim"))
        return rows

    def _short_tool_call_id(self, call_id: str) -> str:
        parts = [part for part in str(call_id).split(":") if part]
        if len(parts) >= 2:
            return ":".join(parts[-2:])
        return call_id[-8:] if len(call_id) > 8 else call_id

    def _llm_stream_live_rows(self) -> list[Text]:
        active_llm_ops = [
            op for op in self.active_operations
            if str(getattr(getattr(op, "type", ""), "value", getattr(op, "type", ""))) == "llm"
        ]
        if not active_llm_ops:
            return []
        op = active_llm_ops[-1]
        rows: list[Text] = []
        elapsed = (datetime.now() - op.start_time).total_seconds()
        header = Text()
        header.append(f"{op.spinner_frame or self._task_graph_spinner_frame} ", style="magenta")
        header.append(f"{op.name} ", style="magenta")
        header.append(f"running {elapsed:.1f}s", style="dim")
        rows.append(header)
        phase = getattr(op, "phase", "")
        if phase:
            rows.append(Text(f"  Phase: {phase}", style="dim"))
        stream_text = str(getattr(op, "stream_text", "") or getattr(op, "response_preview", "") or "")
        if stream_text:
            rows.append(Text("  Visible response:", style="dim"))
            for line in self._stream_preview_lines(stream_text):
                rows.append(Text(f"    {line}", style="white"))
        if getattr(op, "tokens_or_chars", 0):
            rows.append(Text(f"  Response: {op.tokens_or_chars} chars", style="dim"))
        return rows

    def _stream_preview_lines(self, text: str) -> list[str]:
        text = text[-self.max_llm_stream_chars:]
        preview_lines: list[str] = []
        for raw_line in text.splitlines() or [text]:
            wrapped = wrap(raw_line, width=96, replace_whitespace=False, drop_whitespace=False) or [""]
            preview_lines.extend(wrapped)
        return preview_lines[-self.max_llm_stream_lines:]

    def _task_graph_running_path(self) -> list[tuple[dict[str, Any], int]]:
        tasks = self.task_graph_state.get("tasks") or []
        current_task_id = self.task_graph_state.get("current_task_id")
        if current_task_id:
            path = self._task_graph_path_to_node(tasks, current_task_id)
            if path and self._task_graph_path_is_active(path):
                return path
        return self._task_graph_deepest_running_path(tasks)

    def _task_graph_path_to_node(
        self,
        nodes: list[dict[str, Any]],
        node_id: str,
        prefix: list[tuple[dict[str, Any], int]] | None = None,
    ) -> list[tuple[dict[str, Any], int]]:
        prefix = prefix or []
        for index, node in enumerate(nodes, 1):
            path = [*prefix, (node, index)]
            if node.get("id") == node_id:
                return path
            child_path = self._task_graph_path_to_node(node.get("children") or [], node_id, path)
            if child_path:
                return child_path
        return []

    def _task_graph_deepest_running_path(
        self,
        nodes: list[dict[str, Any]],
        prefix: list[tuple[dict[str, Any], int]] | None = None,
    ) -> list[tuple[dict[str, Any], int]]:
        prefix = prefix or []
        for index, node in enumerate(nodes, 1):
            path = [*prefix, (node, index)]
            child_path = self._task_graph_deepest_running_path(node.get("children") or [], path)
            if child_path:
                return child_path
            if self._task_graph_node_is_running(node):
                return path
        return []

    def _task_graph_path_is_active(self, path: list[tuple[dict[str, Any], int]]) -> bool:
        tail = path[-1][0]
        status = str(tail.get("status") or "pending").lower()
        return status not in {"completed", "success", "failed", "error"}

    def _task_graph_node_is_running(self, node: dict[str, Any]) -> bool:
        return str(node.get("status") or "").lower() in {"running", "in_progress"}

    def _refresh_task_graph_tail(self) -> None:
        if self.live is not None:
            self.live.update(self.create_task_graph_live_tail(), refresh=True)

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
        if not self._append_task_graph_enabled:
            self._refresh_main_content()

    def set_active_operations(self, operations: list[Any]) -> None:
        """Update active operations displayed in the activity panel."""
        self.active_operations = operations
        self._advance_task_graph_spinner()
        if self._append_task_graph_enabled:
            self._refresh_task_graph_tail()
        else:
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
        """Context manager for terminal Task Graph history plus a live running tail."""
        self.console.print(Text(title, style="bold white"))
        self.console.print(Text("Press Ctrl+C to interrupt", style="dim"))
        self.console.print()
        self._append_task_graph_enabled = True
        self._reset_append_task_graph()
        with Live(
            self.create_task_graph_live_tail(),
            console=self.console,
            refresh_per_second=4,
            screen=False,
            transient=True,
        ) as live:
            self.live = live
            try:
                yield self
            finally:
                self._append_task_graph_enabled = False
                self.live = None
                self.current_layout = None
                self._main_content = None
                self._reset_append_task_graph()

    @contextmanager
    def transient_operation_session(self):
        """Show transient active operations when no task live session is running."""
        if self.live is not None:
            yield self
            return
        previous_append_enabled = self._append_task_graph_enabled
        self._append_task_graph_enabled = True
        with Live(
            self.create_task_graph_live_tail(),
            console=self.console,
            refresh_per_second=4,
            screen=False,
            transient=True,
        ) as live:
            self.live = live
            try:
                yield self
            finally:
                self.live = None
                self._append_task_graph_enabled = previous_append_enabled
                self.set_active_operations(self._non_llm_active_operations())

    def _non_llm_active_operations(self) -> list[Any]:
        return [
            op for op in self.active_operations
            if str(getattr(getattr(op, "type", ""), "value", getattr(op, "type", ""))) != "llm"
        ]

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
