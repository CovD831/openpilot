from __future__ import annotations

from types import SimpleNamespace

from core.llm import LLMMessage, LLMRequest, LLMResponse
from metadata import (
    FailureMetadata,
    LogEventMetadata,
    ResultStatus,
    ToolCallMetadata,
    ToolErrorMetadata,
    ToolExecutionEnvelopeMetadata,
    ToolInputMetadata,
)
from metadata.agent_runtime import AgentPhase, RuntimeStateMetadata

from autonomous_iteration.runtime_controller import AgentRuntimeController, StateUpdater
from core.tool_event_loop import ToolEventLoopRunner
from runtime_diagnostics import (
    DiagnosticRecorder,
    RawTaskInput,
    collect_from_failure,
    collect_from_runtime_state,
    collect_from_tool_error,
    judge_signal,
    render_summary_markdown,
    summarize_records,
    suspicious_success_signal,
    write_summary_markdown,
    TrajectoryLLMClientProxy,
)
from runtime_diagnostics.hooks import RuntimeDiagnosticsHooks
from runtime_diagnostics.report import generate_stage_summary
from tools.tool_selection import SelectionReason, ToolSelection


def test_raw_task_input_is_minimal_external_wrapper() -> None:
    raw = RawTaskInput(
        task_id="manual_001",
        source="manual",
        raw_input="请总结这个项目的核心模块",
        tags=["understanding", "readonly"],
    )

    payload = raw.to_task_payload()

    assert payload["goal"] == "请总结这个项目的核心模块"
    assert payload["task_id"] == "manual_001"
    assert payload["tags"] == ["understanding", "readonly"]


def test_collect_from_tool_error_reuses_problem_signal_metadata() -> None:
    error = ToolErrorMetadata(
        session_id="s1",
        task_id="task-1",
        step_id="step-1",
        call_id="call-1",
        tool_name="file_reader",
        error_type="FileNotFoundError",
        error_message="missing file",
        suggested_recovery="check path",
    )

    signal = collect_from_tool_error(error)

    assert signal.category == "environment"
    assert signal.task_id == "task-1"
    assert signal.tool_name == "file_reader"
    assert "missing file" in signal.message


def test_collect_from_failure_and_judge_signal() -> None:
    failure = FailureMetadata(
        error_type="AssertionError",
        error_message="verification failed",
        recoverable=False,
    )

    signal = collect_from_failure(failure, source="verification", task_id="task-2")
    judgment = judge_signal(signal)

    assert signal.category == "tool_execution"
    assert judgment.is_problem is True
    assert judgment.severity == "high"
    assert judgment.recommended_repair_kind == "tool_failure_review"


def test_collect_from_runtime_state_detects_verification_failure() -> None:
    state = RuntimeStateMetadata(
        goal="verify result",
        phase=AgentPhase.VERIFY,
        verification_status="failed",
    )

    signals = collect_from_runtime_state(state)

    assert len(signals) == 1
    assert signals[0].category == "verification"


def test_recorder_and_summarizer_round_trip(tmp_path) -> None:
    recorder = DiagnosticRecorder(tmp_path)
    signal = suspicious_success_signal(
        task_id="task-3",
        evidence=["success=true", "verification_status=not_started"],
    )
    judgment = judge_signal(signal)

    record = recorder.record_judgment(signal, judgment)
    records = recorder.load_recent_records()
    summary = summarize_records(records)

    assert record.task_id == "task-3"
    assert len(records) == 1
    assert summary.total_records == 1
    assert summary.by_category == {"suspicious_success": 1}
    assert summary.by_severity == {"review": 1}


def test_hooks_are_no_throw_and_record_tool_failures(tmp_path) -> None:
    hooks = RuntimeDiagnosticsHooks(DiagnosticRecorder(tmp_path))
    error = {
        "task_id": "task-4",
        "tool_name": "command_executor",
        "error_type": "ModuleNotFoundError",
        "error_message": "No module named demo",
        "suggested_recovery": "install dependency",
    }

    record_ids = hooks.on_tool_failed(error)
    records = hooks.recorder.load_recent_records()

    assert record_ids
    assert records[0]["signal"]["category"] == "environment"


