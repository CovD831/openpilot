import json
from pathlib import Path

import pytest

from core.llm import LLMToolCall, LLMToolFunctionCall
from core.provider_tool_admission import (
    ProviderToolAdmissionError,
    _validation_command_violation,
    admit_provider_tool_calls,
    provider_tool_error,
)
from core.provider_tool_roundtrip import build_provider_tool_definitions
from core.tool_contracts import PermissionLevel, ToolCapability, ToolDefinition
from metadata import RuntimeBudgetMetadata, ToolCallMetadata, ToolContractMetadata, ToolInputMetadata
from tools.tool_registry import ToolRegistry
from tools.command_tool import COMMAND_EXECUTOR_DEFINITION
from tools.file_patch_writer import FILE_PATCH_WRITER_DEFINITION, file_patch_writer_executor
from tools.file_reader import FILE_READER_DEFINITION, file_reader_executor
from tools.web_searcher import WEB_SEARCHER_DEFINITION


def _registry(
    *,
    name: str = "file_reader",
    capabilities: list[ToolCapability] | None = None,
    permission: PermissionLevel = PermissionLevel.LOW,
    required: list[str] | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    if required is None:
        required = ["file_path"] if name in {"file_reader", "delete_file"} else []
    defaults = (
        {"read_mode": "full", "max_lines": None, "offset": 0}
        if name == "file_reader"
        else ({"mode": None, "timeout": 30} if name == "command_executor" else {})
    )
    definition = ToolDefinition(
        name=name,
        display_name=name,
        description=f"{name} test tool",
        capabilities=capabilities or [ToolCapability.FILE_READ],
        permission_level=permission,
        contract_metadata=ToolContractMetadata(
            tool_name=name,
            input_metadata_type="ToolInputMetadata",
            output_metadata_type="ToolResultMetadata",
            required_input_fields=required,
            input_defaults=defaults,
        ),
    )
    registry.register(definition, lambda _input: None)
    return registry


def _call(name: str = "file_reader", arguments: str = '{"file_path":"README.md"}', call_id: str = "provider_1") -> LLMToolCall:
    return LLMToolCall(
        id=call_id,
        function=LLMToolFunctionCall(name=name, arguments=arguments),
    )


def _patch_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(FILE_PATCH_WRITER_DEFINITION, file_patch_writer_executor)
    return registry


def test_file_patch_writer_provider_schema_exposes_conditional_modify_fields() -> None:
    definition = build_provider_tool_definitions(_patch_registry(), ["file_patch_writer"])[0]
    parameters = definition.function.parameters

    assert {"file_path", "operation_kind", "symbol_name", "replacement_text", "patch"}.issubset(
        parameters["properties"]
    )
    assert parameters["required"] == ["file_path"]
    modify_condition = next(
        condition
        for condition in parameters["allOf"]
        if condition["if"]["properties"]["operation_kind"] == {"const": "modify_symbol"}
    )
    assert modify_condition["then"]["required"] == ["symbol_name"]
    assert modify_condition["then"]["anyOf"] == [
        {"required": ["replacement_text"]},
        {"required": ["patch"]},
    ]


def test_file_reader_provider_schema_matches_typed_modes_and_bounds() -> None:
    registry = ToolRegistry()
    registry.register(FILE_READER_DEFINITION, file_reader_executor)
    definition = build_provider_tool_definitions(
        registry, ["file_reader"]
    )[0]
    properties = definition.function.parameters["properties"]

    assert properties["read_mode"]["enum"] == [
        "full",
        "adaptive",
        "sample",
        "tail",
        "range",
        "offset",
    ]
    # Defaults are part of the public schema as well as the type/boundary
    # contract; assert each facet independently so harmless schema metadata
    # does not make the contract test brittle.
    assert properties["offset"]["type"] == "integer"
    assert properties["offset"]["minimum"] == 0
    assert properties["offset"]["default"] == 0
    assert properties["max_lines"]["type"] == "integer"
    assert properties["max_lines"]["minimum"] == 1


def test_web_search_provider_schema_keeps_safe_search_string_enum() -> None:
    registry = ToolRegistry()
    registry.register(WEB_SEARCHER_DEFINITION, lambda _input: None)
    properties = build_provider_tool_definitions(
        registry, ["web_searcher"]
    )[0].function.parameters["properties"]

    assert properties["safe_search"] == {
        "type": "string",
        "enum": ["off", "moderate", "strict"],
        "default": "moderate",
    }


@pytest.mark.parametrize(
    ("definition", "tool_name", "arguments", "field_marker"),
    [
        (
            WEB_SEARCHER_DEFINITION,
            "web_searcher",
            '{"query":"typed boundaries","safe_search":"disabled"}',
            "safe_search",
        ),
        (
            COMMAND_EXECUTOR_DEFINITION,
            "command_executor",
            '{"command":"python -m pytest -q","mode":"standard"}',
            "mode",
        ),
    ],
)
def test_provider_enum_violation_blocks_only_invalid_sibling(
    definition: ToolDefinition,
    tool_name: str,
    arguments: str,
    field_marker: str,
) -> None:
    registry = ToolRegistry()
    registry.register(definition, lambda _input: None)
    calls = [
        _call(name=tool_name, arguments=arguments, call_id="invalid-enum"),
    ]
    if tool_name == "web_searcher":
        calls.append(
            _call(
                name=tool_name,
                arguments='{"query":"typed boundaries","safe_search":"strict"}',
                call_id="valid-enum",
            )
        )
    else:
        calls.append(
            _call(
                name=tool_name,
                arguments='{"command":"python -m pytest -q","mode":"dry_run"}',
                call_id="valid-enum",
            )
        )

    admissions = admit_provider_tool_calls(
        calls,
        task_id="task-enum-boundary",
        session_id="session-enum-boundary",
        round_index=1,
        registry=registry,
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=[tool_name],
        user_confirmed=True,
    )

    assert [item.status for item in admissions] == ["blocked", "admitted"]
    assert admissions[0].tool_error is not None
    assert admissions[0].tool_error.error_type == "InvalidToolArguments"
    assert field_marker in admissions[0].tool_error.error_message


def test_mutation_validation_admission_requires_bound_exact_command(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(COMMAND_EXECUTOR_DEFINITION, lambda _input: None)

    admission = admit_provider_tool_calls(
        [
            _call(
                name="command_executor",
                arguments='{"command":"python -m pytest -q","mode":"automatic"}',
            )
        ],
        task_id="task-missing-validation-binding",
        session_id="session-missing-validation-binding",
        round_index=1,
        registry=registry,
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=["command_executor"],
        user_confirmed=True,
        project_path=str(tmp_path),
        require_mutation_before_validation=True,
        mutation_observed=True,
    )[0]

    assert admission.status == "blocked"
    assert admission.tool_error is not None
    assert admission.tool_error.error_type == "ProviderMutationValidationCommandRequired"


def test_file_patch_writer_admission_enforces_conditional_modify_fields(tmp_path) -> None:
    target = tmp_path / "calculator.py"
    registry = _patch_registry()
    common = {
        "task_id": "task-patch-contract",
        "session_id": "session-patch-contract",
        "round_index": 1,
        "registry": registry,
        "budget": RuntimeBudgetMetadata(),
        "advertised_tool_names": ["file_patch_writer"],
        "allow_mutations": True,
        "user_confirmed": True,
        "write_scope": [str(target)],
        "project_path": str(tmp_path),
    }

    missing = admit_provider_tool_calls(
        [_call(
            name="file_patch_writer",
            arguments='{"file_path":"calculator.py","operation_kind":"modify_symbol","symbol_name":"divide"}',
            call_id="patch_missing",
        )],
        **common,
    )[0]
    assert missing.status == "blocked"
    assert missing.tool_error is not None
    assert missing.tool_error.error_type == "MissingRequiredInput"

    omitted_operation = admit_provider_tool_calls(
        [_call(
            name="file_patch_writer",
            arguments='{"file_path":"calculator.py"}',
            call_id="patch_default_missing",
        )],
        **common,
    )[0]
    assert omitted_operation.status == "blocked"
    assert omitted_operation.tool_error is not None
    assert omitted_operation.tool_error.error_type == "MissingRequiredInput"

    valid = admit_provider_tool_calls(
        [_call(
            name="file_patch_writer",
            arguments=(
                '{"file_path":"calculator.py","operation_kind":"modify_symbol",'
                '"symbol_name":"divide","replacement_text":"def divide(a, b):\\n    return a / b"}'
            ),
            call_id="patch_valid",
        )],
        **common,
    )[0]
    assert valid.status == "admitted"
    assert valid.selection is not None
    assert valid.selection.input_metadata.symbol_name == "divide"
    assert valid.selection.input_metadata.replacement_text


def test_provider_call_binds_external_id_without_replacing_project_call_id() -> None:
    admissions = admit_provider_tool_calls(
        [_call()],
        task_id="task_1",
        session_id="session_1",
        round_index=2,
        registry=_registry(required=["file_path"]),
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=["file_reader"],
    )

    admission = admissions[0]
    assert admission.status == "admitted"
    assert admission.provider_call_id == "provider_1"
    assert admission.project_call_id == "task_1:r2:c1"
    assert admission.tool_call.provider_call_id == "provider_1"
    assert admission.tool_call.call_id == "task_1:r2:c1"
    assert admission.selection is not None
    assert admission.selection.requires_confirmation is False
    assert admission.selection.input_metadata.file_path == "README.md"


def test_provider_read_scope_allows_explicit_relative_path(tmp_path) -> None:
    project = tmp_path / "project"
    target = project / "README.md"
    registry = _registry(required=["file_path"])

    admission = admit_provider_tool_calls(
        [_call(arguments='{"file_path":"README.md"}')],
        task_id="task_scope",
        session_id="session_scope",
        round_index=1,
        registry=registry,
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=["file_reader"],
        read_scope=[str(target)],
        project_path=str(project),
    )[0]

    assert admission.status == "admitted"


def test_provider_read_scope_blocks_path_outside_explicit_files(tmp_path) -> None:
    project = tmp_path / "project"
    registry = _registry(required=["file_path"])

    admission = admit_provider_tool_calls(
        [_call(arguments='{"file_path":"src/main.py"}')],
        task_id="task_scope",
        session_id="session_scope",
        round_index=1,
        registry=registry,
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=["file_reader"],
        read_scope=[str(project / "README.md")],
        project_path=str(project),
    )[0]

    assert admission.status == "blocked"
    assert admission.tool_error is not None
    assert admission.tool_error.error_type == "ProviderToolScopeViolation"
    assert admission.tool_error.recoverable is True


@pytest.mark.parametrize(
    "arguments,error_type",
    [
        ('{"file_path":', "InvalidToolArguments"),
        ('[]', "InvalidToolArguments"),
        ('{}', "MissingRequiredInput"),
    ],
)
def test_provider_call_rejects_bad_arguments_before_execution(arguments: str, error_type: str) -> None:
    admission = admit_provider_tool_calls(
        [_call(arguments=arguments)],
        task_id="task_1",
        session_id="session_1",
        round_index=1,
        registry=_registry(required=["file_path"]),
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=["file_reader"],
    )[0]

    assert admission.status == "blocked"
    assert admission.selection is None
    assert admission.tool_error is not None
    assert admission.tool_error.error_type == error_type
    assert admission.tool_error.provider_call_id == "provider_1"


@pytest.mark.parametrize(
    "arguments,field_marker",
    [
        ('{"file_path":"README.md","read_mode":"standard"}', "read_mode"),
        ('{"file_path":"README.md","max_lines":"many"}', "max_lines"),
        ('{"file_path":"README.md","offset":1.5}', "offset"),
    ],
)
def test_provider_call_maps_invalid_typed_values_to_bounded_block(
    arguments: str,
    field_marker: str,
) -> None:
    admission = admit_provider_tool_calls(
        [_call(arguments=arguments)],
        task_id="task_typed_input",
        session_id="session_typed_input",
        round_index=1,
        registry=_registry(required=["file_path"]),
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=["file_reader"],
    )[0]

    assert admission.status == "blocked"
    assert admission.tool_error is not None
    assert admission.tool_error.error_type == "InvalidToolArguments"
    assert field_marker in admission.tool_error.error_message
    assert len(admission.tool_error.error_message) <= 256
    assert "input_value" not in admission.tool_error.error_message


@pytest.mark.parametrize(
    "arguments",
    [
        '{"file_path":"README.md","offset":-1}',
        '{"file_path":"README.md","max_lines":0}',
    ],
)
def test_provider_file_reader_rejects_invalid_ranges(arguments: str) -> None:
    admission = admit_provider_tool_calls(
        [_call(arguments=arguments)],
        task_id="task_range_input",
        session_id="session_range_input",
        round_index=1,
        registry=_registry(required=["file_path"]),
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=["file_reader"],
    )[0]

    assert admission.status == "blocked"
    assert admission.tool_error is not None
    assert admission.tool_error.error_type == "InvalidToolArguments"


def test_provider_invalid_typed_call_does_not_abort_valid_sibling() -> None:
    admissions = admit_provider_tool_calls(
        [
            _call(
                arguments='{"file_path":"README.md","read_mode":"standard"}',
                call_id="invalid-read-mode",
            ),
            _call(
                arguments='{"file_path":"README.md"}',
                call_id="valid-read",
            ),
        ],
        task_id="task_typed_siblings",
        session_id="session_typed_siblings",
        round_index=1,
        registry=_registry(required=["file_path"]),
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=["file_reader"],
    )

    assert [admission.status for admission in admissions] == ["blocked", "admitted"]
    assert admissions[0].tool_error is not None
    assert admissions[0].tool_error.error_type == "InvalidToolArguments"
    assert admissions[1].selection is not None


def test_provider_call_rejects_unknown_and_forbidden_tools() -> None:
    unknown = admit_provider_tool_calls(
        [_call(name="not_registered")],
        task_id="task_1",
        session_id="session_1",
        round_index=1,
        registry=_registry(),
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=[],
    )[0]
    forbidden = admit_provider_tool_calls(
        [_call(name="delete_file")],
        task_id="task_1",
        session_id="session_1",
        round_index=1,
        registry=_registry(
            name="delete_file",
            capabilities=[ToolCapability.FILE_DELETE],
            permission=PermissionLevel.FORBIDDEN,
        ),
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=["delete_file"],
        allow_mutations=True,
        write_scope=["README.md"],
    )[0]

    assert unknown.tool_error is not None and unknown.tool_error.error_type == "UnknownTool"
    assert forbidden.tool_error is not None and forbidden.tool_error.error_type == "PermissionDenied"
    assert forbidden.tool_error.recoverable is False


def test_unknown_tool_identity_precedes_global_typed_field_validation() -> None:
    admissions = admit_provider_tool_calls(
        [
            _call(
                name="not_registered",
                arguments='{"max_lines":"many"}',
                call_id="unknown-invalid-global-field",
            ),
            _call(
                name="file_reader",
                arguments='{"file_path":"README.md"}',
                call_id="valid-sibling",
            ),
        ],
        task_id="task-unknown-precedence",
        session_id="session-unknown-precedence",
        round_index=1,
        registry=_registry(required=["file_path"]),
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=["file_reader"],
    )

    assert admissions[0].status == "blocked"
    assert admissions[0].tool_error is not None
    assert admissions[0].tool_error.error_type == "UnknownTool"
    assert admissions[1].status == "admitted"


def test_unknown_tool_identity_precedes_malformed_json_validation() -> None:
    admission = admit_provider_tool_calls(
        [
            _call(
                name="not_registered",
                arguments='{"unterminated":',
                call_id="unknown-malformed-json",
            )
        ],
        task_id="task-unknown-malformed-precedence",
        session_id="session-unknown-malformed-precedence",
        round_index=1,
        registry=_registry(required=["file_path"]),
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=[],
    )[0]

    assert admission.status == "blocked"
    assert admission.tool_error is not None
    assert admission.tool_error.error_type == "UnknownTool"


def test_provider_mutation_requires_confirmation_and_budget_is_checked_without_consuming() -> None:
    registry = _registry(
        name="file_writer",
        capabilities=[ToolCapability.FILE_WRITE],
        permission=PermissionLevel.MEDIUM,
        required=["file_path", "content"],
    )
    budget = RuntimeBudgetMetadata(max_file_edits=1)
    call = _call(
        name="file_writer",
        arguments='{"file_path":"calculator.py","content":"pass"}',
    )

    blocked = admit_provider_tool_calls(
        [call],
        task_id="task_1",
        session_id="session_1",
        round_index=1,
        registry=registry,
        budget=budget,
        advertised_tool_names=["file_writer"],
        allow_mutations=True,
        write_scope=["calculator.py"],
    )[0]
    admitted = admit_provider_tool_calls(
        [call],
        task_id="task_1",
        session_id="session_1",
        round_index=1,
        registry=registry,
        budget=budget,
        advertised_tool_names=["file_writer"],
        allow_mutations=True,
        user_confirmed=True,
        write_scope=["calculator.py"],
    )[0]

    assert blocked.tool_error is not None
    assert blocked.tool_error.error_type == "UserConfirmationRequired"
    assert admitted.status == "admitted"
    assert budget.tool_calls_used == 0
    assert budget.file_edits_used == 0

    exhausted = admit_provider_tool_calls(
        [call],
        task_id="task_1",
        session_id="session_1",
        round_index=1,
        registry=registry,
        budget=RuntimeBudgetMetadata(max_file_edits=0),
        advertised_tool_names=["file_writer"],
        allow_mutations=True,
        user_confirmed=True,
        write_scope=["calculator.py"],
    )[0]
    assert exhausted.tool_error is not None
    assert exhausted.tool_error.error_type == "ToolBudgetExhausted"


def test_provider_mutation_admission_requires_explicit_opt_in_and_write_scope(tmp_path) -> None:
    registry = _patch_registry()
    target = str(tmp_path / "calculator.py")
    call = _call(
        name="file_patch_writer",
        arguments=(
            '{"file_path":"calculator.py","operation_kind":"modify_symbol",'
            '"symbol_name":"divide","replacement_text":"def divide(a, b):\\n    return a / b"}'
        ),
        call_id="direct-mutation-boundary",
    )
    common = dict(
        task_id="task-direct-mutation-boundary",
        session_id="session-direct-mutation-boundary",
        round_index=1,
        registry=registry,
        budget=RuntimeBudgetMetadata(),
        user_confirmed=True,
        project_path=str(tmp_path),
        advertised_tool_names=["file_patch_writer"],
    )

    no_opt_in = admit_provider_tool_calls(
        [call],
        **common,
        write_scope=[target],
        allow_mutations=False,
    )[0]
    no_scope = admit_provider_tool_calls(
        [call],
        **common,
        write_scope=None,
        allow_mutations=True,
    )[0]
    empty_scope = admit_provider_tool_calls(
        [call],
        **common,
        write_scope=[],
        allow_mutations=True,
    )[0]

    assert no_opt_in.tool_error is not None
    assert no_opt_in.tool_error.error_type == "ProviderToolMutationOptInRequired"
    assert no_scope.tool_error is not None
    assert no_scope.tool_error.error_type == "ProviderToolMutationScopeRequired"
    assert empty_scope.tool_error is not None
    assert empty_scope.tool_error.error_type == "ProviderToolMutationScopeRequired"


def test_provider_mutation_read_scope_is_enforced_even_when_write_is_enabled(tmp_path) -> None:
    registry = ToolRegistry()
    definition = ToolDefinition(
        name="file_reader",
        display_name="file_reader",
        description="read",
        capabilities=[ToolCapability.FILE_READ],
        permission_level=PermissionLevel.LOW,
        contract_metadata=ToolContractMetadata(
            tool_name="file_reader",
            input_metadata_type="ToolInputMetadata",
            output_metadata_type="ToolResultMetadata",
            required_input_fields=["file_path"],
        ),
    )
    registry.register(definition, lambda _input: None)
    admission = admit_provider_tool_calls(
        [_call(arguments='{"file_path":"tests/test_calculator.py"}')],
        task_id="task_scope_mutation",
        session_id="session_scope_mutation",
        round_index=1,
        registry=registry,
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=["file_reader"],
        user_confirmed=True,
        read_scope=[str(tmp_path / "calculator.py")],
        write_scope=[str(tmp_path / "calculator.py")],
        project_path=str(tmp_path),
    )[0]
    assert admission.status == "blocked"
    assert admission.tool_error is not None
    assert admission.tool_error.error_type == "ProviderToolScopeViolation"


def test_provider_mutation_write_scope_denies_unlisted_target(tmp_path) -> None:
    registry = _registry(
        name="file_writer",
        capabilities=[ToolCapability.FILE_WRITE],
        permission=PermissionLevel.MEDIUM,
        required=["file_path", "content"],
    )
    admission = admit_provider_tool_calls(
        [_call(name="file_writer", arguments='{"file_path":"README.md","content":"no"}')],
        task_id="task_write_scope",
        session_id="session_write_scope",
        round_index=1,
        registry=registry,
        budget=RuntimeBudgetMetadata(max_file_edits=1),
        advertised_tool_names=["file_writer"],
        allow_mutations=True,
        user_confirmed=True,
        write_scope=[str(tmp_path / "calculator.py")],
        project_path=str(tmp_path),
    )[0]
    assert admission.status == "blocked"
    assert admission.tool_error is not None
    assert admission.tool_error.error_type == "ProviderToolWriteScopeViolation"


def test_provider_scope_rejects_symlink_authority_and_target(tmp_path) -> None:
    target = tmp_path / "calculator.py"
    target.write_text("pass", encoding="utf-8")
    link = tmp_path / "alias.py"
    link.symlink_to(target)
    registry = _registry(required=["file_path"])
    admission = admit_provider_tool_calls(
        [_call(arguments='{"file_path":"alias.py"}')],
        task_id="task_symlink_scope",
        session_id="session_symlink_scope",
        round_index=1,
        registry=registry,
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=["file_reader"],
        read_scope=[str(link)],
        project_path=str(tmp_path),
    )[0]
    assert admission.status == "blocked"
    assert admission.tool_error is not None
    assert admission.tool_error.error_type == "ProviderToolScopeViolation"


def test_provider_read_scope_rejects_symlink_authority_for_real_target(tmp_path) -> None:
    target = tmp_path / "calculator.py"
    target.write_text("pass", encoding="utf-8")
    link = tmp_path / "alias.py"
    link.symlink_to(target)
    registry = _registry(required=["file_path"])

    admission = admit_provider_tool_calls(
        [_call(arguments='{"file_path":"calculator.py"}')],
        task_id="task_reverse_symlink_read_scope",
        session_id="session_reverse_symlink_read_scope",
        round_index=1,
        registry=registry,
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=["file_reader"],
        read_scope=[str(link)],
        project_path=str(tmp_path),
    )[0]

    assert admission.status == "blocked"
    assert admission.tool_error is not None
    assert admission.tool_error.error_type == "ProviderToolScopeViolation"


def test_provider_write_scope_rejects_symlink_authority_for_real_target(tmp_path) -> None:
    target = tmp_path / "calculator.py"
    target.write_text("pass", encoding="utf-8")
    link = tmp_path / "alias.py"
    link.symlink_to(target)
    registry = _registry(
        name="file_writer",
        capabilities=[ToolCapability.FILE_WRITE],
        permission=PermissionLevel.MEDIUM,
        required=["file_path", "content"],
    )

    admission = admit_provider_tool_calls(
        [_call(name="file_writer", arguments='{"file_path":"calculator.py","content":"updated"}')],
        task_id="task_reverse_symlink_write_scope",
        session_id="session_reverse_symlink_write_scope",
        round_index=1,
        registry=registry,
        budget=RuntimeBudgetMetadata(max_file_edits=1),
        advertised_tool_names=["file_writer"],
        allow_mutations=True,
        user_confirmed=True,
        write_scope=[str(link)],
        project_path=str(tmp_path),
    )[0]

    assert admission.status == "blocked"
    assert admission.tool_error is not None
    assert admission.tool_error.error_type == "ProviderToolWriteScopeViolation"


def test_provider_validation_command_is_exact_and_not_repeated(tmp_path) -> None:
    registry = _registry(
        name="command_executor",
        capabilities=[ToolCapability.SHELL_EXECUTION],
        permission=PermissionLevel.HIGH,
        required=["command"],
    )
    common = dict(
        task_id="task_validation",
        session_id="session_validation",
        round_index=1,
        registry=registry,
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=["command_executor"],
        user_confirmed=True,
        project_path=str(tmp_path),
        validation_command="python -m pytest -q tests/test_calculator.py",
        validation_cwd=str(tmp_path),
    )
    wrong = admit_provider_tool_calls(
        [_call(name="command_executor", arguments='{"command":"python -m pytest -q"}')],
        **common,
    )[0]
    assert wrong.status == "blocked"
    assert wrong.tool_error is not None
    assert wrong.tool_error.error_type == "ProviderToolValidationViolation"

    valid_call = _call(
        name="command_executor",
        arguments='{"command":"python -m pytest -q tests/test_calculator.py"}',
        call_id="validation-1",
    )
    admitted = admit_provider_tool_calls([valid_call], **common)[0]
    assert admitted.status == "admitted"
    assert admitted.selection is not None
    assert admitted.selection.input_metadata.mode == "automatic"

    dry_run = _call(
        name="command_executor",
        arguments='{"command":"python -m pytest -q tests/test_calculator.py","mode":"dry_run"}',
        call_id="validation-dry-run",
    )
    dry_run_admission = admit_provider_tool_calls([dry_run], **common)[0]
    assert dry_run_admission.status == "blocked"
    assert dry_run_admission.tool_error is not None
    assert dry_run_admission.tool_error.error_type == "ProviderToolValidationViolation"

    repeated = admit_provider_tool_calls(
        [valid_call],
        **common,
        validation_commands_used=1,
    )[0]
    assert repeated.status == "blocked"
    assert repeated.tool_error is not None
    assert repeated.tool_error.error_type == "ProviderToolValidationDuplicate"


def test_provider_rejects_wire_fields_not_declared_by_specific_tool_contract(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(COMMAND_EXECUTOR_DEFINITION, lambda _input: None)
    admission = admit_provider_tool_calls(
        [
            _call(
                name="command_executor",
                arguments=json.dumps(
                    {
                        "command": "python -m pytest -q tests/test_calculator.py",
                        "mode": "automatic",
                        "env": {"PYTEST_ADDOPTS": "--ignore=Code/tests"},
                    }
                ),
            )
        ],
        task_id="task-validation-extra-wire-field",
        session_id="session-validation-extra-wire-field",
        round_index=1,
        registry=registry,
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=["command_executor"],
        user_confirmed=True,
        project_path=str(tmp_path),
        validation_command="python -m pytest -q tests/test_calculator.py",
        validation_cwd=str(tmp_path),
    )[0]

    assert admission.status == "blocked"
    assert admission.tool_error is not None
    assert admission.tool_error.error_type == "ProviderToolUndeclaredArgument"
    assert "env" in admission.tool_error.error_message


def test_provider_exact_validation_respects_verification_attempt_budget(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(COMMAND_EXECUTOR_DEFINITION, lambda _input: None)
    admission = admit_provider_tool_calls(
        [
            _call(
                name="command_executor",
                arguments=json.dumps(
                    {
                        "command": "python -m pytest -q tests/test_calculator.py",
                        "mode": "automatic",
                    }
                ),
            )
        ],
        task_id="task-validation-budget-zero",
        session_id="session-validation-budget-zero",
        round_index=1,
        registry=registry,
        budget=RuntimeBudgetMetadata(max_verification_attempts=0),
        advertised_tool_names=["command_executor"],
        user_confirmed=True,
        project_path=str(tmp_path),
        validation_command="python -m pytest -q tests/test_calculator.py",
        validation_cwd=str(tmp_path),
    )[0]

    assert admission.status == "blocked"
    assert admission.tool_error is not None
    assert admission.tool_error.error_type == "ToolBudgetExhausted"


def test_provider_validation_duplicate_routing_uses_typed_violation_code(tmp_path: Path) -> None:
    input_metadata = ToolInputMetadata(
        tool_name="command_executor",
        command="python -m pytest -q tests/test_calculator.py",
    )

    violation = _validation_command_violation(
        input_metadata,
        validation_command="python -m pytest -q tests/test_calculator.py",
        validation_cwd=str(tmp_path),
        validation_commands_used=1,
    )

    assert violation is not None
    assert violation.code == "duplicate"
    assert violation.message


@pytest.mark.parametrize(
    "command",
    [
        "cd /project && python -m pytest -q tests/test_calculator.py",
        "cd /tmp && python -m pytest -q tests/test_calculator.py",
        "python -m pytest -q tests/test_calculator.py && echo extra",
        "python -m pytest -q tests/test_calculator.py; echo extra",
        "python -m pytest -q tests/test_calculator.py | tee result.txt",
        "python -m pytest -q tests/test_calculator.py > result.txt",
        "python -m pytest -q tests/test_calculator.py $(echo extra)",
    ],
)
def test_provider_validation_rejects_shell_wrappers_and_extra_operations(tmp_path, command: str) -> None:
    registry = _registry(
        name="command_executor",
        capabilities=[ToolCapability.SHELL_EXECUTION],
        permission=PermissionLevel.HIGH,
        required=["command"],
    )
    admission = admit_provider_tool_calls(
        [_call(name="command_executor", arguments=json.dumps({"command": command}))],
        task_id="task-validation-boundary",
        session_id="session-validation-boundary",
        round_index=1,
        registry=registry,
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=["command_executor"],
        user_confirmed=True,
        project_path=str(tmp_path),
        validation_command="python -m pytest -q tests/test_calculator.py",
        validation_cwd=str(tmp_path),
    )[0]

    assert admission.status == "blocked"
    assert admission.tool_error is not None
    assert admission.tool_error.error_type == "ProviderToolValidationViolation"


def test_provider_validation_accepts_missing_cwd_for_roundtrip_binding(tmp_path) -> None:
    registry = _registry(
        name="command_executor",
        capabilities=[ToolCapability.SHELL_EXECUTION],
        permission=PermissionLevel.HIGH,
        required=["command"],
    )
    admission = admit_provider_tool_calls(
        [
            _call(
                name="command_executor",
                arguments=json.dumps({"command": "python -m pytest -q tests/test_calculator.py"}),
            )
        ],
        task_id="task-validation-cwd-optional",
        session_id="session-validation-cwd-optional",
        round_index=1,
        registry=registry,
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=["command_executor"],
        user_confirmed=True,
        project_path=str(tmp_path),
        validation_command="python -m pytest -q tests/test_calculator.py",
        validation_cwd=str(tmp_path),
    )[0]

    assert admission.status == "admitted"
    assert admission.selection is not None
    assert admission.selection.input_metadata.cwd is None


def test_provider_validation_rejects_provider_supplied_cwd_even_at_same_root(tmp_path) -> None:
    registry = _registry(
        name="command_executor",
        capabilities=[ToolCapability.SHELL_EXECUTION],
        permission=PermissionLevel.HIGH,
        required=["command"],
    )
    common = dict(
        task_id="task-validation-cwd-boundary",
        session_id="session-validation-cwd-boundary",
        round_index=1,
        registry=registry,
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=["command_executor"],
        user_confirmed=True,
        project_path=str(tmp_path),
        validation_command="python -m pytest -q tests/test_calculator.py",
        validation_cwd=str(tmp_path),
    )

    wrong = admit_provider_tool_calls(
        [
            _call(
                name="command_executor",
                arguments=json.dumps(
                    {
                        "command": "python -m pytest -q tests/test_calculator.py",
                        "cwd": str(tmp_path / "other"),
                    }
                ),
            )
        ],
        **common,
    )[0]
    assert wrong.status == "blocked"
    assert wrong.tool_error is not None
    assert wrong.tool_error.error_type == "ProviderToolUndeclaredArgument"

    canonical = admit_provider_tool_calls(
        [
            _call(
                name="command_executor",
                arguments=json.dumps(
                    {
                        "command": "python -m pytest -q tests/test_calculator.py",
                        "cwd": str(tmp_path),
                    }
                ),
                call_id="validation-cwd-canonical",
            )
        ],
        **common,
    )[0]
    assert canonical.status == "blocked"
    assert canonical.tool_error is not None
    assert canonical.tool_error.error_type == "ProviderToolUndeclaredArgument"


def test_provider_batch_duplicate_ids_fail_closed() -> None:
    with pytest.raises(ProviderToolAdmissionError, match="IDs must be unique"):
        admit_provider_tool_calls(
            [_call(call_id="same"), _call(call_id="same")],
            task_id="task_1",
            session_id="session_1",
            round_index=1,
            registry=_registry(),
            budget=RuntimeBudgetMetadata(),
            advertised_tool_names=["file_reader"],
        )


@pytest.mark.parametrize("field_name", ["allow_mutations", "user_confirmed"])
@pytest.mark.parametrize("invalid_value", [1, "true", "false"])
def test_provider_admission_rejects_non_boolean_authority_flags(
    field_name: str,
    invalid_value: object,
) -> None:
    authority = {"allow_mutations": False, "user_confirmed": False}
    authority[field_name] = invalid_value

    with pytest.raises(ProviderToolAdmissionError, match=f"{field_name} must be a boolean"):
        admit_provider_tool_calls(
            [_call()],
            task_id="task-non-boolean-mutation-authority",
            session_id="session-non-boolean-mutation-authority",
            round_index=1,
            registry=_registry(),
            budget=RuntimeBudgetMetadata(),
            advertised_tool_names=["file_reader"],
            **authority,  # type: ignore[arg-type]
        )


def test_provider_admission_requires_explicit_advertised_surface() -> None:
    with pytest.raises(TypeError, match="advertised_tool_names"):
        admit_provider_tool_calls(  # type: ignore[call-arg]
            [_call()],
            task_id="task-missing-advertised-surface",
            session_id="session-missing-advertised-surface",
            round_index=1,
            registry=_registry(),
            budget=RuntimeBudgetMetadata(),
        )


def test_provider_admission_explicit_empty_surface_blocks_registered_tool() -> None:
    admission = admit_provider_tool_calls(
        [_call()],
        task_id="task-empty-advertised-surface",
        session_id="session-empty-advertised-surface",
        round_index=1,
        registry=_registry(),
        budget=RuntimeBudgetMetadata(),
        advertised_tool_names=[],
    )[0]

    assert admission.status == "blocked"
    assert admission.tool_error is not None
    assert admission.tool_error.error_type == "ProviderToolNotAdvertised"


def test_provider_execution_failure_preserves_both_correlation_ids() -> None:
    tool_call = ToolCallMetadata(
        session_id="session_1",
        task_id="task_1",
        step_id="step_1_1",
        call_id="task_1:r1:c1",
        provider_call_id="provider_1",
        tool_name="file_reader",
        input_metadata=ToolInputMetadata(tool_name="file_reader", file_path="README.md"),
    )
    error = provider_tool_error(
        tool_call,
        error_type="ToolExecutionFailed",
        error_message="read failed",
        recoverable=True,
        suggested_recovery="retry read",
    )

    assert error.call_id == "task_1:r1:c1"
    assert error.provider_call_id == "provider_1"
    assert error.failure is not None
    assert error.failure.details["provider_call_id"] == "provider_1"
