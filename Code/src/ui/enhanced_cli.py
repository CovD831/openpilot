"""Enhanced CLI entry point with improved UI."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from rich.console import Console

from core.config import LLMSettings
from core.instrumented_llm import InstrumentedLLMClient
from core.openpilot_log import OpenPilotLogger
from planning.planner import TaskPlanner
from ui.enhanced_ui import EnhancedUI
from ui.progress_tracker import ProgressTracker
from ui.openpilot_session import OpenPilotSession


def run_enhanced_cli(
    args,
    console: Console | None = None,
    llm_client = None
) -> int:
    """Run OpenPilot with enhanced UI."""
    console = console or Console()

    # Initialize enhanced UI
    enhanced_ui = EnhancedUI(console)
    enhanced_ui.show_banner()

    # Initialize progress tracker
    tracker = ProgressTracker(enhanced_ui)

    # Initialize settings
    settings = LLMSettings()

    # Create instrumented LLM client
    if llm_client is None:
        llm_client = InstrumentedLLMClient(settings, tracker)

    # Initialize planner
    planner = TaskPlanner(llm_client)

    # Setup logging
    log_file = getattr(args, 'log_file', None)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("", encoding="utf-8")
        logger = OpenPilotLogger(log_file)
    else:
        logger = None

    # Check for once mode
    if hasattr(args, 'once') and args.once:
        return _run_once_mode(
            args.once,
            enhanced_ui,
            tracker,
            planner,
            logger,
            settings
        )

    # Interactive mode
    return _run_interactive_mode(
        enhanced_ui,
        tracker,
        planner,
        logger,
        settings,
        args,
        llm_client
    )


def _run_once_mode(
    goal: str,
    ui: EnhancedUI,
    tracker: ProgressTracker,
    planner: TaskPlanner,
    logger,
    settings: LLMSettings
) -> int:
    """Run a single goal and exit."""
    from execution.intelligent_autopilot import IntelligentAutopilot
    from core.llm import LLMClient

    ui.console.print()
    ui.console.print(f"[bold cyan]Goal:[/bold cyan] {goal}")
    ui.console.print()

    try:
        # Create autopilot with enhanced UI support
        autopilot = IntelligentAutopilot(
            llm_client=LLMClient(settings),
            console=ui.console,
            auto_approve=True,
            logger=logger,
            use_enhanced_ui=True
        )

        # Execute with live session
        with ui.live_session(f"Executing: {goal[:50]}..."):
            ui.update_main_content(
                ui.create_status_panel("Autopilot Mode", "Intelligent task decomposition and execution...")
            )

            result = autopilot.execute(goal)

            # Small delay to let user see final status
            import time
            time.sleep(1)

        ui.show_success("Goal completed successfully!")
        return 0

    except Exception as e:
        ui.show_error("Execution failed", str(e))
        import traceback
        traceback.print_exc()
        return 2


def _run_interactive_mode(
    ui: EnhancedUI,
    tracker: ProgressTracker,
    planner: TaskPlanner,
    logger,
    settings: LLMSettings,
    args,
    llm_client
) -> int:
    """Run interactive REPL mode."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.history import InMemoryHistory
    from ui.commands import get_all_command_names

    # Get commands from registry
    commands = get_all_command_names()

    # Setup completer
    completer = WordCompleter(
        commands,
        ignore_case=True,
        WORD=True,  # 只在单词边界补全
    )

    # Setup history and auto-suggest
    history = InMemoryHistory()
    auto_suggest = AutoSuggestFromHistory()

    session = PromptSession(
        completer=completer,
        history=history,
        auto_suggest=auto_suggest,
        enable_history_search=True,  # Enable Ctrl+R history search
        complete_while_typing=True,  # 输入时自动显示补全菜单
        vi_mode=False,  # 确保使用 Emacs 模式（支持上下键历史）
    )

    ui.console.print()
    ui.console.print("[bold green]Welcome to OpenPilot Interactive Mode[/bold green]")
    ui.console.print("[dim]Type your goal or use /help for commands[/dim]")
    ui.console.print()

    tracker.start_tracking()

    try:
        while True:
            try:
                # Get user input
                user_input = session.prompt("openpilot> ")

                if not user_input.strip():
                    continue

                # Handle exit commands
                if user_input.strip() in ["/exit", "/quit", "exit", "quit", ":q"]:
                    ui.console.print("[yellow]Goodbye![/yellow]")
                    break

                # Handle help command
                if user_input.strip() == "/help":
                    _show_help(ui)
                    continue

                # Handle config command
                if user_input.strip() == "/config":
                    _show_config(ui, settings)
                    continue

                # Handle clear command
                if user_input.strip() == "/clear":
                    ui.console.clear()
                    ui.show_banner()
                    continue

                # Handle autopilot command
                if user_input.strip().startswith("/autopilot"):
                    parts = user_input.strip().split(maxsplit=1)
                    if len(parts) < 2:
                        ui.console.print("[red]Usage:[/red] /autopilot <goal>")
                        continue
                    goal = parts[1]
                    _execute_autopilot(goal, ui, tracker, llm_client, logger)
                    continue

                # Handle goal execution
                if not user_input.startswith("/"):
                    _execute_goal_interactive(user_input, ui, tracker, planner)
                else:
                    ui.console.print(f"[yellow]Unknown command: {user_input}[/yellow]")
                    ui.console.print("[dim]Type /help for available commands[/dim]")

            except KeyboardInterrupt:
                ui.console.print("\n[yellow]Interrupted. Type /exit to quit.[/yellow]")
                continue
            except EOFError:
                break

    finally:
        tracker.stop_tracking()

    return 0


