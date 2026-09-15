from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from autonomous_iteration.action_gateway import ActionGateway, ActionRequest, ValidationRequest
from autonomous_iteration.run_coordinator import RunCoordinator
from autonomous_iteration.task_consent import TaskConsentRegistry
from evidence_core import EvidenceStore
from metadata import (
    EnvironmentOperation,
    EnvironmentReadiness,
    EnvironmentSyncMetadata,
    FileMutationPrecondition,
    TaskAdmissionGrant,
    TaskConsentReference,
    ValidationGrant,
)
from tools.tool_selection import SelectionReason, ToolSelection


def _grant(tmp_path, *, task_id: str = "task-1") -> TaskAdmissionGrant:
    target_path = tmp_path / "service.py"
    target_path.write_text("VALUE = 1\n", encoding="utf-8")
    target = str(target_path.resolve())
    stat = target_path.stat()
    return TaskAdmissionGrant(
        admission_id="admission-1",
        task_id=task_id,
        project_root=str(tmp_path.resolve()),
        read_files=[target],
        write_files=[target],
        validation=ValidationGrant(
            command="python -m pytest -q",
            cwd=str(tmp_path.resolve()),
        ),
        write_preconditions=[
            FileMutationPrecondition(
                path=target,
                device=stat.st_dev,
                inode=stat.st_ino,
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
            )
        ],
    )


def _consent(grant: TaskAdmissionGrant, *, run_id: str) -> TaskConsentReference:
    return TaskConsentReference(
        consent_id="consent-1",
        approval_id="approval-1",
        proposal_id="proposal-1",
        admission_id=grant.admission_id,
        task_id=grant.task_id,
        project_root=grant.project_root,
        conversation_id="conversation-1",
        run_id=run_id,
        protocol_version="cli-v2",
    )


def _ready_environment(tmp_path) -> EnvironmentSyncMetadata:
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("python marker", encoding="utf-8")
    return EnvironmentSyncMetadata(
        operation=EnvironmentOperation.PREFLIGHT,
        readiness=EnvironmentReadiness.READY,
        environment_id="environment-1",
        project_path=str(tmp_path.resolve()),
        env_name=".venv",
        venv_path=str(python.parent.parent),
        python_executable=str(python),
        command_cwd=str(tmp_path.resolve()),
        command_env={"PATH": str(python.parent)},
    )


def _selection(file_path: str = "") -> ToolSelection:
    values = {
        "step_id": "patch-1",
        "tool_name": "file_patch_writer",
        "reason": SelectionReason.ONLY_OPTION,
    }
    if file_path:
        values["input_metadata"] = {"file_path": file_path}
    return ToolSelection(
        **values,
    )


def _record_mutation_receipt(coordinator: RunCoordinator, run) -> None:
    coordinator.record_canonical(
        run,
        event_type="mutation_receipt",
        payload={"call_id": "patch-1", "execution_id": "execution-1", "durable": True},
        producer="test",
        call_id="patch-1",
        idempotency_key="mutation-receipt:patch-1",
    )


def test_mutation_rejects_loose_scope_that_differs_from_admission(tmp_path) -> None:
    grant = _grant(tmp_path)
    coordinator = RunCoordinator(EvidenceStore(tmp_path / "evidence"))
    run = coordinator.start_run(grant.task_id)
    target = grant.write_files[0]
    request = ActionRequest(
        call_id="patch-1",
        selection=_selection(target),
        mutation=True,
        declared_read_files=(target,),
        write_scope=(str((tmp_path / "other.py").resolve()),),
        admission=grant,
        consent=_consent(grant, run_id=run.run_id),
    )

    with pytest.raises(PermissionError, match="write scope"):
        ActionGateway(coordinator, executor=SimpleNamespace()).execute(run, request)


