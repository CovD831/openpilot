from __future__ import annotations

import json

import pytest

from metadata import (
    BugFixAttemptMetadata,
    BugFixResultMetadata,
    CodeArtifactMetadata,
    CommandArtifactMetadata,
    DependencyStrategyMetadata,
    FailureMetadata,
    GitDiffContextMetadata,
    GitRepositoryMetadata,
    GitSnapshotMetadata,
    MetadataKind,
    ProductIntentMetadata,
    ProjectDiagnosisMetadata,
    ProjectDimensionAssessmentMetadata,
    ProjectDependencyMetadata,
    ProjectObjectiveMetadata,
    ImprovementCandidateMetadata,
    ReferenceInsightMetadata,
    RelatedProjectFileMetadata,
    ResultStatus,
    RuntimeStateMetadata,
    SuccessMetricMetadata,
    TaskResultMetadata,
    TaskRouteMetadata,
    TaskFileResolutionMetadata,
    TaskFileResolutionRequestMetadata,
    ToolCallMetadata,
    ToolContextMetadata,
    ToolErrorMetadata,
    ToolEventMetadata,
    ToolInputMetadata,
    ToolLoopMetadata,
    ToolResultMetadata,
    ValidationIssueMetadata,
    WarningCheckResultMetadata,
    WarningItemMetadata,
    artifact_to_tool_input,
    json_safe,
    metadata_summary,
)


def test_metadata_base_fields_and_json_serialization() -> None:
    artifact = CodeArtifactMetadata(code="print('ok')", language="python")

    payload = artifact.to_json_dict()

    assert payload["kind"] == MetadataKind.CODE_ARTIFACT
    assert payload["schema_version"] == "1.0"
    assert payload["code"] == "print('ok')"
    assert payload["content"] == "print('ok')"


def test_json_safe_summarizes_callables_and_drops_internal_handles() -> None:
    class CallbackOwner:
        def approve(self) -> bool:
            return True

    owner = CallbackOwner()

    payload = json_safe(
        {
            "callback": owner.approve,
            "_internal_callback": owner.approve,
            "nested": [owner.approve],
        }
    )

    assert payload == {
        "callback": "<callable:approve>",
        "nested": ["<callable:approve>"],
    }


def test_metadata_summary_summarizes_callables() -> None:
    class CallbackOwner:
        def approve(self) -> bool:
            return True

    owner = CallbackOwner()

    assert metadata_summary({"callback": owner.approve}) == {"callback": "<callable:approve>"}


def test_runtime_state_json_export_handles_method_values() -> None:
    class CallbackOwner:
        def approve(self) -> bool:
            return True

    owner = CallbackOwner()
    input_metadata = ToolInputMetadata.from_mapping(
        "command_executor",
        {
            "command": "pytest",
            "_command_approval_callback": owner.approve,
        },
    )
    state = RuntimeStateMetadata(goal="Serialize runtime callbacks")
    state.annotations["callback"] = owner.approve
    state.record_tool_event(
        {
            "event_type": "tool_run",
            "input": input_metadata.to_params(),
            "callback": owner.approve,
        }
    )

    payload = state.to_json_dict()

    json.dumps(payload)
    assert payload["annotations"]["callback"] == "<callable:approve>"
    assert payload["tool_history"][0]["callback"] == "<callable:approve>"
    assert "_command_approval_callback" not in payload["tool_history"][0]["input"]
    assert "runtime_handles" not in input_metadata.to_json_dict()
    assert callable(input_metadata.runtime_handles["_command_approval_callback"])


def test_tool_input_from_mapping_normalizes_llm_aliases_and_preserves_extras() -> None:
    metadata = ToolInputMetadata.from_mapping(
        "file_writer",
        {
            "file_path": "assistant.py",
            "content": "print('ok')",
            "create_intermediate": True,
            "unexpected_planner_hint": "keep as context",
        },
    )

    assert metadata.create_dirs is True
    assert "create_intermediate" not in metadata.attributes
    assert metadata.attributes["unexpected_planner_hint"] == "keep as context"
    assert metadata.to_params()["create_dirs"] is True


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


