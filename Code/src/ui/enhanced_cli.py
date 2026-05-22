"""Enhanced CLI entry point with improved UI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from rich.console import Console

from core.config import EmbeddingSettings, LLMSettings
from core.instrumented_llm import InstrumentedLLMClient
from core.openpilot_log import OpenPilotLogger
from ui.enhanced_ui import EnhancedUI
from ui.progress_tracker import ProgressTracker

if TYPE_CHECKING:
    from metadata import TaskRouteMetadata


DEFAULT_IMPROVEMENT_ITERATIONS = 2


@dataclass(frozen=True)
class OpenPilotRuntimeOptions:
    """Runtime options for autopilot creation."""

    improvement_iterations: int = DEFAULT_IMPROVEMENT_ITERATIONS
    prompt_for_project_improvement_iterations: bool = False

    @property
    def enable_iterative_improvement(self) -> bool:
        return self.improvement_iterations > 0


def run_enhanced_cli(
    args,
    console: Console | None = None,
    llm_client = None
) -> int:
    """Run OpenPilot with enhanced UI."""
    console = console or Console()

    from ui.environment_guard import block_missing_socksio, block_project_venv
    if block_project_venv(console):
        return 2
    if block_missing_socksio(console):
        return 2

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
        runtime_options = _runtime_options_from_args(args, project_prompt_default=False)
        return _run_once_mode(
            args.once,
            enhanced_ui,
            tracker,
            logger,
            settings,
            runtime_options,
            llm_client,
        )

    runtime_options = _runtime_options_from_args(args, project_prompt_default=True)

    # Interactive mode
    return _run_interactive_mode(
        enhanced_ui,
        tracker,
        logger,
        settings,
        args,
        llm_client,
        runtime_options,
    )


def _runtime_options_from_args(
    args,
    *,
    project_prompt_default: bool,
) -> OpenPilotRuntimeOptions:
    """Resolve runtime options from CLI args.

    Interactive autopilot asks per generated project when the user did not pass
    a fixed --improvement-iterations value.
    """
    configured = getattr(args, "improvement_iterations", None)
    if configured is not None:
        return OpenPilotRuntimeOptions(
            improvement_iterations=configured,
            prompt_for_project_improvement_iterations=False,
        )

    return OpenPilotRuntimeOptions(
        improvement_iterations=DEFAULT_IMPROVEMENT_ITERATIONS,
        prompt_for_project_improvement_iterations=project_prompt_default,
    )


def _run_once_mode(
    goal: str,
    ui: EnhancedUI,
    tracker: ProgressTracker,
    logger,
    settings: LLMSettings,
    runtime_options: OpenPilotRuntimeOptions,
    llm_client = None,
) -> int:
    """Run a single goal and exit."""
    from autonomous_iteration.intelligent_autopilot import IntelligentAutopilot
    from core.llm import LLMClient

    ui.console.print()
    ui.console.print(f"[bold cyan]Goal:[/bold cyan] {goal}")
    ui.console.print()

    try:
        classification = _classify_task_route(goal)
        _show_task_route(ui, classification)

        active_llm_client = llm_client or LLMClient(settings)
        if classification.route == "agent_generator":
            return 0 if _execute_agent_generator(goal, ui, active_llm_client, logger) else 2

        # Create autopilot with enhanced UI support
        autopilot = IntelligentAutopilot(
            llm_client=active_llm_client,
            console=ui.console,
            auto_approve=True,
            logger=logger,
            use_enhanced_ui=True,
            enhanced_ui=ui,
            tracker=tracker,
            enable_iterative_improvement=runtime_options.enable_iterative_improvement,
            required_successful_improvements=runtime_options.improvement_iterations,
            prompt_for_project_improvement_iterations=runtime_options.prompt_for_project_improvement_iterations,
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

        ui.show_full_task_graph_timeline()

        if result.get("success"):
            ui.show_success("Goal completed successfully!")
            return 0

        ui.show_error("Execution failed", result.get("error") or "Autopilot reported failure")
        return 2

    except Exception as e:
        ui.show_full_task_graph_timeline()
        ui.show_error("Execution failed", str(e))
        import traceback
        traceback.print_exc()
        return 2


def _run_interactive_mode(
    ui: EnhancedUI,
    tracker: ProgressTracker,
    logger,
    settings: LLMSettings,
    args,
    llm_client,
    runtime_options: OpenPilotRuntimeOptions,
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
    ui.console.print("[dim]Type your task or use /help for commands[/dim]")
    if runtime_options.prompt_for_project_improvement_iterations:
        ui.console.print("[dim]Project improvement iterations: asked per generated project[/dim]")
    else:
        ui.console.print(
            f"[dim]Project improvement iterations: {runtime_options.improvement_iterations}[/dim]"
        )
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
                    _show_config(ui, settings, runtime_options)
                    continue

                # Handle clear command
                if user_input.strip() == "/clear":
                    ui.console.clear()
                    ui.show_banner()
                    continue

                # Handle goal execution
                if not user_input.startswith("/"):
                    _execute_goal_interactive(user_input, ui, tracker, llm_client, logger, runtime_options)
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
    llm_client,
    logger,
    runtime_options: OpenPilotRuntimeOptions,
):
    """Execute a goal in interactive mode."""
    classification = _classify_task_route(goal)
    _show_task_route(ui, classification)
    if classification.route == "agent_generator":
        return _execute_agent_generator(goal, ui, llm_client, logger)
    return _execute_autopilot(goal, ui, tracker, llm_client, logger, runtime_options)


def _classify_task_route(task: str) -> "TaskRouteMetadata":
    """Classify a user task before selecting the execution path."""
    from metadata import TaskRouteMetadata, ToolInputMetadata
    from tools.task_classifier import task_classifier_executor

    result = task_classifier_executor(ToolInputMetadata.from_mapping("task_classifier", {"task": task}))
    if not isinstance(result.result, TaskRouteMetadata):
        raise TypeError(f"task_classifier returned {type(result.result).__name__}, expected TaskRouteMetadata")
    return result.result


def _show_task_route(ui: EnhancedUI, classification: "TaskRouteMetadata") -> None:
    """Show the selected route without interrupting execution."""
    ui.console.print(f"[dim]Task route: {classification.route} ({classification.confidence:.2f}) - {classification.reason}[/dim]")


def _show_help(ui: EnhancedUI):
    """Show help information."""
    from ui.commands import get_command_registry

    registry = get_command_registry()
    ui.console.print()
    ui.console.print(registry.format_help())
    ui.console.print()


def _show_config(
    ui: EnhancedUI,
    settings: LLMSettings,
    runtime_options: OpenPilotRuntimeOptions | None = None,
):
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
    embedding_settings = EmbeddingSettings()
    table.add_row("Embedding Provider", embedding_settings.provider)
    table.add_row("Embedding Model", embedding_settings.model)
    table.add_row("Embedding Base URL", embedding_settings.base_url or "[dim]inherits LLM[/dim]")
    table.add_row("Embedding Timeout", f"{embedding_settings.timeout_seconds}s")
    table.add_row("Embedding API Key", "✓ Set" if embedding_settings.api_key else "✗ Not set")
    if runtime_options is not None:
        if runtime_options.prompt_for_project_improvement_iterations:
            table.add_row("Improvement Iterations", "ask per generated project")
        else:
            table.add_row("Improvement Iterations", str(runtime_options.improvement_iterations))

    ui.console.print()
    ui.console.print(table)
    ui.console.print()


def _execute_autopilot(
    goal: str,
    ui: EnhancedUI,
    tracker: ProgressTracker,
    llm_client,
    logger,
    runtime_options: OpenPilotRuntimeOptions | None = None,
):
    """Execute goal using intelligent autopilot with enhanced UI."""
    from autonomous_iteration.intelligent_autopilot import IntelligentAutopilot
    from core.llm import LLMClient

    ui.console.print()
    runtime_options = runtime_options or OpenPilotRuntimeOptions()

    try:
        # Create autopilot with enhanced UI support
        autopilot = IntelligentAutopilot(
            llm_client=llm_client or LLMClient(),
            console=ui.console,
            auto_approve=True,
            logger=logger,
            use_enhanced_ui=True,
            enhanced_ui=ui,
            tracker=tracker,
            enable_iterative_improvement=runtime_options.enable_iterative_improvement,
            required_successful_improvements=runtime_options.improvement_iterations,
            prompt_for_project_improvement_iterations=runtime_options.prompt_for_project_improvement_iterations,
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

        ui.show_full_task_graph_timeline()

        if result.get("success"):
            warning = result.get("iteration_error")
            if warning:
                ui.show_success(
                    "Goal completed with iteration warning",
                    warning,
                )
            else:
                ui.show_success("Goal completed!")
        else:
            details = (
                result.get("error")
                or result.get("iteration_error")
                or result.get("failure_reason")
                or "Autopilot reported failure"
            )
            if result.get("failure_stage") or result.get("failed_tool"):
                context_lines = [
                    f"Stage: {result.get('failure_stage') or 'unknown'}",
                    f"Tool: {result.get('failed_tool') or 'unknown'}",
                ]
                if result.get("failed_iteration"):
                    context_lines.append(f"Iteration: {result.get('failed_iteration')}")
                details = f"{details}\n" + "\n".join(context_lines)
            ui.show_error("Autopilot execution failed", details)

    except Exception as e:
        ui.console.print()
        ui.show_full_task_graph_timeline()
        ui.show_error("Autopilot execution failed", str(e))
        import traceback
        traceback.print_exc()


def _execute_agent_generator(task: str, ui: EnhancedUI, llm_client = None, logger = None) -> bool:
    """Generate a reusable Python agent from an interactive task."""
    from pathlib import Path

    from agent_generator.runner import run_agent_generator
    from ui.environment_guard import agent_generator_llm_error_message, block_missing_socksio, block_project_venv

    if block_project_venv(ui.console):
        return False
    if block_missing_socksio(ui.console):
        return False
    output_dir = Path(__file__).resolve().parents[2] / "generated_agents"
    try:
        run_agent_generator(task, console=ui.console, output_dir=output_dir, llm_client=llm_client, logger=logger)
        return True
    except Exception as e:
        ui.show_error("Agent generation failed", agent_generator_llm_error_message(e))
        return False
