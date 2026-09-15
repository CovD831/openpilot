from __future__ import annotations

from pathlib import Path

import pytest

from autonomous_iteration.task_admission import TaskAdmissionError, admit_task_plan
from autonomous_iteration.task_models import Task
from metadata import FileMutationPrecondition, TaskAdmissionGrant, TaskApprovalGrant, ValidationGrant


def _task(
    *,
    description: str = "Inspect source",
    read_files: list[str] | None = None,
    write_files: list[str] | None = None,
    validation_command: str = "",
) -> Task:
    return Task(
        id="task-1",
        description=description,
        read_files=list(read_files or []),
        write_files=list(write_files or []),
        validation_command=validation_command,
    )


def test_read_only_admission_canonicalizes_declared_project_file(tmp_path: Path) -> None:
    target = tmp_path / "src" / "service.py"
    target.parent.mkdir()
    target.write_text("VALUE = 1\n", encoding="utf-8")

    admission = admit_task_plan(
        task_id="root-1",
        goal="Inspect service",
        tasks=[_task(read_files=["src/service.py"])],
        project_root=tmp_path,
    )

    assert admission.is_mutation is False
    assert admission.task.read_files == [str(target.resolve())]
    assert admission.task.write_files == []
    assert admission.task.admission is not None
    assert admission.task.admission.read_files == [str(target.resolve())]
    assert admission.task.admission.validation is None


def test_mutation_requires_each_write_target_to_have_declared_read_evidence(tmp_path: Path) -> None:
    target = tmp_path / "service.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")

    with pytest.raises(TaskAdmissionError, match="read-before-write"):
        admit_task_plan(
            task_id="root-1",
            goal="Fix service",
            tasks=[
                _task(
                    description="Fix service",
                    write_files=["service.py"],
                    validation_command="python -m pytest -q",
                )
            ],
            project_root=tmp_path,
        )


def test_mutation_requires_one_exact_validation_command(tmp_path: Path) -> None:
    target = tmp_path / "service.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")

    with pytest.raises(TaskAdmissionError, match="exact validation"):
        admit_task_plan(
            task_id="root-1",
            goal="Fix service",
            tasks=[_task(read_files=["service.py"], write_files=["service.py"])],
            project_root=tmp_path,
        )


def test_mutation_admission_binds_canonical_scope_and_validation(tmp_path: Path) -> None:
    target = tmp_path / "service.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")

    admission = admit_task_plan(
        task_id="root-1",
        goal="Fix service",
        tasks=[
            _task(
                description="Fix service",
                read_files=["service.py"],
                write_files=["service.py"],
                validation_command="python -m pytest -q",
            )
        ],
        project_root=tmp_path,
    )

    assert admission.is_mutation is True
    assert admission.task.admission is not None
    assert admission.task.admission.write_files == [str(target.resolve())]
    assert admission.task.admission.validation is not None
    assert admission.task.admission.validation.command == "python -m pytest -q"
    assert admission.task.admission.validation.cwd == str(tmp_path.resolve())
    assert admission.task.admission.write_preconditions == [
        FileMutationPrecondition(
            path=str(target.resolve()),
            device=target.stat().st_dev,
            inode=target.stat().st_ino,
            size_bytes=target.stat().st_size,
            mtime_ns=target.stat().st_mtime_ns,
        )
    ]


def test_mutation_grant_requires_one_matching_file_precondition_per_write_target(tmp_path: Path) -> None:
    target = tmp_path / "service.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="file precondition"):
        TaskAdmissionGrant(
            admission_id="admission-1",
            task_id="task-1",
            project_root=str(tmp_path),
            read_files=[str(target)],
            write_files=[str(target)],
            validation=ValidationGrant(command="python -m pytest -q", cwd=str(tmp_path)),
        )


def test_task_approval_binds_a_serializable_consent_to_one_run(tmp_path: Path) -> None:
    approval = TaskApprovalGrant(
        approval_id="approval-1",
        proposal_id="proposal-1",
        admission_id="admission-1",
        task_id="task-1",
        project_root=str(tmp_path),
        conversation_id="conversation-1",
    )

    consent = approval.bind_run("run-1")

    assert consent.run_id == "run-1"
    assert consent.admission_id == approval.admission_id
    assert type(consent).model_validate_json(consent.model_dump_json()) == consent


def test_admission_rejects_scope_outside_project(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.py"
    outside.write_text("VALUE = 1\n", encoding="utf-8")

    with pytest.raises(TaskAdmissionError, match="outside the project"):
        admit_task_plan(
            task_id="root-1",
            goal="Inspect outside file",
            tasks=[_task(read_files=[str(outside)])],
            project_root=tmp_path,
        )


@pytest.mark.parametrize("command", ["pytest -q; rm -rf .", "curl https://example.com", "python -c 'print(1)'"])
def test_mutation_admission_rejects_unsafe_validation_command(tmp_path: Path, command: str) -> None:
    target = tmp_path / "service.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")

    with pytest.raises(TaskAdmissionError, match="validation command"):
        admit_task_plan(
            task_id="root-1",
            goal="Fix service",
            tasks=[
                _task(
                    read_files=["service.py"],
                    write_files=["service.py"],
                    validation_command=command,
                )
            ],
            project_root=tmp_path,
        )