def test_tool_event_loop_metadata_serializes() -> None:
    input_metadata = ToolInputMetadata(tool_name="code_generator", task_description="make app", language="python")
    tool_context = ToolContextMetadata(
        session_id="session",
        task_id="task",
        step_id="step_1",
        call_id="call_1",
        project_path="/tmp/project",
        cwd="/tmp/project",
        env={"VIRTUAL_ENV": "/tmp/project/.venv"},
        python_command="/tmp/project/.venv/bin/python",
        git_snapshot={"commit_hash": "abc1234", "created": True},
        safety_notes=["git snapshot available: abc1234"],
    )
    tool_call = ToolCallMetadata(
        session_id="session",
        task_id="task",
        step_id="step_1",
        call_id="call_1",
        tool_name="code_generator",
        input_metadata=input_metadata,
        tool_context=tool_context,
    )
    failure = FailureMetadata(error_type="UnsupportedLanguage", error_message="language=text", recoverable=True)
    tool_error = ToolErrorMetadata(
        session_id="session",
        task_id="task",
        step_id="step_1",
        call_id="call_1",
        tool_name="code_generator",
        error_type=failure.error_type,
        error_message=failure.error_message,
        failure=failure,
        input_metadata=input_metadata,
        tool_context=tool_context,
    )
    event = ToolEventMetadata(
        session_id="session",
        task_id="task",
        step_id="step_1",
        call_id="call_1",
        tool_name="code_generator",
        event_type="error",
        status="error",
        tool_call=tool_call,
        tool_error=tool_error,
        tool_context=tool_context,
        failure=failure,
    )
    loop = ToolLoopMetadata(
        session_id="session",
        task_id="task",
        status="failed",
        success=False,
        events=[event],
        tool_invocations=[tool_call],
        recoverable_errors=[tool_error],
        tool_contexts=[tool_context],
        final_error=failure,
    )

    payload = loop.to_json_dict()

    assert payload["kind"] == MetadataKind.TOOL_LOOP
    assert payload["events"][0]["kind"] == MetadataKind.TOOL_EVENT
    assert payload["tool_contexts"][0]["kind"] == MetadataKind.TOOL_CONTEXT
    assert payload["tool_invocations"][0]["kind"] == MetadataKind.TOOL_CALL
    assert payload["tool_invocations"][0]["tool_context"]["python_command"].endswith("/python")
    assert payload["recoverable_errors"][0]["kind"] == MetadataKind.TOOL_ERROR
    assert payload["events"][0]["call_id"] == "call_1"


def test_tool_loop_metadata_accepts_runtime_invocation_trace_without_context() -> None:
    payload = {
        "kind": MetadataKind.TOOL_LOOP,
        "session_id": "session",
        "task_id": "task",
        "status": "completed",
        "success": True,
        "events": [],
        "tool_invocations": [],
        "recoverable_errors": [],
    }

    loop = ToolLoopMetadata.model_validate(payload)

    assert loop.success is True
    assert loop.tool_contexts == []


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


def test_git_metadata_serializes_repository_snapshot_and_diff() -> None:
    repository = GitRepositoryMetadata(
        project_path="/tmp/project",
        initialized=True,
        branch="main",
        head="abc123",
        dirty=False,
        ignored_paths=[".venv/"],
    )
    snapshot = GitSnapshotMetadata(
        project_path="/tmp/project",
        reason="before_write",
        message="openpilot: safety snapshot before write",
        commit_hash="abc123",
        created=True,
        changed_files=["app.py"],
    )
    diff = GitDiffContextMetadata(
        project_path="/tmp/project",
        base_ref="abc123",
        head_ref="def456",
        changed_files=["app.py"],
        diff_stat="app.py | 2 +-",
    )

    assert repository.to_json_dict()["kind"] == MetadataKind.GIT_REPOSITORY
    assert snapshot.to_json_dict()["kind"] == MetadataKind.GIT_SNAPSHOT
    assert diff.to_json_dict()["kind"] == MetadataKind.GIT_DIFF_CONTEXT


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


