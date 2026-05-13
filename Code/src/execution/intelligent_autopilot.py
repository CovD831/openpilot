"""
Intelligent Autopilot Executor using Task Decomposition Agent.

Replaces the rigid 8-stage workflow with dynamic task decomposition and execution.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.tree import Tree
from rich import box

from agents.task_decomposer import TaskDecomposer
from agents.orchestrator import AgentOrchestrator
from core.llm import LLMClient
from core.semantic_analyzer import SemanticAnalyzer
from memory.memory_store import MemoryStore
from models.task_models import (
    Task,
    TaskStatus,
    TaskPriority,
    Agent,
    AgentCapability,
    TaskExecutionContext,
    TaskExecutionResult
)
from models.tool_orchestration_models import (
    OrchestrationContext,
    ToolSelection,
    ExecutionStrategy
)
from tools.tool_registry import ToolRegistry
from tools.tool_executor import ToolExecutor
from tools.tool_orchestrator import ToolOrchestrator
from core.openpilot_log import OpenPilotLogger


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
    ):
        """Initialize intelligent autopilot.

        Args:
            llm_client: LLM client
            console: Rich console
            auto_approve: Auto-approve low/medium risk operations
            logger: Logger instance
            log_file: Log file path
            use_enhanced_ui: Use enhanced UI with progress tracking
        """
        self.console = console or Console()
        self.auto_approve = auto_approve
        self.use_enhanced_ui = use_enhanced_ui

        # Initialize UI components
        if use_enhanced_ui:
            from ui.enhanced_ui import EnhancedUI
            from ui.progress_tracker import ProgressTracker
            from core.instrumented_llm import InstrumentedLLMClient
            from tools.instrumented_executor import InstrumentedToolExecutor

            self.enhanced_ui = EnhancedUI(self.console)
            self.tracker = ProgressTracker(self.enhanced_ui)
            self.llm_client = InstrumentedLLMClient(llm_client.settings, self.tracker)
        else:
            self.enhanced_ui = None
            self.tracker = None
            self.llm_client = llm_client

        # Initialize components
        self.task_decomposer = TaskDecomposer(self.llm_client)
        self.orchestrator = AgentOrchestrator(max_concurrent_tasks=3)
        self.semantic_analyzer = SemanticAnalyzer(self.llm_client)
        self.memory_store = MemoryStore()
        self.tool_registry = ToolRegistry()

        # Register built-in tools
        from tools.builtin_tools import register_builtin_tools
        register_builtin_tools(self.tool_registry)

        # Use instrumented executor if enhanced UI is enabled
        if use_enhanced_ui:
            from tools.instrumented_executor import InstrumentedToolExecutor
            self.tool_executor = InstrumentedToolExecutor(self.tool_registry, self.tracker)
        else:
            self.tool_executor = ToolExecutor(self.tool_registry)

        # Initialize tool orchestrator
        self.tool_orchestrator = ToolOrchestrator(
            self.tool_registry,
            self.llm_client
        )

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

        # Register task executor
        self.orchestrator.set_task_executor(self._execute_task)

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

        # Use enhanced UI if available
        if self.use_enhanced_ui and self.enhanced_ui and self.tracker:
            try:
                result = self._execute_with_enhanced_ui_v2(goal, context)
                return result
            except Exception as e:
                if self.enhanced_ui:
                    self.enhanced_ui.log_activity("error", f"Execution failed: {str(e)}")
                self.logger.log_event(
                    "execution_error",
                    {"error": str(e), "goal": goal},
                    session_id=self.session_id or "unknown",
                    turn_id=1,
                )
                raise
        else:
            return self._execute_standard(goal, context)

    def _execute_with_enhanced_ui_v2(self, goal, context):
        self.tracker.start_tracking()

        try:
            # Step 1: Semantic analysis
            self.enhanced_ui.update_main_content(
                self.enhanced_ui.create_status_panel("Analyzing", "Performing semantic analysis...")
            )

            with self.tracker.track_task("Semantic Analysis", {"goal": goal}):
                semantic = self.semantic_analyzer.analyze_goal(goal)

            self.enhanced_ui.log_activity("success", f"Analysis complete: {semantic.task_type.value}")

            # Step 2: Retrieve memories
            with self.tracker.track_task("Memory Retrieval", {"query": goal}):
                memories = self.memory_store.query(goal, limit=5)

            if memories.memories:
                self.enhanced_ui.log_activity("success", f"Found {len(memories.memories)} relevant memories")

            context["semantic_analysis"] = semantic.model_dump()
            context["memories"] = [m.model_dump() for m in memories.memories]
            context["goal"] = goal

            # Step 3: Task decomposition
            self.enhanced_ui.update_main_content(
                self.enhanced_ui.create_status_panel("Decomposing", "Breaking down task into subtasks...")
            )

            with self.tracker.track_task("Task Decomposition", {"goal": goal}):
                decomposition = self.task_decomposer.decompose(
                    task_description=goal,
                    context=context
                )

            self.enhanced_ui.log_activity("success", f"Created {len(decomposition.subtasks)} subtasks")

            # Show task tree in UI
            task_tree_panel = self.enhanced_ui.create_task_tree_panel(decomposition)
            self.enhanced_ui.update_main_content(task_tree_panel)

            # Give user time to see the task tree
            import time
            time.sleep(3.0)  # Allow users to read the task breakdown

            # Step 4: Execute tasks
            self.enhanced_ui.update_main_content(
                self.enhanced_ui.create_status_panel("Executing", f"Running {len(decomposition.subtasks)} tasks...")
            )

            results = self._execute_tasks(decomposition.subtasks, goal)

            # Step 5: Assemble results
            with self.tracker.track_task("Result Assembly", {}):
                final_result = self.task_decomposer.assemble_results(
                    decomposition.original_task,
                    decomposition.subtasks
                )

            success = all(t.status == TaskStatus.COMPLETED for t in decomposition.subtasks)
            self.stats["success"] = success
            self.stats["tasks_completed"] = len([t for t in decomposition.subtasks if t.status == TaskStatus.COMPLETED])
            self.stats["tasks_failed"] = len([t for t in decomposition.subtasks if t.status == TaskStatus.FAILED])
            self.stats["end_time"] = datetime.now()

            self.tracker.stop_tracking()

            # Update main content with final status (don't print new panels)
            if success:
                self.enhanced_ui.update_main_content(
                    self.enhanced_ui.create_status_panel(
                        "Success",
                        f"Goal completed successfully!\n\nCompleted {self.stats['tasks_completed']} tasks"
                    )
                )
            else:
                self.enhanced_ui.update_main_content(
                    self.enhanced_ui.create_status_panel(
                        "Failed",
                        f"Goal execution failed\n\nCompleted: {self.stats['tasks_completed']}, Failed: {self.stats['tasks_failed']}"
                    )
                )

            return {
                "success": success,
                "goal": goal,
                "semantic_analysis": semantic,
                "decomposition": decomposition,
                "results": results,
                "stats": self.stats,
            }

        except Exception as e:
            self.tracker.stop_tracking()
            self.enhanced_ui.update_main_content(
                self.enhanced_ui.create_status_panel("Error", f"Execution failed: {str(e)}")
            )
            raise

    def _execute_standard(self, goal: str, context: dict[str, Any]) -> dict[str, Any]:
        """Execute with standard console output."""
        try:
            # Show start panel
            self._show_start_panel(goal)

            # Step 1: Semantic analysis
            self.console.print("[bold cyan]🧠 Analyzing goal...[/bold cyan]")
            semantic = self.semantic_analyzer.analyze_goal(goal)
            self.console.print(f"  • Task type: [cyan]{semantic.task_type.value}[/cyan]")
            self.console.print(f"  • Risk level: [{'red' if semantic.risk_level.value == 'high' else 'yellow' if semantic.risk_level.value == 'medium' else 'green'}]{semantic.risk_level.value}[/]")
            self.console.print(f"  • Confidence: {semantic.confidence:.2f}")
            self.console.print()

            # Step 2: Retrieve relevant memories
            self.console.print("[bold cyan]🧠 Retrieving memories...[/bold cyan]")
            memories = self.memory_store.query(goal, limit=5)
            if memories.memories:
                self.console.print(f"  • Found {len(memories.memories)} relevant memories")
                for mem in memories.memories[:3]:
                    self.console.print(f"    - [{mem.memory_type.value}] {mem.content[:60]}...")
            else:
                self.console.print("  • No relevant memories found")
            self.console.print()

            # Add memories to context
            context["semantic_analysis"] = semantic.model_dump()
            context["memories"] = [m.model_dump() for m in memories.memories]
            context["goal"] = goal

            # Step 3: Decompose task
            self.console.print("[bold cyan]🔍 Decomposing task...[/bold cyan]")
            decomposition = self.task_decomposer.decompose(
                task_description=goal,
                context=context
            )

            self.console.print(f"  • Original task: {decomposition.original_task.description}")
            self.console.print(f"  • Subtasks: {len(decomposition.subtasks)}")
            self.console.print(f"  • Estimated effort: {decomposition.estimated_total_effort:.1f} units")
            self.console.print()

            # Show task tree
            self._show_task_tree(decomposition)

            # Log decomposition
            self.logger.log_event(
                "task_decomposition",
                {
                    "goal": goal,
                    "original_task_id": decomposition.original_task.id,
                    "subtask_count": len(decomposition.subtasks),
                    "estimated_effort": decomposition.estimated_total_effort,
                    "rationale": decomposition.decomposition_rationale,
                },
                session_id=self.session_id,
                turn_id=1,
            )

            # Step 4: Execute tasks
            self.console.print("[bold cyan]⚡ Executing tasks...[/bold cyan]")
            results = self._execute_tasks(decomposition.subtasks, goal)

            # Step 5: Assemble results
            self.console.print()
            self.console.print("[bold cyan]📦 Assembling results...[/bold cyan]")
            final_result = self.task_decomposer.assemble_results(
                decomposition.original_task,
                decomposition.subtasks
            )

            # Calculate success
            success = all(t.status == TaskStatus.COMPLETED for t in decomposition.subtasks)
            self.stats["success"] = success
            self.stats["tasks_completed"] = len([t for t in decomposition.subtasks if t.status == TaskStatus.COMPLETED])
            self.stats["tasks_failed"] = len([t for t in decomposition.subtasks if t.status == TaskStatus.FAILED])
            self.stats["end_time"] = datetime.now()

            # Show completion summary
            self._show_completion_summary(decomposition, results)

            return {
                "success": success,
                "goal": goal,
                "semantic_analysis": semantic,
                "decomposition": decomposition,
                "results": results,
                "final_result": final_result,
                "stats": self.stats,
            }

        except Exception as e:
            self.console.print(f"\n[bold red]❌ Execution failed: {e}[/bold red]")
            self.stats["success"] = False
            self.stats["end_time"] = datetime.now()

            self.logger.log_event(
                "autopilot_failed",
                {
                    "goal": goal,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                session_id=self.session_id or "unknown",
                turn_id=1,
            )
            raise

    def _execute_tasks(self, tasks: list[Task], goal: str = "") -> list[TaskExecutionResult]:
        """Execute tasks using orchestrator.

        Args:
            tasks: List of tasks to execute
            goal: Original goal for context

        Returns:
            List of execution results
        """
        results = []

        # Build task graph for execution order
        task_graph = self.task_decomposer.build_task_graph(tasks)

        # Get execution order
        try:
            execution_order = self.task_decomposer.get_execution_order(task_graph)
        except ValueError as e:
            if self.use_enhanced_ui:
                self.enhanced_ui.log_activity("error", "Cannot determine execution order, executing sequentially")
            else:
                self.console.print(f"[yellow]⚠ Cannot determine execution order (cyclic dependencies?), executing sequentially[/yellow]")
            execution_order = [t.id for t in tasks]

        # Execute tasks differently based on UI mode
        if self.use_enhanced_ui:
            return self._execute_tasks_enhanced_ui(tasks, execution_order, goal)
        else:
            return self._execute_tasks_standard(tasks, execution_order, goal)

    def _execute_tasks_enhanced_ui(self, tasks: list[Task], execution_order: list[str], goal: str) -> list[TaskExecutionResult]:
        """Execute tasks with enhanced UI (updates layout instead of printing)."""
        results = []

        self.logger.log_event(
            "task_execution_started",
            {
                "total_tasks": len(tasks),
                "execution_order": execution_order,
                "goal": goal
            },
            session_id=self.session_id or "unknown",
            turn_id=1,
        )

        for i, task_id in enumerate(execution_order, 1):
            # Find task
            task = next((t for t in tasks if t.id == task_id), None)
            if not task:
                self.logger.log_event(
                    "task_not_found",
                    {"task_id": task_id, "index": i},
                    session_id=self.session_id or "unknown",
                    turn_id=1,
                )
                continue

            self.logger.log_event(
                "task_execution_start",
                {
                    "task_id": task.id,
                    "task_index": i,
                    "description": task.description,
                    "priority": task.priority.value if hasattr(task.priority, 'value') else str(task.priority)
                },
                session_id=self.session_id or "unknown",
                turn_id=1,
            )

            # Update UI with current task and spinner
            completed_count = len([r for r in results if r.status == TaskStatus.COMPLETED])
            failed_count = len([r for r in results if r.status == TaskStatus.FAILED])
            status_detail = f"Task {i}/{len(tasks)}: {task.description}\n\n"
            status_detail += f"Progress: {completed_count} completed, {failed_count} failed"

            self.enhanced_ui.update_main_content(
                self.enhanced_ui.create_executing_panel(status_detail)
            )

            # Execute task
            task_context = TaskExecutionContext(
                task=task,
                parent_context={"goal": goal, "session_id": self.session_id},
                shared_state={},
                execution_history=[]
            )

            try:
                result = self._execute_task(task, task_context)
                results.append(result)

                # Log detailed result
                self.logger.log_event(
                    "task_execution_complete",
                    {
                        "task_id": task.id,
                        "task_index": i,
                        "status": result.status.value if hasattr(result.status, 'value') else str(result.status),
                        "success": result.status == TaskStatus.COMPLETED,
                        "error": result.error,
                        "duration": result.duration,
                        "result_summary": str(result.result)[:200] if result.result else None
                    },
                    session_id=self.session_id or "unknown",
                    turn_id=1,
                )

                # Update task status - this is critical for assemble_results to work
                if result.status == TaskStatus.COMPLETED:
                    task.mark_completed(result.result)
                    self.enhanced_ui.log_activity("success", f"✓ Task {i}: {task.description[:50]}... ({result.duration:.1f}s)")
                else:
                    task.mark_failed(result.error or "Unknown error")
                    self.enhanced_ui.log_activity("error", f"✗ Task {i} failed: {result.error}")
                    self.logger.log_event(
                        "task_execution_failed",
                        {
                            "task_id": task.id,
                            "task_index": i,
                            "description": task.description,
                            "error": result.error,
                            "result": result.result
                        },
                        session_id=self.session_id or "unknown",
                        turn_id=1,
                    )

                # Verify task status was updated
                if task.status == TaskStatus.PENDING:
                    # This should never happen - log it
                    self.logger.log_event(
                        "task_status_update_failed",
                        {
                            "task_id": task.id,
                            "task_index": i,
                            "result_status": result.status.value if hasattr(result.status, 'value') else str(result.status),
                            "task_status": task.status.value if hasattr(task.status, 'value') else str(task.status)
                        },
                        session_id=self.session_id or "unknown",
                        turn_id=1,
                    )
                    # Force update
                    if result.status == TaskStatus.COMPLETED:
                        task.status = TaskStatus.COMPLETED
                        task.result = result.result
                    else:
                        task.status = TaskStatus.FAILED
                        task.error = result.error

            except Exception as e:
                # Handle execution errors
                error_msg = f"Task execution exception: {str(e)}"
                self.enhanced_ui.log_activity("error", f"✗ Task {i} exception: {str(e)}")
                self.logger.log_event(
                    "task_execution_exception",
                    {
                        "task_id": task.id,
                        "task_index": i,
                        "description": task.description,
                        "error": str(e),
                        "error_type": type(e).__name__
                    },
                    session_id=self.session_id or "unknown",
                    turn_id=1,
                )

                # Create failed result
                result = TaskExecutionResult(
                    task_id=task.id,
                    status=TaskStatus.FAILED,
                    error=error_msg,
                    duration=0.0,
                    metadata={}
                )
                results.append(result)
                task.mark_failed(error_msg)

        # Log final summary
        completed = len([r for r in results if r.status == TaskStatus.COMPLETED])
        failed = len([r for r in results if r.status == TaskStatus.FAILED])

        self.logger.log_event(
            "task_execution_summary",
            {
                "total": len(results),
                "completed": completed,
                "failed": failed,
                "task_statuses": [
                    {
                        "id": t.id,
                        "description": t.description[:50],
                        "status": t.status.value if hasattr(t.status, 'value') else str(t.status)
                    }
                    for t in tasks
                ]
            },
            session_id=self.session_id or "unknown",
            turn_id=1,
        )

        return results

    def _execute_tasks_standard(self, tasks: list[Task], execution_order: list[str], goal: str) -> list[TaskExecutionResult]:
        """Execute tasks with standard console output."""
        results = []

        # Execute tasks in order
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=self.console,
        ) as progress:
            task_progress = progress.add_task(
                "Executing tasks...",
                total=len(tasks)
            )

            for i, task_id in enumerate(execution_order, 1):
                # Find task
                task = next((t for t in tasks if t.id == task_id), None)
                if not task:
                    continue

                # Update progress
                progress.update(
                    task_progress,
                    description=f"[{i}/{len(tasks)}] {task.description[:50]}..."
                )

                # Execute task
                task_context = TaskExecutionContext(
                    task=task,
                    parent_context={"goal": goal, "session_id": self.session_id},
                    shared_state={},
                    execution_history=[]
                )

                result = self._execute_task(task, task_context)
                results.append(result)

                # Update task status
                if result.status == TaskStatus.COMPLETED:
                    task.mark_completed(result.result)
                    self.stats["tasks_completed"] += 1
                    status_icon = "✓"
                    status_color = "green"
                else:
                    task.mark_failed(result.error or "Unknown error")
                    self.stats["tasks_failed"] += 1
                    status_icon = "✗"
                    status_color = "red"

                # Show result
                self.console.print(
                    f"  [{status_color}]{status_icon}[/{status_color}] "
                    f"Task {i}: {task.description[:60]} "
                    f"({result.duration:.1f}s)"
                )

                if result.error:
                    self.console.print(f"    [red]Error: {result.error}[/red]")

                progress.advance(task_progress)

        return results

    def _map_reason_to_enum(self, reason_text: str) -> str:
        """Map free-form reason text to SelectionReason enum value.

        Args:
            reason_text: Free-form text from LLM

        Returns:
            Valid SelectionReason enum value
        """
        reason_lower = reason_text.lower()

        # Map keywords to enum values
        if any(word in reason_lower for word in ["capability", "can", "able to", "supports"]):
            return "capability_match"
        elif any(word in reason_lower for word in ["best", "optimal", "performance", "efficient"]):
            return "best_performance"
        elif any(word in reason_lower for word in ["only", "single", "no other", "no alternative"]):
            return "only_option"
        elif any(word in reason_lower for word in ["prefer", "user", "requested"]):
            return "user_preference"
        elif any(word in reason_lower for word in ["fallback", "backup", "alternative"]):
            return "fallback"
        elif any(word in reason_lower for word in ["cost", "cheap", "economical"]):
            return "cost_optimized"
        else:
            # Default to capability_match as it's the most general
            return "capability_match"

    def _execute_task(self, task: Task, context: TaskExecutionContext) -> TaskExecutionResult:
        """Execute a single task by generating and executing tool calls.

        Args:
            task: Task to execute
            context: Execution context

        Returns:
            Task execution result
        """
        start_time = datetime.now()

        try:
            goal = context.parent_context.get("goal", "")

            # Use LLM to generate tool execution plan
            available_tools = self.tool_registry.list_all()
            tools_description = self._format_tools_for_llm(available_tools)

            prompt = f"""You are an AI assistant that selects and sequences tools to accomplish tasks.

