"""
Intelligent Autopilot Executor using Task Decomposition Agent.

Replaces the rigid 8-stage workflow with dynamic task decomposition and execution.
"""

from __future__ import annotations

import json
import ast
import re
import shlex
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
        enhanced_ui: Any | None = None,
        tracker: Any | None = None,
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
        """
        self.console = console or Console()
        self.auto_approve = auto_approve
        self.use_enhanced_ui = use_enhanced_ui

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

        # Initialize components
        self.task_decomposer = TaskDecomposer(self.llm_client)
        self.orchestrator = AgentOrchestrator(max_concurrent_tasks=3)
        self.semantic_analyzer = SemanticAnalyzer(self.llm_client)
        self.memory_store = MemoryStore()
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

    def _register_contextual_tools(self) -> None:
        """Register tool wrappers that can reuse this autopilot's runtime context."""
        from tools.code_generator import CODE_GENERATOR_DEFINITION, code_generator_executor

        def execute_code_generator(params: dict[str, Any]) -> dict[str, Any]:
            return code_generator_executor({**params, "_llm_client": self.llm_client})

        self.tool_registry.register(
            CODE_GENERATOR_DEFINITION,
            execute_code_generator,
            allow_override=True,
        )

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

    def _try_simple_code_artifact_fast_path(self, goal: str, semantic: Any) -> dict[str, Any] | None:
        """Generate simple single-file code artifacts without multi-step decomposition."""
        target_file = self._simple_code_artifact_target(goal, semantic)
        if target_file is None:
            return None

        if self.enhanced_ui:
            self.enhanced_ui.set_task_graph_state(
                goal=goal,
                tasks=[
                    {"id": "fast_code_generator", "description": "Generate Python code", "status": "running"},
                    {"id": "fast_file_writer", "description": f"Write {target_file.name}", "status": "pending"},
                    {"id": "fast_readme_tool", "description": "Generate README.md", "status": "pending"},
                ],
                current_task_id="fast_code_generator",
            )
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

        task = Task(
            id=str(uuid.uuid4()),
            description=f"Generate complete code artifact at {target_file}",
            priority=TaskPriority.HIGH,
        )
        started = datetime.now()
        tool_results: list[dict[str, Any]] = []

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
            input_params={
                "task_description": code_prompt,
                "language": "python",
                "context": f"Output file: {target_file}",
            },
        )
        tool_results.append(code_result)
        if self.enhanced_ui:
            self.enhanced_ui.set_task_graph_state(
                tasks=[
                    {
                        "id": "fast_code_generator",
                        "description": "Generate Python code",
                        "status": "completed" if code_result["success"] else "failed",
                    },
                    {"id": "fast_file_writer", "description": f"Write {target_file.name}", "status": "running"},
                    {"id": "fast_readme_tool", "description": "Generate README.md", "status": "pending"},
                ],
                current_task_id="fast_file_writer",
            )

        code = ""
        if code_result["success"] and isinstance(code_result["result"], dict):
            code = code_result["result"].get("code", "")

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
                input_params={
                    "file_path": str(target_file),
                    "content": code,
                    "encoding": "utf-8",
                    "create_dirs": True,
                    "overwrite": True,
                },
            )
            tool_results.append(write_result)
            if self.enhanced_ui:
                self.enhanced_ui.set_task_graph_state(
                    tasks=[
                        {"id": "fast_code_generator", "description": "Generate Python code", "status": "completed"},
                        {
                            "id": "fast_file_writer",
                            "description": f"Write {target_file.name}",
                            "status": "completed" if write_result["success"] else "failed",
                        },
                        {"id": "fast_readme_tool", "description": "Generate README.md", "status": "running"},
                    ],
                    current_task_id="fast_readme_tool",
                )
            if write_result["success"]:
                readme_result = self._execute_fast_tool(
                    task=task,
                    step_id="fast_readme_tool",
                    tool_name="readme_tool",
                    input_params={
                        "project_path": str(target_file.parent),
                        "project_summary": goal,
                        "written_files": [str(target_file)],
                        "entry_files": [str(target_file)],
                        "run_command": f"python {shlex.quote(target_file.name)}",
                        "overwrite": True,
                    },
                )
                tool_results.append(readme_result)
                if self.enhanced_ui:
                    self.enhanced_ui.set_task_graph_state(
                        tasks=[
                            {"id": "fast_code_generator", "description": "Generate Python code", "status": "completed"},
                            {"id": "fast_file_writer", "description": f"Write {target_file.name}", "status": "completed"},
                            {
                                "id": "fast_readme_tool",
                                "description": "Generate README.md",
                                "status": "completed" if readme_result["success"] else "failed",
                            },
                        ],
                        current_task_id="fast_readme_tool",
                    )
        elif syntax_error:
            tool_results.append({
                "tool": "syntax_validation",
                "params": {"file_path": str(target_file)},
                "result": None,
                "success": False,
                "error": syntax_error,
            })

        primary_results = [result for result in tool_results if result["tool"] != "readme_tool"]
        success = all(result["success"] for result in primary_results)
        duration = (datetime.now() - started).total_seconds()
        error_msg = None
        if not success:
            errors = [r["error"] for r in primary_results if not r["success"]]
            error_msg = "; ".join(error for error in errors if error) or "Fast-path code generation failed"
        readme_result = next((r for r in tool_results if r["tool"] == "readme_tool"), None)
        readme_error = readme_result["error"] if readme_result and not readme_result["success"] else None

        if self.enhanced_ui:
            code_status = "completed" if code_result["success"] else "failed"
            file_result = next((r for r in tool_results if r["tool"] == "file_writer"), None)
            file_status = (
                "completed"
                if file_result and file_result["success"]
                else "failed"
                if file_result
                else "pending"
            )
            readme_status = (
                "completed"
                if readme_result and readme_result["success"]
                else "failed"
                if readme_result
                else "pending"
            )
            self.enhanced_ui.set_task_graph_state(
                tasks=[
                    {"id": "fast_code_generator", "description": "Generate Python code", "status": code_status},
                    {"id": "fast_file_writer", "description": f"Write {target_file.name}", "status": file_status},
                    {"id": "fast_readme_tool", "description": "Generate README.md", "status": readme_status},
                ],
                current_task_id="fast_readme_tool" if readme_result else "fast_file_writer",
            )

        task_result = TaskExecutionResult(
            task_id=task.id,
            status=TaskStatus.COMPLETED if success else TaskStatus.FAILED,
            result={
                "task_id": task.id,
                "description": task.description,
                "status": "completed" if success else "failed",
                "tool_calls": tool_results,
                "all_tools_succeeded": success,
                "final_output": tool_results[-1]["result"] if tool_results else None,
            },
            error=error_msg,
            duration=duration,
            metadata={"fast_path": True, "target_file": str(target_file)},
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
            if success and readme_result and readme_result["success"] and isinstance(readme_result["result"], dict):
                fast_details += f"\nREADME: {readme_result['result']['file_path']}"
            elif success and readme_error:
                fast_details += f"\nREADME generation failed: {readme_error}"
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
                "readme_error": readme_error,
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
            "readme": readme_result,
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
        input_params: dict[str, Any],
    ) -> dict[str, Any]:
        if self.enhanced_ui:
            display_params = dict(input_params)
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
            input_params=input_params,
            requires_confirmation=False,
            fallback_tools=[],
            depends_on=[],
            timeout_override=None,
        )

        self.logger.log_event(
            "tool_execution_start",
            {
                "task_id": task.id,
                "tool": tool_name,
                "params": self._sanitize_tool_params(input_params),
            },
            session_id=self.session_id or "unknown",
            turn_id=1,
        )

        exec_result = self.tool_executor.execute_single(selection, context=None)
        if self.enhanced_ui:
            status = "completed" if exec_result.success else "failed"
            detail = "Tool returned successfully"
            if not exec_result.success and exec_result.error:
                detail = exec_result.error.error_message
            self.enhanced_ui.set_current_task_state(
                title=f"Tool: {tool_name}",
                details=detail,
                status=status,
            )
        result = {
            "tool": tool_name,
            "params": self._sanitize_tool_params(input_params),
            "result": exec_result.output,
            "success": exec_result.success,
            "error": exec_result.error.error_message if exec_result.error else None,
        }
        self.logger.log_event(
            "tool_executed",
            {
                "task_id": task.id,
                "tool": tool_name,
                "success": exec_result.success,
                "error": result["error"],
                "output": self._summarize_tool_output(exec_result.output),
            },
            session_id=self.session_id or "unknown",
            turn_id=1,
        )
        return result

    def _finalize_project_readme(
        self,
        goal: str,
        results: list[TaskExecutionResult],
    ) -> dict[str, Any] | None:
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
            input_params={
                "project_path": str(project_path),
                "project_summary": goal,
                "written_files": written_files,
                "entry_files": written_files,
                "overwrite": True,
            },
        )

        if self.enhanced_ui:
            if readme_result["success"]:
                output = readme_result.get("result") if isinstance(readme_result.get("result"), dict) else {}
                self.enhanced_ui.log_activity("success", f"README generated: {output.get('file_path', 'README.md')}")
            else:
                self.enhanced_ui.log_activity("error", f"README generation failed: {readme_result.get('error')}")
        elif readme_result["success"]:
            output = readme_result.get("result") if isinstance(readme_result.get("result"), dict) else {}
            self.console.print(f"[green]README generated:[/green] {output.get('file_path', project_path / 'README.md')}")
        else:
            self.console.print(f"[yellow]README generation failed:[/yellow] {readme_result.get('error')}")

        self.logger.log_event(
            "readme_finalized",
            {
                "goal": goal,
                "project_path": str(project_path),
                "written_files": written_files,
                "success": readme_result["success"],
                "error": readme_result.get("error"),
                "output": self._summarize_tool_output(readme_result.get("result")),
            },
            session_id=self.session_id or "unknown",
            turn_id=1,
        )
        return readme_result

    def _results_include_tool(self, results: list[TaskExecutionResult], tool_name: str) -> bool:
        for result in results:
            task_result = result.result if isinstance(result.result, dict) else {}
            for tool_call in task_result.get("tool_calls", []):
                if tool_call.get("tool") == tool_name:
                    return True
        return False

    def _collect_written_files(self, results: list[TaskExecutionResult]) -> list[str]:
        files: list[str] = []
        seen: set[str] = set()
        for result in results:
            task_result = result.result if isinstance(result.result, dict) else {}
            for tool_call in task_result.get("tool_calls", []):
                if tool_call.get("tool") != "file_writer" or not tool_call.get("success"):
                    continue
                output = tool_call.get("result")
                path = output.get("file_path") if isinstance(output, dict) else None
                if not path:
                    path = tool_call.get("params", {}).get("file_path")
                if path and path not in seen:
                    files.append(path)
                    seen.add(path)
        return files

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

    def _sanitize_tool_params(self, params: dict[str, Any]) -> dict[str, Any]:
        sanitized: dict[str, Any] = {}
        for key, value in params.items():
            if key.startswith("_"):
                continue
            if key in {"content", "code"} and isinstance(value, str):
                sanitized[key] = f"<{len(value)} chars>"
                sanitized[f"{key}_length"] = len(value)
                sanitized[f"{key}_preview"] = value[:200]
            else:
                sanitized[key] = value
        return sanitized

    def _summarize_tool_output(self, output: Any) -> dict[str, Any]:
        if not isinstance(output, dict):
            return {"output_type": type(output).__name__} if output is not None else {}

        summary = output.copy()
        if "code" in summary and isinstance(summary["code"], str):
            summary["code_length"] = len(summary["code"])
            summary["code_preview"] = summary["code"][:200]
            summary.pop("code", None)
        if "content" in summary and isinstance(summary["content"], str):
            summary["content_length"] = len(summary["content"])
            summary["content_preview"] = summary["content"][:200]
            summary.pop("content", None)
        return summary

    def _resolve_chained_inputs(
        self,
        tool_name: str,
        input_params: dict[str, Any],
        last_output: Any,
        last_code_output: Any,
    ) -> dict[str, Any]:
        params = {
            key: self._replace_output_placeholders(value, last_output, last_code_output)
            for key, value in input_params.items()
        }

        preferred_output = last_code_output or last_output
        content = self._extract_generated_content(preferred_output)

        if tool_name == "file_writer" and "content" not in params and content is not None:
            params["content"] = content
        elif tool_name in {"code_executor", "code_reviewer"} and "code" not in params and content is not None:
            params["code"] = content
            if isinstance(preferred_output, dict) and "language" in preferred_output and "language" not in params:
                params["language"] = preferred_output["language"]

        return params

    def _replace_output_placeholders(
        self,
        value: Any,
        last_output: Any,
        last_code_output: Any,
    ) -> Any:
        if isinstance(value, dict):
            return {
                key: self._replace_output_placeholders(child, last_output, last_code_output)
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [
                self._replace_output_placeholders(child, last_output, last_code_output)
                for child in value
            ]
        if not isinstance(value, str) or "{{" not in value:
            return value

        code_content = self._extract_generated_content(last_code_output)
        previous_content = self._extract_generated_content(last_output)
        replacements = {
            "{{code_generator.output}}": code_content,
            "{{code_generator.code}}": code_content,
            "{{previous.output}}": previous_content,
            "{{previous.code}}": previous_content,
            "{{last_output}}": previous_content,
            "{{code}}": code_content,
        }

        for placeholder, replacement in replacements.items():
            if placeholder not in value or replacement is None:
                continue
            if value.strip() == placeholder:
                return replacement
            value = value.replace(placeholder, replacement)
        return value

    def _extract_generated_content(self, output: Any) -> str | None:
        if output is None:
            return None
        if isinstance(output, str):
            return output
        if isinstance(output, dict):
            for key in ("code", "content", "text"):
                value = output.get(key)
                if isinstance(value, str):
                    return value
        return None

    def _execute_with_enhanced_ui_v2(self, goal, context):
        self.tracker.start_tracking()
        stages = [
            "Semantic Analysis",
            "Memory Retrieval",
            "Task Decomposition",
            "Execution",
            "Result Assembly",
        ]
        stage_statuses = {stage: "pending" for stage in stages}
        self.enhanced_ui.set_task_graph_state(
            goal=goal,
            stages=stages,
            stage_statuses=stage_statuses,
            current_stage="Semantic Analysis",
            tasks=[],
        )
        self.enhanced_ui.set_current_task_state(
            title="Semantic Analysis",
            details=f"Goal: {goal[:120]}",
            status="running",
        )

        try:
            # Step 1: Semantic analysis
            stage_statuses["Semantic Analysis"] = "running"
            self.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                current_stage="Semantic Analysis",
            )

            with self.tracker.track_task("Semantic Analysis", {"goal": goal}):
                semantic = self.semantic_analyzer.analyze_goal(goal)

            stage_statuses["Semantic Analysis"] = "completed"
            self.enhanced_ui.set_task_graph_state(stage_statuses=stage_statuses)
            self.enhanced_ui.log_activity("success", f"Analysis complete: {semantic.task_type.value}")
            self.enhanced_ui.set_current_task_state(
                title="Semantic Analysis",
                details=(
                    f"Task Type: {semantic.task_type.value}\n"
                    f"Risk Level: {semantic.risk_level.value}\n"
                    f"Required Resources: {len(semantic.required_resources)}"
                ),
                status="completed",
            )

            import time
            time.sleep(1.5)

            # Step 2: Retrieve memories
            stage_statuses["Memory Retrieval"] = "running"
            self.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                current_stage="Memory Retrieval",
            )
            self.enhanced_ui.set_current_task_state(
                title="Memory Retrieval",
                details="Searching for relevant past experiences",
                status="running",
            )

            with self.tracker.track_task("Memory Retrieval", {"query": goal}):
                memories = self.memory_store.query(goal, limit=5)

            stage_statuses["Memory Retrieval"] = "completed"
            self.enhanced_ui.set_task_graph_state(stage_statuses=stage_statuses)
            if memories.memories:
                self.enhanced_ui.log_activity("success", f"Found {len(memories.memories)} relevant memories")
                memory_info = f"Found {len(memories.memories)} relevant memories:\n\n"
                for i, mem in enumerate(memories.memories[:3], 1):
                    memory_info += f"{i}. [{mem.memory_type.value}] {mem.content[:60]}...\n"
                self.enhanced_ui.set_current_task_state(
                    title="Memory Retrieval",
                    details=memory_info,
                    status="completed",
                )
                time.sleep(1.5)
            else:
                self.enhanced_ui.log_activity("info", "No relevant memories found")
                self.enhanced_ui.set_current_task_state(
                    title="Memory Retrieval",
                    details="No relevant memories found",
                    status="completed",
                )

            context["semantic_analysis"] = semantic.model_dump()
            context["memories"] = [m.model_dump() for m in memories.memories]
            context["goal"] = goal

            fast_result = self._try_simple_code_artifact_fast_path(goal, semantic)
            if fast_result is not None:
                return fast_result

            # Step 3: Task decomposition
            stage_statuses["Task Decomposition"] = "running"
            self.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                current_stage="Task Decomposition",
            )
            self.enhanced_ui.set_current_task_state(
                title="Task Decomposition",
                details="Breaking down task into executable subtasks",
                status="running",
            )

            with self.tracker.track_task("Task Decomposition", {"goal": goal}):
                decomposition = self.task_decomposer.decompose(
                    task_description=goal,
                    context=context
                )

            stage_statuses["Task Decomposition"] = "completed"
            self.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                tasks=self._dashboard_task_items(decomposition.subtasks),
            )
            self.enhanced_ui.log_activity("success", f"Created {len(decomposition.subtasks)} subtasks")

            # Show task breakdown details
            breakdown_info = f"Created {len(decomposition.subtasks)} subtasks:\n\n"
            for i, subtask in enumerate(decomposition.subtasks[:5], 1):
                breakdown_info += f"{i}. {subtask.description[:70]}...\n"
            if len(decomposition.subtasks) > 5:
                breakdown_info += f"\n... and {len(decomposition.subtasks) - 5} more tasks"

            self.enhanced_ui.set_current_task_state(
                title="Task Decomposition",
                details=breakdown_info,
                status="completed",
            )
            time.sleep(2.0)

            # Give user time to see the task tree
            import time
            time.sleep(3.0)  # Allow users to read the task breakdown

            # Step 4: Execute tasks
            stage_statuses["Execution"] = "running"
            self.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                current_stage="Execution",
                tasks=self._dashboard_task_items(decomposition.subtasks),
            )
            self.enhanced_ui.set_current_task_state(
                title="Execution",
                details=f"Running {len(decomposition.subtasks)} tasks",
                status="running",
            )

            results = self._execute_tasks(decomposition.subtasks, goal)
            all_tasks_completed = all(t.status == TaskStatus.COMPLETED for t in decomposition.subtasks)
            stage_statuses["Execution"] = "completed" if all_tasks_completed else "failed"
            self.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                tasks=self._dashboard_task_items(decomposition.subtasks),
            )
            readme_result = self._finalize_project_readme(goal, results) if all_tasks_completed else None

            # Step 5: Assemble results
            stage_statuses["Result Assembly"] = "running"
            self.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                current_stage="Result Assembly",
            )
            self.enhanced_ui.set_current_task_state(
                title="Result Assembly",
                details="Assembling final result",
                status="running",
            )
            with self.tracker.track_task("Result Assembly", {}):
                final_result = self.task_decomposer.assemble_results(
                    decomposition.original_task,
                    decomposition.subtasks
                )
            stage_statuses["Result Assembly"] = "completed"
            self.enhanced_ui.set_task_graph_state(stage_statuses=stage_statuses)

            success = all(t.status == TaskStatus.COMPLETED for t in decomposition.subtasks)
            self.stats["success"] = success
            self.stats["tasks_completed"] = len([t for t in decomposition.subtasks if t.status == TaskStatus.COMPLETED])
            self.stats["tasks_failed"] = len([t for t in decomposition.subtasks if t.status == TaskStatus.FAILED])
            self.stats["end_time"] = datetime.now()

            self._stop_tracking_if_owned()

            # Update main content with final status (don't print new panels)
            if success:
                success_details = f"Goal completed successfully!\n\nCompleted {self.stats['tasks_completed']} tasks"
                if readme_result:
                    if readme_result["success"] and isinstance(readme_result.get("result"), dict):
                        success_details += f"\nREADME: {readme_result['result'].get('file_path')}"
                    elif readme_result.get("error"):
                        success_details += f"\nREADME generation failed: {readme_result['error']}"
                self.enhanced_ui.set_current_task_state(
                    title="Success",
                    details=success_details,
                    status="completed",
                )
            else:
                self.enhanced_ui.set_current_task_state(
                    title="Failed",
                    details=f"Goal execution failed\n\nCompleted: {self.stats['tasks_completed']}, Failed: {self.stats['tasks_failed']}",
                    status="failed",
                )

            return {
                "success": success,
                "goal": goal,
                "semantic_analysis": semantic,
                "decomposition": decomposition,
                "results": results,
                "readme": readme_result,
                "stats": self.stats,
            }

        except Exception as e:
            self.tracker.stop_tracking()
            self.enhanced_ui.set_current_task_state(
                title="Error",
                details=f"Execution failed: {str(e)}",
                status="failed",
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

            fast_result = self._try_simple_code_artifact_fast_path(goal, semantic)
            if fast_result is not None:
                return fast_result

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
            all_tasks_completed = all(t.status == TaskStatus.COMPLETED for t in decomposition.subtasks)
            readme_result = self._finalize_project_readme(goal, results) if all_tasks_completed else None

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
                "readme": readme_result,
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
            items.append({
                "id": task.id,
                "description": task.description,
                "status": status,
                "effort": f"{task.estimated_effort:.1f}u" if task.estimated_effort else "",
            })
        return items

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

            # Update dashboard with current task
            completed_count = len([r for r in results if r.status == TaskStatus.COMPLETED])
            failed_count = len([r for r in results if r.status == TaskStatus.FAILED])

            status_detail = (
                f"{task.description}\n\n"
                f"Completed: {completed_count}\n"
                f"Failed: {failed_count}\n"
                f"Remaining: {len(tasks) - i}"
            )

            self.enhanced_ui.set_task_graph_state(
                tasks=self._dashboard_task_items(tasks, running_task_id=task.id),
                current_task_id=task.id,
            )
            self.enhanced_ui.set_current_task_state(
                title=f"Task {i}/{len(tasks)}",
                details=status_detail,
                status="running",
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
                    self.enhanced_ui.set_task_graph_state(
                        tasks=self._dashboard_task_items(tasks),
                        current_task_id=task.id,
                    )
                    self.enhanced_ui.set_current_task_state(
                        title=f"Task {i}/{len(tasks)}",
                        details=task.description,
                        status="completed",
                    )
                    self.enhanced_ui.log_activity("success", f"✓ Task {i}: {task.description[:50]}... ({result.duration:.1f}s)")
                else:
                    task.mark_failed(result.error or "Unknown error")
                    self.enhanced_ui.set_task_graph_state(
                        tasks=self._dashboard_task_items(tasks),
                        current_task_id=task.id,
                    )
                    self.enhanced_ui.set_current_task_state(
                        title=f"Task {i}/{len(tasks)}",
                        details=result.error or "Unknown error",
                        status="failed",
                    )
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
                self.enhanced_ui.set_task_graph_state(
                    tasks=self._dashboard_task_items(tasks),
                    current_task_id=task.id,
                )
                self.enhanced_ui.set_current_task_state(
                    title=f"Task {i}/{len(tasks)}",
                    details=error_msg,
                    status="failed",
                )

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
- For completed project/code deliveries, use readme_tool after file_writer to create README.md with run instructions
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
            # Parse response
            try:
                plan_data = (
                    llm_response.parsed_json
                    if isinstance(llm_response.parsed_json, dict)
                    else json.loads(llm_response.content)
                )
                tool_calls = plan_data.get("tool_calls", [])
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse LLM response as JSON: {e}")

            if not tool_calls:
                raise ValueError("LLM generated empty tool plan")

            # Execute tools sequentially
            tool_results = []
            last_output = None
            last_code_output = None

            for i, tool_call in enumerate(tool_calls):
                tool_name = tool_call.get("tool_name")
                input_params = dict(tool_call.get("input_params", {}))
                reason_text = tool_call.get("reason", "")
                input_params = self._resolve_chained_inputs(
                    tool_name,
                    input_params,
                    last_output,
                    last_code_output,
                )

                # Update UI to show current tool execution with more details
                if self.enhanced_ui:
                    tool_status = f"Task: {task.description[:80]}\n"
                    tool_status += f"Tool Execution: {i+1}/{len(tool_calls)}\n"
                    tool_status += f"Tool: {tool_name}\n"

                    if tool_name == "code_generator":
                        task_desc = input_params.get('task_description', '')
                        tool_status += f"Action: Generating code\n"
                        tool_status += f"Request: {task_desc[:120]}\n"
                        tool_status += f"Language: {input_params.get('language', 'unknown')}"
                    elif tool_name == "file_writer":
                        file_path = input_params.get('file_path', 'unknown')
                        content_len = len(input_params.get('content', ''))
                        tool_status += f"Action: Writing file\n"
                        tool_status += f"Path: {file_path}\n"
                        tool_status += f"Size: {content_len} characters"
                    elif tool_name == "code_executor":
                        tool_status += f"Action: Executing code\n"
                        tool_status += f"Language: {input_params.get('language', 'unknown')}"
                    else:
                        tool_status += f"Action: {reason_text[:120]}"

                    self.enhanced_ui.set_current_task_state(
                        title=f"Tool {i+1}/{len(tool_calls)}: {tool_name}",
                        details=tool_status,
                        status="running",
                    )

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
                log_params = self._sanitize_tool_params(input_params)
                if tool_name == "code_generator":
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

                # Show result briefly in UI
                if self.enhanced_ui:
                    result_status = f"Tool: {tool_name}\n"
                    if exec_result.success:
                        result_status += "Status: Success\n"
                        if tool_name == "file_writer" and exec_result.output:
                            result_status += "File written successfully"
                        elif tool_name == "code_generator" and exec_result.output:
                            if isinstance(exec_result.output, dict):
                                code_len = len(exec_result.output.get("code", ""))
                                result_status += f"Generated {code_len} characters of code"
                    else:
                        result_status += "Status: Failed\n"
                        if exec_result.error:
                            result_status += f"Error: {exec_result.error.error_message[:160]}"

                    self.enhanced_ui.set_current_task_state(
                        title=f"Tool result: {tool_name}",
                        details=result_status,
                        status="completed" if exec_result.success else "failed",
                    )

                    # Brief pause to show result
                    import time
                    time.sleep(0.5)

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
                if tool_name == "code_generator" and exec_result.success:
                    last_code_output = exec_result.output

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