def test_mutation_rejects_consent_bound_to_another_run(tmp_path) -> None:
    grant = _grant(tmp_path)
    coordinator = RunCoordinator(EvidenceStore(tmp_path / "evidence"))
    run = coordinator.start_run(grant.task_id)
    target = grant.write_files[0]
    request = ActionRequest(
        call_id="patch-1",
        selection=_selection(target),
        mutation=True,
        declared_read_files=(target,),
        write_scope=(target,),
        admission=grant,
        consent=_consent(grant, run_id="different-run"),
    )

    with pytest.raises(PermissionError, match="consent"):
        ActionGateway(coordinator, executor=SimpleNamespace()).execute(run, request)


def test_mutation_rejects_target_drift_before_dispatching_patch(tmp_path) -> None:
    grant = _grant(tmp_path)
    coordinator = RunCoordinator(EvidenceStore(tmp_path / "evidence"))
    run = coordinator.start_run(grant.task_id)
    target = grant.write_files[0]
    coordinator.record_canonical(
        run,
        event_type="tool_succeeded",
        payload={"tool_name": "file_reader", "declared_read_files": [target]},
        producer="test",
        call_id="read-1",
        idempotency_key="read-1",
    )
    Path(target).write_text("VALUE = externally changed\n", encoding="utf-8")

    class Executor:
        def execute_single(self, *_args, **_kwargs):
            raise AssertionError("drifted mutation must not reach the tool executor")

    request = ActionRequest(
        call_id="patch-1",
        selection=_selection(target),
        mutation=True,
        declared_read_files=(target,),
        write_scope=(target,),
        admission=grant,
        consent=_consent(grant, run_id=run.run_id),
    )

    with pytest.raises(PermissionError, match="precondition"):
        ActionGateway(coordinator, executor=Executor()).execute(run, request)


def test_mutation_rechecks_only_the_target_of_the_current_patch(tmp_path) -> None:
    target = tmp_path / "service.py"
    other = tmp_path / "tests.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    other.write_text("VALUE = 2\n", encoding="utf-8")

    def precondition(path: Path) -> FileMutationPrecondition:
        stat = path.stat()
        return FileMutationPrecondition(
            path=str(path.resolve()),
            device=stat.st_dev,
            inode=stat.st_ino,
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
        )

    grant = TaskAdmissionGrant(
        admission_id="admission-1",
        task_id="task-1",
        project_root=str(tmp_path.resolve()),
        read_files=[str(target.resolve()), str(other.resolve())],
        write_files=[str(target.resolve()), str(other.resolve())],
        validation=ValidationGrant(command="python -m pytest -q", cwd=str(tmp_path.resolve())),
        write_preconditions=[precondition(target), precondition(other)],
    )
    coordinator = RunCoordinator(EvidenceStore(tmp_path / "evidence"))
    run = coordinator.start_run(grant.task_id)
    for index, path in enumerate(grant.read_files, start=1):
        coordinator.record_canonical(
            run,
            event_type="tool_succeeded",
            payload={"tool_name": "file_reader", "declared_read_files": [path]},
            producer="test",
            call_id=f"read-{index}",
            idempotency_key=f"read-{index}",
        )
    other.write_text("VALUE = externally changed\n", encoding="utf-8")
    consent = _consent(grant, run_id=run.run_id)
    consents = TaskConsentRegistry()
    consents.activate(consent)
    calls: list[ToolSelection] = []

    class Executor:
        def execute_single(self, selection, context=None):
            calls.append(selection)
            return SimpleNamespace(
                success=True,
                execution_id="patch-1",
                output_metadata=SimpleNamespace(result=SimpleNamespace(content="ok")),
                error=None,
            )

    result = ActionGateway(coordinator, Executor(), consent_resolver=consents).execute(
        run,
        ActionRequest(
            call_id="patch-1",
            selection=_selection(str(target.resolve())),
            mutation=True,
            declared_read_files=tuple(grant.read_files),
            write_scope=tuple(grant.write_files),
            admission=grant,
            consent=consent,
        ),
    )

    assert result.receipt is not None
    assert calls[0].input_metadata.runtime_handles["_file_mutation_precondition"].path == str(target.resolve())


