"""Composition-root facade for the Harness runtime."""

from __future__ import annotations

from enum import StrEnum
from collections.abc import Callable
from typing import Any

from autonomous_iteration.ports import ApplicationPort
from autonomous_iteration.run_coordinator import RunCoordinator, RunHandle
from autonomous_iteration.verification.completion import CompletionProfile, evaluate_completion
from autonomous_iteration.verification.policies import (
    HarnessPhase,
    HarnessPolicyKind,
    HarnessPolicyProfile,
    policy_profile,
)
from evidence_core import EvidenceStore, EventRecord
from evidence_core import TerminalStatus


class EngineKind(StrEnum):
    PI = "pi"


class HarnessApplication(ApplicationPort):
    """Small synchronous facade; Pi is the default execution engine."""

    def __init__(self, evidence: EvidenceStore | None = None, *, coordinator: RunCoordinator | None = None, engine: EngineKind | str = EngineKind.PI, policy: HarnessPolicyKind | str = HarnessPolicyKind.READ_ONLY):
        self.engine = EngineKind(engine)
        self.policy: HarnessPolicyProfile = policy_profile(policy)
        self.coordinator = coordinator or RunCoordinator(evidence or EvidenceStore())

    def allowed_pi_tools(self, phase: HarnessPhase | str) -> tuple[str, ...]:
        return self.policy.tools_for(phase)

    def start(self, task_id: str, **metadata: Any) -> RunHandle:
        return self.coordinator.start_run(task_id, **metadata)

    def observe(self, run: RunHandle | str, **observation: Any) -> EventRecord:
        return self.coordinator.record_observation(run, **observation)

    def canonical(self, run: RunHandle | str, **observation: Any) -> EventRecord:
        return self.coordinator.record_canonical(run, **observation)

    def map_semantic(self, run: RunHandle | str, **mapping: Any) -> EventRecord:
        return self.coordinator.map_semantic(run, **mapping)

    def run_pi(
        self,
        run_id: str,
        *,
        engine: Any,
        prompt: str,
        action_handler: Any | None = None,
        profile: CompletionProfile | str = CompletionProfile.READ_ONLY,
        externally_verified: bool = False,
        read_only_verifier: Callable[[RunHandle, list[Any]], bool] | None = None,
    ) -> dict[str, Any]:
        if self.engine is not EngineKind.PI:
            raise RuntimeError("Pi engine is not selected")
        run = self.coordinator.attach_run(run_id)
        messages = engine.run_once(
            run,
            prompt=prompt,
            action_handler=action_handler,
        )
        selected_profile = CompletionProfile(profile)
        crashed = str(getattr(engine.state, "value", engine.state)) == "crashed"
        observed = self.coordinator.finish(
            run,
            success=not crashed,
            reason="Pi engine crashed" if crashed else "Pi engine stopped",
        )
        events = self.coordinator.evidence.load_trajectory_events(run_id)
        if (
            selected_profile is CompletionProfile.MUTATION
            and _has_durable_mutation_receipt_without_validation(events)
        ):
            recovery = self.coordinator.mark_recovery_state(
                run,
                status=TerminalStatus.INDETERMINATE,
                reason="durable mutation receipt requires reconciliation validation",
                producer="pi_harness",
            )
            return {
                "run_id": run_id,
                "status": TerminalStatus.INDETERMINATE.value,
                "success": False,
                "reason": "durable mutation receipt requires reconciliation validation",
                "messages": messages,
                "terminal_event_id": recovery.event_id,
            }
        decision = evaluate_completion(
            events,
            profile=selected_profile,
        )
        read_only_response_observed = bool(
            read_only_verifier(run, messages)
            if read_only_verifier is not None
            else False
        )
        if (
            selected_profile is CompletionProfile.READ_ONLY
            and decision.status is TerminalStatus.SUCCESS
            and not externally_verified
            and not read_only_response_observed
        ):
            decision = type(decision)(
                TerminalStatus.BLOCKED,
                "read-only Pi result has no observed model response",
            )
        terminal = self.coordinator.finalize(
            run,
            source_observation_id=observed.event_id,
            source_observation=observed,
            status=decision.status,
            reason=decision.reason,
        )
        return {
            "run_id": run_id,
            "status": decision.status.value,
            "success": decision.status is TerminalStatus.SUCCESS,
            "reason": decision.reason,
            "messages": messages,
            "terminal_event_id": terminal.event_id,
        }

    def finish(self, run: RunHandle | str, *, success: bool, reason: str = "", **payload: Any) -> EventRecord:
        profile = CompletionProfile(payload.pop("profile", CompletionProfile.READ_ONLY))
        observed = self.coordinator.finish(run, success=success, reason=reason, **payload)
        run_id = run.run_id if isinstance(run, RunHandle) else str(run)
        decision = evaluate_completion(
            self.coordinator.evidence.load_trajectory_events(run_id),
            profile=profile,
        )
        return self.coordinator.finalize(
            run,
            source_observation_id=observed.event_id,
            source_observation=observed,
            status=decision.status,
            reason=decision.reason if decision.status.value != "success" else reason or decision.reason,
        )


def _has_durable_mutation_receipt_without_validation(events: list[EventRecord]) -> bool:
    """Identify the only mutation state that can safely enter Pi reconciliation."""

    semantic = [event for event in events if event.layer.value == "semantic"]
    has_durable_receipt = any(
        event.event_type == "mutation_receipt"
        and (event.payload or {}).get("durable") is True
        for event in semantic
    )
    has_completed_validation = any(
        event.event_type == "validation_completed" for event in semantic
    )
    return has_durable_receipt and not has_completed_validation
