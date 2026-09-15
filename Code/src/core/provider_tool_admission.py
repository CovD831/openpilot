"""Admission boundary for provider-native tool calls.

Provider tool calls are wire requests, not execution authority. This module
binds their external IDs to project-owned ``ToolCallMetadata`` while requiring
registry, input-contract, permission, and runtime-budget checks before a
caller can hand a ``ToolSelection`` to the existing executor.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from core.llm import LLMToolCall, LLMToolResult
from core.tool_contracts import PermissionLevel, ToolCapability
from core.validation_command import normalize_command_argv
from metadata import (
    FailureMetadata,
    RuntimeBudgetMetadata,
    ToolCallMetadata,
    ToolErrorMetadata,
    ToolInputMetadata,
)
from tools.mutation_descriptor import FILE_MUTATION_TOOLS
from tools.command_tool import ExecutionMode
from tools.web_searcher import SAFE_SEARCH_PARAMS
from tools.tool_selection import SelectionReason, ToolSelection


class ProviderToolAdmissionError(ValueError):
    """Raised for malformed or ambiguous provider tool-call batches."""


class _ValidationCommandViolation(BaseModel):
    """Typed validation-command admission fact used for error routing."""

    model_config = ConfigDict(extra="forbid")

    code: Literal["duplicate", "mismatch", "mode", "cwd"]
    message: str


class ProviderToolAdmission(BaseModel):
    """One provider call after the project admission boundary."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["admitted", "blocked"]
    provider_call_id: str
    project_call_id: str
    tool_call: ToolCallMetadata
    selection: ToolSelection | None = None
    tool_error: ToolErrorMetadata | None = None
    requires_confirmation: bool = False

    @model_validator(mode="after")
    def _status_matches_payload(self) -> "ProviderToolAdmission":
        if self.status == "admitted" and (self.selection is None or self.tool_error is not None):
            raise ValueError("admitted provider tool call requires selection and no tool_error")
        if self.status == "blocked" and (self.selection is not None or self.tool_error is None):
            raise ValueError("blocked provider tool call requires tool_error and no selection")
        if self.tool_call.provider_call_id != self.provider_call_id:
            raise ValueError("provider call ID must match ToolCallMetadata")
        if self.tool_call.call_id != self.project_call_id:
            raise ValueError("project call ID must match ToolCallMetadata")
        return self


def provider_tool_wire_fields(definition: Any) -> tuple[str, ...]:
    """Return the exact provider-visible fields declared by one tool contract."""

    contract = getattr(definition, "contract_metadata", None)
    if contract is None:
        return ()
    ordered: list[str] = []
    conditional_fields: list[str] = []
    for requirement in getattr(contract, "conditional_requirements", []) or []:
        if not isinstance(requirement, dict):
            continue
        conditional_fields.extend(str(field) for field in (requirement.get("when", {}) or {}))
        conditional_fields.extend(str(field) for field in (requirement.get("required", []) or []))
        conditional_fields.extend(
            str(field)
            for group in (requirement.get("required_any_of", []) or [])
            for field in group
        )
    for raw_field in (
        *(getattr(contract, "required_input_fields", []) or []),
        *(
            field
            for group in (getattr(contract, "required_any_of", []) or [])
            for field in group
        ),
        *(getattr(contract, "input_defaults", {}) or {}),
        *conditional_fields,
    ):
        field = str(raw_field or "").strip()
        if field and field not in ordered:
            ordered.append(field)
    return tuple(ordered)


