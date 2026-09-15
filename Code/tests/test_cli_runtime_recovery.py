from io import StringIO
from types import SimpleNamespace

import pytest
from rich.console import Console

from autonomous_iteration.pi_mutation_recovery import PiMutationRecoveryRunner
from evidence_core import TerminalStatus
from metadata import FileMutationPrecondition, TaskAdmissionGrant, ValidationGrant
from ui.cli import _recover_pi_mutation, build_parser


def _mutation_grant(tmp_path) -> TaskAdmissionGrant:
    target = tmp_path / "service.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    baseline = target.stat()
    return TaskAdmissionGrant(
        admission_id="admission-recovery-cli",
        task_id="task-recovery-cli",
        project_root=str(tmp_path),
        read_files=[str(target)],
        write_files=[str(target)],
        validation=ValidationGrant(command="python -m pytest", cwd=str(tmp_path)),
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


def test_run_parser_retires_legacy_checkpoint_and_resume_arguments() -> None:
    parser = build_parser()

    run_args = parser.parse_args(
        ["run", "--once", "Inspect project", "--project-path", "/tmp/project"]
    )

    assert run_args.project_path == "/tmp/project"

    for deprecated_arguments in (
        ("--log-file", "legacy.jsonl"),
        ("--constraint", "read-only"),
        ("--ignore-memory",),
        ("--improvement-iterations", "1"),
        ("--checkpointing",),
        ("--resume-run-id", "run-1"),
        ("--resume-checkpoint-id", "checkpoint-1"),
    ):
        with pytest.raises(SystemExit) as error:
            parser.parse_args(["run", *deprecated_arguments])
        assert error.value.code == 2


def test_recover_command_requires_a_separate_literal_confirmation(tmp_path, monkeypatch) -> None:
    grant = _mutation_grant(tmp_path)
    prepared: list[tuple[str, str]] = []
    recovered: list[object] = []

    def prepare(self, run_id, *, project_root):
        del self
        prepared.append((run_id, str(project_root)))
        return SimpleNamespace(
            run_id=run_id,
            admission=grant,
            conversation_id="conversation-1",
            proposal_id="proposal-recovery-cli",
        )

    def recover(self, *args, **kwargs):
        del self, args, kwargs
        recovered.append(object())
        return {}

    monkeypatch.setattr(PiMutationRecoveryRunner, "prepare", prepare, raising=False)
    monkeypatch.setattr(PiMutationRecoveryRunner, "recover", recover)
    console_file = StringIO()
    args = build_parser().parse_args(
        ["recover", "--project-path", str(tmp_path), "--run-id", "run-recovery"]
    )

    status = _recover_pi_mutation(
        Console(file=console_file, color_system=None),
        args,
    )

    assert status == 2
    assert prepared == [("run-recovery", str(tmp_path))]
    assert recovered == []
    assert "approval_required" in console_file.getvalue()
    assert "--confirm" in console_file.getvalue()


def test_recover_command_mints_one_fresh_approval_for_exact_validation(tmp_path, monkeypatch) -> None:
    grant = _mutation_grant(tmp_path)
    approvals: list[object] = []

    def prepare(self, run_id, *, project_root):
        del self, project_root
        return SimpleNamespace(
            run_id=run_id,
            admission=grant,
            conversation_id="conversation-1",
            proposal_id="proposal-recovery-cli",
        )

    def recover(self, run_id, admission, *, approval, conversation_id):
        del self
        approvals.append(approval)
        assert run_id == "run-recovery"
        assert admission == grant
        assert conversation_id == "conversation-1"
        return {
            "run_id": run_id,
            "status": TerminalStatus.SUCCESS.value,
            "success": True,
            "resume_attempt_id": "resume-1",
        }

    monkeypatch.setattr(PiMutationRecoveryRunner, "prepare", prepare, raising=False)
    monkeypatch.setattr(PiMutationRecoveryRunner, "recover", recover)
    console_file = StringIO()
    args = build_parser().parse_args(
        [
            "recover",
            "--project-path",
            str(tmp_path),
            "--run-id",
            "run-recovery",
            "--confirm",
        ]
    )

    status = _recover_pi_mutation(
        Console(file=console_file, color_system=None),
        args,
    )

    assert status == 0
    assert len(approvals) == 1
    approval = approvals[0]
    assert approval.approval_id.startswith("approval_recovery_")
    assert approval.proposal_id == "proposal-recovery-cli"
    assert approval.admission_id == grant.admission_id
    assert "resume-1" in console_file.getvalue()
