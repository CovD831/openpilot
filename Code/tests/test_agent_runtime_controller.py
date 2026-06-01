from __future__ import annotations

from types import SimpleNamespace

from autonomous_iteration.runtime_controller import (
    AgentRuntimeController,
    EditGuard,
    FileSelector,
    RuntimeGuard,
    RuntimeReporter,
    StateUpdater,
    ToolRouter,
)
from metadata import (
    AgentPhase,
    DecisionNeedMetadata,
    EditPlanMetadata,
    ResultStatus,
    RuntimeStateMetadata,
    TextArtifactMetadata,
    ToolResultMetadata,
)


def test_runtime_state_serializes_budget_and_phase() -> None:
    state = RuntimeStateMetadata(goal="Refactor runtime")
    state.add_fact("goal understood")
    state.add_unknown("project entrypoint")
    state.budget.consume_tool_call(file_read=True)
    payload = state.to_json_dict()

    assert payload["phase"] == "understand_task"
    assert payload["budget"]["max_tool_calls"] == 20
    assert payload["budget"]["max_file_reads"] == 30
    assert payload["budget"]["max_file_edits"] == 3
    assert payload["budget"]["max_file_creates"] == 20
    assert payload["budget"]["max_verification_attempts"] == 3
    assert payload["budget"]["max_recovery_rounds"] == 3
    assert payload["budget"]["max_replan_rounds"] == 3
    assert payload["budget"]["tool_calls_used"] == 1
    assert payload["known_facts"] == ["goal understood"]
    assert payload["unknowns"] == ["project entrypoint"]
    assert payload["assumptions"] == []
    assert payload["resolved_questions"] == []
    assert payload["decision_history"] == []


def test_tool_router_routes_information_gaps_and_blocks_on_budget() -> None:
    state = RuntimeStateMetadata(goal="Inspect project")
    router = ToolRouter()

    file_need = DecisionNeedMetadata(
        need_type="file_read",
        question="What does README say?",
        target_path="README.md",
    )
    directory_need = DecisionNeedMetadata(
        need_type="project_structure",
        question="What files exist?",
        target_path=".",
    )
    search_need = DecisionNeedMetadata(
        need_type="web_search",
        question="Find reference",
        query="agent runtime design",
    )
    command_need = DecisionNeedMetadata(
        need_type="smoke_test",
        question="Does it run?",
        command="pytest",
    )
    code_execution_command_need = DecisionNeedMetadata(
        need_type="code_execution",
        question="Run the generated script",
        command="python assistant.py",
    )
    bug_fix_need = DecisionNeedMetadata(
        need_type="bug_fix_tool",
        question="Fix failing smoke test",
        command="python test_assistant.py",
        attributes={"file_paths": ["assistant.py"], "max_iterations": 3},
    )

    assert router.route(state, file_need)[0].tool_name == "file_reader"
    assert router.route(state, directory_need)[0].tool_name == "multi_file_reader"
    assert router.route(state, search_need)[0].tool_name == "web_searcher"
    assert router.route(state, command_need)[0].tool_name == "command_executor"
    assert router.route(state, code_execution_command_need)[0].tool_name == "command_executor"
    bug_fix_selection = router.route(state, bug_fix_need)[0]
    assert bug_fix_selection.tool_name == "bug_fix_tool"
    assert bug_fix_selection.input_metadata.max_iterations == 3
    assert [decision.selected_tool for decision in state.decision_history] == [
        "file_reader",
        "multi_file_reader",
        "web_searcher",
        "command_executor",
        "command_executor",
        "bug_fix_tool",
    ]

    state.budget.tool_calls_used = state.budget.max_tool_calls
    assert router.route(state, file_need) == []
    assert state.phase == AgentPhase.BLOCKED
    assert "budget exhausted" in state.completion_reason


