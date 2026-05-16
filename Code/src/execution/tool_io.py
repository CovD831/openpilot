"""Tool input/output helpers for execution flows."""

from __future__ import annotations

from typing import Any

from tools.tool_orchestration_models import ToolSelection


class ExecutionToolIO:
    """Pure helpers for tool prompt formatting, chaining, and summaries."""

    def __init__(self, logger: Any | None = None, session_id_getter: Any | None = None) -> None:
        self.logger = logger
        self.session_id_getter = session_id_getter

    def sanitize_tool_params(self, params: dict[str, Any]) -> dict[str, Any]:
        sanitized: dict[str, Any] = {}
        for key, value in params.items():
            if key.startswith("_"):
                continue
            if key in {"content", "code", "task_description"} and isinstance(value, str):
                sanitized[key] = f"<{len(value)} chars>"
                sanitized[f"{key}_length"] = len(value)
                sanitized[f"{key}_preview"] = value[:200]
            else:
                sanitized[key] = value
        self._log_function("sanitize_tool_params", {"keys": list(params)}, {"keys": list(sanitized)})
        return sanitized

    def summarize_tool_output(self, output: Any) -> dict[str, Any]:
        if hasattr(output, "model_dump"):
            return self.summarize_tool_output(output.model_dump())
        if not isinstance(output, dict):
            summary = {"output_type": type(output).__name__} if output is not None else {}
            self._log_function("summarize_tool_output", {"output_type": type(output).__name__}, summary)
            return summary

        summary = {
            key: self.json_safe_summary(value)
            for key, value in output.items()
        }
        if "code" in summary and isinstance(summary["code"], str):
            summary["code_length"] = len(summary["code"])
            summary["code_preview"] = summary["code"][:200]
            summary.pop("code", None)
        if "content" in summary and isinstance(summary["content"], str):
            summary["content_length"] = len(summary["content"])
            summary["content_preview"] = summary["content"][:200]
            summary.pop("content", None)
        self._log_function("summarize_tool_output", {"keys": list(output)}, {"keys": list(summary)})
        return summary

    def json_safe_summary(self, value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return self.json_safe_summary(value.model_dump())
        if isinstance(value, dict):
            return {key: self.json_safe_summary(child) for key, child in value.items()}
        if isinstance(value, list):
            return [self.json_safe_summary(child) for child in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    def resolve_chained_inputs(
        self,
        tool_name: str,
        input_params: dict[str, Any],
        last_output: Any,
        last_code_output: Any,
    ) -> dict[str, Any]:
        params = {
            key: self.replace_output_placeholders(value, last_output, last_code_output)
            for key, value in input_params.items()
        }

        preferred_output = last_code_output or last_output
        content = self.extract_generated_content(preferred_output)

        if tool_name == "file_writer" and "content" not in params and content is not None:
            params["content"] = content
        elif tool_name in {"code_executor", "code_reviewer"} and "code" not in params and content is not None:
            params["code"] = content
            if isinstance(preferred_output, dict) and "language" in preferred_output and "language" not in params:
                params["language"] = preferred_output["language"]

        self._log_function(
            "resolve_chained_inputs",
            {"tool_name": tool_name, "input_keys": list(input_params)},
            {"output_keys": list(params)},
        )
        return params

    def replace_output_placeholders(
        self,
        value: Any,
        last_output: Any,
        last_code_output: Any,
    ) -> Any:
        if isinstance(value, dict):
            return {
                key: self.replace_output_placeholders(child, last_output, last_code_output)
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [
                self.replace_output_placeholders(child, last_output, last_code_output)
                for child in value
            ]
        if not isinstance(value, str) or "{{" not in value:
            return value

        code_content = self.extract_generated_content(last_code_output)
        previous_content = self.extract_generated_content(last_output)
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

    def extract_generated_content(self, output: Any) -> str | None:
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

    def format_tools_for_llm(self, tools: list[Any]) -> str:
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

        result = "\n\n".join(tool_descriptions)
        self._log_function("format_tools_for_llm", {"tool_count": len(tools)}, {"chars": len(result)})
        return result

    def map_reason_to_enum(self, reason_text: str) -> str:
        reason_lower = reason_text.lower()
        if any(word in reason_lower for word in ["capability", "can", "able to", "supports"]):
            return "capability_match"
        if any(word in reason_lower for word in ["best", "optimal", "performance", "efficient"]):
            return "best_performance"
        if any(word in reason_lower for word in ["only", "single", "no other", "no alternative"]):
            return "only_option"
        if any(word in reason_lower for word in ["prefer", "user", "requested"]):
            return "user_preference"
        if any(word in reason_lower for word in ["fallback", "backup", "alternative"]):
            return "fallback"
        if any(word in reason_lower for word in ["cost", "cheap", "economical"]):
            return "cost_optimized"
        return "capability_match"

    def resolve_selection_inputs(
        self,
        selection: ToolSelection,
        step_outputs: dict[str, Any],
    ) -> ToolSelection:
        input_params = dict(selection.input_params)
        source_step_id = input_params.pop("source_step_id", None)

        if source_step_id and source_step_id in step_outputs:
            source_output = step_outputs[source_step_id]
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
                if isinstance(source_output, dict) and "code" in source_output and "code" not in input_params:
                    input_params["code"] = source_output["code"]
            elif selection.tool_name == "file_reader":
                if isinstance(source_output, str) and "file_path" not in input_params:
                    input_params["file_path"] = source_output
                elif isinstance(source_output, dict) and "file_path" in source_output and "file_path" not in input_params:
                    input_params["file_path"] = source_output["file_path"]
            elif selection.tool_name == "llm_summarizer":
                if isinstance(source_output, dict) and "content" in source_output and "text" not in input_params:
                    input_params["text"] = source_output["content"]
                elif isinstance(source_output, str) and "text" not in input_params:
                    input_params["text"] = source_output

        self._log_function(
            "resolve_selection_inputs",
            {"tool_name": selection.tool_name, "source_step_id": source_step_id},
            {"input_keys": list(input_params)},
        )
        return ToolSelection(
            step_id=selection.step_id,
            tool_name=selection.tool_name,
            reason=selection.reason,
            confidence=selection.confidence,
            input_params=input_params,
            requires_confirmation=selection.requires_confirmation,
            fallback_tools=selection.fallback_tools,
            depends_on=selection.depends_on,
            timeout_override=selection.timeout_override,
        )

    def _log_function(self, source_name: str, input_summary: Any, output_summary: Any) -> None:
        if not self.logger or not hasattr(self.logger, "log_structured_event"):
            return
        session_id = self.session_id_getter() if self.session_id_getter else "unknown"
        self.logger.log_structured_event(
            source_type="function",
            source_name=f"execution.tool_io.{source_name}",
            phase="execution_tool_io",
            event_type="function_completed",
            session_id=session_id or "unknown",
            turn_id=1,
            success=True,
            input_summary=input_summary,
            output_summary=output_summary,
        )
