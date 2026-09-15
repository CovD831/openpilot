"""Host-neutral evidence core for durable task trajectories."""

from evidence_core.export.bundle import copy_run_bundle
from evidence_core.export.jsonl import read_jsonl, write_jsonl
from evidence_core.conformance import EvidenceConformanceResult, validate_trajectory_conformance
from evidence_core.identity import new_artifact_id, new_event_id, new_run_id
from evidence_core.records import (
    ArtifactRecord,
    EvidenceAuthority,
    EvidenceLayer,
    EventRecord,
    RunRecord,
    RunSummaryRecord,
    TerminalStatus,
    terminal_status_transition_allowed,
)
from evidence_core.replay.summary import build_run_summary
from evidence_core.replay.timeline import build_timeline
from evidence_core.serialization import dump_json, json_safe, sanitize_payload, sanitize_text
from evidence_core.store.fs_store import DEFAULT_DATA_DIR, EvidenceStore
from evidence_core.reader import EvidenceReader

__all__ = [
    "ArtifactRecord",
    "EvidenceConformanceResult",
    "EventRecord",
    "EvidenceAuthority",
    "EvidenceLayer",
    "RunRecord",
    "RunSummaryRecord",
    "TerminalStatus",
    "terminal_status_transition_allowed",
    "EvidenceStore",
    "EvidenceReader",
    "DEFAULT_DATA_DIR",
    "build_run_summary",
    "build_timeline",
    "copy_run_bundle",
    "dump_json",
    "json_safe",
    "sanitize_payload",
    "sanitize_text",
    "new_artifact_id",
    "new_event_id",
    "new_run_id",
    "read_jsonl",
    "validate_trajectory_conformance",
    "write_jsonl",
]