def admit_provider_tool_calls(
    tool_calls: Sequence[LLMToolCall],
    *,
    task_id: str,
    session_id: str,
    round_index: int,
    registry: Any,
    budget: RuntimeBudgetMetadata,
    advertised_tool_names: Sequence[str],
    allow_mutations: bool = False,
    user_confirmed: bool = False,
    read_scope: Sequence[str] | None = None,
    write_scope: Sequence[str] | None = None,
    project_path: str | None = None,
    validation_command: str | None = None,
    validation_cwd: str | None = None,
    validation_commands_used: int = 0,
    required_reads_complete: bool = True,
    require_mutation_before_validation: bool = False,
    mutation_observed: bool = False,
) -> list[ProviderToolAdmission]:
    """Bind and admit a provider tool-call batch without executing anything."""

    if not isinstance(allow_mutations, bool):
        raise ProviderToolAdmissionError("allow_mutations must be a boolean")
    if not isinstance(user_confirmed, bool):
        raise ProviderToolAdmissionError("user_confirmed must be a boolean")
    calls = list(tool_calls)
    provider_ids = [call.id for call in calls]
    if not task_id or not session_id or round_index < 1:
        raise ProviderToolAdmissionError("task_id, session_id, and positive round_index are required")
    if len(provider_ids) != len(set(provider_ids)):
        raise ProviderToolAdmissionError("provider tool call IDs must be unique within one response")

    admissions: list[ProviderToolAdmission] = []
    advertised_names = frozenset(
        str(name).strip()
        for name in advertised_tool_names
        if str(name).strip()
    )
    prior_counts = {
        "reads": 0,
        "edits": 0,
        "creates": 0,
        "calls": 0,
        "validation": max(0, int(validation_commands_used)),
        "mutations": int(bool(mutation_observed)),
    }
    for ordinal, call in enumerate(calls, start=1):
        admission = _admit_one(
            call,
            task_id=task_id,
            session_id=session_id,
            round_index=round_index,
            ordinal=ordinal,
            registry=registry,
            budget=budget,
            advertised_tool_names=advertised_names,
            allow_mutations=allow_mutations,
            user_confirmed=user_confirmed,
            prior_counts=prior_counts,
            read_scope=read_scope,
            write_scope=write_scope,
            project_path=project_path,
            validation_command=validation_command,
            validation_cwd=validation_cwd,
            required_reads_complete=required_reads_complete,
            require_mutation_before_validation=require_mutation_before_validation,
        )
        admissions.append(admission)
        if admission.status == "admitted":
            counts = _resource_counts(
                getattr(registry, "get", lambda _name: None)(call.function.name),
                admission.tool_call.input_metadata,
                validation_command=validation_command,
            )
            for key, value in counts.items():
                prior_counts[key] += value
            prior_counts["calls"] += 1
    return admissions


def provider_tool_error(
    tool_call: ToolCallMetadata,
    *,
    error_type: str,
    error_message: str,
    recoverable: bool,
    retry_recommended: bool | None = None,
    suggested_recovery: str = "",
) -> ToolErrorMetadata:
    """Project a provider-bound execution failure into the existing error contract."""

    retry = recoverable if retry_recommended is None else retry_recommended
    failure = FailureMetadata(
        error_type=error_type,
        error_message=error_message,
        recoverable=recoverable,
        retry_recommended=retry,
        recovery_strategy=suggested_recovery,
        details={
            "tool_name": tool_call.tool_name,
            "call_id": tool_call.call_id,
            "provider_call_id": tool_call.provider_call_id,
        },
    )
    return ToolErrorMetadata(
        session_id=tool_call.session_id,
        task_id=tool_call.task_id,
        step_id=tool_call.step_id,
        call_id=tool_call.call_id,
        provider_call_id=tool_call.provider_call_id,
        tool_name=tool_call.tool_name,
        error_type=error_type,
        error_message=error_message,
        recoverable=recoverable,
        suggested_recovery=suggested_recovery,
        failure=failure,
        input_metadata=tool_call.input_metadata,
        tool_context=tool_call.tool_context,
        round_index=tool_call.round_index,
        event_index=tool_call.event_index,
    )


