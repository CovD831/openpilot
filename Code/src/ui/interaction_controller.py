"""Proposal-first CLI interaction orchestration.

The controller accepts user intent, asks a task designer for candidates, and
turns only a deterministic admission result into executable input. It does not
read project bodies, call tools, or create side effects itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from autonomous_iteration.task_admission import TaskAdmission, admit_task_plan
from autonomous_iteration.task_models import Task
from metadata import TaskAdmissionGrant, TaskApprovalGrant


TaskDesigner = Callable[[str, Path, str], Sequence[Task]]
TaskExecutor = Callable[
    [str, TaskAdmissionGrant, TaskApprovalGrant | None, Mapping[str, object]],
    object,
]


@dataclass(frozen=True)
class InteractionProposal:
    """UI-facing, non-authoritative projection of an admitted task."""

    proposal_id: str
    goal: str
    conversation_id: str
    admission: TaskAdmission

    @property
    def is_mutation(self) -> bool:
        return self.admission.is_mutation


class InteractionController:
    """Share proposal and approval rules between REPL and ``--once`` flows."""

    protocol_version = "cli-v2"

    def __init__(
        self,
        *,
        task_designer: TaskDesigner,
        executor: TaskExecutor,
        id_factory: Callable[[], str] | None = None,
        max_pending_proposals: int = 32,
    ) -> None:
        if max_pending_proposals < 1:
            raise ValueError("max_pending_proposals must be positive")
        self._task_designer = task_designer
        self._executor = executor
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self._max_pending_proposals = max_pending_proposals
        self._proposals: dict[str, InteractionProposal] = {}

    def propose(
        self,
        goal: str,
        *,
        project_root: str | Path,
        conversation_id: str,
    ) -> InteractionProposal:
        root = Path(project_root).expanduser().resolve(strict=False)
        normalized_goal = str(goal).strip()
        normalized_conversation = str(conversation_id).strip()
        if not normalized_goal:
            raise ValueError("goal is required")
        if not normalized_conversation:
            raise ValueError("conversation_id is required")
        if len(self._proposals) >= self._max_pending_proposals:
            raise RuntimeError("pending proposal limit reached; approve or discard an existing proposal")
        task_id = f"task_{self._id_factory()}"
        candidates = list(self._task_designer(normalized_goal, root, task_id))
        admission = admit_task_plan(
            task_id=task_id,
            goal=normalized_goal,
            tasks=candidates,
            project_root=root,
        )
        proposal = InteractionProposal(
            proposal_id=f"proposal_{self._id_factory()}",
            goal=normalized_goal,
            conversation_id=normalized_conversation,
            admission=admission,
        )
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    def approve(self, proposal_id: str, *, conversation_id: str) -> TaskApprovalGrant:
        proposal = self._proposal_for_conversation(proposal_id, conversation_id)
        if not proposal.is_mutation:
            raise ValueError("read-only proposals do not require mutation approval")
        grant = proposal.admission.grant
        return TaskApprovalGrant(
            approval_id=f"approval_{self._id_factory()}",
            proposal_id=proposal.proposal_id,
            admission_id=grant.admission_id,
            task_id=grant.task_id,
            project_root=grant.project_root,
            conversation_id=proposal.conversation_id,
            protocol_version=grant.protocol_version,
        )

    def execute(
        self,
        proposal_id: str,
        *,
        conversation_id: str,
        approval: TaskApprovalGrant | None = None,
    ) -> object:
        proposal = self._proposal_for_conversation(proposal_id, conversation_id)
        grant = proposal.admission.grant
        if proposal.is_mutation:
            if approval is None:
                raise PermissionError("mutation proposal requires explicit approval")
            if (
                approval.proposal_id != proposal.proposal_id
                or approval.admission_id != grant.admission_id
                or approval.task_id != grant.task_id
                or approval.project_root != grant.project_root
                or approval.conversation_id != proposal.conversation_id
                or approval.protocol_version != grant.protocol_version
            ):
                raise PermissionError("mutation approval does not match the admitted proposal")
        elif approval is not None:
            raise PermissionError("read-only proposal must not carry mutation approval")

        self._proposals.pop(proposal.proposal_id, None)
        execution_context: dict[str, object] = {
            "task_id": grant.task_id,
            "project_path": grant.project_root,
            "conversation_id": proposal.conversation_id,
            "interaction_protocol_version": grant.protocol_version,
        }
        return self._executor(proposal.goal, grant, approval, execution_context)

    def proposal(self, proposal_id: str, *, conversation_id: str) -> InteractionProposal:
        return self._proposal_for_conversation(proposal_id, conversation_id)

    def _proposal_for_conversation(
        self,
        proposal_id: str,
        conversation_id: str,
    ) -> InteractionProposal:
        proposal = self._proposals.get(str(proposal_id).strip())
        if proposal is None:
            raise KeyError("unknown task proposal")
        if proposal.conversation_id != str(conversation_id).strip():
            raise PermissionError("proposal belongs to a different conversation")
        return proposal


__all__ = ["InteractionController", "InteractionProposal", "TaskDesigner", "TaskExecutor"]