def test_project_diagnosis_metadata_serializes_ranked_candidates() -> None:
    objective = ProjectObjectiveMetadata(
        goal="Build a CLI formatter",
        project_type="cli_tool",
        target_users=["terminal users"],
        core_value=["Format input reliably."],
    )
    metric = SuccessMetricMetadata(
        metric_id="runtime_ready",
        name="Runnable delivery",
        dimension="reliability",
        target="CLI command runs.",
        required=True,
        satisfied=True,
    )
    assessment = ProjectDimensionAssessmentMetadata(
        dimension="user_experience",
        score=0.4,
        gaps=["Help output is unclear."],
    )
    candidate = ImprovementCandidateMetadata(
        candidate_id="gap_cli_help",
        title="Clarify CLI usage feedback",
        dimension="user_experience",
        acceptance_criteria=["Help output documents required arguments."],
        priority_score=0.8,
        selected=True,
    )
    diagnosis = ProjectDiagnosisMetadata(
        project_path="/tmp/tool",
        objective=objective,
        success_metrics=[metric],
        dimension_assessments=[assessment],
        improvement_candidates=[candidate],
        ranked_candidate_ids=[candidate.candidate_id],
        selected_candidate=candidate,
        reference_insights=[ReferenceInsightMetadata(summary="CLI tools should expose useful help text.", confidence=0.6)],
    )

    payload = diagnosis.to_json_dict()

    assert payload["kind"] == MetadataKind.PROJECT_DIAGNOSIS
    assert payload["objective"]["kind"] == MetadataKind.PROJECT_OBJECTIVE
    assert payload["success_metrics"][0]["kind"] == MetadataKind.SUCCESS_METRIC
    assert payload["selected_candidate"]["candidate_id"] == "gap_cli_help"
    assert payload["reference_insights"][0]["kind"] == MetadataKind.REFERENCE_INSIGHT


def test_dependency_metadata_serializes_with_diagnosis() -> None:
    dependency = ProjectDependencyMetadata(
        package_name="pygame",
        version="2.6.1",
        import_names=["pygame"],
        dependency_sources=["installed", "import_scan"],
        import_usage=["import pygame"],
        role="interactive_window_rendering_input_game_loop",
        confidence=0.91,
    )
    strategy = DependencyStrategyMetadata(
        preserve_packages=["pygame"],
        rationale=["Preserve pygame as existing rendering/input capability."],
        confidence=0.85,
    )
    objective = ProjectObjectiveMetadata(goal="Build a game", project_type="interactive_app")
    diagnosis = ProjectDiagnosisMetadata(
        project_path="/tmp/game",
        objective=objective,
        dependencies=[dependency],
        dependency_strategy=strategy,
    )

    payload = diagnosis.to_json_dict()

    assert payload["dependencies"][0]["kind"] == MetadataKind.PROJECT_DEPENDENCY
    assert payload["dependency_strategy"]["kind"] == MetadataKind.DEPENDENCY_STRATEGY
    assert payload["dependency_strategy"]["preserve_packages"] == ["pygame"]


def test_task_file_resolution_metadata_serializes() -> None:
    request = TaskFileResolutionRequestMetadata(
        project_path="/tmp/project",
        task_description="Update README controls",
        acceptance_criteria=["README documents controls."],
        target_file_hints=["README.md"],
    )
    file = RelatedProjectFileMetadata(
        file_path="/tmp/project/README.md",
        name="README.md",
        suffix=".md",
        role="documentation",
        relevance_score=1.0,
        relation_source="target_hint",
    )
    resolution = TaskFileResolutionMetadata(
        task_description=request.task_description,
        project_path=request.project_path,
        related_files=[file],
        primary_file=file,
        recommended_edit_kind="documentation",
    )

    payload = resolution.to_json_dict()

    assert request.to_json_dict()["kind"] == MetadataKind.TASK_FILE_RESOLUTION_REQUEST
    assert payload["kind"] == MetadataKind.TASK_FILE_RESOLUTION
    assert payload["primary_file"]["kind"] == MetadataKind.RELATED_PROJECT_FILE
    assert payload["recommended_edit_kind"] == "documentation"
