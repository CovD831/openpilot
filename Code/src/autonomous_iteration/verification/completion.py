from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from collections.abc import Iterable

from evidence_core import EventRecord, TerminalStatus, validate_trajectory_conformance


class CompletionProfile(StrEnum):
    READ_ONLY = "read_only"
    MUTATION = "mutation"
    WORKFLOW = "workflow"
    APPROVAL_REQUIRED = "approval_required"


@dataclass(frozen=True)
class CompletionDecision:
    status: TerminalStatus
    reason: str
    verified: bool = False


def evaluate_completion(events: Iterable[EventRecord], *, profile: CompletionProfile = CompletionProfile.READ_ONLY) -> CompletionDecision:
    """Derive terminal status from evidence; agent_end alone never succeeds."""
    timeline = list(events)
    if not timeline:
        return CompletionDecision(TerminalStatus.BLOCKED, "no evidence")
    if any(event.event_type in {"engine_crashed", "engine_eof"} for event in timeline):
        return CompletionDecision(TerminalStatus.CRASHED, "engine crashed before completion")
    if any(event.event_type == "mutation_receipt" for event in timeline) and not any(event.event_type == "validation_completed" for event in timeline):
        return CompletionDecision(TerminalStatus.EVIDENCE_GAP, "mutation receipt lacks exact validation")
    terminal = next(
        (
            event
            for event in reversed(timeline)
            if event.event_type in {"completion_observed", "task_finished"}
        ),
        None,
    )
    if terminal is None:
        return CompletionDecision(TerminalStatus.RUNNING, "terminal event not recorded")
    if not bool((terminal.payload or {}).get("success")):
        requested = str((terminal.payload or {}).get("final_status") or "failed")
        try:
            status = TerminalStatus(requested)
        except ValueError:
            status = TerminalStatus.FAILED
        if status is TerminalStatus.SUCCESS:
            status = TerminalStatus.FAILED
        return CompletionDecision(status, str((terminal.payload or {}).get("completion_reason") or "terminal evidence reports failure"))
    if profile is CompletionProfile.MUTATION:
        required = {"mutation_receipt", "validation_completed", "verification_state_changed"}
        if not required.issubset({event.event_type for event in timeline}):
            return CompletionDecision(TerminalStatus.BLOCKED, "mutation completion evidence is incomplete")
        if any(event.producer == "pi" for event in timeline) and not any(
            event.event_type == "engine_stopped" for event in timeline
        ):
            return CompletionDecision(TerminalStatus.BLOCKED, "Pi engine has not durably stopped")
        validations = [
            event for event in timeline if event.event_type == "validation_completed"
        ]
        if not validations or not bool((validations[-1].payload or {}).get("success")):
            return CompletionDecision(TerminalStatus.BLOCKED, "exact validation did not pass")
        receipts = [event for event in timeline if event.event_type == "mutation_receipt"]
        if not receipts or any(
            (event.payload or {}).get("success") is False
            or (event.payload or {}).get("durable") is False
            for event in receipts
        ):
            return CompletionDecision(TerminalStatus.INDETERMINATE, "mutation receipt is not durable")
        verifications = [
            event
            for event in timeline
            if event.event_type == "verification_state_changed"
        ]
        if not verifications or str(
            (verifications[-1].payload or {}).get("verification_status") or ""
        ) not in {"passed", "verified", "success"}:
            return CompletionDecision(TerminalStatus.BLOCKED, "verification did not pass")
    conformance = validate_trajectory_conformance(
        timeline,
        require_mutation_chain=profile is CompletionProfile.MUTATION,
        require_terminal=False,
    )
    if not conformance.valid:
        return CompletionDecision(TerminalStatus.EVIDENCE_GAP, "trajectory conformance failed")
    return CompletionDecision(TerminalStatus.SUCCESS, "completion policy passed", verified=profile is not CompletionProfile.READ_ONLY or any(event.event_type == "verification_state_changed" for event in timeline))