def test_pi_mutation_handler_derives_every_scope_from_admission(tmp_path) -> None:
    grant = _grant(tmp_path)
    coordinator = RunCoordinator(EvidenceStore(tmp_path / "evidence"))
    run = coordinator.start_run(grant.task_id)
    selections: list[ToolSelection] = []

    class Executor:
        def execute_single(self, selection, context=None):
            selections.append(selection)
            result = SimpleNamespace(content="source", success=True, exit_code=0)
            return SimpleNamespace(
                success=True,
                execution_id=f"execution-{len(selections)}",
                output_metadata=SimpleNamespace(result=result),
                error=None,
            )

    consent = _consent(grant, run_id=run.run_id)
    consents = TaskConsentRegistry()
    consents.activate(consent)
    handler = ActionGateway(
        coordinator,
        Executor(),
        environment_preflight=lambda **_kwargs: _ready_environment(tmp_path),
        consent_resolver=consents,
    ).pi_action_handler(
        run,
        admission=grant,
        consent=consent,
    )
    target = grant.write_files[0]

    assert handler(
        {
            "toolName": "openpilot_read",
            "toolCallId": "read-1",
            "args": {"path": target},
        }
    ) == "source"
    patch = handler(
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
    )
    validation = handler(
        {
            "toolName": "openpilot_validate",
            "toolCallId": "validate-1",
            "args": {"command": grant.validation.command},
        }
    )

    assert patch["receipt"]["durable"] is True
    assert validation == {"success": True}
    assert [selection.tool_name for selection in selections] == [
        "file_reader",
        "file_patch_writer",
        "command_executor",
    ]
    validation_params = selections[-1].input_metadata.to_params()
    assert validation_params["command"] == "python -m pytest -q"
    assert validation_params["requested_command"] == "python -m pytest -q"
    assert validation_params["env"] == {"PATH": str(tmp_path / ".venv" / "bin")}