def _admit_one(
    call: LLMToolCall,
    *,
    task_id: str,
    session_id: str,
    round_index: int,
    ordinal: int,
    registry: Any,
    budget: RuntimeBudgetMetadata,
    advertised_tool_names: frozenset[str],
    allow_mutations: bool,
    user_confirmed: bool,
    prior_counts: dict[str, int],
    read_scope: Sequence[str] | None,
    write_scope: Sequence[str] | None,
    project_path: str | None,
    validation_command: str | None,
    validation_cwd: str | None,
    required_reads_complete: bool,
    require_mutation_before_validation: bool,
) -> ProviderToolAdmission:
    project_call_id = f"{task_id}:r{round_index}:c{ordinal}"
    tool_name = call.function.name

    def build_tool_call(input_metadata: ToolInputMetadata) -> ToolCallMetadata:
        return ToolCallMetadata(
            session_id=session_id,
            task_id=task_id,
            step_id=f"step_{round_index}_{ordinal}",
            call_id=project_call_id,
            provider_call_id=call.id,
            tool_name=tool_name,
            input_metadata=input_metadata,
            reason="provider-native tool call",
            round_index=round_index,
        )

    # Resolve registry/executor identity before interpreting any provider
    # arguments. The empty project-owned envelope keeps an unknown call
    # recoverable without binding malformed or undeclared provider fields.
    tool_call = build_tool_call(ToolInputMetadata(tool_name=tool_name))

    definition = getattr(registry, "get", lambda _name: None)(tool_name)
    if definition is None or getattr(registry, "get_executor", lambda _name: None)(tool_name) is None:
        return _blocked(
            tool_call,
            error_type="UnknownTool",
            error_message=f"Unknown or unexecutable tool: {tool_name}",
            recoverable=True,
            suggested_recovery="Choose a registered tool with an executable contract.",
        )

    if tool_name not in advertised_tool_names:
        return _blocked(
            tool_call,
            error_type="ProviderToolNotAdvertised",
            error_message=f"Tool {tool_name} was not exposed in this provider request.",
            recoverable=True,
            suggested_recovery="Choose a tool from the current request tool surface.",
        )

    capabilities = set(getattr(definition, "capabilities", []) or [])
    mutating = bool(
        {ToolCapability.FILE_WRITE, ToolCapability.FILE_DELETE} & capabilities
    ) or tool_name in FILE_MUTATION_TOOLS
    if mutating and not allow_mutations:
        return _blocked(
            tool_call,
            error_type="ProviderToolMutationOptInRequired",
            error_message="Provider-native mutation requires explicit allow_mutations authority.",
            recoverable=False,
            suggested_recovery="Use a read-only tool or obtain explicit mutation authority.",
        )
    if mutating and not write_scope:
        return _blocked(
            tool_call,
            error_type="ProviderToolMutationScopeRequired",
            error_message="Provider-native mutation requires a non-empty explicit write scope.",
            recoverable=False,
            suggested_recovery="Bind an explicit non-empty write_files scope before mutation.",
        )

    arguments, argument_error = _decode_arguments(call)

    if argument_error:
        return _blocked(
            tool_call,
            error_type="InvalidToolArguments",
            error_message=argument_error,
            recoverable=True,
            suggested_recovery="Return one JSON object containing the tool arguments.",
        )

    undeclared_fields = sorted(set(arguments) - set(provider_tool_wire_fields(definition)))
    if undeclared_fields:
        return _blocked(
            tool_call,
            error_type="ProviderToolUndeclaredArgument",
            error_message=(
                f"Provider arguments not declared by {tool_name}: "
                + ", ".join(undeclared_fields[:8])
            )[:256],
            recoverable=True,
            suggested_recovery="Retry using only fields declared by the provider tool schema.",
        )

    typed_input_error: str | None = None
    try:
        input_metadata = ToolInputMetadata.from_mapping(tool_name, arguments)
    except ValidationError as exc:
        fields = _validation_error_fields(exc)
        input_metadata = ToolInputMetadata(
            tool_name=tool_name,
            attributes={"invalid_input_fields": fields},
        )
        typed_input_error = (
            f"Invalid typed input for {tool_name}: {', '.join(fields)}"
        )[:256]
    tool_call = build_tool_call(input_metadata)
    if typed_input_error:
        return _blocked(
            tool_call,
            error_type="InvalidToolArguments",
            error_message=typed_input_error,
            recoverable=True,
            suggested_recovery="Retry with values matching the typed provider tool schema.",
        )

    contract = getattr(definition, "contract_metadata", None)
    for field_name, default in (getattr(contract, "input_defaults", {}) or {}).items():
        if getattr(input_metadata, str(field_name), None) in (None, "", [], {}):
            setattr(input_metadata, str(field_name), deepcopy(default))

    value_error = _provider_input_value_error(tool_name, input_metadata)
    if value_error:
        return _blocked(
            tool_call,
            error_type="InvalidToolArguments",
            error_message=value_error,
            recoverable=True,
            suggested_recovery="Retry with values matching the typed provider tool schema.",
        )

    contract_error = _contract_error(definition, input_metadata)
    if contract_error:
        return _blocked(
            tool_call,
            error_type="MissingRequiredInput",
            error_message=contract_error,
            recoverable=True,
            suggested_recovery="Retry with all required typed tool arguments.",
        )

    counts = _resource_counts(
        definition,
        input_metadata,
        validation_command=validation_command,
    )
    if not _budget_available(budget, counts, prior_counts):
        return _blocked(
            tool_call,
            error_type="ToolBudgetExhausted",
            error_message="Provider tool call exceeds the remaining runtime tool budget.",
            recoverable=False,
            suggested_recovery="Replan within the remaining runtime budget.",
        )

    permission_level = str(getattr(definition, "permission_level", PermissionLevel.MEDIUM) or "medium").lower()
    if ToolCapability.FILE_READ in capabilities and read_scope is not None:
        scope_violation = _read_scope_violation(input_metadata, read_scope, project_path)
        if scope_violation:
            return _blocked(
                tool_call,
                error_type="ProviderToolScopeViolation",
                error_message=scope_violation,
                recoverable=write_scope is None,
                suggested_recovery="Use a file path from the explicit read_files scope or request scope clarification.",
            )
    if mutating and not required_reads_complete:
        return _blocked(
            tool_call,
            error_type="ProviderDeclaredReadEvidenceRequired",
            error_message="Every declared read must have complete typed evidence before mutation.",
            recoverable=False,
            suggested_recovery="Complete each declared read before requesting a mutation.",
        )
    if mutating and write_scope is not None:
        scope_violation = _write_scope_violation(
            input_metadata,
            write_scope,
            project_path,
        )
        if scope_violation:
            return _blocked(
                tool_call,
                error_type="ProviderToolWriteScopeViolation",
                error_message=scope_violation,
                recoverable=False,
                suggested_recovery="Use a mutation target from the explicit write_files scope.",
            )
    if tool_name == "command_executor" and require_mutation_before_validation:
        if not str(validation_command or "").strip():
            return _blocked(
                tool_call,
                error_type="ProviderMutationValidationCommandRequired",
                error_message="Mutation-mode command execution requires a bound exact validation_command.",
                recoverable=False,
                suggested_recovery="Bind the task's exact validation command before mutation execution.",
            )
        if prior_counts["mutations"] < 1:
            return _blocked(
                tool_call,
                error_type="ProviderMutationEvidenceRequiredBeforeValidation",
                error_message="Exact validation requires an admitted mutation in this or an earlier round.",
                recoverable=False,
                suggested_recovery="Complete the scoped mutation before running exact validation.",
            )
    if validation_command and tool_name == "command_executor":
        # ``command_executor`` defaults to dry_run when mode is omitted.  A
        # typed task validation command is different: it is evidence of the
        # requested state change and must execute, never silently simulate.
        # Normalize an omitted provider field to the only safe mode here;
        # explicitly requested dry_run/interactive modes remain rejected by
        # _validation_command_violation below.
        if not str(input_metadata.mode or "").strip():
            input_metadata.mode = "automatic"
        validation_violation = _validation_command_violation(
            input_metadata,
            validation_command=validation_command,
            validation_cwd=validation_cwd or project_path,
            validation_commands_used=prior_counts["validation"],
        )
        if validation_violation:
            error_type = "ProviderToolValidationDuplicate" if validation_violation.code == "duplicate" else "ProviderToolValidationViolation"
            return _blocked(
                tool_call,
                error_type=error_type,
                error_message=validation_violation.message,
                recoverable=False,
                suggested_recovery="Run the exact typed validation command once after the mutation.",
            )
    requires_confirmation = permission_level in {"medium", "high", "forbidden"} or mutating
    if permission_level == PermissionLevel.FORBIDDEN.value or permission_level == str(PermissionLevel.FORBIDDEN):
        return _blocked(
            tool_call,
            error_type="PermissionDenied",
            error_message=f"Tool {tool_name} is forbidden for provider-native execution.",
            recoverable=False,
            suggested_recovery="Use a permitted tool or request a different execution route.",
            requires_confirmation=requires_confirmation,
        )
    if requires_confirmation and not user_confirmed:
        return _blocked(
            tool_call,
            error_type="UserConfirmationRequired",
            error_message=f"Tool {tool_name} requires explicit confirmation before execution.",
            recoverable=True,
            retry_recommended=False,
            suggested_recovery="Obtain explicit user confirmation before retrying this provider call.",
            requires_confirmation=True,
        )

    selection = ToolSelection(
        step_id=tool_call.step_id,
        tool_name=tool_name,
        reason=SelectionReason.CAPABILITY_MATCH,
        confidence=1.0,
        input_metadata=input_metadata,
        # Admission only returns an executable selection after confirmation
        # has already been supplied when policy requires it.
        requires_confirmation=False,
    )
    return ProviderToolAdmission(
        status="admitted",
        provider_call_id=call.id,
        project_call_id=project_call_id,
        tool_call=tool_call,
        selection=selection,
        requires_confirmation=requires_confirmation,
    )


