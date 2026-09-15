from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from autonomous_iteration.application import HarnessApplication
from autonomous_iteration.checkpoint_store import RuntimeCheckpointStore
from autonomous_iteration.pi_mutation_recovery import PiMutationRecoveryRunner
from autonomous_iteration.pi_task_runner import PiTaskRunner
from autonomous_iteration.supervisor import RuntimeSupervisor
from evidence_core import EvidenceStore, TerminalStatus
from metadata import (
    EnvironmentOperation,
    EnvironmentReadiness,
    EnvironmentSyncMetadata,
    FileMutationPrecondition,
    TaskAdmissionGrant,
    TaskApprovalGrant,
    ValidationGrant,
)


def _mutation_grant(tmp_path) -> TaskAdmissionGrant:
    target = tmp_path / "service.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    baseline = target.stat()
    return TaskAdmissionGrant(
        admission_id="admission-recovery",
        task_id="task-recovery",
        project_root=str(tmp_path),
        read_files=[str(target)],
        write_files=[str(target)],
        validation=ValidationGrant(
            command="python -m pytest tests/test_service.py",
            cwd=str(tmp_path),
        ),
        write_preconditions=[
            FileMutationPrecondition(
                path=str(target),
                device=baseline.st_dev,
                inode=baseline.st_ino,
                size_bytes=baseline.st_size,
                mtime_ns=baseline.st_mtime_ns,
            )
        ],
    )


def _approval(
    grant: TaskAdmissionGrant,
    *,
    approval_id: str,
    conversation_id: str = "conversation-1",
) -> TaskApprovalGrant:
    return TaskApprovalGrant(
        approval_id=approval_id,
        proposal_id="proposal-recovery",
        admission_id=grant.admission_id,
        task_id=grant.task_id,
        project_root=grant.project_root,
        conversation_id=conversation_id,
        protocol_version=grant.protocol_version,
    )


def _ready_environment(tmp_path) -> EnvironmentSyncMetadata:
    return EnvironmentSyncMetadata(
        project_path=str(tmp_path),
        command_cwd=str(tmp_path),
        python_executable=str(tmp_path / ".venv" / "bin" / "python"),
        command_env={"PATH": str(tmp_path / ".venv" / "bin")},
        readiness=EnvironmentReadiness.READY,
        environment_id="environment-recovery",
        operation=EnvironmentOperation.SYNC,
    )


class _Executor:
    def __init__(self, selections: list[object]) -> None:
        self._selections = selections

    def execute_single(self, selection, context=None):
        del context
        self._selections.append(selection)
        if selection.tool_name == "file_patch_writer":
            target = Path(str(selection.input_metadata.file_path))
            replacement = str(selection.input_metadata.replacement_text)
            target.write_text(f"{replacement}\n", encoding="utf-8")
        content = "VALUE = 1\n" if selection.tool_name == "file_reader" else "ok"
        return SimpleNamespace(
            success=True,
            execution_id=f"execution-{selection.step_id}",
            output_metadata=SimpleNamespace(
                result=SimpleNamespace(content=content, success=True, exit_code=0)
            ),
            error=None,
        )


class _PatchThenStopEngine:
    state = SimpleNamespace(value="stopped")

    def __init__(self, coordinator, grant: TaskAdmissionGrant) -> None:
        self._coordinator = coordinator
        self._grant = grant

    def run_once(self, run, *, prompt, action_handler=None):
        del prompt
        assert action_handler is not None
        self._coordinator.record_observation(
            run,
            event_type="engine_started",
            payload={},
            producer="pi",
        )
        target = self._grant.write_files[0]
        assert action_handler(
            {"toolName": "openpilot_read", "toolCallId": "read-1", "args": {"path": target}}
        ) == "VALUE = 1\n"
        assert action_handler(
            {
                "toolName": "openpilot_patch",
                "toolCallId": "patch-1",
                "args": {
                    "path": target,
                    "lineStart": 1,
                    "lineEnd": 1,
                    "replacementText": "VALUE = 2",
                },
            }
        )["receipt"]["durable"] is True
        self._coordinator.record_observation(
            run,
            event_type="engine_stopped",
            payload={},
            producer="pi",
        )
        return []


