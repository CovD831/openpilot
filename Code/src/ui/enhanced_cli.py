"""Enhanced CLI entry point with improved UI."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
from typing import TYPE_CHECKING, Sequence
from uuid import uuid4

from rich.console import Console

from core.config import LLMSettings
from core.instrumented_llm import InstrumentedLLMClient
from metadata import (
    ConversationIdentity,
    ProjectImprovementPolicy,
    ProjectImprovementPolicySource,
    ProjectImprovementRequirement,
    SessionIngressState,
    SessionTurn,
)
from memory.session_ingress import SessionIngress
from ui.enhanced_ui import EnhancedUI
from ui.progress_tracker import ProgressTracker

if TYPE_CHECKING:
    from metadata import TaskRouteMetadata


DEFAULT_IMPROVEMENT_ITERATIONS = 2
_CONSTRAINT_COMMANDS = frozenset({"/constraints", "/confirm", "/reject", "/revoke"})
_PROPOSAL_APPROVE_COMMAND = "/approve"


def _is_constraint_command(user_input: str) -> bool:
    """Return whether input belongs to the typed session-constraint ingress."""

    command = str(user_input).strip().split(maxsplit=1)[0].casefold() if str(user_input).strip() else ""
    return command in _CONSTRAINT_COMMANDS


def _proposal_approval_id(user_input: str) -> str | None:
    """Return a proposal id only for the explicit mutation-approval command."""

    parts = str(user_input).strip().split(maxsplit=1)
    if len(parts) != 2 or parts[0].casefold() != _PROPOSAL_APPROVE_COMMAND:
        return None
    proposal_id = parts[1].strip()
    return proposal_id or None


def _runtime_diagnostics_enabled() -> bool:
    value = str(os.getenv("OPENPILOT_RUNTIME_DIAGNOSTICS_ENABLED", "1")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def _project_file_inventory(
    project_root: Path,
    *,
    limit: int = 160,
    max_directories: int = 256,
) -> list[str]:
    """Return body-free candidate paths for task design, never execution authority."""

    if not project_root.is_dir():
        raise ValueError(f"project root is not a directory: {project_root}")
    if limit < 1 or max_directories < 1:
        raise ValueError("project inventory limits must be positive")
    ignored_directories = {
        ".git",
        ".hg",
        ".mypy_cache",
        ".openpilot",
        ".pytest_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "node_modules",
        "venv",
    }
    paths: list[str] = []
    for directory_count, (current_root, directories, files) in enumerate(
        os.walk(project_root, followlinks=False),
        start=1,
    ):
        if directory_count > max_directories:
            return paths
        directories[:] = sorted(
            directory
            for directory in directories
            if directory not in ignored_directories and not directory.startswith(".")
        )
        for filename in sorted(files):
            candidate = Path(current_root) / filename
            if candidate.is_symlink():
                continue
            paths.append(str(candidate.relative_to(project_root)))
            if len(paths) >= limit:
                return paths
    return paths


def _new_cli_interaction_controller(
    *,
    llm_client,
    logger,
    source: str,
    mutation_started_callback=None,
):
    """Build the public CLI's proposal-first Pi-only interaction path."""

    from autonomous_iteration.agents.execution_task_decomposer import TaskDecomposer
    from autonomous_iteration.pi_task_runner import PiTaskRunner
    from ui.interaction_controller import InteractionController

    runner = PiTaskRunner(mutation_started_callback=mutation_started_callback)

    def design_tasks(goal: str, project_root: Path, task_id: str):
        decomposer = TaskDecomposer(llm_client, logger=logger)
        decomposition = decomposer.decompose(
            goal,
            context={
                "project_root": str(project_root),
                "project_files": _project_file_inventory(project_root),
            },
            parent_task_id=task_id,
        )
        return decomposition.subtasks

    def execute_admitted_task(goal, admission, approval, context):
        return runner.run(
            goal,
            admission,
            approval=approval,
            source=source,
            conversation_id=str(context["conversation_id"]),
        )

    return InteractionController(
        task_designer=design_tasks,
        executor=execute_admitted_task,
    )


