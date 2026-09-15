from __future__ import annotations

import json
import socket
import sys
import threading
from types import SimpleNamespace
import pytest

from autonomous_iteration import EngineKind, HarnessApplication, RunCoordinator
from evidence_core import (
    EvidenceAuthority,
    EvidenceLayer,
    EvidenceStore,
    TerminalStatus,
    validate_trajectory_conformance,
)
from autonomous_iteration.action_gateway import ActionGateway, ActionRequest, ValidationRequest
from tools.tool_selection import SelectionReason, ToolSelection
from autonomous_iteration.verification import CompletionProfile, evaluate_completion
from evidence_core import EventRecord
from evidence_core import EvidenceReader
from autonomous_iteration import FakePiEngine, PiRpcEngine, PiSidecarConfig, PiSidecarState
from autonomous_iteration.engines.pi_sidecar import _PiToolSocketBridge
from autonomous_iteration.checkpoint_store import RuntimeCheckpointStore
from autonomous_iteration.supervisor import RuntimeSupervisor, SupervisorSession
from autonomous_iteration.verification import HarnessPhase, HarnessPolicyKind
from autonomous_iteration.intelligent_autopilot import IntelligentAutopilot


def test_harness_application_routes_observation_and_semantic_mapping(tmp_path) -> None:
    app = HarnessApplication(EvidenceStore(tmp_path / "evidence"))
    run = app.start("task-ports", session_id="session-ports")
    raw = app.observe(
        run,
        event_type="tool_result",
        payload={"ok": True},
        producer="tool_executor",
        call_id="call-1",
        idempotency_key="tool-result:1",
    )
    semantic = app.map_semantic(
        run,
        event_type="verification_state_changed",
        source_observation_id=raw.event_id,
        payload={"verification_status": "passed"},
        authority=EvidenceAuthority.VERIFIED,
    )

    assert raw.layer is EvidenceLayer.RAW
    assert semantic.layer is EvidenceLayer.SEMANTIC
    assert semantic.source_observation_id == raw.event_id
    assert semantic.call_id == "call-1"


def test_harness_application_is_pi_only(tmp_path) -> None:
    default = HarnessApplication(EvidenceStore(tmp_path / "default"))

    assert default.engine is EngineKind.PI
    with pytest.raises(ValueError, match="legacy"):
        HarnessApplication(EvidenceStore(tmp_path / "legacy"), engine="legacy")


def test_legacy_adapter_module_is_removed() -> None:
    import importlib.util

    assert importlib.util.find_spec("autonomous_iteration.engines.legacy_adapter") is None


def test_harness_policy_profiles_expose_phase_scoped_affordances(tmp_path) -> None:
    read_only = HarnessApplication(
        EvidenceStore(tmp_path / "read-only"),
        policy=HarnessPolicyKind.READ_ONLY,
    )
    developer = HarnessApplication(
        EvidenceStore(tmp_path / "developer"),
        policy=HarnessPolicyKind.DEVELOPER,
    )
    approval = HarnessApplication(
        EvidenceStore(tmp_path / "approval"),
        policy=HarnessPolicyKind.APPROVAL_REQUIRED,
    )

    assert read_only.allowed_pi_tools(HarnessPhase.ACT) == ("openpilot_read",)
    assert developer.allowed_pi_tools(HarnessPhase.PLAN) == ("openpilot_read",)
    assert developer.allowed_pi_tools(HarnessPhase.ACT) == (
        "openpilot_read",
        "openpilot_patch",
    )
    assert developer.allowed_pi_tools(HarnessPhase.VERIFY) == (
        "openpilot_read",
        "openpilot_validate",
    )
    assert approval.policy.approval_required is True


