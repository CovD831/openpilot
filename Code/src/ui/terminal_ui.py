"""Rich-powered terminal UI for OpenPilot."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from core.config import LLMSettings
from models.planner_models import ExecutionPlan, RiskLevel

if TYPE_CHECKING:
    from planning.clarifier import TaskBrief
    from ui.openpilot_session import OpenPilotTurnResult
    from models.reminder_models import ReminderPlan


class TerminalUI:
    """Modern terminal rendering wrapper around Rich."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self._prompt_session = None  # 延迟初始化

    def _get_prompt_session(self):
        """获取或创建 prompt session（带历史记录和补全菜单）"""
        if self._prompt_session is None:
            try:
                from prompt_toolkit import PromptSession
                from prompt_toolkit.completion import WordCompleter
                from prompt_toolkit.history import FileHistory
                from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
                from ui.commands import get_all_command_names

                # 从命令注册表获取所有命令
                commands = get_all_command_names()

                # 创建补全器（显示下拉菜单）
                completer = WordCompleter(
                    commands,
                    ignore_case=True,
                    WORD=True,  # 只在单词边界补全
                )

                # 创建持久化历史记录文件
                history_dir = Path.home() / ".openpilot"
                history_dir.mkdir(parents=True, exist_ok=True)
                history_file = history_dir / "history.txt"
                history = FileHistory(str(history_file))

                # 创建 session
                self._prompt_session = PromptSession(
                    completer=completer,
                    history=history,
                    enable_history_search=True,  # 启用 Ctrl+R 搜索
                    auto_suggest=AutoSuggestFromHistory(),  # 自动建议（灰色提示）
                    complete_while_typing=False,  # 只在按 Tab 时显示补全
                    vi_mode=False,  # 确保使用 Emacs 模式（支持上下键历史）
                )
            except ImportError:
                # 如果没有 prompt_toolkit，返回 None
                self._prompt_session = None

        return self._prompt_session

    def show_welcome(self, settings: LLMSettings, log_file: str | Path) -> None:
        missing = settings.missing_fields()
        config_state = "ready" if not missing else f"incomplete: {', '.join(missing)}"
        body = (
            "Personal planning agent\n"
            f"Provider: {settings.provider}\n"
            f"Model: {settings.model}\n"
            f"Log: {log_file}\n"
            "Exit: exit, quit, :q\n"
            f"Config: {config_state}"
        )
        self.console.print(
            Panel.fit(
                body,
                title="OpenPilot",
                subtitle="planning-only mode",
                border_style="cyan",
                box=box.ASCII,
            )
        )
        if missing:
            self.show_config_summary(settings)

    def show_config_summary(self, settings: LLMSettings) -> None:
        table = Table(title="API setup", box=box.ASCII, show_header=True)
        table.add_column("Field")
        table.add_column("Status")
        table.add_row("OPENPILOT_LLM_BASE_URL", "set" if settings.base_url.strip() else "missing")
        table.add_row(
            "OPENPILOT_LLM_API_KEY",
            "set" if settings.api_key and settings.api_key.strip() else "missing",
        )
        table.add_row("OPENPILOT_LLM_MODEL", settings.model)
        self.console.print(table)
        self.console.print(
            "Create or edit Code/.env, set OPENPILOT_LLM_BASE_URL, "
            "OPENPILOT_LLM_API_KEY, and OPENPILOT_LLM_MODEL. Never commit real keys.",
            style="yellow",
        )

    def warn_missing_config(self, settings: LLMSettings) -> None:
        missing = settings.missing_fields()
        if missing:
            self.console.print(
                f"WARNING: LLM config incomplete: {', '.join(missing)}",
                style="bold yellow",
            )

    def prompt(self) -> str:
        """获取用户输入，支持命令补全和历史记录"""
        session = self._get_prompt_session()

        if session:
            # 使用 prompt_toolkit（支持历史记录和补全）
            try:
                return session.prompt("openpilot> ").strip()
            except (KeyboardInterrupt, EOFError):
                raise
        else:
            # 回退到简单输入（无历史记录）
            return Prompt.ask("[bold cyan]openpilot[/bold cyan]").strip()

    def ask_clarification(self, question: str) -> str:
        return Prompt.ask(f"[yellow]{question}[/yellow]").strip()

    @contextmanager
    def status(self, message: str) -> Iterator[None]:
        self.console.print(f"[dim]> {message}[/dim]")
        with self.console.status(message, spinner="dots"):
            yield

    def show_plan_summary(self, plan: ExecutionPlan) -> None:
        timeline = plan.timeline
        time_horizon = timeline.time_horizon if timeline else "unspecified"
        summary = (
            f"Task type: {plan.task_card.task_type}\n"
            f"Risk: {_risk_label(plan.task_card.risk_level)}\n"
            f"Timeline: {time_horizon}\n"
            f"Confirmation points: {', '.join(plan.confirmation_points) or 'none'}"
        )
        self.console.print(
            Panel.fit(summary, title="Plan summary", border_style="green", box=box.ASCII)
        )
        self.show_timeline_summary(plan)
        self.show_plan_steps(plan)

    def show_task_brief(self, task_brief: "TaskBrief") -> None:
        if not task_brief.assumptions and not task_brief.answers:
            return
        lines: list[str] = []
        if task_brief.assumptions:
            lines.append("Assumptions:")
            lines.extend(f"- {item}" for item in task_brief.assumptions)
        if task_brief.answers:
            if lines:
                lines.append("")
            lines.append("Clarified details:")
            lines.extend(
                f"- {answer.field}: {answer.answer}"
                for answer in task_brief.answers
            )
        self.console.print(
            Panel.fit(
                "\n".join(lines),
                title="Task brief",
                border_style="yellow",
                box=box.ASCII,
            )
        )

    def show_timeline_summary(self, plan: ExecutionPlan) -> None:
        if not plan.timeline:
            return
        table = Table(title="Timeline", box=box.ASCII, show_header=True)
        table.add_column("When")
        table.add_column("Task")
        table.add_column("Status")
        for slot in plan.timeline.timeline:
            table.add_row(
                f"{slot.start_label} -> {slot.end_label}",
                slot.title,
                slot.status.value,
            )
        self.console.print(table)

    def show_reminder_plan(self, reminder_plan: "ReminderPlan") -> None:
        table = Table(title="Reminder plan", box=box.ASCII, show_header=True)
        table.add_column("#", justify="right")
        table.add_column("When")
        table.add_column("Reminder")
        table.add_column("Channel")
        for index, item in enumerate(reminder_plan.items[:8], start=1):
            table.add_row(
                str(index),
                item.remind_at,
                item.title,
                item.channel,
            )
        self.console.print(table)
        if reminder_plan.notes:
            self.console.print("; ".join(reminder_plan.notes), style="dim")

    def show_plan_steps(self, plan: ExecutionPlan) -> None:
        table = Table(title="Planned steps", box=box.ASCII, show_header=True)
        table.add_column("#", justify="right")
        table.add_column("Step")
        table.add_column("Risk")
        table.add_column("Confirm")
        for index, step in enumerate(plan.steps, start=1):
            table.add_row(
                str(index),
                step.title,
                _risk_label(step.risk_level),
                "yes" if step.confirmation_required else "no",
            )
        self.console.print(table)

    def show_turn_result(self, result: "OpenPilotTurnResult") -> None:
        if result.ok:
            self.console.print(
                f"planned and logged: {result.session_id} turn={result.turn_id} "
                f"log={result.log_file}",
                style="green",
            )
            return
        self.console.print(
            f"planning failed and logged: {result.session_id} turn={result.turn_id} "
            f"log={result.log_file}",
            style="bold red",
        )


def _risk_label(risk: RiskLevel) -> str:
    return risk.value