def _proposal_payload(proposal) -> dict[str, object]:
    """Build a bounded, non-authoritative rendering of an admitted proposal."""

    grant = proposal.admission.grant
    validation = getattr(grant, "validation", None)
    return {
        "proposal_id": proposal.proposal_id,
        "goal": proposal.goal,
        "mode": "mutation" if proposal.is_mutation else "read_only",
        "admission_id": grant.admission_id,
        "task_id": grant.task_id,
        "protocol_version": grant.protocol_version,
        "project_root": grant.project_root,
        "read_files": list(grant.read_files),
        "write_files": list(grant.write_files),
        "validation_command": getattr(validation, "command", "") if validation else "",
    }


def _show_task_proposal(ui: EnhancedUI, proposal) -> None:
    """Render proposal data as literal JSON so untrusted paths cannot become markup."""

    ui.console.print("Task proposal")
    ui.console.print(
        json.dumps(_proposal_payload(proposal), ensure_ascii=False, indent=2),
        markup=False,
    )


@dataclass(frozen=True)
class OpenPilotRuntimeOptions:
    """Runtime options for autopilot creation."""

    improvement_iterations: int = DEFAULT_IMPROVEMENT_ITERATIONS
    prompt_for_project_improvement_iterations: bool = False
    improvement_requirement: ProjectImprovementRequirement = ProjectImprovementRequirement.OPTIONAL
    improvement_policy_source: ProjectImprovementPolicySource = ProjectImprovementPolicySource.AUTOMATIC_DEFAULT

    @property
    def enable_iterative_improvement(self) -> bool:
        return self.improvement_iterations > 0

    @property
    def project_improvement_policy(self) -> ProjectImprovementPolicy:
        if self.improvement_iterations <= 0:
            return ProjectImprovementPolicy(
                requirement=ProjectImprovementRequirement.DISABLED,
                source=self.improvement_policy_source,
                target_successes=0,
                max_attempts=0,
            )
        from autonomous_iteration.agents.iteration_agent import AutonomousIterationAgent

        return ProjectImprovementPolicy(
            requirement=self.improvement_requirement,
            source=self.improvement_policy_source,
            target_successes=self.improvement_iterations,
            max_attempts=AutonomousIterationAgent.minimum_attempt_budget(
                self.improvement_iterations
            ),
        )


def _format_failure_details(result: dict) -> str:
    context = _extract_failure_context(result)
    details = (
        context.get("failure_reason")
        or _result_value(result, "failure_reason")
        or _result_value(result, "error")
        or _result_value(result, "iteration_error")
        or "Autopilot reported failure"
    )
    failure_stage = context.get("failure_stage") or _result_value(result, "failure_stage")
    failed_tool = context.get("failed_tool") or _result_value(result, "failed_tool")
    failed_call_id = context.get("failed_call_id") or _result_value(result, "failed_call_id")
    failed_step_id = context.get("failed_step_id") or _result_value(result, "failed_step_id")
    failed_iteration = _result_value(result, "failed_iteration")
    context_lines = []
    if context.get("task_description"):
        context_lines.append(f"Task: {context['task_description']}")
    if context.get("task_id"):
        context_lines.append(f"Task ID: {context['task_id']}")
    if failure_stage or failed_tool:
        context_lines.extend(
            [
                f"Stage: {failure_stage or 'unknown'}",
                f"Tool: {failed_tool or 'unknown'}",
            ]
        )
        if failed_call_id:
            context_lines.append(f"Call: {failed_call_id}")
        if failed_step_id:
            context_lines.append(f"Step: {failed_step_id}")
        if failed_iteration:
            context_lines.append(f"Iteration: {failed_iteration}")
    if context.get("file_path"):
        context_lines.append(f"File: {context['file_path']}")
    if context.get("error_type"):
        context_lines.append(f"Error Type: {context['error_type']}")
    if context.get("suggested_recovery"):
        context_lines.append(f"Recovery: {context['suggested_recovery']}")
    response_preview = context.get("response_preview") or context.get("response_text")
    if response_preview:
        context_lines.append(f"Response Preview: {str(response_preview)[:1000]}")
    if context_lines:
        details = f"{details}\n" + "\n".join(context_lines)
    return str(details)