def test_agent_runtime_controller_records_task_finish_and_suspicious_success(tmp_path) -> None:
    class FakeSessionRunner:
        def run(self, goal, context, mode="standard"):
            return {
                "success": True,
                "task_id": context.get("task_id"),
                "stats": {"tasks_completed": 1, "tasks_failed": 0},
            }

    hooks = RuntimeDiagnosticsHooks(DiagnosticRecorder(tmp_path))
    runtime = type("Runtime", (), {"tool_registry": None, "runtime_diagnostics_hooks": hooks, "session_id": "session-1"})()
    controller = AgentRuntimeController(runtime, session_executor=FakeSessionRunner())

    result = controller.run("Build app", {"project_path": "/tmp/project", "task_id": "task-5"}, mode="standard")

    assert result["success"] is True
    records = hooks.recorder.load_recent_records()
    run = hooks.recorder.load_run("task-5")
    trajectory_events = hooks.recorder.load_trajectory_events(run.run_id if run else "")
    assert records
    assert records[0]["signal"]["category"] == "suspicious_success"
    assert run is not None
    assert "runtime_phase_changed" in [event["event_type"] for event in trajectory_events]
    assert "task_finished" in [event["event_type"] for event in trajectory_events]


def test_tool_event_loop_records_tool_error_via_runtime_hooks(tmp_path) -> None:
    hooks = RuntimeDiagnosticsHooks(DiagnosticRecorder(tmp_path))

    class FakeRuntime:
        runtime_diagnostics_hooks = hooks

    class FakeOwner:
        def __init__(self) -> None:
            self.runtime = FakeRuntime()

        def _log(self, *args, **kwargs):
            return None

    runner = ToolEventLoopRunner(FakeOwner())
    input_metadata = ToolInputMetadata(tool_name="file_reader", file_path="missing.txt")
    tool_call = ToolCallMetadata(
        session_id="session-2",
        task_id="task-6",
        step_id="step-1",
        call_id="call-1",
        tool_name="file_reader",
        input_metadata=input_metadata,
    )
    tool_error = ToolErrorMetadata(
        session_id="session-2",
        task_id="task-6",
        step_id="step-1",
        call_id="call-1",
        tool_name="file_reader",
        error_type="FileNotFoundError",
        error_message="missing file",
        recoverable=True,
        input_metadata=input_metadata,
    )

    runner._record_tool_error("task-6", tool_call, tool_error, 1)

    records = hooks.recorder.load_recent_records()
    assert records
    assert records[0]["signal"]["source"] == "tool_error"

from runtime_diagnostics import RuntimeTaskPoolRunner, load_raw_tasks


def test_load_raw_tasks_from_jsonl_and_json(tmp_path) -> None:
    jsonl_path = tmp_path / "tasks.jsonl"
    jsonl_path.write_text(
        '{"task_id":"a","source":"manual","raw_input":"one","attachments":[],"tags":[]}\n'
        '{"task_id":"b","source":"manual","raw_input":"two","attachments":[],"tags":["x"]}\n',
        encoding="utf-8",
    )
    json_path = tmp_path / "task.json"
    json_path.write_text(
        '{"task_id":"c","source":"manual","raw_input":"three","attachments":[],"tags":[]}',
        encoding="utf-8",
    )

    tasks_jsonl = load_raw_tasks(jsonl_path)
    tasks_json = load_raw_tasks(json_path)

    assert [task.task_id for task in tasks_jsonl] == ["a", "b"]
    assert [task.task_id for task in tasks_json] == ["c"]


