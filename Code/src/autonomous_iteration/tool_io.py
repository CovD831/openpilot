"""Tool input/output helpers for execution flows."""

from __future__ import annotations

from typing import Any

from metadata import ToolInputMetadata, ToolResultMetadata, artifact_to_tool_input
from tools.tool_selection import ToolSelection


class ExecutionToolIO:
    """Pure helpers for tool prompt formatting, chaining, and summaries."""

    def __init__(self, logger: Any | None = None, session_id_getter: Any | None = None) -> None:
        self.logger = logger
        self.session_id_getter = session_id_getter

    def sanitize_tool_metadata(self, value: Any) -> dict[str, Any]:
        params = value.to_params() if isinstance(value, ToolInputMetadata) else value
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
        self._log_function("sanitize_tool_metadata", {"keys": list(params)}, {"keys": list(sanitized)})
        return sanitized

    def summarize_metadata_output(self, output: Any) -> dict[str, Any]:
        if isinstance(output, ToolResultMetadata):
            return self.summarize_metadata_output(output.result)
        if hasattr(output, "model_dump"):
            return self.summarize_metadata_output(output.model_dump(mode="json"))
        if not isinstance(output, dict):
            summary = {"output_type": type(output).__name__} if output is not None else {}
            self._log_function("summarize_metadata_output", {"output_type": type(output).__name__}, summary)
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
        self._log_function("summarize_metadata_output", {"keys": list(output)}, {"keys": list(summary)})
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

    def resolve_chained_metadata(
        self,
        tool_name: str,
        input_metadata: ToolInputMetadata,
        last_output: Any,
        last_code_output: Any,
    ) -> ToolInputMetadata:
        params = input_metadata.to_params()
        preferred_output = last_code_output or last_output
        if (
            tool_name == "file_writer"
            and isinstance(preferred_output, ToolResultMetadata)
            and preferred_output.tool_name != "code_generator"
        ):
            return input_metadata
        routed = artifact_to_tool_input(tool_name, preferred_output)
        routed_params = routed.to_params()
        for key, value in routed_params.items():
            current = params.get(key)
            if current in (None, "", [], {}) or self._is_generated_placeholder(current):
                params[key] = value
        resolved = ToolInputMetadata.from_mapping(tool_name, params)
        self._log_function(
            "resolve_chained_metadata",
            {"tool_name": tool_name, "input_keys": list(input_metadata.to_params())},
            {"output_keys": list(resolved.to_params())},
        )
        return resolved

    def _is_generated_placeholder(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        lowered = value.lower()
        return any(
            marker in lowered
            for marker in (
                "placeholder",
                "will be replaced",
                "replace_me",
                "to_be_filled",
                "filled_by_codegeneration",
                "todo_generated",
                "code_generator_output",
                "{{code_generation.output}}",
                "{{ code_generation.output }}",
                "占位",
                "待填充",
                "后填充",
                "输出填充",
                "前一步输出",
                "code_generation生成",
            )
        )

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
        if isinstance(output, ToolResultMetadata):
            return self.extract_generated_content(output.result)
        return None

    def format_tools_for_llm(self, tools: list[Any]) -> str:
        tool_descriptions = []
        for tool in tools:
            params_str = ""
            contract = getattr(tool, "contract_metadata", None)
            if contract:
                params = [f"  - {field} [required]" for field in contract.required_input_fields]
                required_any_of = getattr(contract, "required_any_of", []) or []
                if required_any_of:
                    readable_group = " or ".join(
                        " + ".join(str(field) for field in field_group)
                        for field_group in required_any_of
                    )
                    params.append(f"  - one of: {readable_group} [required]")
                for requirement in getattr(contract, "conditional_requirements", []) or []:
                    params.append(f"  - conditional: {requirement}")
                params.extend(f"  - {field} [default={value!r}]" for field, value in contract.input_defaults.items())
                params_str = "\n".join(params)

            tool_descriptions.append(
                f"- {tool.name}: {tool.description}\n"
                f"  Input metadata:\n{params_str if params_str else '  (none)'}"
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

    def resolve_selection_metadata(
        self,
        selection: ToolSelection,
        step_outputs: dict[str, Any],
    ) -> ToolSelection:
        input_metadata = selection.input_metadata
        if selection.depends_on:
            for dependency_step_id in selection.depends_on:
                if dependency_step_id in step_outputs:
                    input_metadata = self.resolve_chained_metadata(
                        selection.tool_name,
                        input_metadata,
                        step_outputs[dependency_step_id],
                        step_outputs[dependency_step_id],
                    )

        self._log_function(
            "resolve_selection_metadata",
            {"tool_name": selection.tool_name, "depends_on": selection.depends_on},
            {"input_keys": list(input_metadata.to_params())},
        )
        return ToolSelection(
            step_id=selection.step_id,
            tool_name=selection.tool_name,
            reason=selection.reason,
            confidence=selection.confidence,
            input_metadata=input_metadata,
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
            source_name=f"autonomous_iteration.tool_io.{source_name}",
            phase="execution_tool_io",
            event_type="function_completed",
            session_id=session_id or "unknown",
            turn_id=1,
            success=True,
            input_summary=input_summary,
            output_summary=output_summary,
        )
