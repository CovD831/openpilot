"""L1/L4 typed admission: no write or command happens without a proposal, an
approval, and a consent bound to the run that requested it.

Demand-driven by design: proposals are created at the moment the model asks
for a patch/write/bash, not by a planning pass. The registry is the sole
authority for whether a side effect may happen. Bash proposals are
per-command; path proposals cover the exact canonical path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator
from uuid import uuid4

MAX_PENDING = 3


@dataclass(frozen=True)
class AdmissionGrant:
    """Typed scope for one task: read roots, write path(s), or one command."""

    admission_id: str
    task_id: str
    goal: str
    project_root: str
    read_roots: tuple[str, ...]
    write_paths: tuple[str, ...]
    created_at: str
    kind: str = "patch"  # patch | write | bash
    command: str = ""    # bash proposals carry the exact command
    diff_preview: str = ""  # projection-only: what the change would look like

    def is_mutation(self) -> bool:
        return bool(self.write_paths) or bool(self.command)


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    grant: AdmissionGrant
    status: str  # pending | approved | denied


@dataclass(frozen=True)
class ConsentGrant:
    consent_id: str
    proposal_id: str
    admission_id: str
    run_id: str
    write_paths: tuple[str, ...]
    validation_command: str = ""
    kind: str = "patch"
    command: str = ""


def _canonical(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


class AdmissionError(Exception):
    pass


class AdmissionRegistry:
    """Owns proposals and consents; answers one question: may this side effect run?"""

    def __init__(self, project_root: str) -> None:
        self.project_root = _canonical(project_root)
        self._proposals: dict[str, Proposal] = {}
        self._consents: dict[str, ConsentGrant] = {}
        self._counter = 0

    def _next_task_id(self) -> str:
        self._counter += 1
        return f"task-{self._counter}"

    def _register(self, grant: AdmissionGrant) -> Proposal:
        if len(self.pending()) >= MAX_PENDING:
            raise AdmissionError(
                f"pending proposal limit reached ({MAX_PENDING}); approve or /deny first"
            )
        proposal = Proposal(proposal_id=f"prop_{uuid4().hex[:12]}", grant=grant, status="pending")
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    def propose(
        self,
        goal: str,
        write_path: str,
        read_roots: tuple[str, ...] = (),
        *,
        kind: str = "patch",
        diff_preview: str = "",
    ) -> Proposal:
        grant = AdmissionGrant(
            admission_id=f"adm_{uuid4().hex[:12]}",
            task_id=self._next_task_id(),
            goal=goal.strip(),
            project_root=self.project_root,
            read_roots=tuple(_canonical(r) for r in read_roots) or (self.project_root,),
            write_paths=(_canonical(write_path),),
            created_at=datetime.now(UTC).isoformat(),
            kind=kind,
            diff_preview=diff_preview,
        )
        return self._register(grant)

    def propose_command(self, goal: str, command: str) -> Proposal:
        grant = AdmissionGrant(
            admission_id=f"adm_{uuid4().hex[:12]}",
            task_id=self._next_task_id(),
            goal=goal.strip(),
            project_root=self.project_root,
            read_roots=(self.project_root,),
            write_paths=(),
            created_at=datetime.now(UTC).isoformat(),
            kind="bash",
            command=command.strip(),
        )
        return self._register(grant)

    def get(self, proposal_id: str) -> Proposal:
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise AdmissionError(f"unknown proposal: {proposal_id}")
        return proposal

    def _issue_consent(
        self,
        proposal: Proposal,
        run_id: str,
        *,
        write_paths: tuple[str, ...],
        validation_command: str,
        proposal_id: str | None,
    ) -> ConsentGrant:
        consent = ConsentGrant(
            consent_id=f"con_{uuid4().hex[:12]}",
            proposal_id=proposal_id or proposal.proposal_id,
            admission_id=proposal.grant.admission_id,
            run_id=run_id,
            write_paths=write_paths,
            validation_command=validation_command.strip(),
            kind=proposal.grant.kind,
            command=proposal.grant.command,
        )
        self._consents[consent.consent_id] = consent
        return consent

    def approve(
        self,
        proposal_id: str,
        run_id: str,
        *,
        validation_command: str = "",
    ) -> ConsentGrant:
        proposal = self.get(proposal_id)
        if proposal.status != "pending":
            raise AdmissionError(f"proposal {proposal_id} is {proposal.status}, not pending")
        if not run_id.strip():
            raise AdmissionError("approval requires a run identity")
        approved = Proposal(proposal.proposal_id, proposal.grant, "approved")
        self._proposals[proposal_id] = approved
        return self._issue_consent(
            proposal,
            run_id,
            write_paths=proposal.grant.write_paths,
            validation_command=validation_command,
            proposal_id=proposal.proposal_id,
        )

    def approve_all(self, run_id: str, *, validation_command: str = "") -> tuple[ConsentGrant, tuple[str, ...]]:
        """Approve every pending proposal of this run as one merged consent."""
        pending = self.pending()
        if not pending:
            raise AdmissionError("no pending proposals to approve")
        if not run_id.strip():
            raise AdmissionError("approval requires a run identity")
        write_paths: list[str] = []
        command_parts: list[str] = []
        for proposal in pending:
            approved = Proposal(proposal.proposal_id, proposal.grant, "approved")
            self._proposals[proposal.proposal_id] = approved
            write_paths.extend(proposal.grant.write_paths)
            if proposal.grant.kind == "bash":
                command_parts.append(proposal.grant.command)
        merged = ConsentGrant(
            consent_id=f"con_{uuid4().hex[:12]}",
            proposal_id=",".join(p.proposal_id for p in pending),
            admission_id=",".join(p.grant.admission_id for p in pending),
            run_id=run_id,
            write_paths=tuple(dict.fromkeys(write_paths)),
            validation_command=validation_command.strip(),
            kind="batch",
            command=" && ".join(command_parts),
        )
        self._consents[merged.consent_id] = merged
        return merged, tuple(p.proposal_id for p in pending)

    def deny(self, proposal_id: str) -> Proposal:
        proposal = self.get(proposal_id)
        if proposal.status != "pending":
            raise AdmissionError(f"proposal {proposal_id} is {proposal.status}, not pending")
        denied = Proposal(proposal.proposal_id, proposal.grant, "denied")
        self._proposals[proposal_id] = denied
        return denied

    def pending(self) -> list[Proposal]:
        return [p for p in self._proposals.values() if p.status == "pending"]

    def active_consents(self) -> tuple[ConsentGrant, ...]:
        return tuple(self._consents.values())

    def authorize_patch(self, path: str, run_id: str) -> ConsentGrant:
        """Return the consent covering this path, or raise — the single gate."""
        canonical = _canonical(path)
        for consent in self._consents.values():
            if consent.run_id == run_id and canonical in consent.write_paths:
                return consent
        raise PermissionError(
            f"write to {path} is not covered by an approved consent; /approve a proposal first"
        )

    def authorize_command(self, command: str, run_id: str) -> ConsentGrant:
        """Bash gate: the exact command string must match an approved consent."""
        normalized = " ".join(command.split())
        for consent in self._consents.values():
            if consent.run_id != run_id or consent.kind not in ("bash", "batch"):
                continue
            if normalized == " ".join(consent.command.split()) or normalized in consent.command:
                return consent
        raise PermissionError(
            "command is not covered by an approved consent; /approve the bash proposal first"
        )

    def __iter__(self) -> Iterator[Proposal]:
        return iter(sorted(self._proposals.values(), key=lambda p: p.grant.created_at))
