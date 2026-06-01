"""Agent for LLM tool planning and tool-call execution."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from autonomous_iteration.runtime_controller import ToolRouter
from autonomous_iteration.task_models import Task, TaskExecutionContext, TaskExecutionResult, TaskStatus
from core.tool_event_loop import ToolEventLoopRunner
from metadata import (
    DecisionNeedMetadata,
    FailureMetadata,
    ResultStatus,
    RuntimeStateMetadata,
    TaskResultMetadata,
    TextArtifactMetadata,
    ToolInputMetadata,
)


NEED_ATTRIBUTE_FIELDS = {
    "code",
    "content",
    "text",
    "language",
    "cwd",
    "env",
    "timeout",
    "mode",
    "project_path",
    "file_path",
    "file_paths",
    "directory_path",
    "pattern",
    "max_files",
    "recursive",
    "max_total_chars",
    "read_mode",
    "encoding",
    "create_dirs",
    "overwrite",
    "run_command",
    "test_command",
    "task_description",
    "operation_kind",
    "target_scope",
    "symbol_name",
    "symbol_type",
    "insertion_hint",
    "patch_mode",
    "generated_unit",
    "replacement_text",
    "patch",
    "line_start",
    "line_end",
}

DEFAULTABLE_DECISION_NEED_FIELDS = {
    "phase",
    "candidate_paths",
    "attributes",
    "cost_hint",
    "risk_level",
    "target_path",
    "operation_kind",
    "target_scope",
    "symbol_name",
    "symbol_type",
    "insertion_hint",
    "patch_mode",
    "query",
    "command",
    "decision_to_unlock",
    "expected_state_change",
}

ACTIONABLE_FALLBACK_TERMS = {
    "add",
    "build",
    "check",
    "code",
    "create",
    "develop",
    "document",
    "fix",
    "generate",
    "implement",
    "integrate",
    "modify",
    "readme",
    "refactor",
    "repair",
    "run",
    "test",
    "update",
    "validate",
    "verify",
    "write",
    "创建",
    "修复",
    "实现",
    "开发",
    "生成",
    "编写",
    "验证",
}

MUTATING_OR_EXECUTING_NEED_TYPES = {
    "bug_fix",
    "bug_fix_tool",
    "code_execution",
    "code_file_create",
    "code_generation",
    "code_patch",
    "code_symbol_modify",
    "code_unit_generate",
    "command_check",
    "directory_generate",
    "documentation",
    "file_write",
    "fix_bug",
    "generate_code",
    "generate_code_unit",
    "readme",
    "readme_generation",
    "repair",
    "smoke_test",
    "test",
    "verify_command",
    "write_file",
}


class DecisionNeedValidationError(ValueError):
    """Raised when an LLM decision need cannot be normalized into metadata."""

    def __init__(self, message: str, details: dict[str, Any]) -> None:
        super().__init__(message)
        self.details = details


class ToolPlanningTaskExecutor:
    """Execute one task by asking the LLM for a tool plan and running it."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def execute_task(self, task: Task, context: TaskExecutionContext) -> TaskExecutionResult:
        """Execute a single task by generating and executing tool calls."""
        start_time = datetime.now()
        self._log(
            "task_executor_started",
            input_summary={"task_id": task.id, "description": task.description},
            success=None,
        )

        try:
            self._active_task_id = task.id
            self._active_task_description = task.description
            goal = context.parent_context.get("goal", "")
            self._active_goal = goal
            self._active_context = context
            tools_description = self.runtime._format_tools_for_llm(self.runtime.tool_registry.list_all())
            prompt = self._build_tool_plan_prompt(task.description, goal, tools_description, context)

            self.runtime.logger.log_event(
                "llm_tool_planning",
                {"task_id": task.id, "task_description": task.description},
                session_id=self._session_id(),
                turn_id=1,
                level="INFO",
            )
            self._log(
                "llm_tool_planning_started",
                input_summary={"task_id": task.id, "goal": goal},
                success=None,
            )

            loop_result = ToolEventLoopRunner(self).run(task, prompt)
            tool_results = loop_result.tool_results
            last_output = loop_result.last_output
            all_succeeded = loop_result.success
            output = {
                "task_id": task.id,
                "description": task.description,
                "status": "completed" if all_succeeded else "failed",
                "tool_results": tool_results,
                "tool_loop": loop_result.loop_metadata.to_json_dict(),
                "all_tools_succeeded": all_succeeded,
                "final_output": last_output,
            }
            duration = (datetime.now() - start_time).total_seconds()
            tool_error_msg = self._build_tool_error(tool_results)
            error_msg = None if all_succeeded else (tool_error_msg or loop_result.error_message)
            failure_details = {"tool_loop": loop_result.loop_metadata.to_json_dict()}
            if loop_result.loop_metadata.final_error:
                failure_details.update(loop_result.loop_metadata.final_error.details or {})

            result = TaskExecutionResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED if all_succeeded else TaskStatus.FAILED,
                result_metadata=TaskResultMetadata(
                    task_id=task.id,
                    status=ResultStatus.SUCCESS if all_succeeded else ResultStatus.FAIL,
                    result=TextArtifactMetadata(content="completed", attributes=output) if all_succeeded else None,
                    failure=FailureMetadata(
                        error_type=loop_result.loop_metadata.final_error.error_type
                        if loop_result.loop_metadata.final_error
                        else "ToolExecutionFailed",
                        error_message=error_msg or "Tool execution failed",
                        details=failure_details,
                    )
                    if not all_succeeded
                    else None,
                    duration=duration,
                ),
                error=error_msg,
                duration=duration,
                attributes={
                    "start_time": start_time.isoformat(),
                    "end_time": datetime.now().isoformat(),
                    "tool_count": len(tool_results),
                },
            )
            self._log(
                "task_executor_completed",
                output_summary={
                    "task_id": task.id,
                    "tool_count": len(tool_results),
                    "success": all_succeeded,
                },
                success=all_succeeded,
                duration_ms=int(duration * 1000),
            )
            return result

        except Exception as exc:
            duration = (datetime.now() - start_time).total_seconds()
            failure_details = getattr(exc, "details", {}) if isinstance(getattr(exc, "details", {}), dict) else {}
            exc_context = getattr(exc, "context", None)
            if isinstance(exc_context, dict):
                failure_details.update({key: value for key, value in exc_context.items() if value is not None})
            failure_details.setdefault("task_id", task.id)
            failure_details.setdefault("task_description", task.description)
            failure_details.setdefault("failed_tool", "tool_planning_executor")
            failure_details.setdefault("failure_stage", "Tool Planning")
            result = TaskExecutionResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error=str(exc),
                duration=duration,
                result_metadata=TaskResultMetadata(
                    task_id=task.id,
                    status=ResultStatus.FAIL,
                    failure=FailureMetadata(
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                        details=failure_details,
                    ),
                    duration=duration,
                ),
                attributes={
                    "start_time": start_time.isoformat(),
                    "end_time": datetime.now().isoformat(),
                },
            )
            self.runtime.logger.log_event(
                "task_failed",
                {
                    "task_id": task.id,
                    "description": task.description,
                    "error": str(exc),
                    "duration": duration,
                    "details": failure_details,
                },
                session_id=self._session_id(),
                turn_id=1,
                level="ERROR",
            )
            self._log(
                "task_executor_failed",
                output_summary={"task_id": task.id},
                success=False,
                error=str(exc),
                duration_ms=int(duration * 1000),
            )
            return result

    def _build_tool_plan_prompt(
        self,
        task_description: str,
        goal: str,
        tools_description: str,
        context: TaskExecutionContext | None = None,
    ) -> str:
        history = self._execution_history_summary(context)
        return f"""You are an AI assistant that selects and sequences tools to accomplish tasks.

Task: {task_description}
Overall Goal: {goal}
Previous Task Results:
{history}

Available Tools:
{tools_description}

Generate a JSON plan with decision_needs. The runtime ToolRouter is the only component
allowed to map needs to concrete tools using budget, risk, and permission checks.

Output ONLY valid JSON in this format:
{{
  "decision_needs": [
    {{
      "need_type": "code_file_create",
      "question": "create the main project file",
      "target_path": "/absolute/path/to/file.py",
      "operation_kind": "create_file",
      "attributes": {{"language": "python"}}
    }}
  ]
}}

Allowed need_type values:
file_read, project_structure, web_search, command_check, file_write, code_file_create,
directory_generate, code_unit_generate, code_symbol_modify, code_patch, code_generation,
code_execution, readme_generation.

Optional fields may include: target_path, operation_kind, target_scope, symbol_name,
symbol_type, insertion_hint, patch_mode, candidate_paths, query, command, risk_level,
attributes. Omit unknown or unavailable optional fields. Do not emit null.

Important:
- Previous task outputs are provided above in Previous Task Results. Use that shared history directly.
- Never invent or read intermediate files such as subtask_0.md, subtask_1.md, requirements.md, or plan.md unless they appear in previous tool outputs or the user explicitly requested them.
- If previous task results are absent or failed, infer sensible defaults from the original goal instead of reading a made-up plan file.
- For project creation, use directory_generate/code_file_create/file_write directly and create the needed files in the target directory.
- Always distinguish create_file, add_symbol, modify_symbol, and code_patch before selecting needs.
- For new code files or generated project files, emit code_file_create or directory_generate, then file_write with operation_kind create_file.
- For adding a function/class to an existing file, emit file_read, then code_unit_generate with operation_kind add_symbol, then file_write with operation_kind add_symbol so ToolRouter uses file_patch_writer.
- For modifying an existing function/class, emit file_read, then code_symbol_modify or code_patch with operation_kind modify_symbol, then file_write with operation_kind modify_symbol so ToolRouter uses file_patch_writer.
- Do not plan code_generator + file_writer for edits to existing functions/classes.
- code_generator only supports executable code languages: python, shell, bash. Never use language "text"
- For design, outline, planning, or prose-only tasks, either return planning metadata through an appropriate text/documentation tool or write Markdown/text with file_writer/readme_tool
- For completed project/code deliveries, emit a readme_generation need after file_write to create README.md with run instructions
- Autopilot will run hard validation and autonomous-iteration improvement analysis after project delivery
- Provide actual values for all parameters, do not use null or placeholders
- If you need to pass output from one tool to another, generate the content directly in the first tool
- For command_executor, input_metadata.mode must be one of: dry_run, interactive, automatic
- For project commands, use mode "automatic" and do not use source/activate/cd/export; OpenPilot injects the target cwd and virtual environment from metadata
"""

    def _execution_history_summary(self, context: TaskExecutionContext | None) -> str:
        if context is None:
            return "No previous task results."
        history = context.execution_history or context.shared_state.get("previous_task_results") or []
        if not history:
            return "No previous task results."
        compact: list[dict[str, Any]] = []
        for item in history[-5:]:
            if not isinstance(item, dict):
                compact.append({"summary": str(item)[:500]})
                continue
            compact.append(
                {
                    "task_id": item.get("task_id"),
                    "description": item.get("description"),
                    "status": item.get("status"),
                    "error": item.get("error"),
                    "result_summary": str(item.get("result_summary") or "")[:500],
                }
            )
        return json.dumps(compact, ensure_ascii=False, indent=2)

    def _parse_decision_needs(self, llm_response: Any) -> list[dict[str, Any]]:
        try:
            plan_data = (
                llm_response.parsed_json
                if isinstance(getattr(llm_response, "parsed_json", None), dict)
                else json.loads(llm_response.content)
            )
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse LLM response as JSON: {exc}") from exc
        tool_requests = self._route_decision_needs(plan_data)
        if not tool_requests:
            fallback_requests = self._fallback_tool_requests(plan_data=plan_data)
            if fallback_requests:
                return fallback_requests
            self._log(
                "decision_need_empty_plan",
                input_summary={
                    "task_id": getattr(self, "_active_task_id", "unknown"),
                    "decision_need_count": len(plan_data.get("decision_needs", [])) if isinstance(plan_data, dict) else 0,
                },
                success=False,
                error="LLM generated empty decision_needs plan",
                level="ERROR",
            )
            raise ValueError("LLM generated empty decision_needs plan")
        return tool_requests

    def _fallback_tool_requests(
        self,
        *,
        plan_data: dict[str, Any] | None = None,
        reason: str = "",
    ) -> list[dict[str, Any]]:
        fallback_plan = self._fallback_decision_plan(plan_data or {"decision_needs": []})
        if fallback_plan is None:
            return []
        fallback_requests = self._route_decision_needs(fallback_plan)
        if not fallback_requests:
            return []
        self._log(
            "decision_need_fallback_plan",
            input_summary={
                "task_id": getattr(self, "_active_task_id", "unknown"),
                "decision_need_count": len((plan_data or {}).get("decision_needs", [])),
                "reason": reason,
            },
            output_summary={
                "fallback_need_count": len(fallback_plan.get("decision_needs", [])),
                "tool_request_count": len(fallback_requests),
            },
            success=True,
            level="WARNING",
        )
        return fallback_requests

    def _fallback_decision_plan(self, plan_data: dict[str, Any]) -> dict[str, Any] | None:
        """Build a conservative tool plan when the LLM plan is actionable but unroutable."""
        if not isinstance(plan_data, dict) or not self._should_generate_fallback_plan(plan_data):
            return None

        task_description = str(getattr(self, "_active_task_description", "") or "").strip()
        goal = str(getattr(self, "_active_goal", "") or "").strip()
        project_path = self._infer_project_path(task_description, goal)
        target_file = self._infer_target_file(task_description, goal, project_path)
        needs: list[dict[str, Any]] = []

        if self._looks_like_validation_task(task_description):
            if project_path is None:
                return None
            command = f"python -m compileall {project_path}"
            needs.append(
                {
                    "need_type": "command_check",
                    "question": f"Validate Python files under {project_path}",
                    "command": command,
                    "attributes": {
                        "mode": "automatic",
                        "test_command": command,
                    },
                }
            )
            return {"decision_needs": needs, "goal": goal}

        if self._looks_like_documentation_only_task(task_description):
            readme_project = project_path or (target_file.parent if target_file else None)
            if readme_project:
                needs.append(
                    {
                        "need_type": "readme_generation",
                        "question": f"Generate documentation for: {task_description}",
                        "target_path": str(readme_project),
                        "attributes": {
                            "project_path": str(readme_project),
                            "goal": goal,
                        },
                    }
                )
                return {"decision_needs": needs, "goal": goal}

        if target_file is None:
            return None

        operation_kind = "file_replace" if target_file.exists() else "create_file"
        prompt_context = self._fallback_prompt_context(task_description, goal, target_file, project_path, operation_kind)
        needs.append(
            {
                "need_type": "code_generation",
                "question": f"Generate implementation for: {task_description}",
                "operation_kind": operation_kind,
                "attributes": {
                    "task_description": self._fallback_code_task_description(task_description, target_file, operation_kind),
                    "language": "python",
                    "operation_kind": operation_kind,
                    "prompt_context": prompt_context,
                },
            }
        )
        needs.append(
            {
                "need_type": "file_write",
                "question": f"Write generated implementation to {target_file}",
                "target_path": str(target_file),
                "operation_kind": operation_kind,
                "attributes": {
                    "operation_kind": operation_kind,
                    "encoding": "utf-8",
                    "create_dirs": True,
                },
            }
        )
        validation_root = project_path or target_file.parent
        needs.append(
            {
                "need_type": "command_check",
                "question": f"Validate generated Python files under {validation_root}",
                "command": f"python -m compileall {validation_root}",
                "attributes": {
                    "mode": "automatic",
                    "test_command": f"python -m compileall {validation_root}",
                },
            }
        )
        return {"decision_needs": needs, "goal": goal}

    def _should_generate_fallback_plan(self, plan_data: dict[str, Any]) -> bool:
        task_description = str(getattr(self, "_active_task_description", "") or "")
        if not self._looks_actionable(task_description):
            return False

        raw_needs = plan_data.get("decision_needs", [])
        if not raw_needs:
            return self._infer_target_file(task_description, str(getattr(self, "_active_goal", "") or ""), None) is not None

        actionable_need_seen = False
        for raw_need in raw_needs:
            if not isinstance(raw_need, dict):
                continue
            need_type = str(raw_need.get("need_type") or "").lower().replace("-", "_")
            if need_type in MUTATING_OR_EXECUTING_NEED_TYPES:
                actionable_need_seen = True
                continue
            if need_type not in {
                "file_read",
                "inspect_file",
                "multi_file_read",
                "project_structure",
                "read_directory",
                "read_file",
                "reference_search",
                "research",
                "web_search",
            }:
                actionable_need_seen = True
        return actionable_need_seen

    def _looks_actionable(self, task_description: str) -> bool:
        lowered = task_description.lower()
        return any(term in lowered or term in task_description for term in ACTIONABLE_FALLBACK_TERMS)

    def _looks_like_documentation_task(self, task_description: str) -> bool:
        lowered = task_description.lower()
        return any(term in lowered for term in ("readme", "documentation", "docs")) or any(
            term in task_description for term in ("文档", "说明")
        )

    def _looks_like_documentation_only_task(self, task_description: str) -> bool:
        lowered = task_description.lower()
        implementation_terms = (
            "build",
            "code",
            "create app",
            "create script",
            "develop",
            "implement",
            "write code",
            "write script",
        )
        chinese_implementation_terms = ("创建程序", "创建脚本", "实现", "开发", "编写程序", "编写脚本")
        return self._looks_like_documentation_task(task_description) and not (
            any(term in lowered for term in implementation_terms)
            or any(term in task_description for term in chinese_implementation_terms)
        )

    def _looks_like_validation_task(self, task_description: str) -> bool:
        lowered = task_description.lower().lstrip()
        return lowered.startswith(("check", "test", "validate", "verify")) or task_description.lstrip().startswith(
            ("检查", "测试", "验证")
        )

    def _fallback_code_task_description(self, task_description: str, target_file: Path, operation_kind: str) -> str:
        if operation_kind == "file_replace" and target_file.exists():
            return (
                f"Produce full replacement source for {target_file}. "
                f"Preserve useful existing behavior and implement this task: {task_description}"
            )
        return f"Produce complete source for {target_file}. Implement this task: {task_description}"

    def _fallback_prompt_context(
        self,
        task_description: str,
        goal: str,
        target_file: Path,
        project_path: Path | None,
        operation_kind: str,
    ) -> dict[str, Any]:
        existing_content = ""
        if target_file.exists() and target_file.is_file():
            try:
                existing_content = target_file.read_text(encoding="utf-8")[:12000]
            except OSError:
                existing_content = ""
        return {
            "fallback_planning": True,
            "operation_kind": operation_kind,
            "target_file": str(target_file),
            "project_path": str(project_path or target_file.parent),
            "goal": goal,
            "task_description": task_description,
            "existing_file_content": existing_content,
            "quality_rubric": [
                "Keep the generated file syntactically valid and runnable.",
                "Preserve existing useful behavior when replacing an existing file.",
                "Use local placeholders or graceful degradation for missing external credentials.",
            ],
        }

    def _infer_project_path(self, task_description: str, goal: str) -> Path | None:
        for path in self._extract_paths(f"{task_description}\n{goal}"):
            candidate = path.parent if path.suffix else path
            if candidate.exists() or path.is_absolute():
                return candidate.expanduser()

        context = getattr(self, "_active_context", None)
        if context is not None:
            for container in (getattr(context, "parent_context", {}), getattr(context, "shared_state", {})):
                if isinstance(container, dict):
                    for key in ("project_path", "cwd", "target_dir", "output_dir"):
                        raw = container.get(key)
                        if raw:
                            return Path(str(raw)).expanduser()

        environments = getattr(self.runtime, "_project_environments", {}) or {}
        for raw_project in environments:
            if raw_project:
                return Path(str(raw_project)).expanduser()
        return None

    def _infer_target_file(self, task_description: str, goal: str, project_path: Path | None) -> Path | None:
        text = f"{task_description}\n{goal}"
        for path in self._extract_paths(text):
            if path.suffix:
                return path.expanduser()

        project_path = project_path or self._infer_project_path(task_description, goal)
        if project_path is None:
            return None

        hinted_name = self._filename_hint(task_description)
        if hinted_name:
            hinted_path = Path(hinted_name)
            return hinted_path if hinted_path.is_absolute() else project_path / hinted_path

        if self._looks_like_documentation_task(task_description):
            return project_path / "README.md"

        python_files = self._candidate_python_files(project_path)
        if python_files:
            return max(python_files, key=lambda path: self._score_python_file(path, task_description, goal, project_path))
        return project_path / "main.py"

    def _extract_paths(self, text: str) -> list[Path]:
        paths: list[Path] = []
        for quoted in re.findall(r"['\"](/[^'\"]+)['\"]", text):
            paths.append(Path(quoted))
        for raw in re.findall(r"(?<![\w.-])/(?:[^\s'\"<>|]+/?)+", text):
            cleaned = raw.rstrip(".,;:，。；：)")
            path = Path(cleaned)
            if path not in paths:
                paths.append(path)
        return paths

    def _filename_hint(self, task_description: str) -> str | None:
        match = re.search(r"([\w./-]+\.(?:py|md|ya?ml|json|toml|txt|sh))", task_description)
        return match.group(1) if match else None

    def _candidate_python_files(self, project_path: Path) -> list[Path]:
        if not project_path.exists() or not project_path.is_dir():
            return []
        excluded_parts = {".git", ".venv", "__pycache__", "node_modules", "site-packages"}
        return [
            path
            for path in project_path.rglob("*.py")
            if path.is_file() and not any(part in excluded_parts for part in path.parts)
        ]

    def _score_python_file(self, path: Path, task_description: str, goal: str, project_path: Path) -> int:
        lowered = f"{task_description}\n{goal}".lower()
        path_text = path.as_posix().lower()
        name = path.name.lower()
        stem = path.stem.lower()
        score = 0
        if name == "__init__.py":
            score -= 20
        if name in lowered:
            score += 30
        if stem and stem in lowered:
            score += 18
        if any(term in lowered for term in ("core", "logic", "module", "class")) and stem in {"core", "assistant", "app"}:
            score += 14
        if any(term in lowered for term in ("main", "entry", "cli", "loop", "command")) and stem in {
            "main",
            "cli",
            "app",
            "assistant",
        }:
            score += 10
        if "assistant" in lowered and "assistant" in path_text:
            score += 8
        try:
            depth = len(path.relative_to(project_path).parts)
        except ValueError:
            depth = len(path.parts)
        score -= depth
        return score

    def _route_decision_needs(self, plan_data: dict[str, Any]) -> list[dict[str, Any]]:
        raw_needs = plan_data.get("decision_needs", [])
        if not raw_needs:
            return []
        controller = getattr(self.runtime, "runtime_controller", None)
        router = getattr(controller, "router", None)
        state = getattr(controller, "state", None)
        if router is None:
            router = ToolRouter(getattr(self.runtime, "tool_registry", None))
        if state is None:
            state = RuntimeStateMetadata(goal=str(plan_data.get("goal") or "tool planning"))
            if controller is not None:
                controller.state = state

        tool_requests: list[dict[str, Any]] = []
        for index, raw_need in enumerate(raw_needs):
            if not isinstance(raw_need, dict):
                continue
            normalized_need, normalized_fields = self._normalize_raw_decision_need(raw_need)
            try:
                need = DecisionNeedMetadata.model_validate(normalized_need)
            except ValidationError as exc:
                raise self._decision_need_validation_failure(raw_need, normalized_need, index, exc) from exc
            if normalized_fields:
                self._log(
                    "decision_need_normalized",
                    input_summary={
                        "task_id": getattr(self, "_active_task_id", "unknown"),
                        "need_index": index,
                        "need_type": need.need_type,
                    },
                    output_summary={"normalized_fields": normalized_fields},
                    success=True,
                    level="DEBUG",
                )
            selections = router.route(state, need)
            for selection in selections:
                tool_requests.append(
                    {
                        "tool_name": selection.tool_name,
                        "reason": need.question,
                        "input_metadata": selection.input_metadata.to_params(),
                        "timeout_override": selection.timeout_override,
                    }
                )
        return tool_requests

    def _normalize_raw_decision_need(self, raw_need: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        normalized = dict(raw_need)
        normalized_fields: list[str] = []
        for key in list(normalized):
            if normalized[key] is None and key in DEFAULTABLE_DECISION_NEED_FIELDS:
                normalized.pop(key)
                normalized_fields.append(f"{key}:null_to_default")

        attributes = normalized.get("attributes")
        if not isinstance(attributes, dict):
            attributes = {}
        else:
            attributes = dict(attributes)

        allowed_fields = set(DecisionNeedMetadata.model_fields)
        tool_input_fields = set(ToolInputMetadata.model_fields)
        moved_fields: list[str] = []
        for key in list(normalized):
            if key in allowed_fields:
                continue
            if key in NEED_ATTRIBUTE_FIELDS or key in tool_input_fields:
                attributes.setdefault(key, normalized.pop(key))
                moved_fields.append(key)
        if moved_fields or attributes:
            normalized["attributes"] = attributes
        normalized_fields.extend(f"{key}:moved_to_attributes" for key in moved_fields)
        if not str(normalized.get("question") or "").strip():
            normalized["question"] = self._default_need_question(normalized)
            normalized_fields.append("question:defaulted")
        return normalized, normalized_fields

    def _default_need_question(self, normalized_need: dict[str, Any]) -> str:
        need_type = str(normalized_need.get("need_type") or "tool_need")
        target = (
            normalized_need.get("target_path")
            or normalized_need.get("query")
            or normalized_need.get("command")
            or ""
        )
        if target:
            return f"{need_type}: {target}"
        return f"Handle {need_type}"

    def _decision_need_validation_failure(
        self,
        raw_need: dict[str, Any],
        normalized_need: dict[str, Any],
        index: int,
        exc: ValidationError,
    ) -> DecisionNeedValidationError:
        invalid_fields = [
            ".".join(str(part) for part in error.get("loc", ()))
            for error in exc.errors()
            if error.get("loc")
        ]
        raw_summary = self._safe_need_summary(raw_need)
        details = {
            "task_id": getattr(self, "_active_task_id", "unknown"),
            "need_index": index,
            "invalid_fields": invalid_fields,
            "raw_need_summary": raw_summary,
            "normalized_keys": sorted(str(key) for key in normalized_need),
            "failed_tool": "tool_planning_executor",
            "failure_stage": "Tool Planning",
        }
        self._log(
            "decision_need_schema_error",
            input_summary={"task_id": details["task_id"], "need_index": index, "raw_need": raw_summary},
            output_summary={"invalid_fields": invalid_fields},
            success=False,
            error=str(exc),
            level="ERROR",
        )
        return DecisionNeedValidationError(
            f"Decision need schema validation failed at index {index}: {str(exc)}",
            details,
        )

    def _safe_need_summary(self, raw_need: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for key, value in raw_need.items():
            if isinstance(value, str) and len(value) > 200:
                summary[key] = f"{value[:200]}..."
            elif isinstance(value, (dict, list)):
                summary[key] = f"<{type(value).__name__}:{len(value)}>"
            else:
                summary[key] = value
        return summary

    def _show_tool_running(
        self,
        task: Task,
        tool_name: str,
        input_payload: dict[str, Any],
        reason_text: str,
        index: int,
        total: int,
    ) -> None:
        if not self.runtime.enhanced_ui:
            return
        tool_status = f"Task: {task.description[:80]}\n"
        tool_status += f"Tool Execution: {index + 1}/{total}\n"
        tool_status += f"Tool: {tool_name}\n"
        if tool_name == "code_generator":
            task_desc = input_payload.get("task_description", "")
            tool_status += "Action: Generating code\n"
            tool_status += f"Request: {task_desc[:120]}\n"
            tool_status += f"Language: {input_payload.get('language', 'unknown')}"
        elif tool_name == "file_writer":
            file_path = input_payload.get("file_path", "unknown")
            content_len = len(input_payload.get("content", ""))
            tool_status += "Action: Writing file\n"
            tool_status += f"Path: {file_path}\n"
            tool_status += f"Size: {content_len} characters"
        elif tool_name == "code_executor":
            tool_status += "Action: Executing code\n"
            tool_status += f"Language: {input_payload.get('language', 'unknown')}"
        else:
            tool_status += f"Action: {reason_text[:120]}"
        self.runtime.enhanced_ui.set_current_task_state(
            title=f"Tool {index + 1}/{total}: {tool_name}",
            details=tool_status,
            status="running",
        )

    def _show_tool_result(self, tool_name: str, exec_result: Any) -> None:
        if not self.runtime.enhanced_ui:
            return
        result_status = f"Tool: {tool_name}\n"
        if exec_result.success:
            result_status += "Status: Success\n"
            output = exec_result.output_metadata.result if exec_result.output_metadata else None
            if tool_name == "file_writer" and output:
                result_status += "File written successfully"
            elif tool_name == "code_generator" and isinstance(output, dict):
                result_status += f"Generated {len(output.get('code', ''))} characters of code"
        else:
            result_status += "Status: Failed\n"
            if exec_result.error:
                result_status += f"Error: {exec_result.error.error_message[:160]}"
        self.runtime.enhanced_ui.set_current_task_state(
            title=f"Tool result: {tool_name}",
            details=result_status,
            status="completed" if exec_result.success else "failed",
        )
        time.sleep(0.5)

    def _log_tool_start(self, task: Task, tool_name: str, input_payload: dict[str, Any]) -> None:
        log_params = self.runtime._sanitize_tool_metadata(input_payload)
        if tool_name == "code_generator":
            log_params["task_description_length"] = len(log_params.get("task_description", ""))
        self.runtime.logger.log_event(
            "tool_execution_start",
            {
                "task_id": task.id,
                "tool": tool_name,
                "input_metadata_summary": log_params,
            },
            session_id=self._session_id(),
            turn_id=1,
            level="INFO",
        )

    def _log_tool_complete(self, task: Task, tool_name: str, exec_result: Any, log_output: dict[str, Any]) -> None:
        self.runtime.logger.log_event(
            "tool_executed",
            {
                "task_id": task.id,
                "tool": tool_name,
                "success": exec_result.success,
                "error": exec_result.error.error_message if exec_result.error else None,
                "output": log_output,
                "execution_time_ms": exec_result.execution_time_ms if hasattr(exec_result, "execution_time_ms") else None,
            },
            session_id=self._session_id(),
            turn_id=1,
            level="INFO" if exec_result.success else "ERROR",
        )

    def _summarize_metadata_output(self, output: Any) -> dict[str, Any]:
        if not output:
            return {}
        if not isinstance(output, dict):
            return {"output_type": type(output).__name__}
        log_output = output.copy()
        if "code" in log_output:
            log_output["code_length"] = len(log_output["code"])
            log_output["code_preview"] = log_output["code"][:200]
        if "content" in log_output:
            log_output["content_length"] = len(log_output["content"])
        return log_output

    def _build_tool_error(self, tool_results: list[dict[str, Any]]) -> str | None:
        failed_tools = [item for item in tool_results if not item["success"]]
        if not failed_tools:
            return None
        error_parts = [f"{len(failed_tools)} tool(s) failed:"]
        for failed in failed_tools:
            input_metadata = failed.get("input_metadata") if isinstance(failed.get("input_metadata"), dict) else {}
            failure_bits = [
                f"tool={failed.get('tool') or 'unknown'}",
                f"call={failed.get('call_id') or 'unknown'}",
            ]
            if input_metadata.get("file_path"):
                failure_bits.append(f"file_path={input_metadata['file_path']}")
            if input_metadata.get("directory_path"):
                failure_bits.append(f"directory_path={input_metadata['directory_path']}")
            if failed.get("suggested_recovery"):
                failure_bits.append(f"recovery={failed['suggested_recovery']}")
            error_parts.append(f"\n  - {'; '.join(failure_bits)}; error={failed.get('error')}")
        return "".join(error_parts)

    def _session_id(self) -> str:
        return getattr(self.runtime, "session_id", None) or "unknown"

    def _log(
        self,
        event_type: str,
        *,
        success: bool | None = None,
        duration_ms: int | None = None,
        input_summary: Any | None = None,
        output_summary: Any | None = None,
        error: str | None = None,
        level: str | None = None,
    ) -> None:
        logger = getattr(self.runtime, "logger", None)
        if not logger or not hasattr(logger, "log_structured_event"):
            return
        logger.log_structured_event(
            source_type="agent",
            source_name="autonomous_iteration.agents.tool_planning_executor",
            phase="task_execution",
            event_type=event_type,
            session_id=self._session_id(),
            turn_id=1,
            success=success,
            duration_ms=duration_ms,
            input_summary=input_summary,
            output_summary=output_summary,
            error=error,
            level=level,
        )