def _result_value(value, key: str):
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _extract_failure_context(result) -> dict:
    if not isinstance(result, dict):
        return {}
    for nested_key in ("session_result", "result"):
        nested_result = result.get(nested_key)
        if isinstance(nested_result, dict):
            nested_context = _extract_failure_context(nested_result)
            if nested_context:
                return nested_context
    direct_reason = result.get("failure_reason")
    if direct_reason and direct_reason != "Autopilot reported failure":
        direct_context = {
            "failure_reason": direct_reason,
            "failure_stage": result.get("failure_stage"),
            "failed_tool": result.get("failed_tool"),
            "failed_call_id": result.get("failed_call_id"),
            "failed_step_id": result.get("failed_step_id"),
            "task_id": result.get("task_id"),
            "task_description": result.get("task_description"),
            "file_path": result.get("file_path"),
            "error_type": result.get("error_type"),
            "suggested_recovery": result.get("suggested_recovery"),
            "response_preview": result.get("response_preview") or result.get("response_text"),
        }
        if any(value for key, value in direct_context.items() if key != "failure_reason"):
            return direct_context
    for task_result in result.get("results") or []:
        context = _failure_context_from_task_result(task_result)
        if context:
            return context
    if direct_reason:
        return {
            "failure_reason": direct_reason,
            "failure_stage": result.get("failure_stage"),
            "failed_tool": result.get("failed_tool"),
            "failed_call_id": result.get("failed_call_id"),
            "failed_step_id": result.get("failed_step_id"),
        }
    decomposition = result.get("decomposition")
    for task in _result_value(decomposition, "subtasks") or []:
        context = _failure_context_from_task(task)
        if context:
            return context
    return {}


def _failure_context_from_task_result(task_result) -> dict:
    metadata = _result_value(task_result, "result_metadata")
    failure = _result_value(metadata, "failure")
    reason = _result_value(failure, "error_message") or _result_value(task_result, "error")
    if not reason:
        return {}
    details = _result_value(failure, "details") or {}
    context = _failure_context_from_details(details, reason)
    context.setdefault("task_id", _result_value(task_result, "task_id"))
    context.setdefault("task_description", details.get("task_description") if isinstance(details, dict) else None)
    return context


def _failure_context_from_task(task) -> dict:
    status = str(_result_value(task, "status") or "").lower()
    if "failed" not in status and "blocked" not in status:
        return {}
    metadata = _result_value(task, "result") or _result_value(task, "result_metadata")
    failure = _result_value(metadata, "failure")
    reason = _result_value(failure, "error_message") or _result_value(task, "error")
    if not reason:
        return {}
    details = _result_value(failure, "details") or {}
    context = _failure_context_from_details(details, reason)
    context.setdefault("task_id", _result_value(task, "id"))
    context.setdefault("task_description", _result_value(task, "description"))
    return context