def _decode_arguments(call: LLMToolCall) -> tuple[dict[str, Any], str | None]:
    raw = str(call.function.arguments or "").strip()
    if not raw:
        return {}, None
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"Tool {call.function.name} arguments are not valid JSON: {exc.msg}."
    if not isinstance(decoded, dict):
        return {}, f"Tool {call.function.name} arguments must be a JSON object."
    return decoded, None


def _validation_error_fields(exc: ValidationError) -> list[str]:
    """Return bounded field/type facts without echoing untrusted values."""

    fields: list[str] = []
    for item in exc.errors(include_context=False)[:4]:
        location = ".".join(str(part) for part in item.get("loc", ())) or "input"
        error_type = str(item.get("type", "invalid"))
        fields.append(f"{location} ({error_type})"[:96])
    return fields or ["input (invalid)"]


def _provider_input_value_error(
    tool_name: str,
    input_metadata: ToolInputMetadata,
) -> str | None:
    """Apply provider-only bounds that are stricter than broad runtime inputs."""

    if tool_name == "file_reader":
        if input_metadata.offset is not None and input_metadata.offset < 0:
            return "file_reader offset must be greater than or equal to 0."
        if input_metadata.max_lines is not None and input_metadata.max_lines < 1:
            return "file_reader max_lines must be greater than 0."
    if tool_name == "web_searcher":
        safe_search = str(input_metadata.safe_search or "").strip().lower()
        if safe_search and safe_search not in SAFE_SEARCH_PARAMS:
            return "web_searcher safe_search must be one of: off, moderate, strict."
    if tool_name == "command_executor":
        mode = str(input_metadata.mode or "").strip().lower()
        allowed_modes = {item.value for item in ExecutionMode}
        if mode and mode not in allowed_modes:
            return (
                "command_executor mode must be one of: "
                + ", ".join(item.value for item in ExecutionMode)
                + "."
            )
    return None