def test_runtime_task_pool_runner_passes_task_context_and_records_runs(tmp_path) -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    def fake_executor(goal: str, context: dict[str, object]) -> dict[str, object]:
        seen.append((goal, context))
        return {
            "success": True,
            "goal": goal,
            "runtime_report": {
                "phase": "summarize",
                "verification_status": "not_required",
                "completion_reason": "ok",
            },
        }

    runner = RuntimeTaskPoolRunner(fake_executor, recorder=DiagnosticRecorder(tmp_path))
    task = RawTaskInput(
        task_id="manual_010",
        source="manual",
        raw_input="请总结核心模块",
        tags=["understanding"],
        context={"project_path": "/tmp/project"},
    )

    results = runner.run_tasks([task])

    assert len(results) == 1
    assert results[0].success is True
    assert seen[0][0] == "请总结核心模块"
    assert seen[0][1]["task_id"] == "manual_010"
    assert seen[0][1]["source"] == "manual"
    assert seen[0][1]["project_path"] == "/tmp/project"
    runs = runner.recorder.runs_file.read_text(encoding="utf-8")
    assert '"event": "task_pool_item_started"' in runs
    assert '"event": "task_pool_item_finished"' in runs


def test_summarizer_highlights_repeated_signals_and_renders_markdown(tmp_path) -> None:
    recorder = DiagnosticRecorder(tmp_path)
    signal_a = suspicious_success_signal(
        task_id="task-a",
        message="Task reported success without enough verification evidence",
        evidence=["verification_status=not_started"],
    )
    signal_b = suspicious_success_signal(
        task_id="task-b",
        message="Task reported success without enough verification evidence",
        evidence=["verification_status=not_started"],
    )
    recorder.record_judgment(signal_a, judge_signal(signal_a))
    recorder.record_judgment(signal_b, judge_signal(signal_b))

    summary = summarize_records(recorder.load_recent_records(limit=0))
    markdown = render_summary_markdown(summary)
    output_path = write_summary_markdown(summary, tmp_path / "summary.md")

    assert summary.suspicious_success_count == 2
    assert summary.repeated_signals
    assert summary.repeated_signals[0].count == 2
    assert "Repeated Signals" in markdown
    assert "task-a" in markdown
    assert output_path.read_text(encoding="utf-8").startswith("# Runtime Diagnostics Summary")


def test_recorder_load_run_events(tmp_path) -> None:
    recorder = DiagnosticRecorder(tmp_path)
    recorder.record_run({"event": "task_pool_item_started", "task_id": "t1"})
    recorder.record_run({"event": "task_pool_item_finished", "task_id": "t1", "success": True})

    events = recorder.load_run_events(limit=0)

    assert [event["event"] for event in events] == ["task_pool_item_started", "task_pool_item_finished"]


def test_recorder_creates_run_directory_and_event_stream(tmp_path) -> None:
    recorder = DiagnosticRecorder(tmp_path)

    event = recorder.record_event(
        "task-trajectory-1",
        event_type="task_received",
        source="manual",
        raw_input="请梳理架构",
        session_id="session-trajectory-1",
        payload=LogEventMetadata(
            source_type="system",
            source_name="openpilot",
            phase="entry",
            event_type="task_received",
            input_summary={
                "task_id": "task-trajectory-1",
                "source": "manual",
                "raw_input": "请梳理架构",
                "session_id": "session-trajectory-1",
            },
        ),
    )
    recorder.record_event(
        "session-trajectory-1",
        event_type="task_finished",
        session_id="session-trajectory-1",
        payload=LogEventMetadata(
            source_type="system",
            source_name="openpilot",
            phase="summarize",
            event_type="task_finished",
            success=True,
            output_summary={
                "task_id": "task-trajectory-1",
                "summary": {"completion_reason": "runtime session completed", "phase": "summarize"},
                "session_id": "session-trajectory-1",
            },
        ),
    )

    run = recorder.load_run(event.run_id)
    trajectory_events = recorder.load_trajectory_events(event.run_id)
    summary = recorder.load_run_summary(event.run_id)

    assert run is not None
    assert run.task_id == "task-trajectory-1"
    assert run.session_id == "session-trajectory-1"
    assert run.final_status == "success"
    assert len(trajectory_events) == 2
    assert [item["event_type"] for item in trajectory_events] == ["task_received", "task_finished"]
    assert trajectory_events[0]["payload_kind"] == "log_event"
    assert trajectory_events[1]["payload_kind"] == "log_event"
    assert trajectory_events[0]["payload"]["correlation"]["task_id"] == "task-trajectory-1"
    assert trajectory_events[0]["payload"]["correlation"]["session_id"] == "session-trajectory-1"
    assert summary is not None
    assert summary.final_status == "success"
    assert summary.event_count == 2