def _failure_context_from_details(details, reason: str) -> dict:
    if not isinstance(details, dict):
        details = {}
    tool_loop = details.get("tool_loop") if isinstance(details.get("tool_loop"), dict) else {}
    final_error = tool_loop.get("final_error") if isinstance(tool_loop, dict) else {}
    final_details = final_error.get("details") if isinstance(final_error, dict) and isinstance(final_error.get("details"), dict) else {}
    input_summary = details.get("input_summary") if isinstance(details.get("input_summary"), dict) else {}
    final_input = final_details.get("input_summary") if isinstance(final_details.get("input_summary"), dict) else {}
    error_type = (
        details.get("error_type")
        or details.get("failure_error_type")
        or final_details.get("error_type")
        or (final_error.get("error_type") if isinstance(final_error, dict) else None)
    )
    response_preview = (
        details.get("response_preview")
        or details.get("response_preview_start")
        or final_details.get("response_preview")
        or final_details.get("response_preview_start")
        or details.get("response_text")
        or final_details.get("response_text")
    )
    return {
        "failure_reason": reason,
        "failure_stage": details.get("failure_stage") or "Task Executor",
        "failed_tool": details.get("tool_name") or details.get("failed_tool") or final_details.get("tool_name"),
        "failed_call_id": details.get("call_id") or final_details.get("call_id"),
        "failed_step_id": details.get("step_id") or final_details.get("step_id"),
        "task_id": details.get("task_id") or final_details.get("task_id"),
        "task_description": details.get("task_description") or final_details.get("task_description"),
        "file_path": (
            details.get("file_path")
            or final_details.get("file_path")
            or input_summary.get("file_path")
            or final_input.get("file_path")
            or final_details.get("received_path")
        ),
        "error_type": error_type,
        "suggested_recovery": (
            details.get("suggested_recovery")
            or final_details.get("suggested_recovery")
            or details.get("recovery_strategy")
            or final_details.get("recovery_strategy")
        ),
        "response_preview": response_preview,
        "response_text": details.get("response_text") or final_details.get("response_text"),
    }


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

    settings = LLMSettings()

    # Initialize enhanced UI
    enhanced_ui = EnhancedUI(console)
    enhanced_ui.show_banner()

    # Initialize progress tracker
    tracker = ProgressTracker(enhanced_ui)

    # Create instrumented LLM client
    if llm_client is None:
        llm_client = InstrumentedLLMClient(settings, tracker)

    # Public Pi CLI has no legacy shared-log or iterative-improvement switch.
    logger = None

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
            project_path=str(getattr(args, "project_path", None) or "").strip(),
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
            improvement_requirement=(
                ProjectImprovementRequirement.REQUIRED
                if configured > 0
                else ProjectImprovementRequirement.DISABLED
            ),
            improvement_policy_source=ProjectImprovementPolicySource.USER_SELECTED,
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
    *,
    project_path: str = "",
) -> int:
    """Design one task and run only an admitted read-only Pi proposal."""
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

        root = Path(project_path or Path.cwd()).expanduser().resolve(strict=False)
        conversation_id = f"once_{uuid4().hex}"
        controller = _new_cli_interaction_controller(
            llm_client=active_llm_client,
            logger=logger,
            source="cli_once",
        )
        proposal = controller.propose(
            goal,
            project_root=root,
            conversation_id=conversation_id,
        )
        _show_task_proposal(ui, proposal)
        if proposal.is_mutation:
            ui.console.print(
                "approval_required: --once never dispatches mutations; use the interactive proposal flow.",
                markup=False,
            )
            return 3

        result = controller.execute(
            proposal.proposal_id,
            conversation_id=conversation_id,
        )

        if result.get("success"):
            response = str(result.get("response") or "").strip()
            if response:
                ui.console.print(response, markup=False)
            ui.show_success("Read-only Pi task completed successfully!")
            return 0

        ui.show_error("Pi task did not complete", _format_failure_details(result))
        return 2

    except Exception as e:
        ui.show_error("Task proposal or execution failed", str(e))
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
    conversation_id = f"conversation_{uuid4().hex}"
    interactive_project_root = Path(
        str(getattr(args, "project_path", None) or Path.cwd())
    ).expanduser().resolve(strict=False)
    ingress_state = SessionIngressState(
        identity=ConversationIdentity(
            conversation_id=conversation_id,
            run_id=f"run_{uuid4().hex}",
            turn_index=0,
            project_root=str(interactive_project_root),
        )
    )
    interaction_controller = _new_cli_interaction_controller(
        llm_client=llm_client,
        logger=logger,
        source="interactive",
        mutation_started_callback=lambda details: _show_mutation_revoke_hint(ui, details),
    )

    ui.console.print()
    ui.console.print("[bold green]Welcome to OpenPilot Interactive Mode[/bold green]")
    ui.console.print("[dim]Type your task or use /help for commands[/dim]")
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

                proposal_id = _proposal_approval_id(user_input)
                if proposal_id is not None:
                    ingress_state = _approve_interactive_proposal(
                        proposal_id,
                        ui,
                        interaction_controller,
                        ingress_state,
                    )
                    continue

                if _is_constraint_command(user_input):
                    ingress_state = _handle_constraint_command(user_input, ingress_state, ui)
                    continue

                # Handle clear command
                if user_input.strip() == "/clear":
                    ui.console.clear()
                    ui.show_banner()
                    continue

                # Handle goal execution
                if not user_input.startswith("/"):
                    ingress_state = _execute_goal_interactive(
                        user_input,
                        ui,
                        tracker,
                        llm_client,
                        logger,
                        runtime_options,
                        ingress_state=ingress_state,
                        interaction_controller=interaction_controller,
                    )
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
    *,
    ingress_state: SessionIngressState | None = None,
    interaction_controller=None,
):
    """Execute every public interactive task through the proposal-first Pi path."""
    del tracker, runtime_options
    active_llm_client = llm_client
    if interaction_controller is None:
        if active_llm_client is None:
            from core.llm import LLMClient

            active_llm_client = LLMClient()
        interaction_controller = _new_cli_interaction_controller(
            llm_client=active_llm_client,
            logger=logger,
            source="interactive",
            mutation_started_callback=lambda details: _show_mutation_revoke_hint(ui, details),
        )
    return _execute_goal_interactive_v2(
        goal,
        ui,
        interaction_controller,
        ingress_state=ingress_state,
        llm_client=active_llm_client,
        logger=logger,
    )


