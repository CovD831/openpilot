from __future__ import annotations

import pytest

from autonomous_iteration.task_consent import TaskConsentRegistry, TaskConsentStatus
from metadata import TaskConsentReference


def _consent(project_root: str = "/tmp/project") -> TaskConsentReference:
    return TaskConsentReference(
        consent_id="consent-1",
        approval_id="approval-1",
        proposal_id="proposal-1",
        admission_id="admission-1",
        task_id="task-1",
        project_root=project_root,
        conversation_id="conversation-1",
        run_id="run-1",
    )


def test_file_backed_registry_observes_a_revoke_from_another_process_instance(tmp_path) -> None:
    consent = _consent()
    active = TaskConsentRegistry(state_directory=tmp_path)
    active.activate(consent)

    revoker = TaskConsentRegistry(state_directory=tmp_path)
    state = revoker.revoke(consent.consent_id, run_id=consent.run_id)

    assert state.status is TaskConsentStatus.REVOKED
    with pytest.raises(PermissionError, match="revoked"):
        with active.authorize(consent, run_id=consent.run_id):
            pass


def test_file_backed_registry_cannot_reactivate_a_closed_or_revoked_consent(tmp_path) -> None:
    consent = _consent()
    registry = TaskConsentRegistry(state_directory=tmp_path)
    registry.activate(consent)
    registry.close(consent.consent_id, run_id=consent.run_id)

    with pytest.raises(PermissionError, match="closed"):
        registry.activate(consent)


def test_file_backed_registry_rejects_a_revoke_for_another_project_identity(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    consent = _consent(str(project))
    registry = TaskConsentRegistry(state_directory=project / ".openpilot" / "consents")
    registry.activate(consent)

    with pytest.raises(PermissionError, match="another project"):
        registry.revoke(
            consent.consent_id,
            run_id=consent.run_id,
            project_root=tmp_path / "other-project",
        )

    with registry.authorize(consent, run_id=consent.run_id):
        pass


def test_file_backed_registry_fails_closed_when_its_state_becomes_unreadable(
    tmp_path,
    monkeypatch,
) -> None:
    consent = _consent(str(tmp_path))
    registry = TaskConsentRegistry(state_directory=tmp_path / ".openpilot" / "consents")
    registry.activate(consent)

    def unreadable(*_args, **_kwargs):
        raise OSError("state device unavailable")

    monkeypatch.setattr("pathlib.Path.read_text", unreadable)

    with pytest.raises(PermissionError, match="unavailable"):
        with registry.authorize(consent, run_id=consent.run_id):
            pass