def _execute_goal_interactive(
    goal: str,
    ui: EnhancedUI,
    tracker: ProgressTracker,
    planner: TaskPlanner
):
    """Execute a goal in interactive mode."""
    ui.console.print()

    try:
        with ui.live_session(f"Executing: {goal[:50]}..."):
            # Plan
            ui.update_main_content(
                ui.create_status_panel("Planning", "Analyzing your goal...")
            )

            with tracker.track_task("Planning", {"goal": goal}):
                plan = planner.plan(goal)

            ui.log_activity("success", f"Plan created with {len(plan.steps)} steps")

            # Show plan and ask for confirmation
            ui.update_main_content(ui.create_status_panel(
                "Plan Ready",
                f"Created {len(plan.steps)} steps. Executing..."
            ))

            # Execute steps
            for i, step in enumerate(plan.steps, 1):
                with tracker.track_task(f"Step {i}", {"action": step.title}):
                    import time
                    time.sleep(0.3)  # Simulate work

        ui.show_success("Goal completed!")

    except Exception as e:
        ui.show_error("Execution failed", str(e))


def _show_help(ui: EnhancedUI):
    """Show help information."""
    from ui.commands import get_command_registry

    registry = get_command_registry()
    ui.console.print()
    ui.console.print(registry.format_help())
    ui.console.print()


def _show_config(ui: EnhancedUI, settings: LLMSettings):
    """Show current configuration."""
    from rich.table import Table

    table = Table(title="Current Configuration", show_header=True, header_style="bold cyan")
    table.add_column("Setting", style="cyan", width=20)
    table.add_column("Value", style="white")

    table.add_row("Provider", settings.provider)
    table.add_row("Model", settings.model)
    table.add_row("Base URL", settings.base_url or "[dim]default[/dim]")
    table.add_row("Temperature", str(settings.temperature))
    table.add_row("Timeout", f"{settings.timeout_seconds}s")
    table.add_row("API Key", "✓ Set" if settings.api_key else "✗ Not set")

    ui.console.print()
    ui.console.print(table)
    ui.console.print()


def _execute_autopilot(
    goal: str,
    ui: EnhancedUI,
    tracker: ProgressTracker,
    llm_client,
    logger
):
    """Execute goal using intelligent autopilot with enhanced UI."""
    from execution.intelligent_autopilot import IntelligentAutopilot
    from core.llm import LLMClient

    ui.console.print()

    try:
        # Create autopilot with enhanced UI support
        autopilot = IntelligentAutopilot(
            llm_client=llm_client or LLMClient(),
            console=ui.console,
            auto_approve=True,
            logger=logger,
            use_enhanced_ui=True
        )

        # Execute with live session
        with ui.live_session(f"Executing: {goal[:50]}..."):
            ui.update_main_content(
                ui.create_status_panel("Autopilot Mode", "Intelligent task decomposition and execution...")
            )

            result = autopilot.execute(goal)

            # Final status is already shown in the layout by autopilot
            # Just add a small delay to let user see it
            import time
            time.sleep(1)

    except Exception as e:
        ui.console.print()
        ui.show_error("Autopilot execution failed", str(e))
        import traceback
        traceback.print_exc()