def test_application_entry_routes_selected_pi_engine_without_legacy_fallback() -> None:
    calls: list[tuple[str, object]] = []
    run = SimpleNamespace(run_id="pi-evidence-run")

    class FakeCoordinator:
        def attach_run(self, run_id):
            return run

    class FakeHarness:
        engine = SimpleNamespace(value="pi")
        coordinator = FakeCoordinator()

        def start(self, task_id, **metadata):
            calls.append(("start", task_id))
            return run

        def canonical(self, handle, **observation):
            calls.append(("canonical", observation["event_type"]))

        def run_pi(self, run_id, **request):
            calls.append(("run_pi", run_id))
            return {"status": "blocked", "success": False}

    fake = SimpleNamespace(
        stats={"start_time": None},
        _normalize_execution_context=lambda context: dict(context),
        runtime_diagnostics_hooks=None,
        harness_application=FakeHarness(),
        runtime_controller=SimpleNamespace(
            run=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("legacy controller fallback is forbidden")
            )
        ),
        tool_executor=SimpleNamespace(),
        use_enhanced_ui=False,
        enhanced_ui=None,
        tracker=None,
        logger=SimpleNamespace(log_event=lambda *_args, **_kwargs: None),
    )

    result = IntelligentAutopilot.execute(fake, "inspect", {"task_id": "pi-entry"})

    assert result == {"status": "blocked", "success": False}
    assert [name for name, _ in calls] == ["start", "canonical", "run_pi"]


def test_pi_entry_rejects_loose_scope_fields_without_an_admission_grant() -> None:
    run = SimpleNamespace(run_id="pi-evidence-run")

    class FakeHarness:
        engine = SimpleNamespace(value="pi")

        def start(self, *_args, **_kwargs):
            return run

        def canonical(self, *_args, **_kwargs):
            return None

    fake = SimpleNamespace(
        stats={"start_time": None},
        _normalize_execution_context=lambda context: dict(context),
        runtime_diagnostics_hooks=None,
        harness_application=FakeHarness(),
        use_enhanced_ui=False,
        enhanced_ui=None,
        tracker=None,
        logger=SimpleNamespace(log_event=lambda *_args, **_kwargs: None),
    )

    with pytest.raises(ValueError, match="TaskAdmissionGrant"):
        IntelligentAutopilot.execute(
            fake,
            "inspect",
            {"task_id": "task-entry", "read_files": ["README.md"]},
        )


def test_coordinator_rejects_unknown_semantic_source(tmp_path) -> None:
    coordinator = RunCoordinator(EvidenceStore(tmp_path / "evidence"))
    run = coordinator.start_run("task-invalid")

    with pytest.raises(ValueError, match="not persisted"):
        coordinator.map_semantic(
            run,
            event_type="task_finished",
            source_observation_id="missing",
        )


def test_conformance_accepts_coordinated_raw_and_semantic_events(tmp_path) -> None:
    app = HarnessApplication(EvidenceStore(tmp_path / "evidence"))
    run = app.start("task-conformance")
    received = app.canonical(run, event_type="task_received", payload={}, producer="pi", call_id="turn-1")
    app.canonical(run, event_type="tool_called", payload={}, producer="tool_executor", call_id="call-1")
    result = app.canonical(run, event_type="tool_succeeded", payload={}, producer="tool_executor", call_id="call-1")
    app.map_semantic(
        run,
        event_type="verification_state_changed",
        source_observation_id=result.source_observation_id,
        payload={"verification_status": "passed"},
        authority=EvidenceAuthority.VERIFIED,
    )
    app.finish(run, success=False, reason="stopped")

    conformance = validate_trajectory_conformance(app.coordinator.evidence.load_trajectory_events(run.run_id))
    assert conformance.valid is True
    assert received.call_id == "turn-1"


def test_action_gateway_fails_closed_for_unconfirmed_mutation(tmp_path) -> None:
    selection = ToolSelection(step_id="step-1", tool_name="file_patch_writer", reason=SelectionReason.ONLY_OPTION)
    request = ActionRequest(call_id="call-1", selection=selection, mutation=True, mutation_opt_in=False, user_confirmed=True, write_scope=("a.py",))

    with pytest.raises(PermissionError, match="opt-in"):
        ActionGateway._admit(request)


def test_action_gateway_requires_completed_declared_reads_before_mutation(tmp_path) -> None:
    class FakeExecutor:
        def execute_single(self, selection, context=None):
            return SimpleNamespace(success=True, execution_id="execution-1")

    coordinator = RunCoordinator(EvidenceStore(tmp_path / "evidence"))
    run = coordinator.start_run("mutation-read-gate")
    gateway = ActionGateway(coordinator, FakeExecutor())
    selection = ToolSelection(
        step_id="patch-1",
        tool_name="file_patch_writer",
        reason=SelectionReason.ONLY_OPTION,
    )

    with pytest.raises(PermissionError, match="declared reads"):
        gateway.execute(
            run,
            ActionRequest(
                call_id="patch-1",
                selection=selection,
                mutation=True,
                declared_read_files=("a.py",),
                write_scope=("a.py",),
                user_confirmed=True,
                mutation_opt_in=True,
            ),
        )


