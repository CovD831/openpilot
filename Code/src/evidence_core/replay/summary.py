"""Summary reconstruction for evidence-core runs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from evidence_core.records import ArtifactRecord, EvidenceLayer, EventRecord, RunRecord, RunSummaryRecord
from evidence_core.replay.timeline import build_timeline


def build_run_summary(
    run: RunRecord,
    events: Iterable[EventRecord | Mapping[str, Any]],
    artifacts: Iterable[ArtifactRecord | Mapping[str, Any]],
) -> RunSummaryRecord:
    complete_timeline = build_timeline(events)
    semantic_timeline = [item for item in complete_timeline if item.layer.value == "semantic"]
    timeline = semantic_timeline or complete_timeline
    artifact_list = [
        artifact if isinstance(artifact, ArtifactRecord) else ArtifactRecord.model_validate(artifact)
        for artifact in artifacts
    ]
    tool_called_count = sum(1 for item in timeline if item.event_type == "tool_called")
    tool_succeeded_count = sum(1 for item in timeline if item.event_type == "tool_succeeded")
    tool_failed_count = sum(1 for item in timeline if item.event_type == "tool_failed")
    verification_state_changes = sum(1 for item in timeline if item.event_type == "verification_state_changed")
    phase_changes = sum(1 for item in timeline if item.event_type == "runtime_phase_changed")
    last_phase = ""
    verification_status = ""
    for item in reversed(timeline):
        payload = item.payload or {}
        if not last_phase:
            last_phase = str(item.phase or payload.get("phase") or "")
        if not verification_status:
            verification_value = payload.get("verification_status")
            if verification_value not in (None, "", [], {}):
                verification_status = str(verification_value)
        if last_phase and verification_status:
            break
    return RunSummaryRecord(
        run_id=run.run_id,
        task_id=run.task_id,
        session_id=run.session_id,
        source=run.source,
        route=run.route,
        goal=run.goal,
        raw_input_preview=(run.raw_input or "")[:200],
        started_at=run.started_at,
        finished_at=run.finished_at,
        success=run.success,
        final_status=run.final_status,
        completion_reason=run.completion_reason,
        event_count=len(timeline),
        last_sequence=max((int(item.sequence or 0) for item in complete_timeline), default=0),
        projection_layer=(EvidenceLayer.SEMANTIC if semantic_timeline else EvidenceLayer.RAW),
        tool_called_count=tool_called_count,
        tool_succeeded_count=tool_succeeded_count,
        tool_failed_count=tool_failed_count,
        verification_state_changes=verification_state_changes,
        phase_changes=phase_changes,
        artifact_count=len(artifact_list),
        last_phase=last_phase,
        verification_status=verification_status,
    )
