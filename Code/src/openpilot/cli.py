"""Command line interface for OpenPilot."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Sequence

from rich.console import Console
from rich.table import Table

from openpilot.openpilot_log import OpenPilotLogger
from openpilot.openpilot_session import OpenPilotSession
from openpilot.config import LLMSettings
from openpilot.exceptions import OpenPilotError
from openpilot.llm import LLMClient
from openpilot.planner import CompletionClient, TaskPlanner
from openpilot.progress_report import ProgressReportGenerator
from openpilot.task_log import TaskLogEventType, TaskLogStore, create_task_log_entry
from openpilot.terminal_ui import TerminalUI
from openpilot.workflow_executor import WorkflowExecutor

DEFAULT_OPENPILOT_LOG = Path(__file__).resolve().parents[2] / "logs" / "openpilot.jsonl"
DEFAULT_TASK_LOG_DIR = Path(__file__).resolve().parents[2] / "data" / "task_logs"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openpilot", description="OpenPilot MVP CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_parser = subparsers.add_parser("config", help="Configuration commands")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    config_subparsers.add_parser("check", help="Check LLM configuration")

    plan_parser = subparsers.add_parser("plan", help="Plan a high-level goal")
    plan_parser.add_argument("goal", help="High-level user goal")
    plan_parser.add_argument("--constraint", action="append", default=[], help="Planning constraint")
    plan_parser.add_argument("--json", action="store_true", help="Print raw JSON")

    # Execute command with Phase 2 workflow
    execute_parser = subparsers.add_parser("execute", help="Execute goal with Phase 2 workflow (8-stage pipeline)")
    execute_parser.add_argument("goal", help="High-level user goal")
    execute_parser.add_argument("--constraint", action="append", default=[], help="Planning constraint")
    execute_parser.add_argument("--dry-run", action="store_true", help="Plan only, do not execute")
    execute_parser.add_argument("--auto-approve", action="store_true", help="Auto-approve low-risk operations")
    execute_parser.add_argument("--save-report", help="Save execution report to file")

    _add_run_parser(subparsers, "run", "Run the modern interactive OpenPilot CLI")
    _add_run_parser(subparsers, "openpilot", "Backward-compatible alias for run")

    # Task log commands
    task_parser = subparsers.add_parser("task", help="Task log management")
    task_subparsers = task_parser.add_subparsers(dest="task_command", required=True)

    task_subparsers.add_parser("list", help="List all tasks with logs")

    task_log_parser = task_subparsers.add_parser("log", help="Add a task log entry")
    task_log_parser.add_argument("task_id", help="Task ID")
    task_log_parser.add_argument("event_type", choices=[e.value for e in TaskLogEventType], help="Event type")
    task_log_parser.add_argument("--old-status", help="Old status (for status_changed)")
    task_log_parser.add_argument("--new-status", help="New status (for status_changed)")
    task_log_parser.add_argument("--blocked-reason", help="Blocked reason (required for blocked)")
    task_log_parser.add_argument("--note", help="Note text")

    task_history_parser = task_subparsers.add_parser("history", help="Show task history")
    task_history_parser.add_argument("task_id", help="Task ID")
    task_history_parser.add_argument("--event-type", choices=[e.value for e in TaskLogEventType], help="Filter by event type")

    # Report commands
    report_parser = subparsers.add_parser("report", help="Generate progress reports")
    report_subparsers = report_parser.add_subparsers(dest="report_command", required=True)

    daily_parser = report_subparsers.add_parser("daily", help="Generate daily report")
    daily_parser.add_argument("--date", help="Date (YYYY-MM-DD), defaults to today")
    daily_parser.add_argument("--save", help="Save report to file")

    weekly_parser = report_subparsers.add_parser("weekly", help="Generate weekly report")
    weekly_parser.add_argument("--week-start", help="Week start date (YYYY-MM-DD), defaults to this Monday")
    weekly_parser.add_argument("--save", help="Save report to file")

    return parser


def _add_run_parser(subparsers, name: str, help_text: str) -> None:
    run_parser = subparsers.add_parser(name, help=help_text)
    run_parser.add_argument("--log-file", default=str(DEFAULT_OPENPILOT_LOG), help="JSONL log file")
    run_parser.add_argument("--constraint", action="append", default=[], help="Planning constraint")
    run_parser.add_argument("--once", help="Plan one goal and exit")
    run_parser.add_argument("--ignore-memory", action="store_true", help="Disable memory retrieval and preference reuse")


def main(argv: Sequence[str] | None = None, llm_client: CompletionClient | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console()
    err_console = Console(stderr=True)

    if args.command == "config" and args.config_command == "check":
        return _config_check(console)

    if args.command == "plan":
        planner = TaskPlanner(llm_client or LLMClient())
        try:
            plan = planner.plan(args.goal, constraints=args.constraint)
        except OpenPilotError as exc:
            err_console.print(f"[red]Planning failed:[/red] {exc}")
            return 2

        if args.json:
            console.print_json(plan.model_dump_json())
        else:
            _print_plan(console, plan)
        return 0

    if args.command == "execute":
        return _execute_workflow(args, console, err_console, llm_client)

    if args.command in {"run", "openpilot"}:
        return _run_openpilot(args, console, llm_client)

    if args.command == "task":
        return _handle_task_command(args, console, err_console)

    if args.command == "report":
        return _handle_report_command(args, console, err_console)

    parser.error("Unknown command")
    return 2


def _execute_workflow(
    args, console: Console, err_console: Console, llm_client: CompletionClient | None
) -> int:
    """Execute goal using Phase 2 workflow."""
    try:
        executor = WorkflowExecutor(
            llm_client=llm_client or LLMClient(),
            console=console,
            dry_run=args.dry_run,
            auto_approve=args.auto_approve,
            save_report=args.save_report,
        )

        result = executor.execute(args.goal, constraints=args.constraint)
        return 0 if result["success"] else 2

    except Exception as exc:
        err_console.print(f"[red]Execution failed:[/red] {exc}")
        return 2


def _run_openpilot(args, console: Console, llm_client: CompletionClient | None) -> int:
    settings = LLMSettings()
    ui = TerminalUI(console)
    planner = TaskPlanner(llm_client or LLMClient(settings))
    logger = OpenPilotLogger(args.log_file)
    enable_memory = not getattr(args, "ignore_memory", False)
    session = OpenPilotSession(
        planner,
        logger,
        constraints=args.constraint,
        settings=settings,
        ui=ui,
        enable_memory=enable_memory,
    )

    if args.once:
        ui.show_welcome(settings, logger.log_file)
        ui.warn_missing_config(settings)
        result = session.handle_goal(args.once, assume_defaults=True)
        return 0 if result.ok else 2

    return session.run()


def _config_check(console: Console) -> int:
    settings = LLMSettings()
    rows = [
        ("provider", settings.provider),
        ("base_url", "set" if settings.base_url.strip() else "missing"),
        ("model", settings.model),
        ("timeout_seconds", str(settings.timeout_seconds)),
        ("temperature", str(settings.temperature)),
        ("api_key", "set" if settings.api_key and settings.api_key.strip() else "missing"),
    ]

    console.print("OpenPilot LLM Configuration")
    for field, value in rows:
        console.print(f"{field}: {value}")

    missing = settings.missing_fields()
    if missing:
        console.print(
            f"Missing LLM configuration: {', '.join(missing)}. "
            "Real LLM calls will fail."
        )
        return 0
    console.print("Configuration is ready.")
    return 0


def _print_plan(console: Console, plan) -> None:
    console.print(f"Goal: {plan.task_card.goal}")
    console.print(f"Task type: {plan.task_card.task_type}")
    console.print(f"Risk: {plan.task_card.risk_level.value}")
    console.print()

    console.print("Execution Steps")
    for step in plan.steps:
        console.print(
            f"- {step.id}: {step.title} "
            f"(risk={step.risk_level.value}, confirmation="
            f"{'yes' if step.confirmation_required else 'no'})"
        )

    if plan.timeline:
        console.print()
        console.print(f"Timeline: {plan.timeline.time_horizon}")
        for slot in plan.timeline.timeline:
            console.print(f"- {slot.start_label} -> {slot.end_label}: {slot.title}")

    console.print("Success criteria:")
    for item in plan.success_criteria:
        console.print(f"- {item}")


def _handle_task_command(args, console: Console, err_console: Console) -> int:
    """Handle task log commands."""
    store = TaskLogStore(DEFAULT_TASK_LOG_DIR)

    if args.task_command == "list":
        task_ids = store.get_all_task_ids()
        if not task_ids:
            console.print("[yellow]No tasks found.[/yellow]")
            return 0

        console.print(f"[bold]Tasks with logs:[/bold] ({len(task_ids)} total)")
        for task_id in sorted(task_ids):
            entries = store.get_entries(task_id)
            console.print(f"  - {task_id} ({len(entries)} entries)")
        return 0

    if args.task_command == "log":
        # Validate blocked events have reason
        event_type = TaskLogEventType(args.event_type)
        if event_type == TaskLogEventType.BLOCKED and not args.blocked_reason:
            err_console.print("[red]Error:[/red] blocked events require --blocked-reason")
            return 2

        # Create log entry
        try:
            entry = create_task_log_entry(
                task_id=args.task_id,
                event_type=event_type,
                old_status=args.old_status,
                new_status=args.new_status,
                blocked_reason=args.blocked_reason,
                note=args.note,
            )
            store.append(entry)
            console.print(f"[green]✓[/green] Logged {event_type.value} for task: {args.task_id}")
            return 0
        except Exception as exc:
            err_console.print(f"[red]Error:[/red] {exc}")
            return 2

    if args.task_command == "history":
        event_type_filter = TaskLogEventType(args.event_type) if args.event_type else None
        entries = store.get_entries(args.task_id, event_type=event_type_filter)

        if not entries:
            console.print(f"[yellow]No log entries found for task: {args.task_id}[/yellow]")
            return 0

        console.print(f"[bold]Task History:[/bold] {args.task_id}")
        console.print()

        table = Table(show_header=True, header_style="bold")
        table.add_column("Timestamp", style="dim")
        table.add_column("Event")
        table.add_column("Details")

        for entry in entries:
            timestamp = entry.timestamp[:19].replace("T", " ")
            event = entry.event_type.value

            details = []
            if entry.old_status and entry.new_status:
                details.append(f"{entry.old_status} → {entry.new_status}")
            if entry.blocked_reason:
                details.append(f"Reason: {entry.blocked_reason}")
            if entry.note:
                details.append(f"Note: {entry.note}")

            table.add_row(timestamp, event, " | ".join(details) if details else "")

        console.print(table)
        return 0

    return 2


def _handle_report_command(args, console: Console, err_console: Console) -> int:
    """Handle report generation commands."""
    store = TaskLogStore(DEFAULT_TASK_LOG_DIR)
    generator = ProgressReportGenerator(store)

    if args.report_command == "daily":
        date = args.date
        if date:
            # Validate date format
            try:
                datetime.fromisoformat(date)
            except ValueError:
                err_console.print("[red]Error:[/red] Invalid date format. Use YYYY-MM-DD")
                return 2

        try:
            report = generator.generate_daily_report(date=date)
            markdown = generator.format_daily_report_markdown(report)

            if args.save:
                Path(args.save).write_text(markdown, encoding="utf-8")
                console.print(f"[green]✓[/green] Daily report saved to: {args.save}")
            else:
                console.print(markdown)

            return 0
        except Exception as exc:
            err_console.print(f"[red]Error:[/red] {exc}")
            return 2

    if args.report_command == "weekly":
        week_start = args.week_start
        if week_start:
            # Validate date format
            try:
                datetime.fromisoformat(week_start)
            except ValueError:
                err_console.print("[red]Error:[/red] Invalid date format. Use YYYY-MM-DD")
                return 2

        try:
            report = generator.generate_weekly_report(week_start=week_start)
            markdown = generator.format_weekly_report_markdown(report)

            if args.save:
                Path(args.save).write_text(markdown, encoding="utf-8")
                console.print(f"[green]✓[/green] Weekly report saved to: {args.save}")
            else:
                console.print(markdown)

            return 0
        except Exception as exc:
            err_console.print(f"[red]Error:[/red] {exc}")
            return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