def test_agent_end_does_not_imply_success() -> None:
    decision = evaluate_completion([
        EventRecord(run_id="r", sequence=1, event_type="agent_end", payload={}),
    ])
    assert decision.status.value == "running"


def test_mutation_completion_requires_receipt_validation_and_verification() -> None:
    events = [
        EventRecord(run_id="r", sequence=1, event_type="task_received", payload={}),
        EventRecord(run_id="r", sequence=2, event_type="mutation_receipt", payload={}),
        EventRecord(run_id="r", sequence=3, event_type="task_finished", payload={"success": True}),
    ]
    decision = evaluate_completion(events, profile=CompletionProfile.MUTATION)
    assert decision.status.value in {"evidence_gap", "blocked"}


def test_pi_mutation_completion_requires_engine_stop_and_passing_validation() -> None:
    base = [
        EventRecord(run_id="r", sequence=1, event_type="engine_started", producer="pi"),
        EventRecord(run_id="r", sequence=2, event_type="task_received"),
        EventRecord(
            run_id="r",
            sequence=3,
            event_type="mutation_requested",
            payload={"action": {"kind": "patch"}},
        ),
        EventRecord(
            run_id="r",
            sequence=4,
            event_type="tool_called",
            call_id="patch-1",
            payload={"action": {"kind": "patch"}},
        ),
        EventRecord(run_id="r", sequence=5, event_type="tool_succeeded", call_id="patch-1"),
        EventRecord(
            run_id="r",
            sequence=6,
            event_type="mutation_receipt",
            call_id="patch-1",
            payload={"durable": True},
        ),
        EventRecord(
            run_id="r",
            sequence=7,
            event_type="validation_completed",
            payload={"success": True},
        ),
        EventRecord(
            run_id="r",
            sequence=8,
            event_type="verification_state_changed",
            payload={"verification_status": "passed"},
        ),
        EventRecord(
            run_id="r",
            sequence=9,
            event_type="task_finished",
            authority="verified",
            payload={"success": True},
        ),
    ]

    not_stopped = evaluate_completion(base, profile=CompletionProfile.MUTATION)
    failed_validation_events = [
        event.model_copy(
            update={"payload": {"success": False}}
        )
        if event.event_type == "validation_completed"
        else event
        for event in base
    ]
    failed_validation_events.insert(
        -1,
        EventRecord(run_id="r", sequence=10, event_type="engine_stopped", producer="pi"),
    )

    assert not_stopped.status.value == "blocked"
    assert evaluate_completion(
        failed_validation_events,
        profile=CompletionProfile.MUTATION,
    ).status.value == "blocked"


