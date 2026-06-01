"""Intelligent Autopilot executor using dynamic task decomposition and tools."""

from __future__ import annotations

import ast
import re
import shlex
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from autonomous_iteration.agents.iteration_agent import AutonomousIterationAgent
from autonomous_iteration.agents.project_evaluator import ProjectEvaluatorAgent
from core.llm import LLMClient
from core.semantic_analyzer import SemanticAnalyzer
from core.tool_event_emitter import ToolEventEmitter
from memory.memory_store import MemoryStore
from autonomous_iteration.task_models import (
    Task,
    TaskStatus,
    TaskPriority,
    TaskExecutionContext,
    TaskExecutionResult
)
from autonomous_iteration.models import EvaluationResult, IterationResult
from tools.tool_selection import (
    ToolSelection,
)
from tools.tool_registry import ToolRegistry
from tools.tool_executor import ToolExecutor
from core.openpilot_log import OpenPilotLogger
from core.exceptions import ErrorCategory, classify_error
from metadata import (
    FailureMetadata,
    ProjectObjectiveMetadata,
    ReferenceInsightMetadata,
    ResultStatus,
    SuccessMetricMetadata,
    TaskResultMetadata,
    TextArtifactMetadata,
    ToolExecutionEnvelopeMetadata,
    ToolInputMetadata,
    ToolResultMetadata,
)
from autonomous_iteration.improvement_context import ImprovementContextHelper
from autonomous_iteration.project_improvement_runtime import ProjectImprovementRuntime
from autonomous_iteration.task_executor import AutonomousTaskExecutor
from autonomous_iteration.agents.execution_orchestrator import AgentOrchestrator
from autonomous_iteration.agents.execution_task_decomposer import TaskDecomposer
from autonomous_iteration.agents.tool_planning_executor import ToolPlanningTaskExecutor
from ui.console_presenter import ConsolePresenter
from ui.iteration_dashboard import IterationDashboardAdapter
from autonomous_iteration.project_iteration import ProjectIterationHelper
from autonomous_iteration.tool_io import ExecutionToolIO
from autonomous_iteration.runtime_controller import AgentRuntimeController