def test_hooks_correlate_session_events_into_one_run(tmp_path) -> None:
    hooks = RuntimeDiagnosticsHooks(DiagnosticRecorder(tmp_path))

    hooks.on_task_received(
        task_id="manual_task_001",
        source="manual",
        raw_input="请总结模块",
        session_id="session-xyz",
    )
    hooks.on_task_card_ready(
        task_id="session-xyz",
        session_id="session-xyz",
        task_card={"goal": "请总结模块", "task_type": "document_summary"},
    )
    hooks.on_task_finished(
        task_id="manual_task_001",
        success=False,
        session_id="session-xyz",
        summary={"completion_reason": "runtime session failed", "phase": "recover"},
    )

    run = hooks.recorder.load_run("session-xyz")
    assert run is not None
    assert run.task_id == "manual_task_001"
    assert run.session_id == "session-xyz"
    assert run.goal == "请总结模块"
    assert run.final_status == "failed"
    events = hooks.recorder.load_trajectory_events(run.run_id)
    assert [event["event_type"] for event in events] == ["task_received", "task_card_ready", "task_finished"]


def test_hooks_record_phase_verification_and_tool_events(tmp_path) -> None:
    hooks = RuntimeDiagnosticsHooks(DiagnosticRecorder(tmp_path))

    hooks.on_task_received(
        task_id="task-phase-1",
        source="manual",
        raw_input="请检查写文件流程",
        session_id="session-phase-1",
    )
    hooks.on_runtime_phase_changed(
        task_id="task-phase-1",
        session_id="session-phase-1",
        previous_phase="understand_task",
        phase="verify",
        verification_status="required",
        completion_reason="",
    )
    hooks.on_verification_state_changed(
        task_id="task-phase-1",
        session_id="session-phase-1",
        previous_status="not_started",
        verification_status="required",
        phase="verify",
        reason="file modified",
    )
    input_metadata = ToolInputMetadata(tool_name="file_writer", file_path="README.md")
    tool_call = ToolCallMetadata(
        session_id="session-phase-1",
        task_id="subtask-phase-1",
        step_id="step-1",
        call_id="call-1",
        tool_name="file_writer",
        input_metadata=input_metadata,
        round_index=1,
    )
    hooks.on_tool_started(tool_call=tool_call)
    hooks.on_tool_completed(
        task_id="subtask-phase-1",
        session_id="session-phase-1",
        tool_execution=ToolExecutionEnvelopeMetadata(
            tool_name="file_writer",
            step_id="step-1",
            status=ResultStatus.SUCCESS,
            success=True,
            input_metadata=input_metadata,
            call_id="call-1",
        ),
    )

    run = hooks.recorder.load_run("session-phase-1")
    assert run is not None
    events = hooks.recorder.load_trajectory_events(run.run_id)
    summary = hooks.recorder.load_run_summary(run.run_id)
    assert [event["event_type"] for event in events] == [
        "task_received",
        "runtime_phase_changed",
        "verification_state_changed",
        "tool_called",
        "tool_succeeded",
    ]
    assert events[1]["payload_kind"] == "log_event"
    assert events[2]["payload_kind"] == "log_event"
    assert events[3]["payload_kind"] == "tool_call"
    assert events[4]["payload_kind"] == "tool_execution_envelope"
    assert events[1]["payload"]["correlation"]["task_id"] == "task-phase-1"
    assert events[1]["payload"]["correlation"]["session_id"] == "session-phase-1"
    assert events[3]["task_id"] == "task-phase-1"
    assert events[3]["payload"]["correlation"]["task_id"] == "task-phase-1"
    assert events[3]["payload"]["annotations"]["subtask_id"] == "subtask-phase-1"
    assert events[3]["payload"]["correlation"]["execution_id"] == "call-1"
    assert events[4]["payload"]["correlation"]["task_id"] == "task-phase-1"
    assert events[4]["payload"]["annotations"]["subtask_id"] == "subtask-phase-1"
    assert summary is not None
    assert summary.phase_changes == 1
    assert summary.verification_state_changes == 1
    assert summary.tool_called_count == 1
    assert summary.tool_succeeded_count == 1


