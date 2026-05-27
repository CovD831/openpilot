"""Shared typed tool event loop runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.llm import LLMMessage, LLMRequest
from core.tool_event_emitter import ToolEventEmitter
from metadata import (
    FailureMetadata,
    ToolCallMetadata,
    ToolContextMetadata,
    ToolErrorMetadata,
    ToolEventMetadata,
    ToolInputMetadata,
    ToolLoopMetadata,
    ToolResultMetadata,
)
from tools.tool_selection import ToolSelection


@dataclass
class ToolEventLoopRunResult:
    success: bool
    tool_results: list[dict[str, Any]]
    last_output: ToolResultMetadata | None
    loop_metadata: ToolLoopMetadata
    error_message: str | None = None


class ToolEventLoopRunner:
    """Run LLM-planned tool calls as a recoverable typed event loop."""

    def __init__(self, owner: Any, *, max_steps: int = 5, doom_loop_threshold: int = 3) -> None:
        self.owner = owner
        self.runtime = owner.runtime
        self.max_steps = max_steps
        self.doom_loop_threshold = doom_loop_threshold
        self.events: list[ToolEventMetadata] = []
        self.tool_calls: list[ToolCallMetadata] = []
        self.tool_contexts: list[ToolContextMetadata] = []
        self.recoverable_errors: list[ToolErrorMetadata] = []
        self.tool_results: list[dict[str, Any]] = []
        self.event_emitter = ToolEventEmitter(self.runtime, log_hook=self.owner._log)
        self._seen_signatures: dict[str, int] = {}

    def run(self, task: Any, initial_prompt: str) -> ToolEventLoopRunResult:
        task_id = str(getattr(task, "id", "unknown"))
        session_id = self.owner._session_id()
        prompt = initial_prompt
        last_output: ToolResultMetadata | None = None
        last_code_output: ToolResultMetadata | None = None
        final_error: FailureMetadata | None = None
        rounds_used = 0

        for round_index in range(1, self.max_steps + 1):
            rounds_used = round_index
            llm_response = self.runtime.llm_client.complete(
                LLMRequest(
                    messages=[LLMMessage(role="user", content=prompt)],
                    response_format="json_object",
                )
            )
            tool_calls = self.owner._parse_tool_calls(llm_response)
            round_had_recoverable_error = False

            for index, tool_call in enumerate(tool_calls):
                tool_name = str(tool_call.get("tool_name") or "").strip()
                reason_text = str(tool_call.get("reason") or "")
                raw_input = tool_call.get("input_metadata")
                if not isinstance(raw_input, dict):
                    raw_input = {}
                call_id = f"{task_id}:r{round_index}:c{index + 1}"
                step_id = f"step_{round_index}_{index + 1}"
                input_metadata = self._input_from_raw(tool_name, dict(raw_input))
                input_metadata = self.runtime._resolve_chained_metadata(
                    tool_name,
                    input_metadata,
                    last_output,
                    last_code_output,
                )
                apply_project_context = getattr(self.runtime, "_apply_project_command_context", None)
                if callable(apply_project_context):
                    input_metadata = apply_project_context(tool_name, input_metadata)

                tool_context = self.event_emitter.build_context(
                    task_id=task_id,
                    session_id=session_id,
                    step_id=step_id,
                    call_id=call_id,
                    tool_name=tool_name,
                    input_metadata=input_metadata,
                )
                self.tool_contexts.append(tool_context)

                tool_call_metadata = self.event_emitter.create_tool_call(
                    session_id=session_id,
                    task_id=task_id,
                    step_id=step_id,
                    call_id=call_id,
                    tool_name=tool_name,
                    input_metadata=input_metadata,
                    tool_context=tool_context,
                    status="pending",
                    reason=reason_text,
                    round_index=round_index,
                )
                self.tool_calls.append(tool_call_metadata)
                self._append_event(
                    task_id,
                    tool_call_metadata,
                    "pending",
                    "pending",
                    input_metadata=input_metadata,
                    tool_context=tool_context,
                    round_index=round_index,
                )

                protocol_error = self._validate_and_normalize_call(tool_call_metadata)
                if protocol_error:
                    self._record_tool_error(task_id, tool_call_metadata, protocol_error, round_index)
                    self._append_tool_result(tool_call_metadata, input_metadata, False, protocol_error.error_message)
                    final_error = protocol_error.failure
                    if not protocol_error.recoverable:
                        return self._finish(
                            task_id,
                            session_id,
                            False,
                            rounds_used,
                            last_output,
                            final_error,
                            protocol_error.error_message,
                        )
                    round_had_recoverable_error = True
                    break

                signature = self._call_signature(tool_name, input_metadata)
                self._seen_signatures[signature] = self._seen_signatures.get(signature, 0) + 1
                if self._seen_signatures[signature] >= self.doom_loop_threshold:
                    final_error = FailureMetadata(
                        error_type="ToolDoomLoop",
                        error_message=f"Repeated the same tool call too many times: {tool_name}",
                        recoverable=False,
                        details={"call_signature": signature},
                    )
                    tool_error = ToolErrorMetadata(
                        session_id=session_id,
                        task_id=task_id,
                        step_id=step_id,
                        call_id=call_id,
                        tool_name=tool_name,
                        error_type=final_error.error_type,
                        error_message=final_error.error_message,
                        recoverable=False,
                        failure=final_error,
                        input_metadata=input_metadata,
                        tool_context=tool_context,
                        round_index=round_index,
                        event_index=self._next_event_index(),
                    )
                    self._record_tool_error(task_id, tool_call_metadata, tool_error, round_index)
                    self._append_tool_result(tool_call_metadata, input_metadata, False, final_error.error_message)
                    return self._finish(task_id, session_id, False, rounds_used, last_output, final_error, final_error.error_message)

                input_payload = input_metadata.to_params()
                self._append_event(
                    task_id,
                    tool_call_metadata,
                    "running",
                    "running",
                    input_metadata=input_metadata,
                    tool_context=tool_context,
                    round_index=round_index,
                )
                self.owner._show_tool_running(task, tool_name, input_payload, reason_text, index, len(tool_calls))
                selection = ToolSelection(
                    step_id=step_id,
                    tool_name=tool_name,
                    reason=self.runtime._map_reason_to_enum(reason_text),
                    confidence=0.9,
                    input_metadata=input_metadata,
                    requires_confirmation=False,
                    fallback_tools=[],
                    depends_on=[],
                    timeout_override=None,
                )
                self.owner._log_tool_start(task, tool_name, input_payload)
                exec_result = self.runtime.tool_executor.execute_single(selection, context=None)
                self.owner._show_tool_result(tool_name, exec_result)
                log_output = self.owner._summarize_metadata_output(exec_result.output_metadata)
                self.owner._log_tool_complete(task, tool_name, exec_result, log_output)

                if exec_result.success:
                    output_metadata = exec_result.output_metadata
                    last_output = output_metadata
                    if tool_name == "code_generator":
                        last_code_output = output_metadata
                    self._append_event(
                        task_id,
                        tool_call_metadata,
                        "completed",
                        "completed",
                        input_metadata=input_metadata,
                        output_metadata=output_metadata,
                        tool_context=tool_context,
                        round_index=round_index,
                    )
                    self._append_tool_result(tool_call_metadata, input_metadata, True, None, output_metadata)
                    continue

                failure = exec_result.error or FailureMetadata(
                    error_type="ToolExecutionFailed",
                    error_message=f"{tool_name} failed",
                )
                if not isinstance(failure, FailureMetadata):
                    failure = FailureMetadata(
                        error_type=str(getattr(failure, "error_type", "") or type(failure).__name__),
                        error_message=str(getattr(failure, "error_message", failure)),
                        recoverable=self._is_recoverable_error(tool_name, str(getattr(failure, "error_message", failure))),
                    )
                recoverable = bool(failure.recoverable) or self._is_recoverable_error(
                    tool_name,
                    f"{failure.error_type}: {failure.error_message}",
                )
                tool_error = ToolErrorMetadata(
                    session_id=session_id,
                    task_id=task_id,
                    step_id=step_id,
                    call_id=call_id,
                    tool_name=tool_name,
                    error_type=failure.error_type,
                    error_message=failure.error_message,
                    recoverable=recoverable,
                    suggested_recovery=self._suggest_recovery(tool_name, failure.error_message),
                    failure=failure,
                    input_metadata=input_metadata,
                    tool_context=tool_context,
                    round_index=round_index,
                    event_index=self._next_event_index(),
                )
                self._record_tool_error(task_id, tool_call_metadata, tool_error, round_index)
                self._append_tool_result(tool_call_metadata, input_metadata, False, failure.error_message)
                final_error = failure
                if not recoverable:
                    return self._finish(task_id, session_id, False, rounds_used, last_output, final_error, failure.error_message)
                round_had_recoverable_error = True
                break

            if not round_had_recoverable_error:
                return self._finish(task_id, session_id, True, rounds_used, last_output, None, None)
            prompt = self._build_recovery_prompt(initial_prompt, self.recoverable_errors[-3:])

        final_error = FailureMetadata(
            error_type="ToolLoopExceeded",
            error_message=self._tool_loop_exceeded_message(),
            recoverable=False,
            details=self._last_recoverable_error_details(),
        )
        return self._finish(task_id, session_id, False, rounds_used, last_output, final_error, final_error.error_message)

    def _build_tool_context(
        self,
        *,
        task_id: str,
        session_id: str,
        step_id: str,
        call_id: str,
        tool_name: str,
        input_metadata: ToolInputMetadata,
    ) -> ToolContextMetadata:
        return self.event_emitter.build_context(
            task_id=task_id,
            session_id=session_id,
            step_id=step_id,
            call_id=call_id,
            tool_name=tool_name,
            input_metadata=input_metadata,
        )

    def _environment_for_input(self, input_metadata: ToolInputMetadata) -> dict[str, Any]:
        environment_for_tool_input = getattr(self.runtime, "_environment_for_tool_input", None)
        if callable(environment_for_tool_input):
            environment = environment_for_tool_input(input_metadata)
            if isinstance(environment, dict):
                return environment
        environments = getattr(self.runtime, "_project_environments", {}) or {}
        if len(environments) == 1:
            return next(iter(environments.values()))
        return {}

    def _project_from_path(self, raw: str) -> str:
        if not raw:
            return ""
        environments = getattr(self.runtime, "_project_environments", {}) or {}
        try:
            path = Path(str(raw)).expanduser().resolve()
        except OSError:
            path = Path(str(raw)).expanduser()
        for project_path in environments:
            try:
                project = Path(str(project_path)).expanduser().resolve()
            except OSError:
                project = Path(str(project_path)).expanduser()
            if path == project or project in path.parents:
                return str(project_path)
        return ""

    def _permission_required(self, tool_name: str, input_metadata: ToolInputMetadata) -> bool:
        if input_metadata.requires_user_input:
            return True
        registry = getattr(self.runtime, "tool_registry", None)
        definition = registry.get(tool_name) if registry and hasattr(registry, "get") else None
        permission_level = str(getattr(definition, "permission_level", "") or "").lower()
        return permission_level in {"medium", "high", "forbidden"}

    def _validate_and_normalize_call(self, tool_call: ToolCallMetadata) -> ToolErrorMetadata | None:
        tool_name = tool_call.tool_name
        input_metadata = tool_call.input_metadata
        session_id = tool_call.session_id
        task_id = tool_call.task_id
        step_id = tool_call.step_id
        call_id = tool_call.call_id

        if not tool_name:
            return self._protocol_error(session_id, task_id, step_id, call_id, tool_name, "UnknownTool", "Tool name is required", input_metadata, tool_call.tool_context)

        registry = getattr(self.runtime, "tool_registry", None)
        get_executor = getattr(registry, "get_executor", None)
        if callable(get_executor) and get_executor(tool_name) is None:
            return self._protocol_error(
                session_id,
                task_id,
                step_id,
                call_id,
                tool_name,
                "UnknownTool",
                f"Unknown tool: {tool_name}",
                input_metadata,
                tool_call.tool_context,
                suggested_recovery="Choose one of the registered tools from the available tool list.",
            )

        missing_fields = [field for field in self._required_fields(tool_name) if not getattr(input_metadata, field, None)]
        if missing_fields:
            return self._protocol_error(
                session_id,
                task_id,
                step_id,
                call_id,
                tool_name,
                "MissingRequiredInput",
                f"Missing required input field(s) for {tool_name}: {', '.join(missing_fields)}",
                input_metadata,
                tool_call.tool_context,
                suggested_recovery=f"Retry with input_metadata containing: {', '.join(missing_fields)}.",
            )

        missing_any_of = self._missing_required_any_of(tool_name, input_metadata)
        if missing_any_of:
            readable_group = " or ".join(missing_any_of)
            return self._protocol_error(
                session_id,
                task_id,
                step_id,
                call_id,
                tool_name,
                "MissingRequiredInputGroup",
                f"Missing required input for {tool_name}: provide {readable_group}",
                input_metadata,
                tool_call.tool_context,
                suggested_recovery=f"Retry with input_metadata containing one of: {readable_group}.",
                details={"required_any_of": [missing_any_of]},
            )

        if tool_name == "code_generator":
            language = (input_metadata.language or "python").lower()
            if language not in {"python", "shell", "bash"}:
                return self._protocol_error(
                    session_id,
                    task_id,
                    step_id,
                    call_id,
                    tool_name,
                    "UnsupportedLanguage",
                    f"Unsupported language: {input_metadata.language}. Use python, shell, or bash.",
                    input_metadata,
                    tool_call.tool_context,
                    suggested_recovery=(
                        "If the task asks for design, outline, or documentation, use README/document writing "
                        "or return planning metadata instead of code_generator(language=text)."
                    ),
                )

        if tool_name == "command_executor":
            mode = (input_metadata.mode or "automatic").lower()
            aliases = {"execute": "automatic", "run": "automatic", "exec": "automatic"}
            if mode in aliases:
                input_metadata.mode = aliases[mode]
            elif mode not in {"dry_run", "interactive", "automatic"}:
                return self._protocol_error(
                    session_id,
                    task_id,
                    step_id,
                    call_id,
                    tool_name,
                    "UnsupportedCommandMode",
                    f"unsupported command execution mode: {input_metadata.mode}",
                    input_metadata,
                    tool_call.tool_context,
                    suggested_recovery="Use command_executor mode dry_run, interactive, or automatic.",
                )
        return None

    def _input_from_raw(self, tool_name: str, raw_input: dict[str, Any]) -> ToolInputMetadata:
        try:
            return ToolInputMetadata.from_mapping(tool_name, raw_input)
        except Exception:
            runtime_handles = {key: value for key, value in raw_input.items() if str(key).startswith("_")}
            attributes = {str(key): value for key, value in raw_input.items() if not str(key).startswith("_")}
            return ToolInputMetadata(tool_name=tool_name, attributes=attributes, runtime_handles=runtime_handles)

    def _required_fields(self, tool_name: str) -> list[str]:
        registry = getattr(self.runtime, "tool_registry", None)
        definition = registry.get(tool_name) if registry and hasattr(registry, "get") else None
        contract = getattr(definition, "contract_metadata", None)
        required = getattr(contract, "required_input_fields", None)
        if required:
            return list(required)
        fallback = {
            "code_generator": ["task_description"],
            "file_writer": ["file_path"],
            "readme_tool": ["project_path"],
            "command_executor": ["command"],
        }
        return fallback.get(tool_name, [])

    def _missing_required_any_of(self, tool_name: str, input_metadata: ToolInputMetadata) -> list[str]:
        registry = getattr(self.runtime, "tool_registry", None)
        definition = registry.get(tool_name) if registry and hasattr(registry, "get") else None
        contract = getattr(definition, "contract_metadata", None)
        required_any_of = getattr(contract, "required_any_of", None)
        if not required_any_of and tool_name == "multi_file_reader":
            required_any_of = [["file_paths"], ["directory_path"]]
        if not required_any_of:
            return []
        params = input_metadata.to_params()
        for field_group in required_any_of:
            if all(params.get(field) not in (None, "", [], {}) for field in field_group):
                return []
        return [str(field) for field_group in required_any_of for field in field_group]

    def _protocol_error(
        self,
        session_id: str,
        task_id: str,
        step_id: str,
        call_id: str,
        tool_name: str,
        error_type: str,
        message: str,
        input_metadata: ToolInputMetadata,
        tool_context: ToolContextMetadata | None,
        *,
        suggested_recovery: str = "",
        details: dict[str, Any] | None = None,
    ) -> ToolErrorMetadata:
        failure = FailureMetadata(
            error_type=error_type,
            error_message=message,
            recoverable=True,
            retry_recommended=True,
            recovery_strategy=suggested_recovery or self._suggest_recovery(tool_name, message),
            details=details or {},
        )
        return ToolErrorMetadata(
            session_id=session_id,
            task_id=task_id,
            step_id=step_id,
            call_id=call_id,
            tool_name=tool_name or "unknown",
            error_type=error_type,
            error_message=message,
            recoverable=True,
            suggested_recovery=suggested_recovery or self._suggest_recovery(tool_name, message),
            failure=failure,
            input_metadata=input_metadata,
            tool_context=tool_context,
            event_index=self._next_event_index(),
        )

    def _record_tool_error(
        self,
        task_id: str,
        tool_call: ToolCallMetadata,
        tool_error: ToolErrorMetadata,
        round_index: int,
    ) -> None:
        if tool_error.recoverable:
            self.recoverable_errors.append(tool_error)
        self.owner._log(
            "tool_loop_recoverable_error" if tool_error.recoverable else "tool_loop_terminal_error",
            output_summary={
                "task_id": task_id,
                "call_id": tool_call.call_id,
                "tool": tool_call.tool_name,
                "error_type": tool_error.error_type,
                "recoverable": tool_error.recoverable,
            },
            success=False,
            error=tool_error.error_message,
        )
        self._append_event(
            task_id,
            tool_call,
            "error",
            "error",
            input_metadata=tool_error.input_metadata,
            tool_context=tool_error.tool_context,
            failure=tool_error.failure,
            tool_error=tool_error,
            recoverable=tool_error.recoverable,
            round_index=round_index,
        )

    def _append_event(
        self,
        task_id: str,
        tool_call: ToolCallMetadata,
        event_type: str,
        status: str,
        *,
        input_metadata: ToolInputMetadata | None = None,
        output_metadata: ToolResultMetadata | None = None,
        tool_context: ToolContextMetadata | None = None,
        failure: FailureMetadata | None = None,
        tool_error: ToolErrorMetadata | None = None,
        recoverable: bool = True,
        round_index: int = 1,
    ) -> None:
        event = self.event_emitter.emit(
            task_id=task_id,
            tool_call=tool_call,
            event_type=event_type,
            status=status,
            input_metadata=input_metadata,
            output_metadata=output_metadata,
            tool_context=tool_context,
            tool_error=tool_error,
            failure=failure,
            recoverable=recoverable,
            round_index=round_index,
        )
        self.events.append(event)

    def _emit_ui_tool_event(self, event: ToolEventMetadata) -> None:
        self.event_emitter.emit_ui(event)

    def _append_tool_result(
        self,
        tool_call: ToolCallMetadata,
        input_metadata: ToolInputMetadata,
        success: bool,
        error: str | None,
        output_metadata: ToolResultMetadata | None = None,
    ) -> None:
        output_result = output_metadata.result if output_metadata else None
        self.tool_results.append(
            {
                "call_id": tool_call.call_id,
                "step_id": tool_call.step_id,
                "tool": tool_call.tool_name,
                "input_metadata": input_metadata.to_json_dict(),
                "tool_context": tool_call.tool_context.to_json_dict() if tool_call.tool_context else None,
                "result": output_result,
                "success": success,
                "error": error,
            }
        )

    def _finish(
        self,
        task_id: str,
        session_id: str,
        success: bool,
        rounds_used: int,
        last_output: ToolResultMetadata | None,
        final_error: FailureMetadata | None,
        error_message: str | None,
    ) -> ToolEventLoopRunResult:
        loop_metadata = ToolLoopMetadata(
            session_id=session_id,
            task_id=task_id,
            status="completed" if success else "failed",
            success=success,
            rounds_used=rounds_used,
            max_rounds=self.max_steps,
            events=self.events,
            tool_calls=self.tool_calls,
            recoverable_errors=self.recoverable_errors,
            tool_contexts=self.tool_contexts,
            final_output=last_output,
            final_error=final_error,
        )
        self.owner._log(
            "tool_event_loop_completed",
            output_summary={
                "task_id": task_id,
                "success": success,
                "rounds_used": rounds_used,
                "events": len(self.events),
                "recoverable_errors": len(self.recoverable_errors),
            },
            success=success,
            error=error_message,
        )
        return ToolEventLoopRunResult(
            success=success,
            tool_results=self.tool_results,
            last_output=last_output,
            loop_metadata=loop_metadata,
            error_message=error_message,
        )

    def _build_recovery_prompt(self, initial_prompt: str, errors: list[ToolErrorMetadata]) -> str:
        errors_payload = [
            {
                "tool_name": error.tool_name,
                "call_id": error.call_id,
                "error_type": error.error_type,
                "error_message": error.error_message,
                "suggested_recovery": error.suggested_recovery,
                "input_metadata": error.input_metadata.to_json_dict() if error.input_metadata else None,
                "tool_contract": self._contract_summary(error.tool_name),
            }
            for error in errors
        ]
        return (
            f"{initial_prompt}\n\n"
            "The previous tool call attempt produced recoverable tool protocol errors. "
            "Revise the tool_calls JSON and try again. Focus on correcting the failed call only; "
            "do not repeat successful calls unless their output is strictly needed again, and do not repeat the same invalid tool/input.\n"
            f"Recoverable errors:\n{json.dumps(errors_payload, ensure_ascii=False, indent=2)}"
        )

    def _call_signature(self, tool_name: str, input_metadata: ToolInputMetadata) -> str:
        return json.dumps({"tool": tool_name, "input": input_metadata.to_json_dict()}, sort_keys=True, ensure_ascii=False)

    def _is_recoverable_error(self, tool_name: str, message: str) -> bool:
        lowered = message.lower()
        recoverable_tokens = (
            "unknown tool",
            "unsupported language",
            "unsupported command execution mode",
            "missing required",
            "missing field",
            "requires",
            "required metadata",
            "provide ",
            "invalid input",
            "invalidinput",
            "validation",
        )
        return any(token in lowered for token in recoverable_tokens)

    def _suggest_recovery(self, tool_name: str, message: str) -> str:
        lowered = message.lower()
        if tool_name == "code_generator" and ("text" in lowered or "unsupported language" in lowered):
            return "Use code_generator only for python/shell/bash code. For prose/design tasks, write Markdown/text with a document/file tool or return planning metadata."
        if tool_name == "command_executor":
            return "Use command_executor mode automatic, interactive, or dry_run. Aliases execute/run/exec are normalized to automatic."
        if tool_name == "multi_file_reader":
            return "Provide file_paths as a list of files, or directory_path with an optional pattern/max_files."
        if "unknown tool" in lowered:
            return "Select a registered tool from the available tools list."
        if "missing required" in lowered or "requires" in lowered:
            return "Provide all required input_metadata fields for the selected tool."
        return "Revise the tool call and arguments according to the tool contract."

    def _contract_summary(self, tool_name: str) -> dict[str, Any]:
        registry = getattr(self.runtime, "tool_registry", None)
        definition = registry.get(tool_name) if registry and hasattr(registry, "get") else None
        contract = getattr(definition, "contract_metadata", None)
        if not contract:
            return {}
        return {
            "required_input_fields": list(getattr(contract, "required_input_fields", []) or []),
            "required_any_of": list(getattr(contract, "required_any_of", []) or []),
            "input_defaults": dict(getattr(contract, "input_defaults", {}) or {}),
        }

    def _last_recoverable_error_details(self) -> dict[str, Any]:
        if not self.recoverable_errors:
            return {}
        error = self.recoverable_errors[-1]
        return {
            "tool_name": error.tool_name,
            "call_id": error.call_id,
            "error_type": error.error_type,
            "error_message": error.error_message,
            "suggested_recovery": error.suggested_recovery,
            "input_metadata": error.input_metadata.to_json_dict() if error.input_metadata else None,
            "tool_contract": self._contract_summary(error.tool_name),
        }

    def _tool_loop_exceeded_message(self) -> str:
        base = f"Tool event loop exceeded {self.max_steps} correction step(s)"
        if not self.recoverable_errors:
            return base
        error = self.recoverable_errors[-1]
        recovery = f"; suggested recovery: {error.suggested_recovery}" if error.suggested_recovery else ""
        return (
            f"{base}. Last unresolved tool error: {error.tool_name} ({error.call_id}) "
            f"{error.error_type}: {error.error_message}{recovery}"
        )

    def _next_event_index(self) -> int:
        return self.event_emitter.next_event_index()