def _stage_indeterminate_run(tmp_path, *, evidence_directory=None):
    grant = _mutation_grant(tmp_path)
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").touch()
    application = HarnessApplication(
        EvidenceStore(evidence_directory or tmp_path / "evidence"),
        engine="pi",
    )
    selections: list[object] = []
    initial_approval = _approval(grant, approval_id="approval-original")
    runner = PiTaskRunner(
        application_factory=lambda _grant: application,
        engine_factory=lambda coordinator, _config: _PatchThenStopEngine(coordinator, grant),
        executor_factory=lambda: _Executor(selections),
        environment_preflight=lambda **_kwargs: _ready_environment(tmp_path),
    )

    result = runner.run(
        "Repair service",
        grant,
        approval=initial_approval,
        conversation_id="conversation-1",
    )

    assert result["status"] == TerminalStatus.INDETERMINATE.value
    assert result["success"] is False
    assert (tmp_path / "service.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    return grant, application, selections, initial_approval, result["run_id"]


def _recovery_runner(tmp_path, application, selections):
    return PiMutationRecoveryRunner(
        application_factory=lambda _grant: application,
        executor_factory=lambda: _Executor(selections),
        environment_preflight=lambda **_kwargs: _ready_environment(tmp_path),
        supervisor_factory=lambda _root: RuntimeSupervisor(
            RuntimeCheckpointStore(tmp_path / "checkpoints")
        ),
    )


def test_pi_mutation_recovery_prepare_is_read_only_when_evidence_is_missing(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="Evidence store"):
        PiMutationRecoveryRunner().prepare(
            "missing-run",
            project_root=tmp_path,
        )

    assert not (tmp_path / ".openpilot").exists()


def test_pi_mutation_recovery_prepare_reloads_the_original_admission_and_proposal(tmp_path) -> None:
    evidence_directory = tmp_path / ".openpilot" / "evidence_core"
    grant, _application, _selections, _initial_approval, run_id = _stage_indeterminate_run(
        tmp_path,
        evidence_directory=evidence_directory,
    )

    prepared = PiMutationRecoveryRunner().prepare(
        run_id,
        project_root=tmp_path,
    )

    assert prepared.run_id == run_id
    assert prepared.admission == grant
    assert prepared.conversation_id == "conversation-1"
    assert prepared.proposal_id == "proposal-recovery"


def test_pi_mutation_recovery_reconciles_same_indeterminate_run_without_replaying_patch(tmp_path) -> None:
    grant, application, selections, initial_approval, run_id = _stage_indeterminate_run(tmp_path)
    events_before = application.coordinator.evidence.load_trajectory_events(run_id)

    received = next(event for event in events_before if event.event_type == "task_received")
    assert received.payload["admission"] == grant.model_dump(mode="json")
    assert all(event.event_type != "task_finished" for event in events_before)
    assert application.coordinator.evidence.load_run(run_id).final_status is TerminalStatus.INDETERMINATE

    result = _recovery_runner(tmp_path, application, selections).recover(
        run_id,
        grant,
        approval=_approval(grant, approval_id="approval-recovery"),
        conversation_id="conversation-1",
    )

    assert result["run_id"] == run_id
    assert result["success"] is True
    assert result["status"] == TerminalStatus.SUCCESS.value
    assert result["resume_attempt_id"]
    assert [selection.tool_name for selection in selections] == [
        "file_reader",
        "file_patch_writer",
        "command_executor",
    ]
    events_after = application.coordinator.evidence.load_trajectory_events(run_id)
    semantic_types = [
        event.event_type for event in events_after if event.layer.value == "semantic"
    ]
    assert semantic_types.count("mutation_receipt") == 1
    assert semantic_types.count("validation_completed") == 1
    assert semantic_types.count("task_finished") == 1
    loaded = application.coordinator.evidence.load_run(run_id)
    assert loaded is not None
    assert loaded.final_status is TerminalStatus.SUCCESS
    assert loaded.resume_attempt_id == result["resume_attempt_id"]


def test_pi_mutation_recovery_rejects_reused_original_approval(tmp_path) -> None:
    grant, application, selections, initial_approval, run_id = _stage_indeterminate_run(tmp_path)

    with pytest.raises(PermissionError, match="fresh approval"):
        _recovery_runner(tmp_path, application, selections).recover(
            run_id,
            grant,
            approval=initial_approval,
            conversation_id="conversation-1",
        )

    assert [selection.tool_name for selection in selections] == ["file_reader", "file_patch_writer"]


@pytest.mark.parametrize(
    ("grant_update", "conversation_id", "message"),
    [
        ({"task_id": "other-task"}, "conversation-1", "task identity"),
        ({"project_root": "/other-project"}, "conversation-1", "persisted admission"),
        ({}, "other-conversation", "session identity"),
    ],
)
def test_pi_mutation_recovery_rejects_task_project_and_session_mismatch(
    tmp_path,
    grant_update,
    conversation_id,
    message,
) -> None:
    grant, application, selections, _initial_approval, run_id = _stage_indeterminate_run(tmp_path)
    supplied_grant = grant.model_copy(update=grant_update)
    approval = _approval(
        supplied_grant,
        approval_id="approval-recovery",
        conversation_id=conversation_id,
    )

    with pytest.raises(PermissionError, match=message):
        _recovery_runner(tmp_path, application, selections).recover(
            run_id,
            supplied_grant,
            approval=approval,
            conversation_id=conversation_id,
        )

    assert [selection.tool_name for selection in selections] == ["file_reader", "file_patch_writer"]


def test_pi_mutation_recovery_rejects_a_run_with_existing_validation_evidence(tmp_path) -> None:
    grant, application, selections, _initial_approval, run_id = _stage_indeterminate_run(tmp_path)
    run = application.coordinator.attach_run(run_id)
    application.coordinator.record_canonical(
        run,
        event_type="validation_started",
        payload={"command": grant.validation.command},
        producer="test",
        idempotency_key="validation-started:test",
    )

    with pytest.raises(PermissionError, match="validation evidence"):
        _recovery_runner(tmp_path, application, selections).recover(
            run_id,
            grant,
            approval=_approval(grant, approval_id="approval-recovery"),
            conversation_id="conversation-1",
        )

    assert [selection.tool_name for selection in selections] == ["file_reader", "file_patch_writer"]


def test_pi_mutation_recovery_fails_closed_when_another_supervisor_holds_the_run_lease(tmp_path) -> None:
    grant, application, selections, _initial_approval, run_id = _stage_indeterminate_run(tmp_path)
    supervisor = RuntimeSupervisor(RuntimeCheckpointStore(tmp_path / "checkpoints"))
    lease = supervisor.try_acquire_run_lease(run_id)
    assert lease is not None
    try:
        with pytest.raises(RuntimeError, match="lease"):
            _recovery_runner(tmp_path, application, selections).recover(
                run_id,
                grant,
                approval=_approval(grant, approval_id="approval-recovery"),
                conversation_id="conversation-1",
            )
    finally:
        supervisor.release_run_lease(lease)

    assert [selection.tool_name for selection in selections] == ["file_reader", "file_patch_writer"]
