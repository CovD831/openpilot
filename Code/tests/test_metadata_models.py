from __future__ import annotations

import pytest

from metadata import (
    BugFixAttemptMetadata,
    BugFixResultMetadata,
    CodeArtifactMetadata,
    CommandArtifactMetadata,
    FailureMetadata,
    MetadataKind,
    ProductIntentMetadata,
    ResultStatus,
    TaskResultMetadata,
    TaskRouteMetadata,
    ToolInputMetadata,
    ToolResultMetadata,
    ValidationIssueMetadata,
    WarningCheckResultMetadata,
    WarningItemMetadata,
    artifact_to_tool_input,
)


def test_metadata_base_fields_and_json_serialization() -> None:
    artifact = CodeArtifactMetadata(code="print('ok')", language="python")

    payload = artifact.to_json_dict()

    assert payload["kind"] == MetadataKind.CODE_ARTIFACT
    assert payload["schema_version"] == "1.0"
    assert payload["code"] == "print('ok')"
    assert payload["content"] == "print('ok')"


def test_task_route_metadata_serializes_typed_route_fields() -> None:
    route = TaskRouteMetadata(
        route="agent_generator",
        confidence=0.88,
        reason="Task asks for a reusable agent.",
    )

    payload = route.to_json_dict()

    assert payload["kind"] == MetadataKind.TASK_ROUTE
    assert payload["route"] == "agent_generator"
    assert payload["confidence"] == 0.88


def test_tool_result_requires_result_or_failure_by_status() -> None:
    success = ToolResultMetadata(
        tool_name="code_generator",
        status=ResultStatus.SUCCESS,
        result=CodeArtifactMetadata(code="print('ok')", language="python"),
    )

    assert isinstance(success.result, CodeArtifactMetadata)

    failure = ToolResultMetadata(
        tool_name="code_generator",
        status=ResultStatus.FAIL,
        failure=FailureMetadata(error_type="InvalidInput", error_message="missing task"),
    )
    assert failure.failure.error_type == "InvalidInput"

    with pytest.raises(ValueError):
        ToolResultMetadata(tool_name="code_generator", status=ResultStatus.SUCCESS)


def test_task_result_and_tool_chain_routing_use_metadata_types() -> None:
    tool_result = ToolResultMetadata(
        tool_name="code_generator",
        status=ResultStatus.SUCCESS,
        result=CodeArtifactMetadata(code="print('ok')", language="python"),
    )

    task_result = TaskResultMetadata(
        task_id="task",
        status=ResultStatus.SUCCESS,
        result=tool_result,
    )
    writer_input = artifact_to_tool_input("file_writer", task_result.result)
    executor_input = artifact_to_tool_input("code_executor", task_result.result)

    assert isinstance(writer_input, ToolInputMetadata)
    assert writer_input.content == "print('ok')"
    assert writer_input.code is None
    assert executor_input.code == "print('ok')"
    assert executor_input.language == "python"


def test_bug_fix_metadata_serializes_attempts_and_failure_result() -> None:
    command_result = CommandArtifactMetadata(
        command="python app.py",
        success=False,
        stderr="SyntaxError",
        exit_code=1,
    )
    attempt = BugFixAttemptMetadata(
        iteration=1,
        command_result=command_result,
        error_summary="SyntaxError",
        modified_files=["app.py"],
        rationale="Fix broken syntax",
    )
    result = BugFixResultMetadata(
        command="python app.py",
        target_files=["app.py"],
        fixed=False,
        iterations_used=1,
        attempts=[attempt],
        final_command_result=command_result,
        requires_user_decision=True,
    )

    envelope = ToolResultMetadata(
        tool_name="bug_fix_tool",
        status=ResultStatus.FAIL,
        result=result,
        failure=FailureMetadata(
            error_type="MaxBugFixIterationsReached",
            error_message="still failing",
            retry_recommended=True,
        ),
    )
    payload = envelope.to_json_dict()

    assert payload["result"]["kind"] == MetadataKind.BUG_FIX_RESULT
    assert payload["result"]["attempts"][0]["kind"] == MetadataKind.BUG_FIX_ATTEMPT
    assert payload["result"]["requires_user_decision"] is True


def test_warning_check_metadata_serializes_items() -> None:
    item = WarningItemMetadata(
        warning_text="System fonts cannot be loaded",
        warning_source="pygame.sysfont",
        category="font_rendering",
        severity="fix_required",
        affects_user_experience=True,
        requires_fix=True,
        reason="Text may render as boxes.",
    )
    result = WarningCheckResultMetadata(
        command="python main.py",
        cwd="/tmp/project",
        warnings=[item],
        requires_fix=True,
        reason=item.reason,
        recommended_fix="Use a bundled font or pygame.font.Font(None, size).",
    )

    payload = result.to_json_dict()

    assert payload["kind"] == MetadataKind.WARNING_CHECK_RESULT
    assert payload["warnings"][0]["kind"] == MetadataKind.WARNING_ITEM
    assert payload["requires_fix"] is True


def test_product_intent_and_validation_issue_metadata_serialize() -> None:
    intent = ProductIntentMetadata(
        experience_type="interactive_app",
        runtime_mode="standalone_gui",
        delivery_surface="native_window",
        core_capabilities=["visible_feedback"],
        non_regression_constraints=["Preserve native window delivery."],
        disallowed_substitutions=["terminal_ui"],
    )
    issue = ValidationIssueMetadata(
        category="product_intent_drift",
        severity="blocking",
        message="Implementation changed delivery surface.",
        recommended_action="Regenerate while preserving product intent.",
        product_intent=intent,
        preserves_product_intent=False,
    )

    payload = issue.to_json_dict()

    assert payload["kind"] == MetadataKind.VALIDATION_ISSUE
    assert payload["product_intent"]["kind"] == MetadataKind.PRODUCT_INTENT
    assert payload["product_intent"]["disallowed_substitutions"] == ["terminal_ui"]