def _contract_error(definition: Any, input_metadata: ToolInputMetadata) -> str | None:
    contract = getattr(definition, "contract_metadata", None)
    if contract is None:
        return None
    missing = [
        field
        for field in (getattr(contract, "required_input_fields", []) or [])
        if not getattr(input_metadata, field, None)
    ]
    if missing:
        return f"Missing required input field(s) for {input_metadata.tool_name}: {', '.join(missing)}"
    required_any_of = getattr(contract, "required_any_of", []) or []
    if required_any_of and not any(
        all(getattr(input_metadata, str(field), None) not in (None, "", [], {}) for field in group)
        for group in required_any_of
    ):
        readable = " or ".join(" + ".join(str(field) for field in group) for group in required_any_of)
        return f"Missing required input for {input_metadata.tool_name}: provide {readable}"
    for requirement in getattr(contract, "conditional_requirements", []) or []:
        if not isinstance(requirement, dict):
            continue
        when = requirement.get("when")
        if not isinstance(when, dict) or not when:
            continue
        active = True
        for field, expected in when.items():
            actual = getattr(input_metadata, str(field), None)
            if isinstance(expected, str):
                active = str(actual or "").strip().lower() == expected.strip().lower()
            else:
                active = actual == expected
            if not active:
                break
        if not active:
            continue
        conditional_missing = [
            str(field)
            for field in (requirement.get("required", []) or [])
            if not getattr(input_metadata, str(field), None)
        ]
        if conditional_missing:
            return (
                f"Missing required input field(s) for {input_metadata.tool_name} when "
                f"{', '.join(f'{key}={value}' for key, value in when.items())}: "
                f"{', '.join(conditional_missing)}"
            )
        conditional_any_of = requirement.get("required_any_of", []) or []
        if conditional_any_of and not any(
            all(getattr(input_metadata, str(field), None) not in (None, "", [], {}) for field in group)
            for group in conditional_any_of
        ):
            readable = " or ".join(" + ".join(str(field) for field in group) for group in conditional_any_of)
            return (
                f"Missing required input for {input_metadata.tool_name} when "
                f"{', '.join(f'{key}={value}' for key, value in when.items())}: "
                f"provide {readable}"
            )
    return None


