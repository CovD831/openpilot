"""Typed, host-neutral record contracts for evidence-core."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from evidence_core.identity import new_artifact_id, new_event_id, new_run_id


class EvidenceLayer(StrEnum):
    RAW = "raw"
    SEMANTIC = "semantic"


class EvidenceAuthority(StrEnum):
    OBSERVED = "observed"
    RECEIPT = "receipt"
    VERIFIED = "verified"
    DERIVED = "derived"


class TerminalStatus(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    BLOCKED = "blocked"
    ABORTED = "aborted"
    FAILED = "failed"
    CRASHED = "crashed"
    EVIDENCE_GAP = "evidence_gap"
    INDETERMINATE = "indeterminate"
    SUCCESS = "success"


_TERMINAL_STATUS_TRANSITIONS = {
    TerminalStatus.RUNNING: set(TerminalStatus),
    TerminalStatus.PAUSED: {
        TerminalStatus.RUNNING,
        TerminalStatus.BLOCKED,
        TerminalStatus.ABORTED,
        TerminalStatus.FAILED,
        TerminalStatus.CRASHED,
        TerminalStatus.EVIDENCE_GAP,
        TerminalStatus.INDETERMINATE,
    },
    TerminalStatus.BLOCKED: {
        TerminalStatus.RUNNING,
        TerminalStatus.ABORTED,
        TerminalStatus.FAILED,
        TerminalStatus.EVIDENCE_GAP,
        TerminalStatus.INDETERMINATE,
    },
    TerminalStatus.EVIDENCE_GAP: {
        TerminalStatus.BLOCKED,
        TerminalStatus.FAILED,
        TerminalStatus.INDETERMINATE,
    },
    TerminalStatus.INDETERMINATE: {
        TerminalStatus.BLOCKED,
        TerminalStatus.FAILED,
        TerminalStatus.SUCCESS,
    },
    TerminalStatus.ABORTED: set(),
    TerminalStatus.FAILED: set(),
    TerminalStatus.CRASHED: set(),
    TerminalStatus.SUCCESS: set(),
}


def terminal_status_transition_allowed(
    current: TerminalStatus | str,
    target: TerminalStatus | str,
) -> bool:
    source = TerminalStatus(current)
    destination = TerminalStatus(target)
    return source == destination or destination in _TERMINAL_STATUS_TRANSITIONS[source]


class RunRecord(BaseModel):
    """Durable header for one recorded run."""

    model_config = ConfigDict(extra="ignore")
    schema_version: str = "v1"

    run_id: str = Field(default_factory=new_run_id)
    task_id: str = ""
    root_task_id: str = ""
    parent_run_id: str = ""
    resume_attempt_id: str = ""
    session_id: str = ""
    source: str = ""
    raw_input: str = ""
    goal: str = ""
    route: str = ""
    started_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str | None = None
    final_status: TerminalStatus = TerminalStatus.RUNNING
    completion_reason: str = ""
    success: bool | None = None


class EventRecord(BaseModel):
    """Chronological event within one run trajectory."""

    model_config = ConfigDict(extra="ignore")
    schema_version: str = "v1"

    event_id: str = Field(default_factory=new_event_id)
    run_id: str
    sequence: int
    event_type: str
    idempotency_key: str = ""
    task_id: str = ""
    session_id: str = ""
    phase: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    summary: str = ""
    payload_kind: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    layer: EvidenceLayer = EvidenceLayer.RAW
    authority: EvidenceAuthority = EvidenceAuthority.OBSERVED
    source_observation_id: str = ""
    parent_event_id: str = ""
    mapper_version: str = ""
    producer: str = ""
    call_id: str = ""


class ArtifactRecord(BaseModel):
    """Large payload retained outside the main event stream."""

    model_config = ConfigDict(extra="ignore")
    schema_version: str = "v1"

    artifact_id: str = Field(default_factory=new_artifact_id)
    run_id: str
    kind: str
    path: str
    content_type: str = "text/plain"
    bytes: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    source_event_id: str = ""


class RunSummaryRecord(BaseModel):
    """Compact per-run summary for human review."""

    model_config = ConfigDict(extra="ignore")
    schema_version: str = "v1"

    run_id: str
    task_id: str = ""
    session_id: str = ""
    source: str = ""
    route: str = ""
    goal: str = ""
    raw_input_preview: str = ""
    started_at: str = ""
    finished_at: str | None = None
    success: bool | None = None
    final_status: str = "running"
    completion_reason: str = ""
    event_count: int = 0
    last_sequence: int = 0
    projection_layer: EvidenceLayer = EvidenceLayer.RAW
    tool_called_count: int = 0
    tool_succeeded_count: int = 0
    tool_failed_count: int = 0
    verification_state_changes: int = 0
    phase_changes: int = 0
    artifact_count: int = 0
    last_phase: str = ""
    verification_status: str = ""