def test_hooks_record_generic_log_event_with_correlation(tmp_path) -> None:
    hooks = RuntimeDiagnosticsHooks(DiagnosticRecorder(tmp_path))

    hooks.on_task_received(
        task_id="root-task-1",
        source="manual",
        raw_input="请梳理真实任务链路",
        session_id="session-root-1",
    )
    hooks.on_log_event(
        task_id="subtask-trajectory-1",
        session_id="session-root-1",
        step_id="phase-1",
        source_type="module",
        source_name="autonomous_iteration.project_improvement_runtime",
        phase="project_improvement_runtime",
        event_type="pipeline_started",
        input_summary={"goal": "请梳理真实任务链路"},
        annotations={"module": "project_improvement_runtime"},
    )

    run = hooks.recorder.load_run("session-root-1")
    assert run is not None
    events = hooks.recorder.load_trajectory_events(run.run_id)
    pipeline_event = next(event for event in events if event["event_type"] == "pipeline_started")
    assert pipeline_event["payload_kind"] == "log_event"
    assert pipeline_event["payload"]["correlation"]["task_id"] == "root-task-1"
    assert pipeline_event["payload"]["annotations"]["subtask_id"] == "subtask-trajectory-1"
    assert pipeline_event["payload"]["annotations"]["module"] == "project_improvement_runtime"


def test_state_updater_emits_phase_and_verification_callbacks_without_direct_diagnostics_coupling() -> None:
    emitted: list[tuple[str, str, str, str]] = []

    def sink(state: RuntimeStateMetadata, kind: str, previous_value: str) -> None:
        emitted.append((kind, previous_value, state.phase.value if hasattr(state.phase, "value") else str(state.phase), state.verification_status))

    updater = StateUpdater(state_event_sink=sink)
    state = RuntimeStateMetadata(goal="write readme", phase=AgentPhase.EXECUTE, verification_status="not_started")
    selection = ToolSelection(
        step_id="step-1",
        tool_name="file_writer",
        reason=SelectionReason.CAPABILITY_MATCH,
        input_metadata=ToolInputMetadata(tool_name="file_writer", file_path="README.md"),
    )
    execution_result = type(
        "ExecResult",
        (),
        {
            "success": True,
            "output_metadata": type(
                "Output",
                (),
                {"result": type("Result", (), {"file_path": "README.md"})()},
            )(),
            "error": None,
        },
    )()

    updater.apply_tool_result(state, selection, execution_result)

    assert emitted == [
        ("phase", "execute", "verify", "required"),
        ("verification", "not_started", "verify", "required"),
    ]