def _resource_counts(
    definition: Any,
    input_metadata: ToolInputMetadata,
    *,
    validation_command: str | None = None,
) -> dict[str, int]:
    capabilities = set(getattr(definition, "capabilities", []) or []) if definition is not None else set()
    reads = int(ToolCapability.FILE_READ in capabilities)
    writes = bool({ToolCapability.FILE_WRITE, ToolCapability.FILE_DELETE} & capabilities)
    operation = str(input_metadata.operation_kind or "").lower()
    creates = int(writes and operation in {"create_file", "file_create", "directory_generate"})
    edits = int(writes and not creates)
    validation = int(bool(validation_command and input_metadata.tool_name == "command_executor"))
    return {
        "reads": reads,
        "edits": edits,
        "creates": creates,
        "validation": validation,
        "mutations": int(writes),
    }


def _canonical_path(raw_path: Any, project_path: str | None) -> str:
    path = Path(str(raw_path or ""))
    if not path.is_absolute() and project_path:
        path = Path(project_path) / path
    return str(path.expanduser().resolve(strict=False))


def _read_scope_violation(
    input_metadata: ToolInputMetadata,
    read_scope: Sequence[str],
    project_path: str | None,
) -> str | None:
    raw_allowed = [path for path in read_scope if str(path or "").strip()]
    boundary_error = _scope_path_boundary_error(raw_allowed, project_path, "read scope")
    if boundary_error:
        return boundary_error
    allowed = {
        _canonical_path(path, project_path)
        for path in read_scope
        if str(path or "").strip()
    }
    if not allowed:
        return None
    params = input_metadata.to_params()
    requested_raw: list[str] = []
    for field in ("file_path", "directory_path"):
        value = params.get(field)
        if value:
            requested_raw.append(str(value))
    for value in params.get("file_paths") or []:
        if value:
            requested_raw.append(str(value))
    boundary_error = _scope_path_boundary_error(requested_raw, project_path, "read request")
    if boundary_error:
        return boundary_error
    requested = [_canonical_path(value, project_path) for value in requested_raw]
    root = _canonical_path(project_path, None) if project_path else None
    outside_project = [
        path for path in requested
        if root and not Path(path).is_relative_to(Path(root))
    ]
    if outside_project:
        return "Provider read scope rejects paths outside the project root: " + ", ".join(outside_project[:4])
    outside = [path for path in requested if path not in allowed]
    if not outside:
        return None
    return (
        "Provider read scope permits only explicit files; outside path(s): "
        + ", ".join(outside[:4])
    )


