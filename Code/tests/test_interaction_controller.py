from __future__ import annotations

from pathlib import Path

import pytest

from autonomous_iteration.task_models import Task
from ui.interaction_controller import InteractionController


def _task(*, mutation: bool) -> Task:
    return Task(
        id="candidate-1",
        description="Repair service" if mutation else "Inspect service",
        read_files=["service.py"],
        write_files=["service.py"] if mutation else [],
        validation_command="python -m pytest -q" if mutation else "",
    )


def test_mutation_proposal_requires_explicit_matching_approval(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    executions: list[tuple[object, object]] = []
    controller = InteractionController(
        task_designer=lambda *_args: [_task(mutation=True)],
        executor=lambda _goal, admission, approval, _context: executions.append((admission, approval)) or {"success": True},
    )

    proposal = controller.propose(
        "Repair service",
        project_root=tmp_path,
        conversation_id="conversation-1",
    )

    assert proposal.is_mutation is True
    assert executions == []
    with pytest.raises(PermissionError, match="explicit approval"):
        controller.execute(proposal.proposal_id, conversation_id="conversation-1")

    approval = controller.approve(proposal.proposal_id, conversation_id="conversation-1")
    result = controller.execute(
        proposal.proposal_id,
        conversation_id="conversation-1",
        approval=approval,
    )

    assert result == {"success": True}
    assert len(executions) == 1
    admission, received_approval = executions[0]
    assert admission.admission_id == proposal.admission.grant.admission_id
    assert received_approval == approval


def test_read_only_proposal_executes_without_mutation_approval(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    controller = InteractionController(
        task_designer=lambda *_args: [_task(mutation=False)],
        executor=lambda _goal, _admission, approval, _context: {"approval": approval},
    )

    proposal = controller.propose(
        "Inspect service",
        project_root=tmp_path,
        conversation_id="conversation-1",
    )

    assert controller.execute(proposal.proposal_id, conversation_id="conversation-1") == {"approval": None}


def test_approval_cannot_cross_conversation_boundary(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    controller = InteractionController(
        task_designer=lambda *_args: [_task(mutation=True)],
        executor=lambda *_args: {"success": True},
    )
    proposal = controller.propose(
        "Repair service",
        project_root=tmp_path,
        conversation_id="conversation-1",
    )

    with pytest.raises(PermissionError, match="conversation"):
        controller.approve(proposal.proposal_id, conversation_id="conversation-2")


def test_pending_proposals_are_bounded_and_completed_read_only_proposals_release_capacity(
    tmp_path: Path,
) -> None:
    (tmp_path / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    controller = InteractionController(
        task_designer=lambda *_args: [_task(mutation=False)],
        executor=lambda *_args: {"success": True},
        max_pending_proposals=1,
    )
    first = controller.propose(
        "Inspect service",
        project_root=tmp_path,
        conversation_id="conversation-1",
    )

    with pytest.raises(RuntimeError, match="pending proposal limit"):
        controller.propose(
            "Inspect service again",
            project_root=tmp_path,
            conversation_id="conversation-1",
        )

    controller.execute(first.proposal_id, conversation_id="conversation-1")
    second = controller.propose(
        "Inspect service again",
        project_root=tmp_path,
        conversation_id="conversation-1",
    )
    assert second.proposal_id != first.proposal_id
