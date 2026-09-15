from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from autonomous_iteration.application import HarnessApplication
from autonomous_iteration.pi_task_runner import PiTaskRunner
from evidence_core import EvidenceStore
from metadata import (
    EnvironmentOperation,
    EnvironmentReadiness,
    EnvironmentSyncMetadata,
    FileMutationPrecondition,
    TaskAdmissionGrant,
    TaskApprovalGrant,
    ValidationGrant,
)


def _read_grant(tmp_path) -> TaskAdmissionGrant:
    target = tmp_path / "service.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    return TaskAdmissionGrant(
        admission_id="admission-1",
        task_id="task-1",
        project_root=str(tmp_path),
        read_files=[str(target)],
    )


def _mutation_grant(tmp_path) -> TaskAdmissionGrant:
    target = tmp_path / "service.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    stat = target.stat()
    return TaskAdmissionGrant(
        admission_id="admission-1",
        task_id="task-1",
        project_root=str(tmp_path),
        read_files=[str(target)],
        write_files=[str(target)],
        validation=ValidationGrant(
            command="python -m pytest -q",
            cwd=str(tmp_path),
        ),
        write_preconditions=[
            FileMutationPrecondition(
                path=str(target),
                device=stat.st_dev,
                inode=stat.st_ino,
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
            )
        ],
    )


def _approval(grant: TaskAdmissionGrant) -> TaskApprovalGrant:
    return TaskApprovalGrant(
        approval_id="approval-1",
        proposal_id="proposal-1",
        admission_id=grant.admission_id,
        task_id=grant.task_id,
        project_root=grant.project_root,
        conversation_id="conversation-1",
    )


def _ready_environment(tmp_path) -> EnvironmentSyncMetadata:
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("python marker", encoding="utf-8")
    return EnvironmentSyncMetadata(
        operation=EnvironmentOperation.PREFLIGHT,
        readiness=EnvironmentReadiness.READY,
        environment_id="environment-1",
        project_path=str(tmp_path),
        env_name=".venv",
        venv_path=str(python.parent.parent),
        python_executable=str(python),
        command_cwd=str(tmp_path),
        command_env={"PATH": str(python.parent)},
    )


def test_read_only_runner_uses_pi_and_projects_sanitized_model_response(tmp_path) -> None:
    application = HarnessApplication(EvidenceStore(tmp_path / "evidence"), engine="pi")

    class ResponseEngine:
        state = SimpleNamespace(value="stopped")

        def __init__(self, coordinator) -> None:
            self.coordinator = coordinator

        def run_once(self, run, *, prompt, action_handler=None):
            self.coordinator.record_observation(
                run,
                event_type="engine_started",
                payload={},
                producer="pi",
            )
            self.coordinator.record_observation(
                run,
                event_type="model_response",
                payload={
                    "message": {
                        "content": [{"type": "text", "text": "answer\x1b[31m\u202e"}]
                    }
                },
                producer="pi",
            )
            self.coordinator.record_observation(
                run,
                event_type="engine_stopped",
                payload={},
                producer="pi",
            )
            return []

    runner = PiTaskRunner(
        application_factory=lambda _grant: application,
        engine_factory=lambda coordinator, _config: ResponseEngine(coordinator),
    )

    result = runner.run("Inspect service", _read_grant(tmp_path), approval=None)

    assert result["success"] is True
    assert result["status"] == "success"
    assert result["response"] == "answer"
    assert application.engine.value == "pi"


def test_runner_fails_closed_before_creating_a_mutation_run_without_matching_approval(tmp_path) -> None:
    grant = _mutation_grant(tmp_path)
    created: list[object] = []

    runner = PiTaskRunner(
        application_factory=lambda _grant: created.append(object()) or HarnessApplication(engine="pi"),
    )

    with pytest.raises(PermissionError, match="explicit matching approval"):
        runner.run("Repair service", grant, approval=None)

    assert created == []


def test_approved_mutation_runner_uses_pi_gateway_and_exact_validation(tmp_path) -> None:
    grant = _mutation_grant(tmp_path)
    application = HarnessApplication(EvidenceStore(tmp_path / "evidence"), engine="pi")
    configs: list[object] = []
    selections: list[object] = []
    started: list[dict[str, str]] = []

    class Executor:
        def execute_single(self, selection, context=None):
            selections.append(selection)
            content = "source" if selection.tool_name == "file_reader" else "ok"
            return SimpleNamespace(
                success=True,
                execution_id=f"execution-{selection.step_id}",
                output_metadata=SimpleNamespace(
                    result=SimpleNamespace(content=content, success=True, exit_code=0)
                ),
                error=None,
            )

    class MutationEngine:
        state = SimpleNamespace(value="stopped")

        def __init__(self, coordinator) -> None:
            self.coordinator = coordinator

        def run_once(self, run, *, prompt, action_handler=None):
            self.coordinator.record_observation(run, event_type="engine_started", payload={}, producer="pi")
            assert action_handler is not None
            target = grant.write_files[0]
            assert action_handler(
                {"toolName": "openpilot_read", "toolCallId": "read-1", "args": {"path": target}}
            ) == "source"
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
            assert action_handler(
                {
                    "toolName": "openpilot_validate",
                    "toolCallId": "validate-1",
                    "args": {"command": grant.validation.command},
                }
            ) == {"success": True}
            self.coordinator.record_observation(
                run,
                event_type="model_response",
                payload={"text": "fixed"},
                producer="pi",
            )
            self.coordinator.record_observation(run, event_type="engine_stopped", payload={}, producer="pi")
            return []

    def mutation_started(details: dict[str, str]) -> None:
        started.append(details)
        raise RuntimeError("terminal renderer unavailable")

    runner = PiTaskRunner(
        application_factory=lambda _grant: application,
        engine_factory=lambda coordinator, config: configs.append(config) or MutationEngine(coordinator),
        executor_factory=lambda: Executor(),
        environment_preflight=lambda **_kwargs: _ready_environment(tmp_path),
        mutation_started_callback=mutation_started,
    )

    result = runner.run(
        "Repair service",
        grant,
        approval=_approval(grant),
        conversation_id="conversation-1",
    )

    assert result["success"] is True
    assert result["response"] == "fixed"
    assert configs[0].enable_mutation_tools is True
    assert [selection.tool_name for selection in selections] == [
        "file_reader",
        "file_patch_writer",
        "command_executor",
    ]
    assert started and started[0]["run_id"] == result["run_id"]
    assert (tmp_path / ".openpilot" / "consents" / f"{started[0]['consent_id']}.json").exists()


def test_mutation_runner_closes_consent_if_engine_construction_fails(tmp_path) -> None:
    grant = _mutation_grant(tmp_path)
    application = HarnessApplication(EvidenceStore(tmp_path / "evidence"), engine="pi")
    started: list[dict[str, str]] = []

    runner = PiTaskRunner(
        application_factory=lambda _grant: application,
        engine_factory=lambda *_args: (_ for _ in ()).throw(RuntimeError("engine unavailable")),
        environment_preflight=lambda **_kwargs: _ready_environment(tmp_path),
        mutation_started_callback=started.append,
    )

    with pytest.raises(RuntimeError, match="engine unavailable"):
        runner.run(
            "Repair service",
            grant,
            approval=_approval(grant),
            conversation_id="conversation-1",
        )

    state_path = tmp_path / ".openpilot" / "consents" / f"{started[0]['consent_id']}.json"
    assert json.loads(state_path.read_text(encoding="utf-8"))["status"] == "closed"