def _write_scope_violation(
    input_metadata: ToolInputMetadata,
    write_scope: Sequence[str],
    project_path: str | None,
) -> str | None:
    raw_allowed = [path for path in write_scope if str(path or "").strip()]
    boundary_error = _scope_path_boundary_error(raw_allowed, project_path, "write scope")
    if boundary_error:
        return boundary_error
    allowed = {
        _canonical_path(path, project_path)
        for path in write_scope
        if str(path or "").strip()
    }
    if not allowed:
        return "Provider mutation requires a non-empty explicit write_files scope."
    params = input_metadata.to_params()
    requested_raw: list[str] = []
    for field in ("file_path", "directory_path", "project_path"):
        value = params.get(field)
        if value:
            requested_raw.append(str(value))
    for value in params.get("file_paths") or []:
        if value:
            requested_raw.append(str(value))
    boundary_error = _scope_path_boundary_error(requested_raw, project_path, "write request")
    if boundary_error:
        return boundary_error
    requested = [_canonical_path(value, project_path) for value in requested_raw]
    if not requested:
        return "Provider mutation did not provide an explicit target path."
    root = _canonical_path(project_path, None) if project_path else None
    outside_project = [
        path for path in requested
        if root and not Path(path).is_relative_to(Path(root))
    ]
    if outside_project:
        return "Provider mutation rejects paths outside the project root: " + ", ".join(outside_project[:4])
    outside = [path for path in requested if path not in allowed]
    if outside:
        return "Provider write scope permits only explicit files; outside path(s): " + ", ".join(outside[:4])
    return None


def _scope_path_boundary_error(
    raw_paths: Sequence[str],
    project_path: str | None,
    label: str,
) -> str | None:
    if not project_path:
        return None
    root = Path(project_path).expanduser().resolve(strict=False)
    for raw in raw_paths:
        candidate = Path(str(raw)).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        if candidate.is_symlink():
            return f"Provider {label} rejects symlink paths: {candidate}"
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(root):
            return f"Provider {label} rejects paths outside the project root: {resolved}"
    return None


def _validation_command_violation(
    input_metadata: ToolInputMetadata,
    *,
    validation_command: str,
    validation_cwd: str | None,
    validation_commands_used: int,
) -> _ValidationCommandViolation | None:
    if validation_commands_used > 0:
        return _ValidationCommandViolation(
            code="duplicate",
            message="The exact validation command was already admitted; duplicate validation is denied.",
        )
    expected = normalize_command_argv(validation_command)
    actual = normalize_command_argv(str(input_metadata.command or ""))
    if expected is None or actual != expected:
        return _ValidationCommandViolation(
            code="mismatch",
            message="Provider command does not exactly match the typed validation_command.",
        )
    mode = str(input_metadata.mode or "").strip().lower()
    if mode and mode != ExecutionMode.AUTOMATIC.value:
        return _ValidationCommandViolation(
            code="mode",
            message="Provider validation command must use automatic execution mode.",
        )
    requested_cwd = str(input_metadata.cwd or "").strip()
    if requested_cwd and validation_cwd:
        if _canonical_path(requested_cwd, None) != _canonical_path(validation_cwd, None):
            return _ValidationCommandViolation(
                code="cwd",
                message="Provider validation command cwd does not match the project root.",
            )
    return None


def _budget_available(
    budget: RuntimeBudgetMetadata,
    counts: dict[str, int],
    prior_counts: dict[str, int],
) -> bool:
    return (
        budget.tool_calls_used + prior_counts["calls"] < budget.max_tool_calls
        and budget.file_reads_used + prior_counts["reads"] + counts["reads"] <= budget.max_file_reads
        and budget.file_edits_used + prior_counts["edits"] + counts["edits"] <= budget.max_file_edits
        and budget.file_creates_used + prior_counts["creates"] + counts["creates"] <= budget.max_file_creates
        and (
            budget.verification_attempts_used
            + prior_counts["validation"]
            + counts["validation"]
            <= budget.max_verification_attempts
        )
    )


def _blocked(
    tool_call: ToolCallMetadata,
    *,
    error_type: str,
    error_message: str,
    recoverable: bool,
    suggested_recovery: str,
    retry_recommended: bool | None = None,
    requires_confirmation: bool = False,
) -> ProviderToolAdmission:
    error = provider_tool_error(
        tool_call,
        error_type=error_type,
        error_message=error_message,
        recoverable=recoverable,
        retry_recommended=retry_recommended,
        suggested_recovery=suggested_recovery,
    )
    return ProviderToolAdmission(
        status="blocked",
        provider_call_id=str(tool_call.provider_call_id),
        project_call_id=tool_call.call_id,
        tool_call=tool_call,
        tool_error=error,
        requires_confirmation=requires_confirmation,
    )


__all__ = [
    "ProviderToolAdmission",
    "ProviderToolAdmissionError",
    "admit_provider_tool_calls",
    "provider_tool_wire_fields",
    "provider_tool_error",
]