def _execute_goal_interactive_v2(
    goal: str,
    ui: EnhancedUI,
    interaction_controller,
    *,
    ingress_state: SessionIngressState | None,
    llm_client=None,
    logger=None,
):
    """Design and run the public Pi-only interaction path for one input turn."""

    if _handle_shell_state_command(goal, ui):
        return ingress_state if ingress_state is not None else None
    classification = _classify_task_route(goal)
    _show_task_route(ui, classification)
    if classification.route == "agent_generator":
        result = _execute_agent_generator(goal, ui, llm_client, logger)
        return _append_interactive_assistant_turn(ingress_state, result)

    conversation_id = (
        ingress_state.identity.conversation_id
        if ingress_state is not None
        else f"conversation_{uuid4().hex}"
    )
    project_root = (
        ingress_state.identity.project_root
        if ingress_state is not None
        else str(Path.cwd().expanduser().resolve())
    )
    proposal = interaction_controller.propose(
        goal,
        project_root=project_root,
        conversation_id=conversation_id,
    )
    _show_task_proposal(ui, proposal)
    if proposal.is_mutation:
        result: dict[str, object] = {
            "success": False,
            "status": "approval_required",
            "proposal_id": proposal.proposal_id,
        }
        ui.console.print(
            "approval_required: use /approve <proposal_id> to start the scoped Pi mutation. "
            "It will recheck file baselines and the ready project environment before dispatch.",
            markup=False,
        )
    else:
        result = interaction_controller.execute(
            proposal.proposal_id,
            conversation_id=conversation_id,
        )
        response = str(result.get("response") or "").strip()
        if response:
            ui.console.print(response, markup=False)
    return _append_interactive_assistant_turn(ingress_state, result)


def _approve_interactive_proposal(
    proposal_id: str,
    ui: EnhancedUI,
    interaction_controller,
    ingress_state: SessionIngressState,
) -> SessionIngressState:
    """Consume one explicit approval and dispatch the matching admitted task."""

    try:
        approval = interaction_controller.approve(
            proposal_id,
            conversation_id=ingress_state.identity.conversation_id,
        )
        result = interaction_controller.execute(
            proposal_id,
            conversation_id=ingress_state.identity.conversation_id,
            approval=approval,
        )
        response = str(result.get("response") or "").strip()
        if response:
            ui.console.print(response, markup=False)
    except Exception as exc:
        result = {
            "success": False,
            "status": "blocked",
            "reason": str(exc),
        }
        ui.show_error("Proposal was not dispatched", str(exc))
    return _append_interactive_assistant_turn(ingress_state, result)