def test_recorder_writes_artifact_and_updates_summary(tmp_path) -> None:
    recorder = DiagnosticRecorder(tmp_path)
    event = recorder.record_event(
        "task-artifact-1",
        event_type="task_received",
        source="manual",
        raw_input="请输出日志",
        session_id="session-artifact-1",
        payload=LogEventMetadata(
            source_type="system",
            source_name="openpilot",
            phase="entry",
            event_type="task_received",
            input_summary={
                "task_id": "task-artifact-1",
                "source": "manual",
                "raw_input": "请输出日志",
                "session_id": "session-artifact-1",
            },
        ),
    )

    artifact = recorder.record_artifact(
        "session-artifact-1",
        kind="stdout",
        content="hello world",
        filename="stdout.txt",
        source_event_id=event.event_id,
    )
    summary = recorder.load_run_summary("session-artifact-1")

    assert artifact.path.endswith("stdout.txt")
    assert summary is not None
    assert summary.artifact_count == 1


def test_llm_proxy_records_request_response_events_and_artifacts(tmp_path) -> None:
    hooks = RuntimeDiagnosticsHooks(DiagnosticRecorder(tmp_path))

    class FakeLLMClient:
        settings = SimpleNamespace(model="demo-model", provider="demo-provider")

        def complete(self, request, max_retries=3, use_cache=True, stream_callback=None):
            return LLMResponse(
                content='{"task_type":"document_summary"}',
                parsed_json={"task_type": "document_summary"},
                model="demo-model",
                provider="demo-provider",
                usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
                finish_reason="stop",
                provider_details={"transport_retry_history": []},
            )

    proxy = TrajectoryLLMClientProxy(
        FakeLLMClient(),
        hooks=hooks,
        task_id_getter=lambda: "task-llm-1",
        session_id_getter=lambda: "session-llm-1",
        phase_getter=lambda: "understand_task",
        goal_getter=lambda: "请总结项目结构",
    )

    response = proxy.complete(
        LLMRequest(
            messages=[LLMMessage(role="user", content="请总结项目结构")],
            response_format="json_object",
            trace_info={"semantic_task": "goal"},
        )
    )

    assert response.model == "demo-model"
    run = hooks.recorder.load_run("session-llm-1")
    assert run is not None
    events = hooks.recorder.load_trajectory_events(run.run_id)
    summary = hooks.recorder.load_run_summary(run.run_id)
    assert [event["event_type"] for event in events] == ["llm_requested", "llm_responded"]
    assert events[0]["payload_kind"] == "llm_request"
    assert events[1]["payload_kind"] == "llm_response"
    assert events[0]["payload"]["correlation"]["task_id"] == "task-llm-1"
    diagnostics = events[0]["payload"]["trace_info"]["diagnostics"]
    assert diagnostics["message_count"] == 1
    assert diagnostics["prompt_chars"] == len("请总结项目结构")
    assert diagnostics["response_format"] == "json_object"
    assert diagnostics["model"] == "demo-model"
    assert diagnostics["provider"] == "demo-provider"
    assert events[1]["payload"]["correlation"]["execution_id"].startswith("llm_")
    assert summary is not None
    assert summary.artifact_count >= 2
    artifacts = hooks.recorder._load_jsonl(hooks.recorder._artifacts_index_file(run.run_id))
    assert {artifact["kind"] for artifact in artifacts} >= {"llm_request", "llm_response_text", "llm_response_json"}


def test_llm_proxy_records_failure_event(tmp_path) -> None:
    hooks = RuntimeDiagnosticsHooks(DiagnosticRecorder(tmp_path))

    class FailingLLMClient:
        settings = SimpleNamespace(model="demo-model", provider="demo-provider")

        def complete(self, request, max_retries=3, use_cache=True, stream_callback=None):
            raise TimeoutError("provider timed out")

    proxy = TrajectoryLLMClientProxy(
        FailingLLMClient(),
        hooks=hooks,
        task_id_getter=lambda: "task-llm-2",
        session_id_getter=lambda: "session-llm-2",
        phase_getter=lambda: "plan",
        goal_getter=lambda: "请分析模块依赖",
    )

    try:
        proxy.complete(
            LLMRequest(
                messages=[LLMMessage(role="user", content="请分析模块依赖")],
                response_format="text",
                trace_info={"purpose": "dependency_analysis"},
            )
        )
    except TimeoutError:
        pass
    else:
        raise AssertionError("Expected TimeoutError")

    run = hooks.recorder.load_run("session-llm-2")
    assert run is not None
    events = hooks.recorder.load_trajectory_events(run.run_id)
    assert [event["event_type"] for event in events] == ["llm_requested", "llm_failed"]
    assert events[1]["payload_kind"] == "failure"
    assert events[1]["payload"]["error_type"] == "TimeoutError"
    failure_diagnostics = events[1]["payload"]["details"]["diagnostics"]
    assert failure_diagnostics["message_count"] == 1
    assert failure_diagnostics["response_format"] == "text"
    assert failure_diagnostics["model"] == "demo-model"