Task: {task.description}
Overall Goal: {goal}

Available Tools:
{tools_description}

Generate a JSON plan with a list of tool calls to accomplish this task. Each tool call should specify:
- tool_name: name of the tool to use
- reason: why this tool is needed
- input_params: dictionary of input parameters

Output ONLY valid JSON in this format:
{{
  "tool_calls": [
    {{
      "tool_name": "tool_name_here",
      "reason": "explanation",
      "input_params": {{"param1": "value1"}}
    }}
  ]
}}

Important:
- For code generation tasks, use code_generator to generate code, then file_writer to save it
- Provide actual values for all parameters, do not use null or placeholders
- If you need to pass output from one tool to another, generate the content directly in the first tool
"""

            # Call LLM
            self.logger.log_event(
                "llm_tool_planning",
                {"task_id": task.id, "task_description": task.description},
                session_id=self.session_id or "unknown",
                turn_id=1,
            )

            from core.llm import LLMRequest, LLMMessage

            llm_request = LLMRequest(
                messages=[LLMMessage(role="user", content=prompt)],
                response_format="json_object"
            )

            llm_response = self.llm_client.complete(llm_request)
            response = llm_response.content

            # Parse response
            try:
                plan_data = json.loads(response)
                tool_calls = plan_data.get("tool_calls", [])
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse LLM response as JSON: {e}")

            if not tool_calls:
                raise ValueError("LLM generated empty tool plan")

            # Execute tools sequentially
            tool_results = []
            last_output = None

            for i, tool_call in enumerate(tool_calls):
                tool_name = tool_call.get("tool_name")
                input_params = tool_call.get("input_params", {})
                reason_text = tool_call.get("reason", "")

                # Update UI to show current tool execution
                if self.enhanced_ui:
                    tool_status = f"Executing tool {i+1}/{len(tool_calls)}: {tool_name}\n"
                    if tool_name == "code_generator":
                        tool_status += f"Generating code for: {input_params.get('task_description', '')[:60]}..."
                    elif tool_name == "file_writer":
                        tool_status += f"Writing to: {input_params.get('file_path', 'unknown')}"
                    elif tool_name == "code_executor":
                        tool_status += f"Executing {input_params.get('language', 'code')}..."

                    self.enhanced_ui.update_main_content(
                        self.enhanced_ui.create_executing_panel(tool_status)
                    )

                # Auto-inject previous output for chained tools
                if i > 0 and last_output is not None:
                    # file_writer needs content from code_generator
                    if tool_name == "file_writer" and "content" not in input_params:
                        if isinstance(last_output, dict) and "code" in last_output:
                            input_params["content"] = last_output["code"]
                            self.console.print(f"[yellow]Auto-injecting code ({len(last_output['code'])} chars) into file_writer[/yellow]")
                        elif isinstance(last_output, dict) and "content" in last_output:
                            input_params["content"] = last_output["content"]
                        elif isinstance(last_output, str):
                            input_params["content"] = last_output

                    # code_executor needs code from code_generator
                    elif tool_name == "code_executor" and "code" not in input_params:
                        if isinstance(last_output, dict) and "code" in last_output:
                            input_params["code"] = last_output["code"]
                            if "language" in last_output and "language" not in input_params:
                                input_params["language"] = last_output["language"]

                # Map free-form reason to enum value
                reason_enum = self._map_reason_to_enum(reason_text)

                # Create ToolSelection
                selection = ToolSelection(
                    step_id=f"step_{i+1}",
                    tool_name=tool_name,
                    reason=reason_enum,
                    confidence=0.9,
                    input_params=input_params,
                    requires_confirmation=False,
                    fallback_tools=[],
                    depends_on=[],
                    timeout_override=None
                )

                # Log tool execution start with detailed params
                log_params = input_params.copy()
                if tool_name == "file_writer" and "content" in log_params:
                    content_len = len(log_params["content"]) if log_params["content"] else 0
                    log_params["content_length"] = content_len
                    log_params["content_preview"] = log_params["content"][:200] if log_params["content"] else ""
                elif tool_name == "code_generator":
                    log_params["task_description_length"] = len(log_params.get("task_description", ""))

                self.logger.log_event(
                    "tool_execution_start",
                    {
                        "task_id": task.id,
                        "tool": tool_name,
                        "params": log_params
                    },
                    session_id=self.session_id or "unknown",
                    turn_id=1,
                )

                # Execute tool
                exec_result = self.tool_executor.execute_single(
                    selection,
                    context=None
                )

                # Log detailed output
                log_output = {}
                if exec_result.output:
                    if isinstance(exec_result.output, dict):
                        log_output = exec_result.output.copy()
                        if "code" in log_output:
                            log_output["code_length"] = len(log_output["code"])
                            log_output["code_preview"] = log_output["code"][:200]
                        if "content" in log_output:
                            log_output["content_length"] = len(log_output["content"])
                    else:
                        log_output = {"output_type": type(exec_result.output).__name__}

                # Track result
                tool_results.append({
                    "tool": tool_name,
                    "params": input_params,
                    "result": exec_result.output,
                    "success": exec_result.success,
                    "error": exec_result.error.error_message if exec_result.error else None
                })

                # Log execution with detailed output
                self.logger.log_event(
                    "tool_executed",
                    {
                        "task_id": task.id,
                        "tool": tool_name,
                        "success": exec_result.success,
                        "error": exec_result.error.error_message if exec_result.error else None,
                        "output": log_output,
                        "execution_time_ms": exec_result.execution_time_ms if hasattr(exec_result, 'execution_time_ms') else None
                    },
                    session_id=self.session_id or "unknown",
                    turn_id=1,
                )

                last_output = exec_result.output

            # Determine overall success
            all_succeeded = all(t["success"] for t in tool_results)

            output = {
                "task_id": task.id,
                "description": task.description,
                "status": "completed" if all_succeeded else "failed",
                "tool_calls": tool_results,
                "all_tools_succeeded": all_succeeded,
                "final_output": last_output
            }

            duration = (datetime.now() - start_time).total_seconds()

            # Build detailed error message if any tools failed
            error_msg = None
            if not all_succeeded:
                failed_tools = [t for t in tool_results if not t["success"]]
                error_parts = [f"{len(failed_tools)} tool(s) failed:"]
                for ft in failed_tools:
                    error_parts.append(f"\n  - {ft['tool']}: {ft['error']}")
                error_msg = "".join(error_parts)

            result = TaskExecutionResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED if all_succeeded else TaskStatus.FAILED,
                result=output,
                error=error_msg,
                duration=duration,
                metadata={
                    "start_time": start_time.isoformat(),
                    "end_time": datetime.now().isoformat(),
                    "tool_count": len(tool_results)
                }
            )

            return result

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()

            result = TaskExecutionResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error=str(e),
                duration=duration,
                metadata={
                    "start_time": start_time.isoformat(),
                    "end_time": datetime.now().isoformat()
                }
            )

            # Log failure
            self.logger.log_event(
                "task_failed",
                {
                    "task_id": task.id,
                    "description": task.description,
                    "error": str(e),
                    "duration": duration,
                },
                session_id=self.session_id or "unknown",
                turn_id=1,
            )

            return result

    def _format_tools_for_llm(self, tools: list) -> str:
        """Format available tools for LLM prompt."""
        tool_descriptions = []
        for tool in tools:
            params_str = ""
            if tool.input_schema:
                params = []
                for param in tool.input_schema:
                    param_desc = f"  - {param.name} ({param.type})"
                    if param.required:
                        param_desc += " [required]"
                    if param.description:
                        param_desc += f": {param.description}"
                    params.append(param_desc)
                params_str = "\n".join(params)

            tool_descriptions.append(
                f"- {tool.name}: {tool.description}\n"
                f"  Parameters:\n{params_str if params_str else '  (none)'}"
            )

        return "\n\n".join(tool_descriptions)

    def _resolve_selection_inputs(
        self,
        selection: ToolSelection,
        step_outputs: dict[str, Any]
    ) -> ToolSelection:
        """Resolve tool inputs from previous step outputs.

        Based on WorkflowExecutor pattern for proper tool chaining.
        """
        input_params = dict(selection.input_params)
        source_step_id = input_params.pop("source_step_id", None)

        if source_step_id and source_step_id in step_outputs:
            source_output = step_outputs[source_step_id]

            # Tool-specific extraction logic
            if selection.tool_name == "file_writer":
                if "content" not in input_params:
                    if isinstance(source_output, dict) and "code" in source_output:
                        input_params["content"] = source_output["code"]
                    elif isinstance(source_output, dict) and "content" in source_output:
                        input_params["content"] = source_output["content"]
                    else:
                        input_params["content"] = str(source_output)

            elif selection.tool_name == "code_reviewer":
                if isinstance(source_output, dict):
                    if "code" in source_output and "code" not in input_params:
                        input_params["code"] = source_output["code"]
                    if "language" in source_output and "language" not in input_params:
                        input_params["language"] = source_output["language"]

            elif selection.tool_name == "code_executor":
                if isinstance(source_output, dict) and "code" in source_output:
                    if "code" not in input_params:
                        input_params["code"] = source_output["code"]

            elif selection.tool_name == "file_reader":
                if isinstance(source_output, str) and "file_path" not in input_params:
                    input_params["file_path"] = source_output
                elif isinstance(source_output, dict) and "file_path" in source_output:
                    if "file_path" not in input_params:
                        input_params["file_path"] = source_output["file_path"]

            elif selection.tool_name == "llm_summarizer":
                if isinstance(source_output, dict) and "content" in source_output:
                    if "text" not in input_params:
                        input_params["text"] = source_output["content"]
                elif isinstance(source_output, str):
                    if "text" not in input_params:
                        input_params["text"] = source_output

        # Return new ToolSelection with resolved inputs
        return ToolSelection(
            step_id=selection.step_id,
            tool_name=selection.tool_name,
            reason=selection.reason,
            confidence=selection.confidence,
            input_params=input_params,
            requires_confirmation=selection.requires_confirmation,
            fallback_tools=selection.fallback_tools,
            depends_on=selection.depends_on,
            timeout_override=selection.timeout_override
        )

    def _show_start_panel(self, goal: str):
        """Show start panel."""
        panel = Panel(
            f"[bold cyan]Goal:[/bold cyan] {goal}\n\n"
            f"[dim]Mode: Intelligent Autopilot (Dynamic Task Decomposition)[/dim]\n"
            f"[dim]Auto-approve: {'Yes' if self.auto_approve else 'No'}[/dim]",
            title="[bold green]🚀 Intelligent Autopilot Activated[/bold green]",
            border_style="green",
        )
        self.console.print(panel)
        self.console.print()

    def _show_task_tree(self, decomposition):
        """Show task decomposition tree."""
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

        self.console.print(tree)
        self.console.print()

    def _show_completion_summary(self, decomposition, results):
        """Show completion summary."""
        duration = (self.stats["end_time"] - self.stats["start_time"]).total_seconds()

        self.console.print()
        self.console.print("━" * 80)

        if self.stats["success"]:
            self.console.print("[bold green]✨ Autopilot mission completed successfully![/bold green]")
        else:
            self.console.print("[bold yellow]⚠ Autopilot mission completed with errors[/bold yellow]")

        self.console.print("━" * 80)
        self.console.print()

        # Summary stats
        self.console.print(f"[cyan]Total duration:[/cyan] {duration:.1f}s")
        self.console.print(f"[cyan]Tasks completed:[/cyan] {self.stats['tasks_completed']}/{len(decomposition.subtasks)}")

        if self.stats["tasks_failed"] > 0:
            self.console.print(f"[yellow]Tasks failed:[/yellow] {self.stats['tasks_failed']}")

        # Success rate
        if decomposition.subtasks:
            success_rate = self.stats["tasks_completed"] / len(decomposition.subtasks) * 100
            self.console.print(f"[cyan]Success rate:[/cyan] {success_rate:.0f}%")

        self.console.print()

    def _build_task_graph_for_ui(self, decomposition) -> dict[str, Any]:
        """Build task graph structure for enhanced UI display."""
        tasks = []

        for subtask in decomposition.subtasks:
            task_dict = {
                "name": subtask.description,
                "status": subtask.status.value if hasattr(subtask.status, 'value') else str(subtask.status),
                "priority": subtask.priority.value if hasattr(subtask.priority, 'value') else str(subtask.priority),
                "estimated_effort": subtask.estimated_effort,
            }

            # Add dependencies info
            if subtask.dependencies:
                task_dict["dependencies"] = len(subtask.dependencies)

            tasks.append(task_dict)

        return {
            "original_task": decomposition.original_task.description,
            "tasks": tasks,
            "total_effort": decomposition.estimated_total_effort,
        }