def _show_mutation_revoke_hint(ui: EnhancedUI, details: dict[str, str]) -> None:
    """Show the separate-terminal revoke command after a consent becomes active."""

    project_root = str(details["project_root"])
    command = " ".join(
        (
            "openpilot revoke",
            "--project-path",
            shlex.quote(project_root),
            "--run-id",
            shlex.quote(str(details["run_id"])),
            "--consent-id",
            shlex.quote(str(details["consent_id"])),
        )
    )
    ui.console.print(
        "Mutation consent is active for this Run. To revoke it from another terminal before "
        f"the next tool dispatch, run: {command}",
        markup=False,
    )


def _append_interactive_assistant_turn(
    ingress_state: SessionIngressState | None,
    result,
):
    if ingress_state is None:
        return result
    assistant_turn = SessionTurn(
        identity=ConversationIdentity(
            conversation_id=ingress_state.identity.conversation_id,
            run_id=ingress_state.identity.run_id,
            turn_index=ingress_state.identity.turn_index + 1,
            project_root=ingress_state.identity.project_root,
        ),
        message_id=f"message_{uuid4().hex}",
        role="assistant",
        content=f"Execution result: {str(result)[:2000]}",
    )
    return SessionIngress.open_turn(ingress_state, assistant_turn)


def _handle_constraint_command(
    user_input: str,
    ingress_state: SessionIngressState,
    ui: EnhancedUI,
) -> SessionIngressState:
    """Apply explicit in-session constraint commands without Provider calls."""
    parts = user_input.strip().split()
    command = parts[0].casefold() if parts else "/constraints"
    if command == "/constraints" and len(parts) == 1:
        pending = [proposal.proposal_id for proposal in ingress_state.pending_proposals if proposal.status == "proposed"]
        active = [entry.constraint_key for entry in ingress_state.session_constraints.active_entries]
        ui.console.print(f"[dim]Pending constraint proposals: {pending or 'none'}[/dim]")
        ui.console.print(f"[dim]Active session constraints: {active or 'none'}[/dim]")
        return ingress_state
    try:
        if command in {"/confirm", "/reject"} and len(parts) == 2:
            if command == "/confirm":
                return SessionIngress.confirm_proposal(
                    ingress_state,
                    proposal_id=parts[1],
                    confirmation_turn=ingress_state.identity.turn_index + 1,
                )
            return SessionIngress.reject_proposal(ingress_state, proposal_id=parts[1])
        if command == "/revoke" and len(parts) == 2:
            return SessionIngress.revoke_constraint(
                ingress_state,
                constraint_key=parts[1],
                turn_index=ingress_state.identity.turn_index + 1,
            )
        ui.console.print("[yellow]Usage: /constraints | /confirm <proposal_id> | /reject <proposal_id> | /revoke <constraint_key>[/yellow]")
    except ValueError as exc:
        ui.console.print(f"[yellow]Constraint command rejected: {exc}[/yellow]")
    return ingress_state


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


def _handle_shell_state_command(user_input: str, ui: EnhancedUI) -> bool:
    """Explain shell state commands that cannot affect the user's outer shell."""
    text = " ".join(str(user_input or "").strip().split())
    lowered = text.casefold()
    if not text:
        return False
    state_commands = (
        lowered.startswith("source ")
        or lowered.startswith(". ")
        or lowered.startswith("conda activate")
        or lowered == "deactivate"
        or lowered.startswith("deactivate ")
        or lowered.startswith("export ")
        or lowered.startswith("cd ")
    )
    if not state_commands:
        return False
    ui.console.print("[yellow]Shell state command was not executed inside OpenPilot.[/yellow]")
    ui.console.print(
        "[dim]OpenPilot runs project commands with the target project cwd and .venv injected through metadata. "
        "If you want to change your outer terminal environment, run this command in your system shell instead.[/dim]"
    )
    return True


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