def test_revoked_consent_blocks_validation_after_a_successful_patch(tmp_path) -> None:
    grant = _grant(tmp_path)
    coordinator = RunCoordinator(EvidenceStore(tmp_path / "evidence"))
    run = coordinator.start_run(grant.task_id)
    consent = _consent(grant, run_id=run.run_id)
    consents = TaskConsentRegistry()
    consents.activate(consent)

    class Executor:
        def execute_single(self, selection, context=None):
            result = SimpleNamespace(content="source", success=True, exit_code=0)
            if selection.tool_name == "file_patch_writer":
                consents.revoke(consent.consent_id)
            return SimpleNamespace(
                success=True,
                execution_id=f"execution-{selection.step_id}",
                output_metadata=SimpleNamespace(result=result),
                error=None,
            )

    handler = ActionGateway(
        coordinator,
        Executor(),
        environment_preflight=lambda **_kwargs: _ready_environment(tmp_path),
        consent_resolver=consents,
    ).pi_action_handler(
        run,
        admission=grant,
        consent=consent,
    )
    target = grant.write_files[0]
    handler(
        {
            "toolName": "openpilot_read",
            "toolCallId": "read-1",
            "args": {"path": target},
        }
    )
    assert handler(
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

    with pytest.raises(PermissionError, match="revoked"):
        handler(
            {
                "toolName": "openpilot_validate",
                "toolCallId": "validate-1",
                "args": {"command": grant.validation.command},
            }
        )


def test_admitted_patch_fails_closed_without_an_action_time_consent_resolver(tmp_path) -> None:
    grant = _grant(tmp_path)
    coordinator = RunCoordinator(EvidenceStore(tmp_path / "evidence"))
    run = coordinator.start_run(grant.task_id)
    consent = _consent(grant, run_id=run.run_id)

    class Executor:
        def execute_single(self, selection, context=None):
            if selection.tool_name != "file_reader":
                raise AssertionError("unresolved consent must not reach the patch executor")
            return SimpleNamespace(
                success=True,
                execution_id="read-1",
                output_metadata=SimpleNamespace(result=SimpleNamespace(content="source")),
                error=None,
            )

    handler = ActionGateway(coordinator, Executor()).pi_action_handler(
        run,
        admission=grant,
        consent=consent,
    )
    target = grant.write_files[0]
    handler(
        {
            "toolName": "openpilot_read",
            "toolCallId": "read-1",
            "args": {"path": target},
        }
    )

    with pytest.raises(PermissionError, match="action-time consent"):
        handler(
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
        )


def test_admitted_validation_rejects_a_non_ready_project_environment(tmp_path) -> None:
    grant = _grant(tmp_path)
    coordinator = RunCoordinator(EvidenceStore(tmp_path / "evidence"))
    run = coordinator.start_run(grant.task_id)
    consent = _consent(grant, run_id=run.run_id)
    _record_mutation_receipt(coordinator, run)
    not_ready = EnvironmentSyncMetadata(
        operation=EnvironmentOperation.PREFLIGHT,
        readiness=EnvironmentReadiness.SETUP_REQUIRED,
        project_path=grant.project_root,
        command_cwd=grant.project_root,
    )

    class Executor:
        def execute_single(self, *_args, **_kwargs):
            raise AssertionError("non-ready environment must not execute validation")

    gateway = ActionGateway(
        coordinator,
        Executor(),
        environment_preflight=lambda **_kwargs: not_ready,
    )
    with pytest.raises(PermissionError, match="ready project environment"):
        gateway.execute_validation(
            run,
            ValidationRequest(
                call_id="validate-1",
                command=grant.validation.command,
                cwd=grant.validation.cwd,
                timeout_seconds=grant.validation.timeout_seconds,
                admission=grant,
                consent=consent,
            ),
            requested_command=grant.validation.command,
        )


def test_admitted_validation_requires_a_durable_mutation_receipt(tmp_path) -> None:
    grant = _grant(tmp_path)
    coordinator = RunCoordinator(EvidenceStore(tmp_path / "evidence"))
    run = coordinator.start_run(grant.task_id)
    consent = _consent(grant, run_id=run.run_id)

    class Executor:
        def execute_single(self, *_args, **_kwargs):
            raise AssertionError("validation must not run before a mutation receipt")

    gateway = ActionGateway(
        coordinator,
        Executor(),
        environment_preflight=lambda **_kwargs: _ready_environment(tmp_path),
    )
    with pytest.raises(PermissionError, match="mutation receipt"):
        gateway.execute_validation(
            run,
            ValidationRequest(
                call_id="validate-1",
                command=grant.validation.command,
                cwd=grant.validation.cwd,
                timeout_seconds=grant.validation.timeout_seconds,
                admission=grant,
                consent=consent,
            ),
            requested_command=grant.validation.command,
        )


def test_admitted_pi_read_handler_accepts_only_canonical_relative_scope_paths(tmp_path) -> None:
    grant = _grant(tmp_path)
    coordinator = RunCoordinator(EvidenceStore(tmp_path / "evidence"))
    run = coordinator.start_run(grant.task_id)

    class Executor:
        def execute_single(self, selection, context=None):
            return SimpleNamespace(
                success=True,
                execution_id="read-1",
                output_metadata=SimpleNamespace(result=SimpleNamespace(content="source")),
                error=None,
            )

    handler = ActionGateway(coordinator, Executor()).pi_read_handler(
        run,
        admission=grant,
    )

    assert handler(
        {
            "toolName": "openpilot_read",
            "toolCallId": "read-1",
            "args": {"path": "service.py"},
        }
    ) == "source"
    with pytest.raises(PermissionError, match="outside declared scope"):
        handler(
            {
                "toolName": "openpilot_read",
                "toolCallId": "read-2",
                "args": {"path": "../outside.py"},
            }
        )