def test_generate_stage_summary_writes_markdown_and_json(tmp_path) -> None:
    recorder = DiagnosticRecorder(tmp_path / "data")
    signal = suspicious_success_signal(task_id="task-z", evidence=["verification_status=not_started"])
    recorder.record_judgment(signal, judge_signal(signal))

    md_path, json_path = generate_stage_summary(data_dir=tmp_path / "data", output_dir=tmp_path / "out")

    assert md_path.exists()
    assert json_path.exists()
    assert md_path.read_text(encoding="utf-8").startswith("# Runtime Diagnostics Summary")


def test_recorder_normalizes_subtask_payload_to_root_task(tmp_path) -> None:
    recorder = DiagnosticRecorder(tmp_path)
    recorder.record_event(
        "root-task-1",
        event_type="task_received",
        source="manual",
        raw_input="请检查根任务",
        session_id="session-root-1",
        payload=LogEventMetadata(
            source_type="system",
            source_name="openpilot",
            phase="entry",
            event_type="task_received",
            input_summary={
                "task_id": "root-task-1",
                "source": "manual",
                "raw_input": "请检查根任务",
                "session_id": "session-root-1",
            },
        ),
    )

    recorder.record_event(
        "session-root-1",
        event_type="tool_failed",
        session_id="session-root-1",
        payload={
            "kind": "tool_error",
            "tool_name": "file_reader",
            "error_type": "FileNotFoundError",
            "error_message": "missing file",
            "correlation": {
                "task_id": "subtask-root-1",
                "session_id": "session-root-1",
                "step_id": "step-9",
                "execution_id": "call-9",
            },
        },
    )

    run = recorder.load_run("session-root-1")
    assert run is not None
    events = recorder.load_trajectory_events(run.run_id)
    tool_failed = events[-1]
    assert tool_failed["task_id"] == "root-task-1"
    assert tool_failed["payload"]["correlation"]["task_id"] == "root-task-1"
    assert tool_failed["payload"]["annotations"]["subtask_id"] == "subtask-root-1"
    assert tool_failed["payload"]["annotations"]["parent_task_id"] == "root-task-1"


def test_hooks_task_finished_normalizes_subtask_to_root_task(tmp_path) -> None:
    hooks = RuntimeDiagnosticsHooks(DiagnosticRecorder(tmp_path))
    hooks.on_task_received(
        task_id="root-finish-1",
        source="manual",
        raw_input="请完成任务",
        session_id="session-finish-1",
    )

    hooks.on_task_finished(
        task_id="subtask-finish-1",
        success=True,
        session_id="session-finish-1",
        summary={"completion_reason": "done", "phase": "summarize"},
    )

    run = hooks.recorder.load_run("session-finish-1")
    assert run is not None
    events = hooks.recorder.load_trajectory_events(run.run_id)
    finished = events[-1]
    assert finished["event_type"] == "task_finished"
    assert finished["task_id"] == "root-finish-1"
    assert finished["payload"]["correlation"]["task_id"] == "root-finish-1"
    assert finished["payload"]["annotations"]["subtask_id"] == "subtask-finish-1"
