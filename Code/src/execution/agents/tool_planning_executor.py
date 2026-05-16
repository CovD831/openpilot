"""Agent for LLM tool planning and tool-call execution."""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from execution.task_models import Task, TaskExecutionContext, TaskExecutionResult, TaskStatus
from core.llm import LLMMessage, LLMRequest
from tools.tool_orchestration_models import ToolSelection


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

            llm_request = LLMRequest(
                messages=[LLMMessage(role="user", content=prompt)],
                response_format="json_object",
            )
            llm_response = self.runtime.llm_client.complete(llm_request)
            tool_calls = self._parse_tool_calls(llm_response)

            tool_results, last_output = self._execute_tool_calls(task, tool_calls)
            all_succeeded = all(item["success"] for item in tool_results)
            output = {
                "task_id": task.id,
                "description": task.description,
                "status": "completed" if all_succeeded else "failed",
                "tool_calls": tool_results,
                "all_tools_succeeded": all_succeeded,
                "final_output": last_output,
            }
            duration = (datetime.now() - start_time).total_seconds()
            error_msg = self._build_tool_error(tool_results)

            result = TaskExecutionResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED if all_succeeded else TaskStatus.FAILED,
                result=output,
                error=error_msg,
                duration=duration,
                metadata={
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
                metadata={
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
- Autopilot will run hard validation and project_improvement_tool after project delivery; only call project_improvement_tool yourself when explicitly asked to analyze improvements
- Provide actual values for all parameters, do not use null or placeholders
- If you need to pass output from one tool to another, generate the content directly in the first tool
"""

    def _parse_tool_calls(self, llm_response: Any) -> list[dict[str, Any]]:
        try:
            plan_data = (
                llm_response.parsed_json
                if isinstance(getattr(llm_response, "parsed_json", None), dict)
                else json.loads(llm_response.content)
            )
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse LLM response as JSON: {exc}") from exc
        tool_calls = plan_data.get("tool_calls", [])
        if not tool_calls:
            raise ValueError("LLM generated empty tool plan")
        return tool_calls

    def _execute_tool_calls(
        self,
        task: Task,
        tool_calls: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], Any]:
        tool_results = []
        last_output = None
        last_code_output = None

        for index, tool_call in enumerate(tool_calls):
            tool_name = tool_call.get("tool_name")
            input_params = dict(tool_call.get("input_params", {}))
            reason_text = tool_call.get("reason", "")
            input_params = self.runtime._resolve_chained_inputs(
                tool_name,
                input_params,
                last_output,
                last_code_output,
            )

            self._show_tool_running(task, tool_name, input_params, reason_text, index, len(tool_calls))
            selection = ToolSelection(
                step_id=f"step_{index + 1}",
                tool_name=tool_name,
                reason=self.runtime._map_reason_to_enum(reason_text),
                confidence=0.9,
                input_params=input_params,
                requires_confirmation=False,
                fallback_tools=[],
                depends_on=[],
                timeout_override=None,
            )
            self._log_tool_start(task, tool_name, input_params)
            exec_result = self.runtime.tool_executor.execute_single(selection, context=None)
            self._show_tool_result(tool_name, exec_result)
            log_output = self._summarize_tool_output(exec_result.output)
            tool_results.append(
                {
                    "tool": tool_name,
                    "params": input_params,
                    "result": exec_result.output,
                    "success": exec_result.success,
                    "error": exec_result.error.error_message if exec_result.error else None,
                }
            )
            self._log_tool_complete(task, tool_name, exec_result, log_output)

            last_output = exec_result.output
            if tool_name == "code_generator" and exec_result.success:
                last_code_output = exec_result.output

        return tool_results, last_output

    def _show_tool_running(
        self,
        task: Task,
        tool_name: str,
        input_params: dict[str, Any],
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
            task_desc = input_params.get("task_description", "")
            tool_status += "Action: Generating code\n"
            tool_status += f"Request: {task_desc[:120]}\n"
            tool_status += f"Language: {input_params.get('language', 'unknown')}"
        elif tool_name == "file_writer":
            file_path = input_params.get("file_path", "unknown")
            content_len = len(input_params.get("content", ""))
            tool_status += "Action: Writing file\n"
            tool_status += f"Path: {file_path}\n"
            tool_status += f"Size: {content_len} characters"
        elif tool_name == "code_executor":
            tool_status += "Action: Executing code\n"
            tool_status += f"Language: {input_params.get('language', 'unknown')}"
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
            if tool_name == "file_writer" and exec_result.output:
                result_status += "File written successfully"
            elif tool_name == "code_generator" and isinstance(exec_result.output, dict):
                result_status += f"Generated {len(exec_result.output.get('code', ''))} characters of code"
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

    def _log_tool_start(self, task: Task, tool_name: str, input_params: dict[str, Any]) -> None:
        log_params = self.runtime._sanitize_tool_params(input_params)
        if tool_name == "code_generator":
            log_params["task_description_length"] = len(log_params.get("task_description", ""))
        self.runtime.logger.log_event(
            "tool_execution_start",
            {
                "task_id": task.id,
                "tool": tool_name,
                "params": log_params,
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

    def _summarize_tool_output(self, output: Any) -> dict[str, Any]:
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
            source_name="execution.agents.tool_planning_executor",
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
