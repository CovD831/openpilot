"""Canonical raw-observation to semantic-evidence coordinator.

The coordinator is deliberately small: engines, tools, and verifiers submit
observations here, while only this module is allowed to create semantic
evidence. Business policy remains outside Evidence Core.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from evidence_core import (
    EvidenceAuthority,
    EvidenceLayer,
    EvidenceStore,
    EventRecord,
    RunRecord,
    TerminalStatus,
)


@dataclass(frozen=True)
class RunHandle:
    run: RunRecord

    @property
    def run_id(self) -> str:
        return self.run.run_id


class RunCoordinator:
    """Own run identity, raw event persistence, and canonical mapping."""

    mapper_version = "semantic-mapper-v1"

    def __init__(self, evidence: EvidenceStore):
        self.evidence = evidence

    def start_run(self, task_id: str, **metadata: Any) -> RunHandle:
        return RunHandle(self.evidence.start_run(task_id, **metadata))

    def attach_run(self, run_id: str, **identity: Any) -> RunHandle:
        return RunHandle(self.evidence.attach_existing_run(run_id, **identity))

    def start_child_run(self, parent: RunHandle, task_id: str, **metadata: Any) -> RunHandle:
        """Create an explicit child Run; never hide lineage in task aliases."""
        child = self.evidence.start_run(task_id, **metadata)
        child = self.evidence.update_run(child.run_id, root_task_id=parent.run.root_task_id or parent.run.task_id, parent_run_id=parent.run_id)
        return RunHandle(child)

    def record_observation(
        self,
        handle: RunHandle | str,
        *,
        event_type: str,
        payload: Any = None,
        producer: str,
        call_id: str = "",
        idempotency_key: str = "",
        parent_event_id: str = "",
        **fields: Any,
    ) -> EventRecord:
        """Persist one raw observation; no semantic status can be supplied."""
        run_id = handle.run_id if isinstance(handle, RunHandle) else str(handle)
        return self.evidence.append_event(
            run_id,
            event_type=event_type,
            payload=payload,
            layer=EvidenceLayer.RAW,
            authority=EvidenceAuthority.OBSERVED,
            producer=producer,
            call_id=call_id,
            parent_event_id=parent_event_id,
            idempotency_key=idempotency_key,
            **fields,
        )

    def record_canonical(
        self,
        handle: RunHandle | str,
        *,
        event_type: str,
        payload: Any = None,
        producer: str,
        authority: EvidenceAuthority = EvidenceAuthority.DERIVED,
        call_id: str = "",
        idempotency_key: str = "",
        **fields: Any,
    ) -> EventRecord:
        """Persist a raw observation and its single canonical semantic event."""
        raw = self.record_observation(
            handle,
            event_type=event_type,
            payload=payload,
            producer=producer,
            call_id=call_id,
            idempotency_key=f"raw:{idempotency_key}" if idempotency_key else "",
            **fields,
        )
        return self.map_semantic(
            handle,
            event_type=event_type,
            source_observation_id=raw.event_id,
            source_observation=raw,
            payload=payload,
            authority=authority,
            call_id=call_id,
            idempotency_key=f"semantic:{idempotency_key}" if idempotency_key else "",
            **fields,
        )

    def map_semantic(
        self,
        handle: RunHandle | str,
        *,
        event_type: str,
        source_observation_id: str,
        source_observation: EventRecord | None = None,
        payload: Any = None,
        authority: EvidenceAuthority = EvidenceAuthority.DERIVED,
        producer: str = "run_coordinator",
        call_id: str = "",
        parent_event_id: str = "",
        idempotency_key: str = "",
        **fields: Any,
    ) -> EventRecord:
        """Create semantic evidence only from an existing raw observation."""
        run_id = handle.run_id if isinstance(handle, RunHandle) else str(handle)
        raw = source_observation or next(
            (
                event
                for event in self.evidence.load_trajectory_events(run_id)
                if event.event_id == source_observation_id
            ),
            None,
        )
        if raw is None or raw.layer is not EvidenceLayer.RAW:
            raise ValueError(f"semantic source observation is not persisted: {source_observation_id}")
        return self.evidence.append_event(
            run_id,
            event_type=event_type,
            payload=payload,
            layer=EvidenceLayer.SEMANTIC,
            authority=authority,
            source_observation_id=source_observation_id,
            mapper_version=self.mapper_version,
            producer=producer,
            call_id=call_id or raw.call_id,
            parent_event_id=parent_event_id or source_observation_id,
            idempotency_key=idempotency_key,
            **fields,
        )

    def finish(self, handle: RunHandle | str, *, success: bool, reason: str = "", **payload: Any) -> EventRecord:
        """Compatibility terminal observation; use finalize() after policy."""
        run_id = handle.run_id if isinstance(handle, RunHandle) else str(handle)
        return self.record_observation(
            run_id,
            event_type="completion_observed",
            payload={"success": success, "completion_reason": reason, **payload},
            producer="completion_producer",
        )

    def mark_recovery_state(
        self,
        handle: RunHandle | str,
        *,
        status: TerminalStatus,
        reason: str,
        producer: str = "supervisor",
    ) -> EventRecord:
        """Persist a non-success recovery state without creating task_finished."""

        if status not in {
            TerminalStatus.PAUSED,
            TerminalStatus.BLOCKED,
            TerminalStatus.EVIDENCE_GAP,
            TerminalStatus.INDETERMINATE,
        }:
            raise ValueError(
                "recovery state must be paused, blocked, evidence_gap, or indeterminate"
            )
        run_id = handle.run_id if isinstance(handle, RunHandle) else str(handle)
        raw = self.record_observation(
            run_id,
            event_type="recovery_state_observed",
            payload={"status": status.value, "reason": reason},
            producer=producer,
            idempotency_key=f"recovery-state:{status.value}:{reason}",
        )
        semantic = self.map_semantic(
            run_id,
            event_type="recovery_state_changed",
            source_observation_id=raw.event_id,
            source_observation=raw,
            payload={"status": status.value, "reason": reason},
            producer="run_coordinator",
            idempotency_key=f"semantic:recovery-state:{status.value}:{reason}",
        )
        self.evidence.update_run(
            run_id,
            final_status=status.value,
            success=False,
            completion_reason=reason,
        )
        return semantic

    def finalize(
        self,
        handle: RunHandle | str,
        *,
        source_observation_id: str,
        source_observation: EventRecord | None = None,
        status: TerminalStatus,
        reason: str,
    ) -> EventRecord:
        """Persist the unique semantic terminal event and update the Run header."""
        run_id = handle.run_id if isinstance(handle, RunHandle) else str(handle)
        event = self.map_semantic(
            run_id,
            event_type="task_finished",
            source_observation_id=source_observation_id,
            source_observation=source_observation,
            payload={
                "success": status is TerminalStatus.SUCCESS,
                "final_status": status.value,
                "completion_reason": reason,
            },
            authority=(
                EvidenceAuthority.VERIFIED
                if status is TerminalStatus.SUCCESS
                else EvidenceAuthority.DERIVED
            ),
            idempotency_key=f"terminal:{source_observation_id}",
        )
        self.evidence.update_run(
            run_id,
            finished_at=event.created_at,
            success=status is TerminalStatus.SUCCESS,
            final_status=status.value,
            completion_reason=reason,
        )
        return event

    def complete_from_observation(
        self,
        handle: RunHandle | str,
        *,
        observation: EventRecord,
        profile: str = "read_only",
    ):
        """Apply Completion Policy to a persisted terminal observation."""
        from autonomous_iteration.verification.completion import CompletionProfile, evaluate_completion

        run_id = handle.run_id if isinstance(handle, RunHandle) else str(handle)
        decision = evaluate_completion(
            self.evidence.load_trajectory_events(run_id),
            profile=CompletionProfile(profile),
        )
        event = self.finalize(
            run_id,
            source_observation_id=observation.event_id,
            source_observation=observation,
            status=decision.status,
            reason=decision.reason,
        )
        return decision, event