def test_tool_router_routes_directory_shaped_file_reads_to_multi_file_reader(tmp_path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    readme = project_dir / "README.md"
    readme.write_text("hello", encoding="utf-8")
    router = ToolRouter()

    directory_state = RuntimeStateMetadata(goal="Inspect project")
    directory_need = DecisionNeedMetadata(
        need_type="file_read",
        question="What files and directories exist in the project folder?",
        target_path=str(project_dir),
    )
    directory_selection = router.route(directory_state, directory_need)[0]

    assert directory_selection.tool_name == "multi_file_reader"
    assert directory_selection.input_metadata.directory_path == str(project_dir)
    assert directory_selection.input_metadata.pattern == "*"

    file_state = RuntimeStateMetadata(goal="Inspect file")
    file_need = DecisionNeedMetadata(
        need_type="file_read",
        question="What does README say?",
        target_path=str(readme),
    )
    file_selection = router.route(file_state, file_need)[0]

    assert file_selection.tool_name == "file_reader"
    assert file_selection.input_metadata.file_path == str(readme)


def test_tool_router_routes_non_executable_file_creation_to_writer(tmp_path) -> None:
    router = ToolRouter()
    state = RuntimeStateMetadata(goal="Create project files")
    config_path = tmp_path / "config.json"
    readme_path = tmp_path / "README.md"

    config_selection = router.route(
        state,
        DecisionNeedMetadata(
            need_type="code_file_create",
            question="Create JSON configuration",
            target_path=str(config_path),
            attributes={"language": "json", "content": "{\"enabled\": true}\n"},
        ),
    )[0]
    readme_selection = router.route(
        state,
        DecisionNeedMetadata(
            need_type="code_file_create",
            question="Create README",
            target_path=str(readme_path),
            attributes={"language": "text"},
        ),
    )[0]

    assert config_selection.tool_name == "file_writer"
    assert config_selection.input_metadata.content == "{\"enabled\": true}\n"
    assert readme_selection.tool_name == "readme_tool"
    assert readme_selection.input_metadata.project_path == str(tmp_path)


def test_tool_router_replaces_existing_files_for_idempotent_generation(tmp_path) -> None:
    existing = tmp_path / "config.json"
    existing.write_text("{}", encoding="utf-8")
    router = ToolRouter()
    state = RuntimeStateMetadata(goal="Regenerate project files")

    selection = router.route(
        state,
        DecisionNeedMetadata(
            need_type="file_write",
            question="Write config",
            target_path=str(existing),
            operation_kind="create_file",
            attributes={"content": "{\"ok\": true}", "overwrite": True},
        ),
    )[0]

    assert selection.tool_name == "file_writer"
    assert selection.input_metadata.operation_kind == "file_replace"


def test_tool_router_distinguishes_code_generation_and_symbol_edits() -> None:
    router = ToolRouter()
    state = RuntimeStateMetadata(goal="Patch code")

    add_selection = router.route(
        state,
        DecisionNeedMetadata(
            need_type="code_unit_generate",
            question="Add helper function",
            target_path="app.py",
            operation_kind="add_symbol",
            symbol_name="format_name",
            symbol_type="function",
        ),
    )[0]
    modify_selection = router.route(
        state,
        DecisionNeedMetadata(
            need_type="code_symbol_modify",
            question="Modify helper function",
            target_path="app.py",
            operation_kind="modify_symbol",
            symbol_name="format_name",
            symbol_type="function",
        ),
    )[0]
    patch_selection = router.route(
        state,
        DecisionNeedMetadata(
            need_type="file_write",
            question="Apply generated symbol edit",
            target_path="app.py",
            operation_kind="modify_symbol",
            symbol_name="format_name",
        ),
    )[0]
    create_selection = router.route(
        state,
        DecisionNeedMetadata(
            need_type="code_file_create",
            question="Create new app file",
            target_path="app.py",
            operation_kind="create_file",
        ),
    )[0]

    assert add_selection.tool_name == "code_unit_generator"
    assert add_selection.input_metadata.operation_kind == "add_symbol"
    assert modify_selection.tool_name == "code_editor"
    assert modify_selection.input_metadata.symbol_name == "format_name"
    assert patch_selection.tool_name == "file_patch_writer"
    assert create_selection.tool_name == "code_generator"


def test_runtime_guard_centralizes_risk_budget_and_confirmation_policy() -> None:
    guard = RuntimeGuard()
    state = RuntimeStateMetadata(goal="Risky work")
    high_risk_need = DecisionNeedMetadata(
        need_type="command_check",
        question="Run migration",
        command="python migrate.py",
        risk_level="high",
    )

    decision = guard.approve_need(state, high_risk_need, "command_executor")

    assert decision.approved is False
    assert decision.attributes["requires_user_confirmation"] is True
    assert "user confirmation" in decision.reason

    forbidden = DecisionNeedMetadata(
        need_type="command_check",
        question="Delete project",
        command="rm -rf .",
        risk_level="forbidden",
    )
    decision = guard.approve_need(state, forbidden, "command_executor")
    assert decision.approved is False
    assert "forbidden" in decision.reason


def test_tool_router_moves_high_risk_need_to_ask_user() -> None:
    state = RuntimeStateMetadata(goal="Risky work")
    router = ToolRouter()

    selections = router.route(
        state,
        DecisionNeedMetadata(
            need_type="command_check",
            question="Run migration",
            command="python migrate.py",
            risk_level="high",
        ),
    )

    assert selections == []
    assert state.phase == AgentPhase.ASK_USER
    assert "user confirmation" in state.completion_reason


def test_file_selector_promotes_only_evidence_backed_candidates() -> None:
    state = RuntimeStateMetadata(goal="Patch bug")
    selector = FileSelector()
    state.add_candidate_file("app.py", "traceback references app.py")

    selected = selector.select(state, ["app.py", "guess.py"])

    assert selected == ["app.py"]
    assert state.selected_files["app.py"] == ["traceback references app.py"]
    assert state.unknowns == ["Missing file-selection evidence for guess.py"]


def test_edit_guard_requires_evidence_selection_scope_and_verification() -> None:
    guard = EditGuard()
    state = RuntimeStateMetadata(goal="Patch bug")
    state.add_candidate_file("app.py", "traceback points here")

    no_evidence = EditPlanMetadata(subgoal="Patch", target_files=["app.py"])
    decision = guard.approve(state, no_evidence)
    assert decision.approved is False
    assert "evidence" in decision.reason.lower()

    unselected = EditPlanMetadata(
        subgoal="Patch",
        target_files=["app.py"],
        evidence=["traceback points here"],
        allowed_changes=["Fix failing branch"],
        verification=["pytest"],
    )
    decision = guard.approve(state, unselected)
    assert decision.approved is False
    assert decision.blocked_files == ["app.py"]

    state.select_file("app.py", "traceback points here")
    too_many_files = EditPlanMetadata(
        subgoal="Patch",
        target_files=["app.py", "b.py", "c.py", "d.py"],
        evidence=["traceback points here"],
        allowed_changes=["Fix failing branch"],
        verification=["pytest"],
    )
    decision = guard.approve(state, too_many_files)
    assert decision.approved is False
    assert "budget" in decision.reason.lower()

    approved = EditPlanMetadata(
        subgoal="Patch",
        target_files=["app.py"],
        evidence=["traceback points here"],
        allowed_changes=["Fix failing branch"],
        forbidden_changes=["Do not change public CLI"],
        verification=["pytest"],
    )
    decision = guard.approve(state, approved)
    assert decision.approved is True


def test_file_creation_uses_a_separate_runtime_budget(tmp_path) -> None:
    state = RuntimeStateMetadata(goal="Scaffold project")
    state.budget.file_edits_used = state.budget.max_file_edits
    router = ToolRouter()
    new_file = tmp_path / "new_module.py"

    selections = router.route(
        state,
        DecisionNeedMetadata(
            need_type="file_write",
            question="Create module",
            target_path=str(new_file),
            operation_kind="create_file",
            attributes={"content": "VALUE = 1\n"},
        ),
    )

    assert len(selections) == 1
    assert selections[0].input_metadata.operation_kind == "create_file"

    new_file.write_text("VALUE = 0\n", encoding="utf-8")
    selections = router.route(
        state,
        DecisionNeedMetadata(
            need_type="file_write",
            question="Replace module",
            target_path=str(new_file),
            operation_kind="create_file",
            attributes={"content": "VALUE = 2\n"},
        ),
    )

    assert selections == []


def test_edit_guard_limits_creates_independently_from_edits() -> None:
    guard = EditGuard()
    state = RuntimeStateMetadata(goal="Scaffold project")
    state.budget.file_edits_used = state.budget.max_file_edits
    state.select_file("new_module.py", "scaffold plan")
    create_plan = EditPlanMetadata(
        subgoal="Create module",
        target_files=["new_module.py"],
        evidence=["scaffold plan"],
        allowed_changes=["Create requested module"],
        forbidden_changes=["Do not modify existing files"],
        verification=["python -m compileall ."],
        attributes={"budget_kind": "file_create"},
    )

    assert guard.approve(state, create_plan).approved is True

    state.budget.file_creates_used = state.budget.max_file_creates
    decision = guard.approve(state, create_plan)
    assert decision.approved is False
    assert "create budget" in decision.reason.lower()


def test_state_updater_absorbs_tool_results_and_forces_write_verification() -> None:
    state = RuntimeStateMetadata(goal="Write file", phase=AgentPhase.EXECUTE)
    router = ToolRouter()
    updater = StateUpdater()
    selection = router.route(
        state,
        DecisionNeedMetadata(
            need_type="file_write",
            question="Save app",
            target_path="app.py",
            attributes={"content": "print('ok')"},
        ),
    )[0]
    result = SimpleNamespace(
        success=True,
        output_metadata=ToolResultMetadata(
            tool_name="file_writer",
            status=ResultStatus.SUCCESS,
            result=TextArtifactMetadata(content="written", attributes={"file_path": "app.py"}),
        ),
        error=None,
    )

    updater.apply_tool_result(state, selection, result)

    assert state.phase == AgentPhase.VERIFY
    assert state.verification_status == "required"
    assert "app.py" in state.modified_files
    assert state.budget.file_edits_used == 0
    assert state.budget.file_creates_used == 1
    assert state.tool_history[0]["tool_name"] == "file_writer"


def test_state_updater_moves_successful_verification_to_summary() -> None:
    state = RuntimeStateMetadata(goal="Verify", phase=AgentPhase.VERIFY, modified_files=["app.py"], verification_status="required")
    router = ToolRouter()
    updater = StateUpdater()
    selection = router.route(
        state,
        DecisionNeedMetadata(
            need_type="smoke_test",
            question="Run tests",
            command="pytest",
        ),
    )[0]
    result = SimpleNamespace(
        success=True,
        output_metadata=ToolResultMetadata(
            tool_name="command_executor",
            status=ResultStatus.SUCCESS,
            result=TextArtifactMetadata(content="passed"),
        ),
        error=None,
    )

    updater.apply_tool_result(state, selection, result)

    assert state.phase == AgentPhase.SUMMARIZE
    assert state.verification_status == "passed"
    assert state.completion_reason == "verification passed"


def test_state_updater_replans_after_failed_verification() -> None:
    state = RuntimeStateMetadata(goal="Verify", phase=AgentPhase.VERIFY, modified_files=["app.py"], verification_status="required")
    router = ToolRouter()
    updater = StateUpdater()
    selection = router.route(
        state,
        DecisionNeedMetadata(
            need_type="smoke_test",
            question="Run tests",
            command="pytest",
        ),
    )[0]
    result = SimpleNamespace(
        success=False,
        output_metadata=None,
        error=SimpleNamespace(error_message="pytest failed"),
    )

    updater.apply_tool_result(state, selection, result)

    assert state.phase == AgentPhase.REPLAN
    assert state.verification_status == "failed"
    assert state.replan_count == 1
    assert state.budget.replan_rounds_used == 1


def test_state_updater_blocks_after_repeated_no_progress_results() -> None:
    state = RuntimeStateMetadata(goal="Observe")
    updater = StateUpdater()
    selection = SimpleNamespace(
        tool_name="noop_tool",
        step_id="noop",
        reason="observe",
        input_metadata=SimpleNamespace(to_params=lambda: {}),
    )
    result = SimpleNamespace(success=True, output_metadata=None, error=None)

    updater.apply_tool_result(state, selection, result)
    updater.apply_tool_result(state, selection, result)
    updater.apply_tool_result(state, selection, result)

    assert state.phase == AgentPhase.BLOCKED
    assert state.completion_reason == "no new runtime facts after repeated tool results"


def test_runtime_controller_streamed_need_interrupt_routes_and_resumes_state() -> None:
    runtime = SimpleNamespace(tool_registry=None)
    controller = AgentRuntimeController(runtime, session_executor=SimpleNamespace(run=lambda *_args, **_kwargs: {"success": True}))

    selections = controller.handle_streamed_need(
        DecisionNeedMetadata(
            need_type="file_read",
            question="Inspect app",
            target_path="app.py",
        )
    )

    assert selections[0].tool_name == "file_reader"
    assert controller.state.tool_history[0]["event_type"] == "stream_need_interrupt"

    result = SimpleNamespace(
        success=True,
        output_metadata=ToolResultMetadata(
            tool_name="file_reader",
            status=ResultStatus.SUCCESS,
            result=TextArtifactMetadata(content="app", attributes={"file_path": "app.py"}),
        ),
        error=None,
    )
    state = controller.absorb_streamed_tool_result(selections[0], result)

    assert "app.py" in state.candidate_files
    assert state.tool_history[-1]["event_type"] == "stream_need_resume"


def test_runtime_reporter_summarizes_evidence_changes_and_risks() -> None:
    state = RuntimeStateMetadata(goal="Patch bug", phase=AgentPhase.BLOCKED, verification_status="failed")
    state.add_fact("Observed failing test")
    state.add_unknown("Need failure diagnosis")
    state.select_file("app.py", "test failure references app.py")
    state.add_modified_file("app.py")
    state.completion_reason = "verification failed"

    report = RuntimeReporter().report(state)

    assert report.goal == "Patch bug"
    assert report.phase == AgentPhase.BLOCKED
    assert report.selected_files == {"app.py": ["test failure references app.py"]}
    assert report.modified_files == ["app.py"]
    assert "unresolved runtime questions remain" in report.residual_risks
    assert "verification status is failed" in report.residual_risks


def test_agent_runtime_controller_returns_runtime_state_and_report() -> None:
    class FakeSessionRunner:
        def __init__(self) -> None:
            self.calls = []

        def run(self, goal, context, mode="standard"):
            self.calls.append((goal, context, mode))
            return {"success": True, "stats": {"tasks_completed": 1, "tasks_failed": 0}, "written_files": ["app.py"]}

    session_executor = FakeSessionRunner()
    runtime = SimpleNamespace(tool_registry=None)
    controller = AgentRuntimeController(runtime, session_executor=session_executor)

    result = controller.run("Build app", {"project_path": "/tmp/project"}, mode="standard")

    assert result["success"] is True
    assert session_executor.calls == [("Build app", {"project_path": "/tmp/project"}, "standard")]
    state = result["agent_runtime_state"]
    assert state["goal"] == "Build app"
    assert state["phase"] == "summarize"
    assert state["modified_files"] == ["app.py"]
    assert result["runtime_report"]["goal"] == "Build app"
    assert result["runtime_report"]["modified_files"] == ["app.py"]