class IntelligentAutopilot:
    """Intelligent autopilot using dynamic task decomposition."""

    def __init__(
        self,
        llm_client: LLMClient,
        console: Console | None = None,
        auto_approve: bool = True,
        logger: OpenPilotLogger | None = None,
        log_file: str | Path | None = None,
        use_enhanced_ui: bool = False,
        enhanced_ui: Any | None = None,
        tracker: Any | None = None,
        enable_iterative_improvement: bool = True,
        required_successful_improvements: int = 2,
        required_successful_iterations: int | None = None,
        max_iteration_attempts: int = 4,
        prompt_for_project_improvement_iterations: bool = False,
        project_objective_override: ProjectObjectiveMetadata | None = None,
        success_metric_overrides: list[SuccessMetricMetadata] | None = None,
        preferred_improvement_dimensions: list[str] | None = None,
        disallowed_improvement_directions: list[str] | None = None,
        allow_reference_search: bool = True,
        reference_provider: Callable[..., list[Any]] | None = None,
    ):
        """Initialize intelligent autopilot.

        Args:
            llm_client: LLM client
            console: Rich console
            auto_approve: Auto-approve low/medium risk operations
            logger: Logger instance
            log_file: Log file path
            use_enhanced_ui: Use enhanced UI with progress tracking
            enhanced_ui: Existing enhanced UI instance to update
            tracker: Existing progress tracker to reuse
            enable_iterative_improvement: Run evaluation and improvement loops for project outputs
            required_successful_improvements: Successful code improvement rounds required before stopping
            required_successful_iterations: Backward-compatible alias for required_successful_improvements
            max_iteration_attempts: Maximum improvement/repair attempts before stopping
            prompt_for_project_improvement_iterations: Ask per generated project how many improvement rounds to run
        """
        self.console = console or Console()
        self.auto_approve = auto_approve
        self.use_enhanced_ui = use_enhanced_ui
        self.enable_iterative_improvement = enable_iterative_improvement
        if required_successful_iterations is not None:
            required_successful_improvements = required_successful_iterations
        self.required_successful_improvements = required_successful_improvements
        self.max_iteration_attempts = max(
            max_iteration_attempts,
            AutonomousIterationAgent.minimum_attempt_budget(required_successful_improvements),
        )
        self.prompt_for_project_improvement_iterations = prompt_for_project_improvement_iterations
        self.allow_reference_search = allow_reference_search
        self._project_improvement_iterations_prompted = False
        self._project_environments: dict[str, dict[str, Any]] = {}

        # Initialize UI components
        if use_enhanced_ui:
            from ui.enhanced_ui import EnhancedUI
            from ui.progress_tracker import ProgressTracker
            from core.instrumented_llm import InstrumentedLLMClient

            self.enhanced_ui = enhanced_ui or EnhancedUI(self.console)
            self.tracker = tracker or ProgressTracker(self.enhanced_ui)
            self._owns_tracker = tracker is None
            if isinstance(llm_client, InstrumentedLLMClient):
                llm_client.tracker = self.tracker
                self.llm_client = llm_client
            elif hasattr(llm_client, "settings"):
                self.llm_client = InstrumentedLLMClient(llm_client.settings, self.tracker)
            else:
                self.llm_client = llm_client
        else:
            self.enhanced_ui = None
            self.tracker = None
            self._owns_tracker = False
            self.llm_client = llm_client

        # Initialize logger
        default_log_file = Path(__file__).resolve().parents[2] / "logs" / "autopilot.jsonl"
        self.logger = logger or OpenPilotLogger(log_file or default_log_file)

        # Session tracking
        self.session_id: str | None = None
        self.stats = {
            "start_time": None,
            "end_time": None,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "success": False,
        }

        # Initialize components
        self.task_decomposer = TaskDecomposer(
            self.llm_client,
            logger=self.logger,
            session_id_getter=lambda: self.session_id,
        )
        self.project_evaluator = ProjectEvaluatorAgent(
            self.llm_client,
            logger=self.logger,
            session_id_getter=lambda: self.session_id,
        )
        self.memory_store = MemoryStore()
        try:
            from memory.context_builder import MemoryContextBuilder
            from memory.agents.memory_vault_agent import MemoryVaultAgent

            self.memory_vault_agent = MemoryVaultAgent(
                memory_store=self.memory_store,
                logger=self.logger,
                session_id_getter=lambda: self.session_id,
            )
            self.memory_context_builder = MemoryContextBuilder(
                memory_store=self.memory_store,
                memory_vault_agent=self.memory_vault_agent,
            )
        except Exception as exc:
            self.memory_vault_agent = None
            self.memory_context_builder = None
            self.logger.log_structured_event(
                source_type="module",
                source_name="autonomous_iteration.intelligent_autopilot.memory_context_builder",
                phase="initialization",
                event_type="module_failed",
                session_id="unknown",
                turn_id=1,
                success=False,
                error=str(exc),
            )
        self.iterative_improvement = AutonomousIterationAgent(
            self.project_evaluator,
            required_successful_improvements=self.required_successful_improvements,
            max_iteration_attempts=self.max_iteration_attempts,
            llm_client=self.llm_client,
            memory_store=self.memory_store,
            memory_context_builder=self.memory_context_builder,
            logger=self.logger,
            project_objective_override=project_objective_override,
            success_metric_overrides=success_metric_overrides,
            preferred_improvement_dimensions=preferred_improvement_dimensions,
            disallowed_improvement_directions=disallowed_improvement_directions,
            allow_reference_search=allow_reference_search,
            reference_provider=reference_provider or self._gather_project_reference_insights,
        )
        self.orchestrator = AgentOrchestrator(max_concurrent_tasks=3)
        self.semantic_analyzer = SemanticAnalyzer(self.llm_client)
        self.tool_registry = ToolRegistry()

        # Register built-in tools
        from tools.builtin_tools import register_builtin_tools
        register_builtin_tools(self.tool_registry)
        self._register_contextual_tools()

        # Use instrumented executor if enhanced UI is enabled
        if use_enhanced_ui:
            from tools.instrumented_executor import InstrumentedToolExecutor
            self.tool_executor = InstrumentedToolExecutor(self.tool_registry, self.tracker)
        else:
            self.tool_executor = ToolExecutor(self.tool_registry, logger=self.logger)

        self.tool_io = ExecutionToolIO(self.logger, lambda: self.session_id)
        self.project_iteration = ProjectIterationHelper(self.logger, lambda: self.session_id)
        self.iteration_dashboard = IterationDashboardAdapter(self, self.logger, lambda: self.session_id)
        self.improvement_context = ImprovementContextHelper(
            environment_context_getter=self._project_environment_context,
            logger=self.logger,
            session_id_getter=lambda: self.session_id,
        )
        self.project_improvement_runtime = ProjectImprovementRuntime(self)
        self.autonomous_task_executor = AutonomousTaskExecutor(self)
        self.tool_planning_task_executor = ToolPlanningTaskExecutor(self)
        self.console_presenter = ConsolePresenter(
            self.console,
            auto_approve_getter=lambda: self.auto_approve,
            stats_getter=lambda: self.stats,
            logger=self.logger,
            session_id_getter=lambda: self.session_id,
        )
        self.runtime_controller = AgentRuntimeController(self)

        # Register task executor
        self.orchestrator.set_task_executor(self._execute_task)

    def _register_contextual_tools(self) -> None:
        """Register tool wrappers that can reuse this autopilot's runtime context."""
        from tools.code_generator import CODE_GENERATOR_DEFINITION, code_generator_executor
        from tools.code_editor import CODE_EDITOR_DEFINITION, code_editor_executor
        from tools.code_unit_generator import CODE_UNIT_GENERATOR_DEFINITION, code_unit_generator_executor

        def _with_llm_client(input_metadata: ToolInputMetadata, tool_name: str) -> ToolInputMetadata:
            if not isinstance(input_metadata, ToolInputMetadata):
                raise TypeError(f"contextual {tool_name} requires ToolInputMetadata")
            runtime_handles = dict(input_metadata.runtime_handles)
            runtime_handles["_llm_client"] = self.llm_client
            return input_metadata.model_copy(update={"runtime_handles": runtime_handles})

        def execute_code_generator(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
            return code_generator_executor(_with_llm_client(input_metadata, "code_generator"))

        def execute_code_unit_generator(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
            return code_unit_generator_executor(_with_llm_client(input_metadata, "code_unit_generator"))

        def execute_code_editor(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
            return code_editor_executor(_with_llm_client(input_metadata, "code_editor"))

        self.tool_registry.register(
            CODE_GENERATOR_DEFINITION,
            execute_code_generator,
            allow_override=True,
        )
        self.tool_registry.register(
            CODE_UNIT_GENERATOR_DEFINITION,
            execute_code_unit_generator,
            allow_override=True,
        )
        self.tool_registry.register(
            CODE_EDITOR_DEFINITION,
            execute_code_editor,
            allow_override=True,
        )

    def _gather_project_reference_insights(self, query: str, state: Any, objective: Any) -> list[ReferenceInsightMetadata]:
        """Fetch a compact optional reference insight for a low-evidence diagnosis."""
        if not self.allow_reference_search:
            return []
        try:
            from tools.web_searcher import web_searcher_executor

            result = web_searcher_executor(
                ToolInputMetadata.from_mapping(
                    "web_searcher",
                    {
                        "query": query,
                        "max_results": 3,
                        "max_pages": 0,
                        "llm_cleanup": False,
                        "timeout": 8,
                    },
                )
            )
        except Exception:
            return []
        artifact = result.result if isinstance(result, ToolResultMetadata) else None
        if artifact is None:
            return []
        summary = str(getattr(artifact, "research_summary", "") or "")
        results = getattr(artifact, "results", []) or []
        source_notes = []
        best_practices = []
        for item in results[:3]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("name") or "").strip()
            snippet = str(item.get("snippet") or item.get("summary") or "").strip()
            if title:
                source_notes.append(title[:180])
            if snippet:
                best_practices.append(snippet[:220])
        if not summary and not best_practices:
            return []
        return [
            ReferenceInsightMetadata(
                query=query,
                summary=summary or f"Reference search returned {len(results)} result(s) for {getattr(objective, 'project_type', 'project')}.",
                best_practices=best_practices,
                applicability="external_reference",
                source_notes=source_notes,
                confidence=0.45,
            )
        ]

    def _stop_tracking_if_owned(self) -> None:
        if self.tracker and self._owns_tracker:
            self.tracker.stop_tracking()

    def execute(self, goal: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute goal using intelligent task decomposition.

        Args:
            goal: User goal
            context: Optional context information

        Returns:
            Execution result
        """
        self.session_id = str(uuid.uuid4())
        self.stats["start_time"] = datetime.now()
        context = context or {}

        mode = "enhanced_ui" if self.use_enhanced_ui and self.enhanced_ui and self.tracker else "standard"
        try:
            return self.runtime_controller.run(goal, context, mode=mode)
        except Exception as e:
            if self.enhanced_ui:
                self.enhanced_ui.log_activity("error", f"Execution failed: {str(e)}")
            self.logger.log_event(
                "execution_error",
                {"error": str(e), "goal": goal},
                session_id=self.session_id or "unknown",
                turn_id=1,
            )
            if classify_error(e) in {ErrorCategory.NETWORK, ErrorCategory.TIMEOUT, ErrorCategory.RETRYABLE}:
                return self._structured_execution_error(goal, e)
            raise

    def _structured_execution_error(self, goal: str, error: Exception) -> dict[str, Any]:
        category = classify_error(error)
        self.stats["success"] = False
        self.stats["tasks_failed"] = max(1, self.stats.get("tasks_failed", 0))
        self.stats["end_time"] = datetime.now()
        if self.enhanced_ui:
            self.enhanced_ui.set_current_task_state(
                title="Autopilot execution failed",
                details=(
                    f"Stage: LLM Transport\n"
                    f"Category: {category.value}\n"
                    f"Reason: {error}"
                ),
                status="failed",
            )
        self._stop_tracking_if_owned()
        return {
            "success": False,
            "goal": goal,
            "error": str(error),
            "failure_stage": "LLM Transport",
            "failed_tool": "llm_client",
            "failure_reason": str(error),
            "retry_attempted": True,
            "retry_history": [],
            "partial_success": False,
            "stats": self.stats,
        }

    def _try_simple_code_artifact_fast_path(self, goal: str, semantic: Any) -> dict[str, Any] | None:
        """Generate simple single-file code artifacts without multi-step decomposition."""
        target_file = self._simple_code_artifact_target(goal, semantic)
        if target_file is None:
            return None

        if self.enhanced_ui:
            self.enhanced_ui.set_current_task_state(
                title="Fast path code generation",
                details=f"Target: {target_file}",
                status="running",
            )
            self.enhanced_ui.update_main_content(
                self.enhanced_ui.create_status_panel(
                    "Task Decomposition",
                    "Simple code artifact detected. Using 1-step fast path."
                )
            )
            self.enhanced_ui.log_activity("task", "Task Decomposition: 1 fast-path code task")
        else:
            self.console.print("[cyan]Fast path:[/cyan] generating a single code artifact")

        self._project_improvement_actions: list[str] = []
        task = Task(
            id=str(uuid.uuid4()),
            description=f"Generate complete code artifact at {target_file}",
            priority=TaskPriority.HIGH,
        )
        started = datetime.now()
        tool_results: list[ToolExecutionEnvelopeMetadata] = []

        code_prompt = (
            f"Create a complete, runnable single-file Python program for this user request: {goal}\n"
            f"Write the final artifact for: {target_file}\n"
            "Prefer Python standard library modules when practical. If this is a game, include controls, "
            "score display, restart or exit behavior, collision/game-over handling, and clear inline comments. "
            "Return only the Python source code."
        )

        code_result = self._execute_fast_tool(
            task=task,
            step_id="fast_code_generator",
            tool_name="code_generator",
            input_metadata=ToolInputMetadata.from_mapping("code_generator", {
                "task_description": code_prompt,
                "language": "python",
                "context": f"Output file: {target_file}",
            }),
        )
        tool_results.append(code_result)

        code = ""
        if code_result.success and code_result.output is not None:
            code = str(code_result.output.get("code", ""))

        syntax_error = None
        if code:
            try:
                ast.parse(code)
            except SyntaxError as exc:
                syntax_error = f"Syntax error on line {exc.lineno}: {exc.msg}"

        if code and syntax_error is None:
            write_result = self._execute_fast_tool(
                task=task,
                step_id="fast_file_writer",
                tool_name="file_writer",
                input_metadata=ToolInputMetadata.from_mapping("file_writer", {
                    "file_path": str(target_file),
                    "content": code,
                    "encoding": "utf-8",
                    "create_dirs": True,
                    "overwrite": True,
                }),
            )
            tool_results.append(write_result)
            if write_result.success:
                environment_result = self._sync_project_environment(
                    task=task,
                    step_id="fast_project_environment_tool",
                    project_path=target_file.parent,
                    written_files=[str(target_file)],
                    entry_files=[str(target_file)],
                    run_command=f"python {shlex.quote(target_file.name)}",
                )
                tool_results.append(environment_result)
                if not environment_result.success:
                    if self.enhanced_ui:
                        self.enhanced_ui.set_current_task_state(
                            title="Environment Setup failed",
                            details=str(environment_result.error_message or "Project environment sync failed."),
                            status="failed",
                        )
                    readme_result = None
                    environment_payload = None
                    run_command = f"python {shlex.quote(target_file.name)}"
                else:
                    readme_result = None
                    environment_payload = environment_result.output
                    run_command = str(environment_payload.get("run_command") or f"python {shlex.quote(target_file.name)}") if environment_payload else f"python {shlex.quote(target_file.name)}"
                if environment_result.success:
                    readme_result = self._execute_fast_tool(
                        task=task,
                        step_id="fast_readme_tool",
                        tool_name="readme_tool",
                        input_metadata=ToolInputMetadata.from_mapping("readme_tool", {
                            "project_path": str(target_file.parent),
                            "project_summary": goal,
                            "written_files": [str(target_file)],
                            "entry_files": [str(target_file)],
                            "run_command": run_command,
                            "setup_commands": (environment_payload.get("setup_commands") or []) if environment_payload else [],
                            "environment": self._readme_environment_context(environment_payload.to_json_dict() if environment_payload else {}),
                            "overwrite": True,
                        }),
                    )
                    tool_results.append(readme_result)
        elif syntax_error:
            tool_results.append(ToolExecutionEnvelopeMetadata(
                tool_name="syntax_validation",
                step_id="fast_syntax_validation",
                status=ResultStatus.FAIL,
                success=False,
                input_metadata=ToolInputMetadata.from_mapping("syntax_validation", {"file_path": str(target_file)}),
                failure=FailureMetadata(error_type="SyntaxError", error_message=syntax_error),
            ))

        primary_results = [result for result in tool_results if result.tool_name != "readme_tool"]
        success = all(result.success for result in primary_results)
        duration = (datetime.now() - started).total_seconds()
        error_msg = None
        if not success:
            errors = [r.error_message for r in primary_results if not r.success]
            error_msg = "; ".join(error for error in errors if error) or "Fast-path code generation failed"
        readme_result = next((r for r in tool_results if r.tool_name == "readme_tool"), None)
        readme_error = readme_result.error_message if readme_result and not readme_result.success else None
        improvement_result = None
        iteration_error_msg = None
        if success:
            run_command = f"python {shlex.quote(target_file.name)}"
            environment_result = next((r for r in tool_results if r.tool_name == "project_environment_tool" and r.success), None)
            if environment_result and environment_result.output is not None:
                run_command = str(environment_result.output.get("run_command") or run_command)
            improvement_result = self._run_iterative_improvement(
                goal=goal,
                project_path=target_file.parent,
                written_files=[str(target_file)],
                run_command=run_command,
                readme_path=(
                    readme_result.output.get("file_path")
                    if readme_result and readme_result.output is not None
                    else target_file.parent / "README.md"
                ),
            )
            if improvement_result is not None and not improvement_result.get("success", False):
                iteration_error_msg = self._format_iteration_failure(improvement_result)
                success = False
                error_msg = iteration_error_msg

        task_result = TaskExecutionResult(
            task_id=task.id,
            status=TaskStatus.COMPLETED if success else TaskStatus.FAILED,
            result_metadata=TaskResultMetadata(
                task_id=task.id,
                status=ResultStatus.SUCCESS if success else ResultStatus.FAIL,
                result=TextArtifactMetadata(
                    content="completed" if success else (error_msg or "failed"),
                    attributes={
                        "description": task.description,
                        "tool_results": [tool_result.to_json_dict() for tool_result in tool_results],
                        "all_tools_succeeded": success,
                        "final_output": tool_results[-1].output.to_json_dict() if tool_results and tool_results[-1].output else None,
                    },
                ) if success else None,
                failure=None if success else FailureMetadata(error_type="FastPathError", error_message=error_msg or "Fast-path code generation failed"),
            ),
            error=error_msg,
            duration=duration,
            annotations={"fast_path": True, "target_file": str(target_file)},
        )

        self.stats["success"] = success
        self.stats["tasks_completed"] = 1 if success else 0
        self.stats["tasks_failed"] = 0 if success else 1
        self.stats["end_time"] = datetime.now()
        self._stop_tracking_if_owned()

        if self.enhanced_ui:
            fast_details = (
                f"Wrote {target_file}"
                if success
                else f"Fast-path execution failed: {error_msg}"
            )
            if success and readme_result and readme_result.success and readme_result.output is not None:
                fast_details += f"\nREADME: {readme_result.output.get('file_path', 'README.md')}"
            elif success and readme_error:
                fast_details += f"\nREADME generation failed: {readme_error}"
            if improvement_result and improvement_result.get("validation"):
                fast_details += (
                    f"\nImprovements applied: {improvement_result.get('completed_improvements', 0)}/"
                    f"{improvement_result.get('required_improvements', self.required_successful_improvements)}"
                )
                if iteration_error_msg:
                    fast_details += f"\nIteration warning: {iteration_error_msg}"
            self.enhanced_ui.update_main_content(
                self.enhanced_ui.create_status_panel(
                    "Success" if success else "Failed",
                    fast_details,
                )
            )

        self.logger.log_event(
            "fast_path_completed",
            {
                "goal": goal,
                "target_file": str(target_file),
                "success": success,
                "error": error_msg,
                "iteration_error": iteration_error_msg,
                "readme_error": readme_error,
                "improvement": self._summarize_metadata_output(improvement_result),
            },
            session_id=self.session_id or "unknown",
            turn_id=1,
        )

        return {
            "success": success,
            "goal": goal,
            "semantic_analysis": semantic,
            "fast_path": True,
            "target_file": str(target_file),
            "results": [task_result],
            "stats": self.stats,
            "error": error_msg,
            "iteration_error": iteration_error_msg,
            "readme": readme_result,
            "validation": improvement_result.get("validation") if improvement_result else None,
            "evaluation": improvement_result.get("evaluation") if improvement_result else None,
            "completed_improvements": improvement_result.get("completed_improvements", 0) if improvement_result else 0,
            "required_improvements": improvement_result.get("required_improvements", self.required_successful_improvements) if improvement_result else self.required_successful_improvements,
            "completed_iterations": improvement_result.get("completed_iterations", 0) if improvement_result else 0,
            "required_iterations": improvement_result.get("required_iterations", self.required_successful_improvements) if improvement_result else self.required_successful_improvements,
            "improvement_report": improvement_result.get("improvement_report", {}) if improvement_result else {},
            "iterations": improvement_result.get("iterations", []) if improvement_result else [],
            "partial_success": improvement_result.get("partial_success", False) if improvement_result else False,
            "failure_stage": improvement_result.get("failure_stage") if improvement_result else None,
            "failed_iteration": improvement_result.get("failed_iteration") if improvement_result else None,
            "failed_tool": improvement_result.get("failed_tool") if improvement_result else None,
            "failure_reason": improvement_result.get("failure_reason") if improvement_result else None,
            "retry_attempted": improvement_result.get("retry_attempted", False) if improvement_result else False,
            "retry_history": improvement_result.get("retry_history", []) if improvement_result else [],
            "remaining_goals": improvement_result.get("remaining_goals", []) if improvement_result else [],
        }

    def _simple_code_artifact_target(self, goal: str, semantic: Any) -> Path | None:
        path_match = re.search(r"['\"](?P<path>/[^'\"]+)['\"]", goal)
        if not path_match:
            return None

        goal_lower = goal.lower()
        code_keywords = ("snake", "贪吃蛇", "game", "小游戏", "脚本", "script", "程序", "app")
        if not any(keyword in goal_lower for keyword in code_keywords):
            return None

        task_type = getattr(getattr(semantic, "task_type", None), "value", getattr(semantic, "task_type", ""))
        if task_type and task_type not in {"coding", "file_workflow", "automation", "unknown"}:
            return None

        requested_path = Path(path_match.group("path")).expanduser()
        if requested_path.suffix == ".py":
            return requested_path
        return requested_path / "main.py"

    def _execute_fast_tool(
        self,
        task: Task,
        step_id: str,
        tool_name: str,
        input_metadata: ToolInputMetadata,
        timeout_override: int | None = None,
        parent_task_id: str | None = None,
    ) -> ToolExecutionEnvelopeMetadata:
        if timeout_override is None:
            timeout_override = self._llm_tool_timeout_override(tool_name)
        typed_input = self._apply_project_command_context(tool_name, input_metadata)
        display_payload = typed_input.to_params()
        session_id = self.session_id or "unknown"
        task_id = str(task.id)
        call_id = f"{task_id}:{step_id}"
        event_emitter = ToolEventEmitter(self)
        tool_context = event_emitter.build_context(
            task_id=task_id,
            session_id=session_id,
            step_id=step_id,
            call_id=call_id,
            tool_name=tool_name,
            input_metadata=typed_input,
        )
        tool_call = event_emitter.create_tool_call(
            session_id=session_id,
            task_id=task_id,
            step_id=step_id,
            call_id=call_id,
            tool_name=tool_name,
            input_metadata=typed_input,
            tool_context=tool_context,
            status="pending",
            reason="capability_match",
        )
        tool_events = [
            event_emitter.emit(
                task_id=task_id,
                tool_call=tool_call,
                event_type="pending",
                status="pending",
                input_metadata=typed_input,
                tool_context=tool_context,
            )
        ]

        if self.enhanced_ui:
            if parent_task_id:
                self._set_dashboard_task_status(parent_task_id, "running")
            self._set_dashboard_tool_status(
                parent_task_id=parent_task_id,
                tool_id=step_id,
                tool_name=tool_name,
                status="running",
            )
            display_params = dict(display_payload)
            if "content" in display_params:
                display_params["content"] = f"<{len(str(display_params['content']))} chars>"
            param_lines = "\n".join(f"{key}: {value}" for key, value in display_params.items())
            self.enhanced_ui.set_current_task_state(
                title=f"Tool: {tool_name}",
                details=f"Task: {task.description}\nStep: {step_id}\n{param_lines}",
                status="running",
            )

        selection = ToolSelection(
            step_id=step_id,
            tool_name=tool_name,
            reason="capability_match",
            confidence=0.95,
            input_metadata=typed_input,
            requires_confirmation=False,
            fallback_tools=[],
            depends_on=[],
            timeout_override=timeout_override,
        )

        self.logger.log_event(
            "tool_execution_start",
            {
                "task_id": task.id,
                "step_id": step_id,
                "tool": tool_name,
                "timeout_override": timeout_override,
                "input_metadata_summary": self._sanitize_tool_metadata(typed_input),
            },
            session_id=self.session_id or "unknown",
            turn_id=1,
        )

        tool_events.append(
            event_emitter.emit(
                task_id=task_id,
                tool_call=tool_call,
                event_type="running",
                status="running",
                input_metadata=typed_input,
                tool_context=tool_context,
            )
        )
        exec_result, retry_history = self._execute_tool_with_fast_retry(selection)
        if self.enhanced_ui:
            status = "completed" if exec_result.success else "failed"
            self._set_dashboard_tool_status(
                parent_task_id=parent_task_id,
                tool_id=step_id,
                tool_name=tool_name,
                status=status,
            )
            detail = "Tool returned successfully"
            if not exec_result.success and exec_result.error:
                detail = exec_result.error.error_message
            self.enhanced_ui.set_current_task_state(
                title=f"Tool: {tool_name}",
                details=detail,
                status=status,
            )
        status_text = getattr(exec_result.status, "value", str(exec_result.status))
        status = self._result_status_from_execution(status_text, exec_result.success)
        failure = self._failure_metadata_from_execution(exec_result.error)
        if exec_result.success:
            tool_events.append(
                event_emitter.emit(
                    task_id=task_id,
                    tool_call=tool_call,
                    event_type="completed",
                    status="completed",
                    input_metadata=typed_input,
                    output_metadata=exec_result.output_metadata,
                    tool_context=tool_context,
                )
            )
        else:
            tool_events.append(
                event_emitter.emit(
                    task_id=task_id,
                    tool_call=tool_call,
                    event_type="error",
                    status="error",
                    input_metadata=typed_input,
                    tool_context=tool_context,
                    failure=failure,
                    recoverable=bool(failure and failure.recoverable),
                )
            )
        result = ToolExecutionEnvelopeMetadata(
            tool_name=tool_name,
            step_id=step_id,
            status=status,
            success=exec_result.success,
            input_metadata=typed_input,
            output_metadata=exec_result.output_metadata,
            failure=failure,
            duration_seconds=exec_result.duration_seconds,
            timeout_override=timeout_override,
            attempts_used=getattr(exec_result, "attempt_number", 1),
            retry_count=getattr(exec_result, "retry_count", 0),
            retry_history=retry_history,
            call_id=call_id,
            tool_context=tool_context,
            tool_events=tool_events,
        )
        self.logger.log_event(
            "tool_executed",
            {
                "task_id": task.id,
                "step_id": step_id,
                "tool": tool_name,
                "success": exec_result.success,
                "status": status.value,
                "error_type": failure.error_type if failure else None,
                "error": failure.error_message if failure else None,
                "duration_seconds": result.duration_seconds,
                "attempts_used": result.attempts_used,
                "retry_count": result.retry_count,
                "output": self._summarize_metadata_output(exec_result.output_metadata),
            },
            session_id=self.session_id or "unknown",
            turn_id=1,
        )
        return result

    def _apply_project_command_context(self, tool_name: str, input_metadata: ToolInputMetadata) -> ToolInputMetadata:
        """Inject the project-local cwd and venv environment into command-like tools."""
        if tool_name not in {"command_executor", "bug_fix_tool", "warning_check_tool"}:
            return input_metadata
        input_metadata = self._attach_command_approval_callback(tool_name, input_metadata)
        environment = self._environment_for_tool_input(input_metadata)
        if not environment:
            return input_metadata
        updates: dict[str, Any] = {}
        command_cwd = str(environment.get("command_cwd") or environment.get("project_path") or "").strip()
        if command_cwd and input_metadata.cwd != command_cwd:
            updates["cwd"] = command_cwd
        command_env = environment.get("command_env") if isinstance(environment.get("command_env"), dict) else {}
        if command_env:
            merged_env = {str(key): str(value) for key, value in (input_metadata.env or {}).items()}
            merged_env.update({str(key): str(value) for key, value in command_env.items()})
            updates["env"] = merged_env
        if input_metadata.command:
            rewritten_command = self._rewrite_project_command(input_metadata.command, environment)
            if rewritten_command != input_metadata.command:
                updates["command"] = rewritten_command
        if not updates:
            return input_metadata
        return input_metadata.model_copy(update=updates)

    def _attach_command_approval_callback(self, tool_name: str, input_metadata: ToolInputMetadata) -> ToolInputMetadata:
        if tool_name not in {"command_executor", "bug_fix_tool"}:
            return input_metadata
        handles = dict(input_metadata.runtime_handles or {})
        handles.setdefault("_command_approval_callback", self._confirm_command_execution)
        if tool_name == "bug_fix_tool":
            handles.setdefault("_bug_fix_progress_callback", self._report_bug_fix_progress)
        return input_metadata.model_copy(update={"runtime_handles": handles})

    def _report_bug_fix_progress(self, event: dict[str, Any]) -> None:
        """Expose the bug-fix tool's internal loop through logs and the live UI."""
        payload = {str(key): value for key, value in dict(event or {}).items()}
        self.logger.log_event(
            "bug_fix_iteration_progress",
            payload,
            session_id=self.session_id or "unknown",
            turn_id=1,
        )
        if self.enhanced_ui:
            iteration = int(payload.get("iteration") or 0)
            budget = int(payload.get("budget") or 0)
            details = [f"Event: {payload.get('event') or 'progress'}"]
            if payload.get("modified_files"):
                details.append(f"Modified files: {', '.join(payload['modified_files'])}")
            if payload.get("error_summary"):
                details.append(f"Latest error: {payload['error_summary']}")
            self.enhanced_ui.set_current_task_state(
                title=f"Bug Fix Iteration {iteration}/{budget}",
                details="\n".join(details),
                status="success" if payload.get("success") else "running",
            )

    def _confirm_command_execution(self, decision) -> bool:
        reasons = "; ".join(getattr(decision, "reasons", []) or ["Command requires confirmation."])
        command = getattr(decision, "command", "")
        cwd = getattr(decision, "cwd", "")
        description = f"Command:\n{command}\n\nWorking directory: {cwd or '(current)'}\n\nReason: {reasons}"
        if self.enhanced_ui:
            self.enhanced_ui.set_current_task_state(
                title="Command Approval Required",
                details=description,
                status="running",
            )
        from ui.question_ui import QuestionUI

        return QuestionUI(self.console).ask_confirm(
            "command_approval",
            "Run this command?",
            title="Command Approval Required",
            description=description,
            default=False,
        )

    def _environment_for_tool_input(self, input_metadata: ToolInputMetadata) -> dict[str, Any]:
        candidates = []
        for raw in (
            input_metadata.project_path,
            input_metadata.cwd,
            input_metadata.file_path,
            *(input_metadata.file_paths or []),
            *(input_metadata.written_files or []),
        ):
            if raw:
                candidates.append(Path(str(raw)).expanduser())
        environments = getattr(self, "_project_environments", {}) or {}
        for candidate in candidates:
            match = self._environment_for_path(candidate, environments)
            if match:
                return match
        if len(environments) == 1:
            return next(iter(environments.values()))
        return {}

    def _environment_for_path(self, path: Path, environments: dict[str, dict[str, Any]]) -> dict[str, Any]:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        for project_path, environment in environments.items():
            try:
                project = Path(project_path).expanduser().resolve()
            except OSError:
                project = Path(project_path).expanduser()
            if resolved == project or project in resolved.parents:
                return environment
        return {}

    def _rewrite_project_command(self, command: str, environment: dict[str, Any]) -> str:
        try:
            parts = shlex.split(command)
        except ValueError:
            return command
        if not parts:
            return command
        executable = Path(parts[0]).name.lower()
        if executable in {"python", "python3"} and environment.get("python_command"):
            parts[0] = str(environment["python_command"])
        elif executable in {"pip", "pip3"} and environment.get("pip_command"):
            parts[0] = str(environment["pip_command"])
        else:
            return command
        return shlex.join(parts)

    def _result_status_from_execution(self, status_text: str, success: bool) -> ResultStatus:
        if success:
            return ResultStatus.SUCCESS
        if "timeout" in status_text.lower():
            return ResultStatus.TIMEOUT
        if "cancel" in status_text.lower():
            return ResultStatus.CANCELLED
        return ResultStatus.FAIL

    def _failure_metadata_from_execution(self, error: Any) -> FailureMetadata | None:
        if error is None:
            return None
        return FailureMetadata(
            error_type=getattr(error, "error_type", type(error).__name__),
            error_message=getattr(error, "error_message", str(error)),
            error_code=getattr(error, "error_code", None),
            recoverable=bool(getattr(error, "recoverable", False)),
            retry_recommended=bool(getattr(error, "retry_recommended", False)),
        )

    def _execute_tool_with_fast_retry(self, selection: ToolSelection):
        tool_def = self.tool_registry.get(selection.tool_name)
        max_retries = max(0, int(getattr(tool_def, "max_retries", 0) or 0))
        attempts_allowed = max_retries + 1
        retry_history: list[dict[str, Any]] = []
        last_result = None
        delay = 0.25

        for attempt in range(1, attempts_allowed + 1):
            exec_result = self.tool_executor.execute_single(selection, context=None)
            exec_result.attempt_number = attempt
            exec_result.retry_count = attempt - 1
            last_result = exec_result
            retry_history.append(self._tool_retry_history_item(selection, exec_result, attempt))

            if exec_result.success:
                return exec_result, retry_history
            if self._execution_result_is_timeout(exec_result):
                return exec_result, retry_history
            if not self._should_retry_execution_result(exec_result):
                return exec_result, retry_history
            if attempt >= attempts_allowed:
                return exec_result, retry_history

            self.logger.log_event(
                "tool_execution_retry",
                {
                    "step_id": selection.step_id,
                    "tool": selection.tool_name,
                    "attempt": attempt,
                    "next_attempt": attempt + 1,
                    "max_attempts": attempts_allowed,
                    "error_type": exec_result.error.error_type if exec_result.error else None,
                    "error": exec_result.error.error_message if exec_result.error else None,
                },
                session_id=self.session_id or "unknown",
                turn_id=1,
            )
            if self.enhanced_ui:
                self.enhanced_ui.set_current_task_state(
                    title=f"Tool retry: {selection.tool_name}",
                    details=(
                        f"Attempt {attempt}/{attempts_allowed} failed\n"
                        f"Retrying step: {selection.step_id}"
                    ),
                    status="running",
                )
            time.sleep(delay)
            delay = min(delay * 2, 1.0)

        return last_result, retry_history

    def _tool_retry_history_item(self, selection: ToolSelection, exec_result, attempt: int) -> dict[str, Any]:
        return {
            "attempt": attempt,
            "step_id": selection.step_id,
            "tool": selection.tool_name,
            "status": getattr(exec_result.status, "value", str(exec_result.status)),
            "success": exec_result.success,
            "duration_seconds": exec_result.duration_seconds,
            "error_type": exec_result.error.error_type if exec_result.error else None,
            "error": exec_result.error.error_message if exec_result.error else None,
        }

    def _execution_result_is_timeout(self, exec_result) -> bool:
        status = getattr(exec_result.status, "value", str(exec_result.status))
        error_type = exec_result.error.error_type if exec_result.error else ""
        error_message = exec_result.error.error_message if exec_result.error else ""
        return "timeout" in f"{status} {error_type} {error_message}".lower()

    def _should_retry_execution_result(self, exec_result) -> bool:
        if exec_result.success or not exec_result.error:
            return False
        if self._execution_result_is_timeout(exec_result):
            return False
        error_type = exec_result.error.error_type or ""
        if error_type in {"LLMProviderError", "LLMTimeoutError"}:
            return False
        if exec_result.error.retry_recommended:
            return True
        category = classify_error(Exception(exec_result.error.error_message))
        return category.value in {"retryable", "network"}

    def _llm_tool_timeout_override(self, tool_name: str) -> int | None:
        tool_def = self.tool_registry.get(tool_name) if getattr(self, "tool_registry", None) else None
        capabilities = getattr(tool_def, "capabilities", []) if tool_def else []
        has_llm_call = any(getattr(capability, "value", capability) == "llm_call" for capability in capabilities)
        if not has_llm_call:
            return None

        settings = getattr(self.llm_client, "settings", None)
        provider_timeout = float(getattr(settings, "timeout_seconds", 60.0) or 60.0)
        transport_attempts = max(1, int(getattr(settings, "transport_retries", 0) or 0) + 1)
        initial_delay = max(0.0, float(getattr(settings, "retry_initial_delay", 0.0) or 0.0))
        max_delay = max(initial_delay, float(getattr(settings, "retry_max_delay", initial_delay) or initial_delay))
        delay_budget = 0.0
        delay = initial_delay
        for _ in range(max(0, transport_attempts - 1)):
            delay_budget += min(delay, max_delay)
            delay = min(delay * 2 if delay else 0.0, max_delay)

        json_attempt_budget = 2
        computed = int(provider_timeout * transport_attempts * json_attempt_budget + delay_budget * json_attempt_budget + 30)
        default_timeout = int(getattr(tool_def, "timeout_seconds", 30) or 30)
        return max(default_timeout, min(computed, 900))

    def _finalize_project_readme(
        self,
        goal: str,
        results: list[TaskExecutionResult],
    ) -> ToolExecutionEnvelopeMetadata | None:
        """Generate README.md once after successful project/file creation."""
        if self._results_include_tool(results, "readme_tool"):
            return None

        written_files = self._collect_written_files(results)
        if not written_files:
            return None

        project_path = self._infer_project_path_from_files(goal, written_files)
        if project_path is None:
            return None

        task = Task(
            id=str(uuid.uuid4()),
            description=f"Generate README.md for {project_path}",
            priority=TaskPriority.MEDIUM,
        )
        readme_result = self._execute_fast_tool(
            task=task,
            step_id="final_readme_tool",
            tool_name="readme_tool",
            input_metadata=ToolInputMetadata.from_mapping("readme_tool", {
                "project_path": str(project_path),
                "project_summary": goal,
                "written_files": written_files,
                "entry_files": written_files,
                "overwrite": True,
            }),
        )

        if self.enhanced_ui:
            if readme_result.success:
                output = readme_result.output
                self.enhanced_ui.log_activity("success", f"README generated: {output.get('file_path', 'README.md') if output else 'README.md'}")
            else:
                self.enhanced_ui.log_activity("error", f"README generation failed: {readme_result.error_message}")
        elif readme_result.success:
            output = readme_result.output
            self.console.print(f"[green]README generated:[/green] {output.get('file_path', project_path / 'README.md') if output else project_path / 'README.md'}")
        else:
            self.console.print(f"[yellow]README generation failed:[/yellow] {readme_result.error_message}")

        self.logger.log_event(
            "readme_finalized",
            {
                "goal": goal,
                "project_path": str(project_path),
                "written_files": written_files,
                "success": readme_result.success,
                "error": readme_result.error_message,
                "output": self._summarize_metadata_output(readme_result.output),
            },
            session_id=self.session_id or "unknown",
            turn_id=1,
        )
        return readme_result

    def _run_iterative_improvement(
        self,
        *,
        goal: str,
        project_path: str | Path,
        written_files: list[str],
        run_command: str = "",
        readme_path: str | Path | None = None,
    ) -> dict[str, Any] | None:
        """Run fixed-count validation and improvement loop."""
        return self.project_improvement_runtime.run(
            goal=goal,
            project_path=project_path,
            written_files=written_files,
            run_command=run_command,
            readme_path=readme_path,
        )

    def _sync_project_environment(
        self,
        *,
        task: Task,
        step_id: str,
        project_path: Path,
        written_files: list[str],
        entry_files: list[str],
        run_command: str,
        parent_task_id: str | None = None,
    ) -> ToolExecutionEnvelopeMetadata:
        if self.enhanced_ui and parent_task_id:
            self._set_dashboard_task_status(parent_task_id, "running")
            self.enhanced_ui.set_current_task_state(
                title="Environment Setup",
                details=f"Project: {project_path}\nVirtual environment: .venv",
                status="running",
            )
        input_metadata_payload = {
            "project_path": str(project_path),
            "written_files": written_files,
            "entry_files": entry_files,
            "run_command": run_command,
            "env_name": ".venv",
            "install": True,
        }
        result = self._execute_project_environment_agent_tool(
            task=task,
            step_id=step_id,
            input_metadata=ToolInputMetadata.from_mapping("project_environment_tool", input_metadata_payload),
            parent_task_id=parent_task_id,
        )
        if result.success and result.output is not None:
            payload = result.output
            if not hasattr(self, "_project_environments"):
                self._project_environments = {}
            self._project_environments[str(project_path.resolve())] = payload.to_json_dict()
            if self.enhanced_ui and parent_task_id:
                packages = payload.get("detected_packages") or []
                self._set_dashboard_task_status(parent_task_id, "completed")
                self._append_dashboard_stage_child(
                    "environment",
                    child_id=f"sync_{step_id}",
                    description=(
                        f".venv ready; packages: {', '.join(packages) if packages else 'none'}; "
                        f"python: {Path(str(payload.get('python_executable') or '')).name}"
                    ),
                    kind="result",
                )
                self._append_dashboard_stage_child(
                    "environment",
                    child_id=f"memory_{step_id}",
                    description="Saved project environment dependency context to short-term memory",
                    kind="note",
                )
                git_repository = payload.get("git_repository")
                if git_repository:
                    head = git_repository.get("head") if hasattr(git_repository, "get") else ""
                    self._append_dashboard_stage_child(
                        "environment",
                        child_id=f"git_{step_id}",
                        description=f"Git initialized{f' at {head}' if head else ''}",
                        kind="note",
                    )
                git_snapshot = payload.get("git_snapshot")
                if git_snapshot:
                    commit_hash = git_snapshot.get("commit_hash") if hasattr(git_snapshot, "get") else ""
                    created = git_snapshot.get("created") if hasattr(git_snapshot, "get") else False
                    self._append_dashboard_stage_child(
                        "environment",
                        child_id=f"git_snapshot_{step_id}",
                        description=(
                            f"Safety snapshot {'created' if created else 'ready'}"
                            f"{f': {commit_hash}' if commit_hash else ''}"
                        ),
                        kind="note",
                    )
                self.enhanced_ui.set_current_task_state(
                    title="Environment Setup",
                    details=(
                        f"Virtual environment: {payload.get('venv_path')}\n"
                        f"Run command: {payload.get('run_command')}\n"
                        f"Packages: {', '.join(packages) if packages else 'none'}"
                    ),
                    status="completed",
                )
        elif self.enhanced_ui and parent_task_id:
            self._set_dashboard_task_status(parent_task_id, "failed")
            self._append_dashboard_stage_child(
                "environment",
                child_id=f"sync_failed_{step_id}",
                description=str(result.error_message or "Project environment sync failed."),
                kind="result",
                status="failed",
            )
        return result

    def _execute_project_environment_agent_tool(
        self,
        *,
        task: Task,
        step_id: str,
        input_metadata: ToolInputMetadata,
        parent_task_id: str | None = None,
    ) -> ToolExecutionEnvelopeMetadata:
        """Run the environment manager's agent-local tool without public registry selection."""
        from memory.agents.project_environment_tool import project_environment_tool_executor

        tool_name = "project_environment_tool"
        typed_input = input_metadata
        input_payload = typed_input.to_params()
        started = time.monotonic()
        if self.enhanced_ui:
            self._set_dashboard_tool_status(
                parent_task_id=parent_task_id,
                tool_id=step_id,
                tool_name=tool_name,
                status="running",
            )
            param_lines = "\n".join(f"{key}: {value}" for key, value in input_payload.items())
            self.enhanced_ui.set_current_task_state(
                title=f"Tool: {tool_name}",
                details=f"Task: {task.description}\nStep: {step_id}\n{param_lines}",
                status="running",
            )

        self.logger.log_event(
            "tool_execution_start",
            {
                "task_id": task.id,
                "step_id": step_id,
                "tool": tool_name,
                "timeout_override": None,
                "input_metadata_summary": self._sanitize_tool_metadata(typed_input),
            },
            session_id=self.session_id or "unknown",
            turn_id=1,
        )

        success = False
        output_metadata: ToolResultMetadata | None = None
        error: str | None = None
        error_type: str | None = None
        try:
            typed_input.runtime_handles["_memory_store"] = self.memory_store
            output_metadata = project_environment_tool_executor(typed_input)
            success = True
        except Exception as exc:
            error = str(exc)
            error_type = exc.__class__.__name__

        duration_seconds = time.monotonic() - started
        status = ResultStatus.SUCCESS if success else ResultStatus.FAIL
        failure = None if success else FailureMetadata(error_type=error_type or "ToolError", error_message=error or "Project environment sync failed.")
        result = ToolExecutionEnvelopeMetadata(
            tool_name=tool_name,
            step_id=step_id,
            status=status,
            success=success,
            input_metadata=typed_input,
            output_metadata=output_metadata,
            failure=failure,
            duration_seconds=duration_seconds,
        )

        if self.enhanced_ui:
            self._set_dashboard_tool_status(
                parent_task_id=parent_task_id,
                tool_id=step_id,
                tool_name=tool_name,
                status=status.value,
            )
            self.enhanced_ui.set_current_task_state(
                title=f"Tool: {tool_name}",
                details="Tool returned successfully" if success else (error or "Project environment sync failed."),
                status=status.value,
            )

        self.logger.log_event(
            "tool_executed",
            {
                "task_id": task.id,
                "step_id": step_id,
                "tool": tool_name,
                "success": success,
                "status": status.value,
                "error_type": error_type,
                "error": error,
                "duration_seconds": duration_seconds,
                "attempts_used": 1,
                "retry_count": 0,
                "output": self._summarize_metadata_output(output_metadata),
            },
            session_id=self.session_id or "unknown",
            turn_id=1,
        )
        return result

    def _execute_project_state_reader_agent_tool(
        self,
        *,
        task: Task,
        step_id: str,
        input_metadata: ToolInputMetadata,
        parent_task_id: str | None = None,
    ) -> ToolExecutionEnvelopeMetadata:
        """Run the autonomous-iteration project state reader without public registry selection."""
        from autonomous_iteration.tool.project_improvement_tool import project_state_reader_executor

        return self._execute_module_owned_tool(
            task=task,
            step_id=step_id,
            tool_name="project_state_reader",
            input_metadata=input_metadata,
            executor=lambda metadata: (
                metadata.runtime_handles.__setitem__("_memory_store", self.memory_store)
                or project_state_reader_executor(metadata)
            ),
            parent_task_id=parent_task_id,
        )

    def _execute_project_improvement_agent_tool(
        self,
        *,
        task: Task,
        step_id: str,
        input_metadata: ToolInputMetadata,
        parent_task_id: str | None = None,
    ) -> ToolExecutionEnvelopeMetadata:
        """Run the autonomous-iteration improvement analyzer without public registry selection."""
        from autonomous_iteration.tool.project_improvement_tool import project_improvement_tool_executor

        return self._execute_module_owned_tool(
            task=task,
            step_id=step_id,
            tool_name="project_improvement_tool",
            input_metadata=input_metadata,
            executor=lambda metadata: (
                metadata.runtime_handles.__setitem__("_llm_client", self.llm_client)
                or project_improvement_tool_executor(metadata)
            ),
            parent_task_id=parent_task_id,
        )

    def _execute_environment_fix_agent_tool(
        self,
        *,
        task: Task,
        step_id: str,
        input_metadata: ToolInputMetadata,
        parent_task_id: str | None = None,
    ) -> ToolExecutionEnvelopeMetadata:
        """Run the project environment repair tool without public registry selection."""
        from tools.environment_fix_tool import environment_fix_tool_executor

        handles = dict(input_metadata.runtime_handles or {})
        handles.setdefault("_command_approval_callback", self._confirm_command_execution)
        handles.setdefault("_memory_store", self.memory_store)
        input_metadata = input_metadata.model_copy(update={"runtime_handles": handles})
        result = self._execute_module_owned_tool(
            task=task,
            step_id=step_id,
            tool_name="environment_fix_tool",
            input_metadata=input_metadata,
            executor=environment_fix_tool_executor,
            parent_task_id=parent_task_id,
        )
        if result.output_metadata and result.output_metadata.status != ResultStatus.SUCCESS:
            return result.model_copy(
                update={
                    "status": result.output_metadata.status,
                    "success": False,
                    "failure": result.output_metadata.failure,
                }
            )
        return result

    def _execute_module_owned_tool(
        self,
        *,
        task: Task,
        step_id: str,
        tool_name: str,
        input_metadata: ToolInputMetadata,
        executor: Callable[[ToolInputMetadata], ToolResultMetadata],
        parent_task_id: str | None = None,
    ) -> ToolExecutionEnvelopeMetadata:
        """Run a module-owned tool and return the same envelope as registry-backed tools."""
        typed_input = input_metadata
        input_payload = typed_input.to_params()
        started = time.monotonic()
        if self.enhanced_ui:
            self._set_dashboard_tool_status(
                parent_task_id=parent_task_id,
                tool_id=step_id,
                tool_name=tool_name,
                status="running",
            )
            param_lines = "\n".join(f"{key}: {value}" for key, value in input_payload.items())
            self.enhanced_ui.set_current_task_state(
                title=f"Tool: {tool_name}",
                details=f"Task: {task.description}\nStep: {step_id}\n{param_lines}",
                status="running",
            )

        self.logger.log_event(
            "tool_execution_start",
            {
                "task_id": task.id,
                "step_id": step_id,
                "tool": tool_name,
                "timeout_override": None,
                "input_metadata_summary": self._sanitize_tool_metadata(typed_input),
            },
            session_id=self.session_id or "unknown",
            turn_id=1,
        )

        success = False
        output_metadata: ToolResultMetadata | None = None
        error: str | None = None
        error_type: str | None = None
        try:
            output_metadata = executor(typed_input)
            success = True
        except Exception as exc:
            error = str(exc)
            error_type = exc.__class__.__name__

        duration_seconds = time.monotonic() - started
        status = ResultStatus.SUCCESS if success else ResultStatus.FAIL
        failure = None if success else FailureMetadata(error_type=error_type or "ToolError", error_message=error or f"{tool_name} failed.")
        result = ToolExecutionEnvelopeMetadata(
            tool_name=tool_name,
            step_id=step_id,
            status=status,
            success=success,
            input_metadata=typed_input,
            output_metadata=output_metadata,
            failure=failure,
            duration_seconds=duration_seconds,
        )

        if self.enhanced_ui:
            self._set_dashboard_tool_status(
                parent_task_id=parent_task_id,
                tool_id=step_id,
                tool_name=tool_name,
                status=status.value,
            )
            self.enhanced_ui.set_current_task_state(
                title=f"Tool: {tool_name}",
                details="Tool returned successfully" if success else (error or f"{tool_name} failed."),
                status=status.value,
            )

        self.logger.log_event(
            "tool_executed",
            {
                "task_id": task.id,
                "step_id": step_id,
                "tool": tool_name,
                "success": success,
                "status": status.value,
                "error_type": error_type,
                "error": error,
                "duration_seconds": duration_seconds,
                "attempts_used": 1,
                "retry_count": 0,
                "output": self._summarize_metadata_output(output_metadata),
            },
            session_id=self.session_id or "unknown",
            turn_id=1,
        )
        return result

    def _readme_environment_context(self, environment_payload: dict[str, Any]) -> dict[str, Any]:
        return self.project_iteration.readme_environment_context(environment_payload)

    def _project_environment_context(self, project_path: Path | None) -> dict[str, Any]:
        return self.project_iteration.project_environment_context(
            project_path,
            getattr(self, "_project_environments", {}),
        )

    def _resolve_project_improvement_iterations(self, goal: str, project_path: str | Path) -> bool:
        """Resolve per-project improvement count, optionally asking the user."""
        return self.project_iteration.resolve_project_improvement_iterations(self, goal, project_path)

    def _analyze_project_improvements(
        self,
        *,
        goal: str,
        project_path: Path,
        written_files: list[str],
        run_command: str,
        readme_path: Path,
        completed_iteration: int,
        evaluation: EvaluationResult,
    ) -> dict[str, Any]:
        prompt_context = self._build_prompt_context(
            original_goal=goal,
            project_path=project_path,
            written_files=written_files,
            run_command=run_command,
            evaluation=evaluation,
            iteration_goal="Analyze product-fit and choose the next autonomous improvement.",
            acceptance_criteria=evaluation.recommended_actions,
            tool_task="Produce a concrete next-iteration project improvement report.",
            agent_instruction=(
                "Goal Maker context: judge what is actually better for the user's project type, "
                "not only what is easiest to add to the current implementation."
            ),
        )
        task = Task(
            id=str(uuid.uuid4()),
            description=f"Analyze project improvements after iteration {completed_iteration}",
            priority=TaskPriority.MEDIUM,
        )
        tool_result = self._execute_project_improvement_agent_tool(
            task=task,
            step_id=f"iteration_{completed_iteration}_project_improvement_tool",
            input_metadata=ToolInputMetadata.from_mapping("project_improvement_tool", {
                "project_path": str(project_path),
                "goal": goal,
                "written_files": written_files,
                "run_command": run_command,
                "iteration": completed_iteration,
                "validation_result": evaluation.model_dump(),
                "readme_path": str(readme_path),
                "prompt_context": prompt_context,
            }),
            parent_task_id=self._dashboard_stage_id("goal_maker"),
        )
        if tool_result.success and tool_result.output is not None:
            return tool_result.output.to_json_dict()
        fallback = {
            "summary": evaluation.summary,
            "improvement_opportunities": evaluation.improvement_opportunities,
            "recommended_actions": evaluation.recommended_actions,
            "next_iteration_goal": evaluation.next_iteration_goal,
            "blocking_risks": evaluation.validation_errors,
            "prompt_context": prompt_context,
            "product_judgment": prompt_context.get("product_judgment") or {},
            "source": "fallback",
            "fallback_reason": tool_result.error_message or "project_improvement_tool did not return a usable report.",
        }
        return fallback

    def _build_prompt_context(
        self,
        *,
        original_goal: str,
        project_path: Path | None = None,
        written_files: list[str] | None = None,
        run_command: str = "",
        evaluation: EvaluationResult | None = None,
        iteration_goal: str = "",
        acceptance_criteria: list[str] | None = None,
        tool_task: str = "",
        agent_instruction: str = "",
        target_file: Path | None = None,
        current_code: str = "",
        code_context: str = "",
        mode: str = "",
    ) -> dict[str, Any]:
        return self.improvement_context.build_prompt_context(
            original_goal=original_goal,
            project_path=project_path,
            written_files=written_files,
            run_command=run_command,
            evaluation=evaluation,
            iteration_goal=iteration_goal,
            acceptance_criteria=acceptance_criteria,
            tool_task=tool_task,
            agent_instruction=agent_instruction,
            target_file=target_file,
            current_code=current_code,
            code_context=code_context,
            mode=mode,
        )

    def _infer_product_judgment(
        self,
        *,
        original_goal: str,
        project_path: Path | None,
        written_files: list[str],
        current_code: str = "",
    ) -> dict[str, Any]:
        return self.improvement_context.infer_product_judgment(
            original_goal=original_goal,
            project_path=project_path,
            written_files=written_files,
            current_code=current_code,
        )

    def _quality_rubric_for_product(self, product_judgment: dict[str, Any]) -> list[str]:
        return self.improvement_context.quality_rubric_for_product(product_judgment)

    def _apply_project_improvement(
        self,
        *,
        goal: str,
        project_path: Path,
        written_files: list[str],
        run_command: str,
        readme_path: Path,
        iteration: int,
        evaluation: EvaluationResult,
        actions: list[str],
        improvement_report: dict[str, Any] | None = None,
        is_repair: bool = False,
    ) -> IterationResult:
        """Apply one safe project improvement round."""
        return self.autonomous_task_executor.execute_improvement(
            goal=goal,
            project_path=project_path,
            written_files=written_files,
            run_command=run_command,
            readme_path=readme_path,
            iteration=iteration,
            evaluation=evaluation,
            actions=actions,
            improvement_report=improvement_report,
            is_repair=is_repair,
        )

    def _run_code_generation_retry_pipeline(
        self,
        *,
        task: Task,
        iteration: int,
        goal: str,
        target_file: Path,
        current_code: str,
        evaluation: EvaluationResult,
        actions: list[str],
        improvement_report: dict[str, Any],
        is_repair: bool,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        return self.autonomous_task_executor.run_code_generation_retry_pipeline(
            task=task,
            iteration=iteration,
            goal=goal,
            target_file=target_file,
            current_code=current_code,
            evaluation=evaluation,
            actions=actions,
            improvement_report=improvement_report,
            is_repair=is_repair,
        )

    def _build_code_generation_prompt_context(
        self,
        *,
        goal: str,
        target_file: Path,
        current_code: str,
        evaluation: EvaluationResult,
        actions: list[str],
        improvement_report: dict[str, Any],
        is_repair: bool,
        simplified: bool,
        mode: str,
    ) -> dict[str, Any]:
        return self.autonomous_task_executor.build_code_generation_prompt_context(
            goal=goal,
            target_file=target_file,
            current_code=current_code,
            evaluation=evaluation,
            actions=actions,
            improvement_report=improvement_report,
            is_repair=is_repair,
            simplified=simplified,
            mode=mode,
        )

    def _prompt_context_layer_summary(self, prompt_context: dict[str, Any]) -> dict[str, Any]:
        return self.improvement_context.prompt_context_layer_summary(prompt_context)

    def _build_surgical_project_improvement_prompt(
        self,
        *,
        goal: str,
        target_file: Path,
        current_code: str,
        evaluation: EvaluationResult,
        actions: list[str],
        improvement_report: dict[str, Any],
        is_repair: bool,
    ) -> str:
        return self.autonomous_task_executor.build_surgical_project_improvement_prompt(
            goal=goal,
            target_file=target_file,
            current_code=current_code,
            evaluation=evaluation,
            actions=actions,
            improvement_report=improvement_report,
            is_repair=is_repair,
        )

    def _code_generation_attempt_summary(
        self,
        *,
        mode: str,
        prompt: str,
        result: dict[str, Any],
        attempt: int,
    ) -> dict[str, Any]:
        return self.autonomous_task_executor.code_generation_attempt_summary(
            mode=mode,
            prompt=prompt,
            result=result,
            attempt=attempt,
        )

    def _append_code_generation_attempt_to_dashboard(self, iteration: int, attempt: dict[str, Any]) -> None:
        self.autonomous_task_executor.append_code_generation_attempt_to_dashboard(iteration, attempt)

    def _should_retry_code_generation_attempt(self, result: dict[str, Any]) -> bool:
        return self.autonomous_task_executor.should_retry_code_generation_attempt(result)

    def _build_project_improvement_prompt(
        self,
        *,
        goal: str,
        target_file: Path,
        current_code: str,
        evaluation: EvaluationResult,
        actions: list[str],
        improvement_report: dict[str, Any],
        is_repair: bool,
        simplified: bool,
    ) -> str:
        return self.autonomous_task_executor.build_project_improvement_prompt(
            goal=goal,
            target_file=target_file,
            current_code=current_code,
            evaluation=evaluation,
            actions=actions,
            improvement_report=improvement_report,
            is_repair=is_repair,
            simplified=simplified,
        )

    def _execute_code_generation_for_improvement(
        self,
        *,
        task: Task,
        iteration: int,
        target_file: Path,
        improvement_prompt: str,
        simplified: bool,
        mode: str | None = None,
        prompt_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.autonomous_task_executor.execute_code_generation_for_improvement(
            task=task,
            iteration=iteration,
            target_file=target_file,
            improvement_prompt=improvement_prompt,
            simplified=simplified,
            mode=mode,
            prompt_context=prompt_context,
        )

    def _is_timeout_tool_result(self, result: dict[str, Any]) -> bool:
        return self.autonomous_task_executor.is_timeout_tool_result(result)

    def _visible_tool_failure_summary(
        self,
        *,
        tool: str,
        tool_result: dict[str, Any],
        retry_attempted: bool = False,
    ) -> str:
        """Create a compact failure reason suitable for the dashboard."""
        return self.autonomous_task_executor.visible_tool_failure_summary(
            tool=tool,
            tool_result=tool_result,
            retry_attempted=retry_attempted,
        )

    def _budget_code_context(self, code: str, max_chars: int) -> str:
        return self.autonomous_task_executor.budget_code_context(code, max_chars)

    def _compact_code_context(self, code: str, actions: list[str], max_chars: int) -> str:
        return self.autonomous_task_executor.compact_code_context(code, actions, max_chars)

    def _log_iteration_failure(
        self,
        *,
        iteration: int,
        stage: str,
        tool: str,
        target_file: Path,
        actions: list[str],
        error: str,
        prompt_length: int,
        current_code_length: int,
        retry_attempted: bool,
        tool_result: dict[str, Any],
        retry_history: list[dict[str, Any]] | None = None,
    ) -> None:
        self.autonomous_task_executor.log_iteration_failure(
            iteration=iteration,
            stage=stage,
            tool=tool,
            target_file=target_file,
            actions=actions,
            error=error,
            prompt_length=prompt_length,
            current_code_length=current_code_length,
            retry_attempted=retry_attempted,
            tool_result=tool_result,
            retry_history=retry_history,
        )

    def _finish_active_operations(self, reason: str) -> None:
        """Clear stale active LLM/tool traces after a terminal iteration state."""
        self.iteration_dashboard.finish_active_operations(reason)

    def _format_iteration_failure(self, improvement_result: dict[str, Any] | None) -> str:
        """Return a concise, user-facing iteration failure summary."""
        return self.iteration_dashboard.format_iteration_failure(improvement_result)

    def _select_iteration_target_file(self, written_files: list[str], actions: list[str]) -> Path | None:
        return self.improvement_context.select_iteration_target_file(written_files, actions)

    def _reset_iteration_dashboard(self, goal: str) -> None:
        self.iteration_dashboard.reset_iteration_dashboard(goal)

    def _ensure_dashboard_iteration(self, iteration_number: int | None = None) -> str:
        return self.iteration_dashboard.ensure_dashboard_iteration(iteration_number)

    def _dashboard_iteration_stage_nodes(self, iteration_id: str) -> list[dict[str, Any]]:
        return self.iteration_dashboard.dashboard_iteration_stage_nodes(iteration_id)

    def _dashboard_stage_id(self, stage_key: str) -> str | None:
        return self.iteration_dashboard.dashboard_stage_id(stage_key)

    def _short_dashboard_text(self, value: Any, limit: int = 140) -> str:
        return self.iteration_dashboard.short_dashboard_text(value, limit)

    def _append_dashboard_stage_child(
        self,
        stage_key: str,
        *,
        child_id: str,
        description: str,
        kind: str,
        status: str = "completed",
        children: list[dict[str, Any]] | None = None,
    ) -> None:
        self.iteration_dashboard.append_dashboard_stage_child(
            stage_key,
            child_id=child_id,
            description=description,
            kind=kind,
            status=status,
            children=children,
        )

    def _handle_iteration_progress(self, event: str, payload: dict[str, Any]) -> None:
        self.iteration_dashboard.handle_iteration_progress(event, payload)

    def _append_dashboard_tasks(self, new_tasks: list[dict[str, Any]], current_task_id: str | None = None) -> None:
        self.iteration_dashboard.append_dashboard_tasks(new_tasks, current_task_id)

    def _set_dashboard_task_status(self, task_id: str, status: str) -> None:
        self.iteration_dashboard.set_dashboard_task_status(task_id, status)

    def _set_dashboard_running_descendants_status(self, parent_id: str | None, status: str) -> None:
        self.iteration_dashboard.set_dashboard_running_descendants_status(parent_id, status)

    def _append_dashboard_child(
        self,
        *,
        parent_id: str,
        child: dict[str, Any],
        current_task_id: str | None = None,
    ) -> None:
        self.iteration_dashboard.append_dashboard_child(
            parent_id=parent_id,
            child=child,
            current_task_id=current_task_id,
        )

    def _set_dashboard_tool_status(
        self,
        *,
        parent_task_id: str | None,
        tool_id: str,
        tool_name: str,
        status: str,
    ) -> None:
        self.iteration_dashboard.set_dashboard_tool_status(
            parent_task_id=parent_task_id,
            tool_id=tool_id,
            tool_name=tool_name,
            status=status,
        )

    def _update_dashboard_node(
        self,
        nodes: list[dict[str, Any]],
        node_id: str,
        updater,
    ) -> tuple[list[dict[str, Any]], bool]:
        return self.iteration_dashboard.update_dashboard_node(nodes, node_id, updater)

    def _results_include_tool(self, results: list[TaskExecutionResult], tool_name: str) -> bool:
        for result in results:
            task_payload = result.result_metadata.result if result.result_metadata else None
            tool_results = getattr(task_payload, "attributes", {}).get("tool_results", []) if task_payload else []
            for tool_result in tool_results:
                if tool_result.get("tool_name") == tool_name or tool_result.get("tool") == tool_name:
                    return True
        return False

    def _collect_written_files(self, results: list[TaskExecutionResult]) -> list[str]:
        files: list[str] = []
        seen: set[str] = set()
        for result in results:
            task_payload = result.result_metadata.result if result.result_metadata else None
            tool_results = getattr(task_payload, "attributes", {}).get("tool_results", []) if task_payload else []
            for tool_result in tool_results:
                if not isinstance(tool_result, dict):
                    continue
                tool_name = tool_result.get("tool_name") or tool_result.get("tool")
                if tool_name != "file_writer" or not tool_result.get("success"):
                    continue
                output = self._tool_result_payload(tool_result)
                path = self._file_path_from_payload(output)
                if not path:
                    input_metadata = tool_result.get("input_metadata") or {}
                    path = self._file_path_from_payload(input_metadata)
                if path and path not in seen:
                    files.append(path)
                    seen.add(path)
        return files

    def _tool_result_payload(self, tool_result: dict[str, Any]) -> Any:
        direct_result = tool_result.get("result")
        if direct_result is not None:
            return direct_result
        output_metadata = tool_result.get("output_metadata") or {}
        if hasattr(output_metadata, "result"):
            return output_metadata.result
        if isinstance(output_metadata, dict):
            return output_metadata.get("result")
        return None

    def _file_path_from_payload(self, payload: Any) -> str | None:
        if payload is None:
            return None
        file_path = getattr(payload, "file_path", None)
        if file_path:
            return str(file_path)
        if isinstance(payload, dict):
            direct = payload.get("file_path")
            if direct:
                return str(direct)
            result = payload.get("result")
            if isinstance(result, dict) and result.get("file_path"):
                return str(result["file_path"])
        return None

    def _infer_project_path_from_files(self, goal: str, written_files: list[str]) -> Path | None:
        goal_path = self._extract_goal_path(goal)
        if goal_path:
            path = Path(goal_path).expanduser()
            if path.suffix:
                return path.parent
            return path

        if not written_files:
            return None
        first_file = Path(written_files[0]).expanduser()
        if first_file.suffix:
            return first_file.parent
        return first_file

    def _extract_goal_path(self, goal: str) -> str | None:
        path_match = re.search(r"['\"](?P<path>/[^'\"]+)['\"]", goal)
        return path_match.group("path") if path_match else None

    def _sanitize_tool_metadata(self, value: Any) -> dict[str, Any]:
        return self.tool_io.sanitize_tool_metadata(value)

    def _summarize_metadata_output(self, output: Any) -> dict[str, Any]:
        return self.tool_io.summarize_metadata_output(output)

    def _json_safe_summary(self, value: Any) -> Any:
        return self.tool_io.json_safe_summary(value)

    def _resolve_chained_metadata(
        self,
        tool_name: str,
        input_metadata: ToolInputMetadata,
        last_output: Any,
        last_code_output: Any,
    ) -> ToolInputMetadata:
        return self.tool_io.resolve_chained_metadata(
            tool_name,
            input_metadata,
            last_output,
            last_code_output,
        )

    def _extract_generated_content(self, output: Any) -> str | None:
        return self.tool_io.extract_generated_content(output)

    def _execute_with_enhanced_ui_v2(self, goal, context):
        return self.runtime_controller.run(goal, context, mode="enhanced_ui")

    def _execute_standard(self, goal: str, context: dict[str, Any]) -> dict[str, Any]:
        """Execute with standard console output."""
        return self.runtime_controller.run(goal, context, mode="standard")

    def _execute_tasks(self, tasks: list[Task], goal: str = "") -> list[TaskExecutionResult]:
        """Execute tasks using the runtime task graph and selected UI mode."""
        self._log_task_execution_event(
            "task_execution_started",
            input_summary={"total_tasks": len(tasks), "goal": goal},
            success=None,
        )
        task_graph = self.task_decomposer.build_task_graph(tasks)

        try:
            execution_order = self.task_decomposer.get_execution_order(task_graph)
        except ValueError:
            if self.use_enhanced_ui:
                self.enhanced_ui.log_activity(
                    "error",
                    "Cannot determine execution order, executing sequentially",
                )
            else:
                self.console.print(
                    "[yellow]⚠ Cannot determine execution order (cyclic dependencies?), executing sequentially[/yellow]"
                )
            execution_order = [task.id for task in tasks]

        if self.use_enhanced_ui:
            results = self._execute_tasks_enhanced_ui(tasks, execution_order, goal)
        else:
            results = self._execute_tasks_standard(tasks, execution_order, goal)

        self._log_task_execution_event(
            "task_execution_completed",
            output_summary={
                "results": len(results),
                "completed": len([result for result in results if result.status == TaskStatus.COMPLETED]),
                "failed": len([result for result in results if result.status == TaskStatus.FAILED]),
            },
            success=all(result.status == TaskStatus.COMPLETED for result in results),
        )
        return results

    def _dashboard_task_items(
        self,
        tasks: list[Task],
        running_task_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Convert task models into UI dashboard rows."""
        items = []
        for task in tasks:
            status = task.status.value if hasattr(task.status, "value") else str(task.status)
            if running_task_id and task.id == running_task_id and status == "pending":
                status = "running"
            items.append(
                {
                    "id": task.id,
                    "description": task.description,
                    "status": status,
                    "effort": f"{task.estimated_effort:.1f}u" if task.estimated_effort else "",
                }
            )
        return items

    def _implicit_dependencies_for_task(self, task: Task, execution_order: list[str], zero_based_index: int) -> list[str]:
        """Infer simple sequential dependencies from task wording."""
        dependencies = list(task.dependencies or [])
        description = task.description.lower()
        previous_markers = (
            "based on subtask",
            "requirements from subtask",
            "from subtask",
            "previous task",
            "prior task",
            "上一步",
            "上一",
            "前序",
            "前一步",
            "子任务 0",
            "子任务0",
        )
        if zero_based_index > 0 and any(marker in description for marker in previous_markers):
            previous_id = execution_order[zero_based_index - 1]
            if previous_id not in dependencies:
                dependencies.append(previous_id)
        return dependencies

    def _blocking_dependency(
        self,
        task: Task,
        tasks: list[Task],
        results: list[TaskExecutionResult],
        execution_order: list[str],
        zero_based_index: int,
    ) -> tuple[str, str] | None:
        dependencies = self._implicit_dependencies_for_task(task, execution_order, zero_based_index)
        if not dependencies:
            return None
        task_by_id = {candidate.id: candidate for candidate in tasks}
        result_by_id = {result.task_id: result for result in results}
        for dependency_id in dependencies:
            dependency_task = task_by_id.get(dependency_id)
            dependency_result = result_by_id.get(dependency_id)
            dependency_status = getattr(dependency_task, "status", None)
            result_status = getattr(dependency_result, "status", None)
            if dependency_status in {TaskStatus.FAILED, TaskStatus.BLOCKED} or result_status == TaskStatus.FAILED:
                reason = (
                    getattr(dependency_result, "error", None)
                    or getattr(dependency_task, "error", None)
                    or "dependency did not complete successfully"
                )
                return dependency_id, str(reason)
        return None

    def _blocked_task_result(self, task: Task, blocking_task_id: str, root_cause: str) -> TaskExecutionResult:
        message = f"Blocked because task {blocking_task_id} failed: {root_cause}"
        task.mark_blocked()
        task.error = message
        metadata = TaskResultMetadata(
            task_id=task.id,
            status=ResultStatus.FAIL,
            failure=FailureMetadata(
                error_type="TaskBlocked",
                error_message=message,
                details={
                    "task_id": task.id,
                    "task_description": task.description,
                    "blocked_by_task_id": blocking_task_id,
                    "root_cause": root_cause,
                    "failure_stage": "Task Dependency",
                    "suggested_recovery": "Fix the failed dependency task before retrying this task.",
                },
            ),
        )
        task.result = metadata
        return TaskExecutionResult(
            task_id=task.id,
            status=TaskStatus.FAILED,
            result_metadata=metadata,
            error=message,
            duration=0.0,
            attributes={"blocked": True, "blocked_by_task_id": blocking_task_id},
        )

    def _execution_history_payload(self, tasks: list[Task], results: list[TaskExecutionResult]) -> list[dict[str, Any]]:
        task_by_id = {task.id: task for task in tasks}
        history: list[dict[str, Any]] = []
        for result in results:
            task = task_by_id.get(result.task_id)
            history.append(
                {
                    "task_id": result.task_id,
                    "description": task.description if task else None,
                    "status": result.status.value if hasattr(result.status, "value") else str(result.status),
                    "error": result.error,
                    "result_summary": str(result.result_metadata)[:1000] if result.result_metadata else None,
                }
            )
        return history

    def _execute_tasks_enhanced_ui(self, tasks: list[Task], execution_order: list[str], goal: str) -> list[TaskExecutionResult]:
        """Execute tasks with enhanced UI updates."""
        results = []

        self.logger.log_event(
            "task_execution_started",
            {
                "total_tasks": len(tasks),
                "execution_order": execution_order,
                "goal": goal,
            },
            session_id=self.session_id or "unknown",
            turn_id=1,
        )
        self._log_task_execution_event(
            "enhanced_task_execution_started",
            input_summary={"total_tasks": len(tasks), "execution_order": execution_order},
            success=None,
        )

        for index, task_id in enumerate(execution_order, 1):
            task = next((candidate for candidate in tasks if candidate.id == task_id), None)
            if not task:
                self.logger.log_event(
                    "task_not_found",
                    {"task_id": task_id, "index": index},
                    session_id=self.session_id or "unknown",
                    turn_id=1,
                )
                continue

            blocking = self._blocking_dependency(task, tasks, results, execution_order, index - 1)
            if blocking:
                blocked_by, root_cause = blocking
                result = self._blocked_task_result(task, blocked_by, root_cause)
                results.append(result)
                self.enhanced_ui.set_task_graph_state(
                    tasks=self._dashboard_task_items(tasks),
                    current_task_id=task.id,
                )
                self.enhanced_ui.set_current_task_state(
                    title=f"Task {index}/{len(tasks)}",
                    details=result.error or "Task blocked",
                    status="failed",
                )
                self.enhanced_ui.log_activity("error", f"✗ Task {index} blocked: {result.error}")
                self.logger.log_event(
                    "task_execution_blocked",
                    {
                        "task_id": task.id,
                        "task_index": index,
                        "description": task.description,
                        "blocked_by_task_id": blocked_by,
                        "root_cause": root_cause,
                    },
                    session_id=self.session_id or "unknown",
                    turn_id=1,
                )
                continue

            self.logger.log_event(
                "task_execution_start",
                {
                    "task_id": task.id,
                    "task_index": index,
                    "description": task.description,
                    "priority": task.priority.value if hasattr(task.priority, "value") else str(task.priority),
                },
                session_id=self.session_id or "unknown",
                turn_id=1,
            )

            completed_count = len([result for result in results if result.status == TaskStatus.COMPLETED])
            failed_count = len([result for result in results if result.status == TaskStatus.FAILED])
            status_detail = (
                f"{task.description}\n\n"
                f"Completed: {completed_count}\n"
                f"Failed: {failed_count}\n"
                f"Remaining: {len(tasks) - index}"
            )

            self.enhanced_ui.set_task_graph_state(
                tasks=self._dashboard_task_items(tasks, running_task_id=task.id),
                current_task_id=task.id,
            )
            self.enhanced_ui.set_current_task_state(
                title=f"Task {index}/{len(tasks)}",
                details=status_detail,
                status="running",
            )

            task_context = TaskExecutionContext(
                task=task,
                parent_context={"goal": goal, "session_id": self.session_id},
                shared_state={"previous_task_results": self._execution_history_payload(tasks, results)},
                execution_history=self._execution_history_payload(tasks, results),
            )

            try:
                result = self._execute_task(task, task_context)
                results.append(result)

                self.logger.log_event(
                    "task_execution_complete",
                    {
                        "task_id": task.id,
                        "task_index": index,
                        "status": result.status.value if hasattr(result.status, "value") else str(result.status),
                        "success": result.status == TaskStatus.COMPLETED,
                        "error": result.error,
                        "duration": result.duration,
                        "result_summary": str(result.result_metadata)[:200] if result.result_metadata else None,
                    },
                    session_id=self.session_id or "unknown",
                    turn_id=1,
                )

                if result.status == TaskStatus.COMPLETED:
                    task.mark_completed(result.result_metadata)
                    self.enhanced_ui.set_task_graph_state(
                        tasks=self._dashboard_task_items(tasks),
                        current_task_id=task.id,
                    )
                    self.enhanced_ui.set_current_task_state(
                        title=f"Task {index}/{len(tasks)}",
                        details=task.description,
                        status="completed",
                    )
                    self.enhanced_ui.log_activity(
                        "success",
                        f"✓ Task {index}: {task.description[:50]}... ({result.duration:.1f}s)",
                    )
                else:
                    task.mark_failed(result.error or "Unknown error")
                    task.result = result.result_metadata
                    self.enhanced_ui.set_task_graph_state(
                        tasks=self._dashboard_task_items(tasks),
                        current_task_id=task.id,
                    )
                    self.enhanced_ui.set_current_task_state(
                        title=f"Task {index}/{len(tasks)}",
                        details=result.error or "Unknown error",
                        status="failed",
                    )
                    self.enhanced_ui.log_activity("error", f"✗ Task {index} failed: {result.error}")
                    self.logger.log_event(
                        "task_execution_failed",
                        {
                            "task_id": task.id,
                            "task_index": index,
                            "description": task.description,
                            "error": result.error,
                            "result_metadata": result.result_metadata.to_json_dict() if result.result_metadata else None,
                        },
                        session_id=self.session_id or "unknown",
                        turn_id=1,
                    )

                if task.status == TaskStatus.PENDING:
                    self.logger.log_event(
                        "task_status_update_failed",
                        {
                            "task_id": task.id,
                            "task_index": index,
                            "result_status": result.status.value if hasattr(result.status, "value") else str(result.status),
                            "task_status": task.status.value if hasattr(task.status, "value") else str(task.status),
                        },
                        session_id=self.session_id or "unknown",
                        turn_id=1,
                    )
                    if result.status == TaskStatus.COMPLETED:
                        task.status = TaskStatus.COMPLETED
                        task.result = result.result_metadata
                    else:
                        task.status = TaskStatus.FAILED
                        task.error = result.error
                        task.result = result.result_metadata

            except Exception as exc:
                error_msg = f"Task execution exception: {str(exc)}"
                self.enhanced_ui.log_activity("error", f"✗ Task {index} exception: {str(exc)}")
                self.logger.log_event(
                    "task_execution_exception",
                    {
                        "task_id": task.id,
                        "task_index": index,
                        "description": task.description,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                    session_id=self.session_id or "unknown",
                    turn_id=1,
                )

                result = TaskExecutionResult(
                    task_id=task.id,
                    status=TaskStatus.FAILED,
                    error=error_msg,
                    duration=0.0,
                    attributes={},
                )
                results.append(result)
                task.mark_failed(error_msg)
                self.enhanced_ui.set_task_graph_state(
                    tasks=self._dashboard_task_items(tasks),
                    current_task_id=task.id,
                )
                self.enhanced_ui.set_current_task_state(
                    title=f"Task {index}/{len(tasks)}",
                    details=error_msg,
                    status="failed",
                )

        completed = len([result for result in results if result.status == TaskStatus.COMPLETED])
        failed = len([result for result in results if result.status == TaskStatus.FAILED])
        self.logger.log_event(
            "task_execution_summary",
            {
                "total": len(results),
                "completed": completed,
                "failed": failed,
                "task_statuses": [
                    {
                        "id": task.id,
                        "description": task.description[:50],
                        "status": task.status.value if hasattr(task.status, "value") else str(task.status),
                    }
                    for task in tasks
                ],
            },
            session_id=self.session_id or "unknown",
            turn_id=1,
        )
        self._log_task_execution_event(
            "enhanced_task_execution_completed",
            output_summary={"completed": completed, "failed": failed},
            success=failed == 0,
        )

        return results

    def _execute_tasks_standard(self, tasks: list[Task], execution_order: list[str], goal: str) -> list[TaskExecutionResult]:
        """Execute tasks with standard console output."""
        results = []
        self._log_task_execution_event(
            "standard_task_execution_started",
            input_summary={"total_tasks": len(tasks), "execution_order": execution_order},
            success=None,
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=self.console,
        ) as progress:
            task_progress = progress.add_task("Executing tasks...", total=len(tasks))

            for index, task_id in enumerate(execution_order, 1):
                task = next((candidate for candidate in tasks if candidate.id == task_id), None)
                if not task:
                    continue

                blocking = self._blocking_dependency(task, tasks, results, execution_order, index - 1)
                if blocking:
                    blocked_by, root_cause = blocking
                    result = self._blocked_task_result(task, blocked_by, root_cause)
                    results.append(result)
                    self.stats["tasks_failed"] += 1
                    self.logger.log_event(
                        "task_execution_blocked",
                        {
                            "task_id": task.id,
                            "task_index": index,
                            "description": task.description,
                            "blocked_by_task_id": blocked_by,
                            "root_cause": root_cause,
                        },
                        session_id=self.session_id or "unknown",
                        turn_id=1,
                    )
                    self.console.print(
                        f"  [red]✗[/red] Task {index}: {task.description[:60]} (blocked)"
                    )
                    self.console.print(f"    [red]Error: {result.error}[/red]")
                    progress.advance(task_progress)
                    continue

                progress.update(
                    task_progress,
                    description=f"[{index}/{len(tasks)}] {task.description[:50]}...",
                )

                task_context = TaskExecutionContext(
                    task=task,
                    parent_context={"goal": goal, "session_id": self.session_id},
                    shared_state={"previous_task_results": self._execution_history_payload(tasks, results)},
                    execution_history=self._execution_history_payload(tasks, results),
                )

                try:
                    result = self._execute_task(task, task_context)
                except Exception as exc:
                    result = TaskExecutionResult(
                        task_id=task.id,
                        status=TaskStatus.FAILED,
                        error=f"Task execution exception: {str(exc)}",
                        duration=0.0,
                        attributes={},
                    )
                results.append(result)

                if result.status == TaskStatus.COMPLETED:
                    task.mark_completed(result.result_metadata)
                    self.stats["tasks_completed"] += 1
                    status_icon = "✓"
                    status_color = "green"
                else:
                    task.mark_failed(result.error or "Unknown error")
                    task.result = result.result_metadata
                    self.stats["tasks_failed"] += 1
                    status_icon = "✗"
                    status_color = "red"

                self.console.print(
                    f"  [{status_color}]{status_icon}[/{status_color}] "
                    f"Task {index}: {task.description[:60]} "
                    f"({result.duration:.1f}s)"
                )

                if result.error:
                    self.console.print(f"    [red]Error: {result.error}[/red]")

                progress.advance(task_progress)

        self._log_task_execution_event(
            "standard_task_execution_completed",
            output_summary={
                "results": len(results),
                "completed": len([result for result in results if result.status == TaskStatus.COMPLETED]),
                "failed": len([result for result in results if result.status == TaskStatus.FAILED]),
            },
            success=all(result.status == TaskStatus.COMPLETED for result in results),
        )
        return results

    def _log_task_execution_event(
        self,
        event_type: str,
        *,
        success: bool | None = None,
        input_summary: Any | None = None,
        output_summary: Any | None = None,
        error: str | None = None,
    ) -> None:
        logger = getattr(self, "logger", None)
        if not logger:
            return
        logger.log_structured_event(
            source_type="module",
            source_name="autonomous_iteration.intelligent_autopilot",
            phase="task_execution",
            event_type=event_type,
            session_id=getattr(self, "session_id", None) or "unknown",
            turn_id=1,
            success=success,
            input_summary=input_summary,
            output_summary=output_summary,
            error=error,
        )

    def _map_reason_to_enum(self, reason_text: str) -> str:
        """Map free-form reason text to SelectionReason enum value.

        Args:
            reason_text: Free-form text from LLM

        Returns:
            Valid SelectionReason enum value
        """
        return self.tool_io.map_reason_to_enum(reason_text)

    def _execute_task(self, task: Task, context: TaskExecutionContext) -> TaskExecutionResult:
        """Execute a single task through the module-owned tool planning agent."""
        return self.tool_planning_task_executor.execute_task(task, context)

    def _format_tools_for_llm(self, tools: list) -> str:
        """Format available tools for LLM prompt."""
        return self.tool_io.format_tools_for_llm(tools)

    def _resolve_selection_metadata(
        self,
        selection: ToolSelection,
        step_outputs: dict[str, Any]
    ) -> ToolSelection:
        """Resolve tool metadata from previous step outputs.

        Based on the modern autopilot tool-chaining path.
        """
        return self.tool_io.resolve_selection_metadata(selection, step_outputs)

    def _show_start_panel(self, goal: str):
        """Show start panel."""
        return self.console_presenter.show_start_panel(goal)

    def _show_task_tree(self, decomposition):
        """Show task decomposition tree."""
        return self.console_presenter.show_task_tree(decomposition)

    def _show_completion_summary(self, decomposition, results):
        """Show completion summary."""
        return self.console_presenter.show_completion_summary(decomposition, results)

    def _build_task_graph_for_ui(self, decomposition) -> dict[str, Any]:
        """Build task graph structure for enhanced UI display."""
        return self.console_presenter.build_task_graph_for_ui(decomposition)
