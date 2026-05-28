"""Agent for LLM tool planning and tool-call execution."""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

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
)



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
            goal = context.parent_context.get("goal", "")
            tools_description = self.runtime._format_tools_for_llm(self.runtime.tool_registry.list_all())
            prompt = self._build_tool_plan_prompt(task.description, goal, tools_description)

            self.runtime.logger.log_event(
                "llm_tool_planning",
                {"task_id": task.id, "task_description": task.description},
                session_id=self._session_id(),
                turn_id=1,
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
            error_msg = loop_result.error_message or self._build_tool_error(tool_results)

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
                        details={"tool_loop": loop_result.loop_metadata.to_json_dict()},
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
            result = TaskExecutionResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error=str(exc),
                duration=duration,
                result_metadata=TaskResultMetadata(
                    task_id=task.id,
                    status=ResultStatus.FAIL,
                    failure=FailureMetadata(error_type=type(exc).__name__, error_message=str(exc)),
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
                },
                session_id=self._session_id(),
                turn_id=1,
            )
            self._log(
                "task_executor_failed",
                output_summary={"task_id": task.id},
                success=False,
                error=str(exc),
                duration_ms=int(duration * 1000),
            )
            return result

    def _build_tool_plan_prompt(self, task_description: str, goal: str, tools_description: str) -> str:
        return f"""You are an AI assistant that selects and sequences tools to accomplish tasks.

Task: {task_description}
Overall Goal: {goal}

Available Tools:
{tools_description}

Generate a JSON plan with decision_needs. The runtime ToolRouter is the only component
allowed to map needs to concrete tools using budget, risk, and permission checks.

Output ONLY valid JSON in this format:
{{
  "decision_needs": [
    {{
      "need_type": "file_read | project_structure | web_search | command_check | file_write | code_generation | code_execution | readme_generation",
      "question": "what decision this information will unlock",
      "target_path": "optional path",
      "candidate_paths": ["optional paths"],
      "query": "optional search query",
      "command": "optional command",
      "risk_level": "low | medium | high | forbidden",
      "attributes": {{"optional": "tool-specific inputs"}}
    }}
  ]
}}

Important:
- For code generation tasks, emit a code_generation need, then a file_write need to save the generated output
- code_generator only supports executable code languages: python, shell, bash. Never use language "text"
- For design, outline, planning, or prose-only tasks, either return planning metadata through an appropriate text/documentation tool or write Markdown/text with file_writer/readme_tool
- For completed project/code deliveries, emit a readme_generation need after file_write to create README.md with run instructions
- Autopilot will run hard validation and autonomous-iteration improvement analysis after project delivery
- Provide actual values for all parameters, do not use null or placeholders
- If you need to pass output from one tool to another, generate the content directly in the first tool
- For command_executor, input_metadata.mode must be one of: dry_run, interactive, automatic
- For project commands, use mode "automatic" and do not use source/activate/cd/export; OpenPilot injects the target cwd and virtual environment from metadata
"""

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
            raise ValueError("LLM generated empty decision_needs plan")
        return tool_requests

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
        for raw_need in raw_needs:
            if not isinstance(raw_need, dict):
                continue
            need = DecisionNeedMetadata.model_validate(raw_need)
            selections = router.route(state, need)
            for selection in selections:
                tool_requests.append(
                    {
                        "tool_name": selection.tool_name,
                        "reason": need.question,
                        "input_metadata": selection.input_metadata.to_params(),
                    }
                )
        return tool_requests

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
            error_parts.append(f"\n  - {failed['tool']}: {failed['error']}")
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
        )