def test_fake_pi_sidecar_crash_is_observable_and_never_success(tmp_path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    coordinator = RunCoordinator(store)
    run = coordinator.start_run("task-pi")
    engine = FakePiEngine(coordinator)
    messages = engine.run_once(run, prompt="inspect", crash=True)

    assert engine.state is PiSidecarState.CRASHED
    assert messages[-1].message_type == "engine_crashed"
    events = EvidenceReader(store).events(run.run_id)
    decision = evaluate_completion(events)
    assert decision.status.value == "crashed"


def test_pi_application_route_never_treats_agent_stop_as_readonly_success(tmp_path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    app = HarnessApplication(store, engine="pi")
    run = app.start("pi-application")
    app.canonical(
        run,
        event_type="task_received",
        payload={},
        producer="application_entry",
    )

    result = app.run_pi(
        run.run_id,
        engine=FakePiEngine(app.coordinator),
        prompt="inspect",
    )

    assert result["success"] is False
    assert result["status"] == "blocked"
    assert store.load_run(run.run_id).final_status == "blocked"


def test_child_run_has_explicit_parent_lineage(tmp_path) -> None:
    coordinator = RunCoordinator(EvidenceStore(tmp_path / "evidence"))
    root = coordinator.start_run("root-task")
    child = coordinator.start_child_run(root, "child-task")

    assert child.run.parent_run_id == root.run_id
    assert child.run.root_task_id == root.run.task_id


def test_coordinator_marks_indeterminate_without_emitting_task_finished(tmp_path) -> None:
    coordinator = RunCoordinator(EvidenceStore(tmp_path / "evidence"))
    run = coordinator.start_run("recovery-state")

    event = coordinator.mark_recovery_state(
        run,
        status=TerminalStatus.INDETERMINATE,
        reason="receipt requires reconciliation",
    )

    events = coordinator.evidence.load_trajectory_events(run.run_id)
    assert event.event_type == "recovery_state_changed"
    assert all(item.event_type != "task_finished" for item in events)
    loaded = coordinator.evidence.load_run(run.run_id)
    assert loaded is not None
    assert loaded.final_status.value == "indeterminate"


def test_supervisor_owns_resume_identity_and_serializes_run_lease(tmp_path) -> None:
    coordinator = RunCoordinator(EvidenceStore(tmp_path / "evidence"))
    run = coordinator.start_run("supervised-run")
    first = RuntimeSupervisor(RuntimeCheckpointStore(tmp_path / "checkpoints"))
    second = RuntimeSupervisor(RuntimeCheckpointStore(tmp_path / "checkpoints"))
    session = SupervisorSession(first, run)

    assert session.acquire() is True
    assert second.try_acquire_run_lease(run.run_id) is None
    assert first.new_resume_attempt_id() != first.new_resume_attempt_id()
    session.release()

    second_lease = second.try_acquire_run_lease(run.run_id)
    assert second_lease is not None
    second.release_run_lease(second_lease)


def test_pi_rpc_engine_persists_lf_jsonl_events_before_stopping(tmp_path) -> None:
    fake = tmp_path / "fake_pi.py"
    fake.write_text(
        "import json, sys\n"
        "request = json.loads(sys.stdin.buffer.readline())\n"
        "records = [\n"
        " {'id': request['id'], 'type': 'response', 'command': 'prompt', 'success': True},\n"
        " {'type': 'agent_start'}, {'type': 'turn_start'},\n"
        " {'type': 'message_end', 'message': {'role': 'assistant', 'content': 'ok'}},\n"
        " {'type': 'turn_end'}, {'type': 'agent_end'}]\n"
        "sys.stdout.write(''.join(json.dumps(item) + '\\n' for item in records))\n"
        "sys.stdout.flush()\n",
        encoding="utf-8",
    )
    store = EvidenceStore(tmp_path / "evidence")
    coordinator = RunCoordinator(store)
    run = coordinator.start_run("pi-rpc-task")
    engine = PiRpcEngine(
        coordinator,
        PiSidecarConfig(command=(sys.executable, str(fake)), timeout_seconds=2),
        engine_session_id="engine-1",
    )

    messages = engine.run_once(run, prompt="hello")

    assert engine.state is PiSidecarState.STOPPED
    assert messages[-1].message_type == "engine_stopped"
    assert "--no-tools" in engine.config.argv()
    assert [event.event_type for event in store.load_trajectory_events(run.run_id)] == [
        "engine_started",
        "model_request",
        "engine_started",
        "turn_started",
        "model_response",
        "turn_finished",
        "agent_end",
        "engine_stopped",
    ]


def test_pi_rpc_engine_eof_is_crashed_not_success(tmp_path) -> None:
    fake = tmp_path / "crash_pi.py"
    fake.write_text("import sys\nsys.stdin.buffer.readline()\n", encoding="utf-8")
    store = EvidenceStore(tmp_path / "evidence")
    coordinator = RunCoordinator(store)
    run = coordinator.start_run("pi-rpc-crash")
    engine = PiRpcEngine(
        coordinator,
        PiSidecarConfig(command=(sys.executable, str(fake)), timeout_seconds=2),
    )

    messages = engine.run_once(run, prompt="hello")

    assert engine.state is PiSidecarState.CRASHED
    assert messages[-1].message_type == "engine_crashed"
    assert evaluate_completion(store.load_trajectory_events(run.run_id)).status.value == "crashed"


def test_pi_rpc_engine_rejects_oversized_unframed_stdout(tmp_path) -> None:
    fake = tmp_path / "oversized_pi.py"
    fake.write_text(
        "import sys\n"
        "sys.stdin.buffer.readline()\n"
        "sys.stdout.buffer.write(b'x' * 1000001)\n"
        "sys.stdout.buffer.flush()\n",
        encoding="utf-8",
    )
    store = EvidenceStore(tmp_path / "evidence")
    coordinator = RunCoordinator(store)
    run = coordinator.start_run("pi-rpc-oversized")
    engine = PiRpcEngine(
        coordinator,
        PiSidecarConfig(command=(sys.executable, str(fake)), timeout_seconds=2),
    )

    messages = engine.run_once(run, prompt="hello")

    assert engine.state is PiSidecarState.CRASHED
    assert messages[-1].message_type == "engine_crashed"
    assert store.events_file(run.run_id).stat().st_size < 20_000


def test_pi_read_tool_bridge_routes_request_to_openpilot_handler() -> None:
    observed_requests: list[dict[str, object]] = []
    observed_results: list[dict[str, object]] = []
    bridge = _PiToolSocketBridge(
        lambda request: {"text": f"read:{request['args']['path']}"},
        on_request=observed_requests.append,
        on_result=observed_results.append,
    )
    bridge.start()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(bridge.socket_path)
            client.sendall(
                json.dumps(
                    {
                        "type": "tool_call",
                        "toolName": "openpilot_read",
                        "toolCallId": "call-1",
                        "args": {"path": "README.md"},
                    }
                ).encode("utf-8")
                + b"\n"
            )
            response = json.loads(client.makefile("rb").readline())
    finally:
        bridge.stop()

    assert response["success"] is True
    assert "read:README.md" in response["content"]
    assert observed_requests[0]["toolCallId"] == "call-1"
    assert observed_results == [{"toolCallId": "call-1", "success": True}]


def _send_bridge_record(socket_path: str, payload: bytes) -> dict[str, object]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        client.connect(socket_path)
        client.sendall(payload)
        return json.loads(client.makefile("rb").readline())


def test_pi_tool_bridge_rejects_malformed_and_oversized_requests_without_dying() -> None:
    bridge = _PiToolSocketBridge(
        lambda request: "ok",
        on_request=lambda request: None,
        on_result=lambda result: None,
    )
    bridge.start()
    try:
        malformed = _send_bridge_record(bridge.socket_path, b"not-json\n")
        oversized = _send_bridge_record(
            bridge.socket_path,
            b'{"toolName":"openpilot_read","toolCallId":"large","args":{"path":"'
            + (b"x" * 1_000_001)
            + b'"}}\n',
        )
        healthy = _send_bridge_record(
            bridge.socket_path,
            json.dumps(
                {
                    "toolName": "openpilot_read",
                    "toolCallId": "healthy",
                    "args": {"path": "README.md"},
                }
            ).encode("utf-8")
            + b"\n",
        )
    finally:
        bridge.stop()

    assert malformed["success"] is False
    assert oversized["success"] is False
    assert healthy["success"] is True


def test_pi_tool_bridge_bounds_results_and_does_not_expose_handler_secrets() -> None:
    def handler(request: dict[str, object]) -> str:
        if request["toolCallId"] == "secret":
            raise RuntimeError("authorization=Bearer super-secret")
        return "x" * 100_000

    bridge = _PiToolSocketBridge(
        handler,
        on_request=lambda request: None,
        on_result=lambda result: None,
    )
    bridge.start()
    try:
        failed = _send_bridge_record(
            bridge.socket_path,
            b'{"toolName":"openpilot_read","toolCallId":"secret","args":{}}\n',
        )
        bounded = _send_bridge_record(
            bridge.socket_path,
            b'{"toolName":"openpilot_read","toolCallId":"large-result","args":{}}\n',
        )
    finally:
        bridge.stop()

    assert failed["success"] is False
    assert "super-secret" not in str(failed)
    assert bounded["success"] is True
    assert len(str(bounded["content"]).encode("utf-8")) <= 16_384


def test_pi_tool_bridge_marks_handler_timeout_indeterminate_and_stops_cleanly() -> None:
    release = threading.Event()
    observed_results: list[dict[str, object]] = []

    def handler(_request):
        release.wait(timeout=1)
        return "late"

    bridge = _PiToolSocketBridge(
        handler,
        on_request=lambda request: None,
        on_result=observed_results.append,
        handler_timeout_seconds=0.05,
    )
    bridge.start()
    try:
        response = _send_bridge_record(
            bridge.socket_path,
            b'{"toolName":"openpilot_patch","toolCallId":"slow","args":{}}\n',
        )
    finally:
        bridge.stop()
        release.set()

    assert response["success"] is False
    assert response["indeterminate"] is True
    assert observed_results == [
        {"toolCallId": "slow", "success": False, "indeterminate": True}
    ]


def test_pi_rpc_engine_crash_evidence_does_not_persist_exception_secrets(tmp_path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    coordinator = RunCoordinator(store)
    run = coordinator.start_run("pi-secret-crash")
    engine = PiRpcEngine(
        coordinator,
        PiSidecarConfig(command=("/missing/Bearer-super-secret",), timeout_seconds=1),
    )

    engine.run_once(run, prompt="hello")

    persisted = store.events_file(run.run_id).read_text(encoding="utf-8")
    assert "Bearer-super-secret" not in persisted


def test_pi_sidecar_environment_forwards_only_allowlisted_provider_credentials(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "provider-secret")
    monkeypatch.setenv("UNRELATED_PRIVATE_SECRET", "must-not-cross-boundary")
    engine = PiRpcEngine(
        RunCoordinator(EvidenceStore(tmp_path / "evidence")),
        environment={"OPENPILOT_EXPLICIT_SETTING": "enabled"},
    )

    environment = engine._sidecar_environment()

    assert environment["OPENAI_API_KEY"] == "provider-secret"
    assert environment["OPENPILOT_EXPLICIT_SETTING"] == "enabled"
    assert "UNRELATED_PRIVATE_SECRET" not in environment


def test_pi_read_tool_config_loads_only_openpilot_extension() -> None:
    argv = PiSidecarConfig(enable_read_tool=True).argv()
    assert "--no-builtin-tools" in argv
    assert "--no-tools" not in argv
    assert argv[argv.index("--tools") + 1] == "openpilot_read"


def test_pi_read_handler_uses_action_gateway_and_declared_scope(tmp_path) -> None:
    class FakeExecutor:
        def execute_single(self, selection, context=None):
            return SimpleNamespace(
                success=True,
                execution_id="execution-1",
                output_metadata=SimpleNamespace(
                    result=SimpleNamespace(content=f"content:{selection.input_metadata.file_path}")
                ),
                error=None,
            )

    coordinator = RunCoordinator(EvidenceStore(tmp_path / "evidence"))
    run = coordinator.start_run("pi-read")
    gateway = ActionGateway(coordinator, FakeExecutor())
    handler = gateway.pi_read_handler(run, allowed_read_files=("README.md",))

    assert handler(
        {
            "toolName": "openpilot_read",
            "toolCallId": "call-1",
            "args": {"path": "README.md"},
        }
    ) == "content:README.md"
    with pytest.raises(PermissionError, match="outside declared scope"):
        handler(
            {
                "toolName": "openpilot_read",
                "toolCallId": "call-2",
                "args": {"path": "secret.txt"},
            }
        )
    semantic = [
        event
        for event in coordinator.evidence.load_trajectory_events(run.run_id)
        if event.layer.value == "semantic"
    ]
    assert [event.event_type for event in semantic] == ["tool_called", "tool_succeeded"]
    assert {event.call_id for event in semantic} == {"call-1"}


def test_pi_mutation_routes_through_receipt_and_exact_validation(tmp_path) -> None:
    selections: list[ToolSelection] = []

    class FakeExecutor:
        def execute_single(self, selection, context=None):
            selections.append(selection)
            content = "source" if selection.tool_name == "file_reader" else "ok"
            return SimpleNamespace(
                success=True,
                execution_id=f"execution-{len(selections)}",
                output_metadata=SimpleNamespace(
                    result=SimpleNamespace(content=content)
                ),
                error=None,
            )

    coordinator = RunCoordinator(EvidenceStore(tmp_path / "evidence"))
    run = coordinator.start_run("pi-mutation")
    gateway = ActionGateway(coordinator, FakeExecutor())
    handler = gateway.pi_action_handler(
        run,
        allowed_read_files=("a.py",),
        allowed_write_files=("a.py",),
        validation=ValidationRequest(
            call_id="validation",
            command="python -m pytest -q",
            cwd=str(tmp_path),
        ),
        mutation_opt_in=True,
        user_confirmed=True,
    )

    assert handler(
        {
            "toolName": "openpilot_read",
            "toolCallId": "read-1",
            "args": {"path": "a.py"},
        }
    ) == "source"
    patch_result = handler(
        {
            "toolName": "openpilot_patch",
            "toolCallId": "patch-1",
            "args": {
                "path": "a.py",
                "lineStart": 1,
                "lineEnd": 1,
                "replacementText": "updated",
            },
        }
    )
    validation_result = handler(
        {
            "toolName": "openpilot_validate",
            "toolCallId": "validate-1",
            "args": {"command": "python -m pytest -q"},
        }
    )

    assert patch_result["receipt"]["durable"] is True
    assert validation_result["success"] is True
    assert [selection.tool_name for selection in selections] == [
        "file_reader",
        "file_patch_writer",
        "command_executor",
    ]
    semantic_types = [
        event.event_type
        for event in coordinator.evidence.load_trajectory_events(run.run_id)
        if event.layer.value == "semantic"
    ]
    assert "mutation_requested" in semantic_types
    assert "mutation_receipt" in semantic_types
    assert "validation_completed" in semantic_types
    assert "verification_state_changed" in semantic_types

    with pytest.raises(PermissionError, match="exact declared command"):
        handler(
            {
                "toolName": "openpilot_validate",
                "toolCallId": "validate-2",
                "args": {"command": "python -m pytest -q other.py"},
            }
        )


def test_pi_action_handler_normalizes_relative_paths_within_declared_scope(tmp_path) -> None:
    target = tmp_path / "a.py"

    class FakeExecutor:
        def execute_single(self, selection, context=None):
            content = "source" if selection.tool_name == "file_reader" else "ok"
            return SimpleNamespace(
                success=True,
                execution_id=f"execution-{selection.step_id}",
                output_metadata=SimpleNamespace(
                    result=SimpleNamespace(content=content, success=True, exit_code=0)
                ),
                error=None,
            )

    coordinator = RunCoordinator(EvidenceStore(tmp_path / "evidence"))
    run = coordinator.start_run("normalized-pi-path")
    handler = ActionGateway(coordinator, FakeExecutor()).pi_action_handler(
        run,
        allowed_read_files=(str(target),),
        allowed_write_files=(str(target),),
        validation=ValidationRequest(
            call_id="validation",
            command="python check.py",
            cwd=str(tmp_path),
        ),
        mutation_opt_in=True,
        user_confirmed=True,
    )

    assert handler(
        {
            "toolName": "openpilot_read",
            "toolCallId": "read-relative",
            "args": {"path": "a.py"},
        }
    ) == "source"
    result = handler(
        {
            "toolName": "openpilot_patch",
            "toolCallId": "patch-relative",
            "args": {
                "path": "a.py",
                "lineStart": 1,
                "lineEnd": 1,
                "replacementText": "updated",
            },
        }
    )

    assert result["success"] is True
    mutation_events = [
        event
        for event in coordinator.evidence.load_trajectory_events(run.run_id)
        if event.event_type == "mutation_requested" and event.layer.value == "semantic"
    ]
    assert mutation_events


def test_exact_validation_fails_closed_on_nonzero_command_artifact(tmp_path) -> None:
    class FakeExecutor:
        def execute_single(self, selection, context=None):
            return SimpleNamespace(
                success=True,
                execution_id="validation-execution",
                output_metadata=SimpleNamespace(
                    result=SimpleNamespace(success=False, exit_code=1)
                ),
                error=None,
            )

    coordinator = RunCoordinator(EvidenceStore(tmp_path / "evidence"))
    run = coordinator.start_run("validation-exit-code")
    gateway = ActionGateway(coordinator, FakeExecutor())
    result = gateway.execute_validation(
        run,
        ValidationRequest(
            call_id="validate-1",
            command="python check.py",
            cwd=str(tmp_path),
        ),
        requested_command="python check.py",
    )

    assert result.verified is False
    completed = [
        event
        for event in coordinator.evidence.load_trajectory_events(run.run_id)
        if event.event_type == "validation_completed" and event.layer.value == "semantic"
    ]
    assert completed[-1].payload["success"] is False
    assert completed[-1].payload["exit_code"] == 1


def test_pi_mutation_tool_config_exposes_only_openpilot_tools() -> None:
    argv = PiSidecarConfig(enable_read_tool=True, enable_mutation_tools=True).argv()

    assert "--no-builtin-tools" in argv
    assert argv[argv.index("--tools") + 1] == (
        "openpilot_read,openpilot_patch,openpilot_validate"
    )
