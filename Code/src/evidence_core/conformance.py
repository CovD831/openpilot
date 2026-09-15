"""Producer-agnostic checks for the minimum Evidence Core trajectory contract."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from evidence_core.records import EventRecord


class EvidenceConformanceResult(BaseModel):
    """Structured result of validating one persisted trajectory."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    checks: dict[str, bool] = Field(default_factory=dict)
    violations: list[str] = Field(default_factory=list)


def validate_trajectory_conformance(
    events: Iterable[EventRecord | Mapping[str, Any]],
    *,
    require_mutation_chain: bool = False,
    require_terminal: bool = True,
    supported_mapper_versions: set[str] | None = None,
) -> EvidenceConformanceResult:
    """Validate the shared event contract without inspecting terminal output.

    The common contract requires a received task, paired tool outcomes, and a
    terminal task event. Verification is optional for a read-only trajectory;
    the stricter mutation profile additionally requires explicit mutation
    request / receipt and validation completion events.
    """

    all_events = sorted(
        (event if isinstance(event, EventRecord) else EventRecord.model_validate(event) for event in events),
        key=lambda event: (int(event.sequence or 0), str(event.created_at or ""), str(event.event_id or "")),
    )
    semantic_events = [event for event in all_events if event.layer.value == "semantic"]
    timeline = semantic_events or all_events
    supported_mappers = supported_mapper_versions or {"semantic-mapper-v1"}
    event_types = [event.event_type for event in timeline]
    violations: list[str] = []
    checks = {
        "task_received": "task_received" in event_types,
        "task_finished": not require_terminal or "task_finished" in event_types,
        "tool_outcomes_paired": True,
        "verification_follows_tool": True,
        "semantic_sources_resolve": True,
        "event_identity_unique": True,
        "parent_graph_valid": True,
        "authority_valid": True,
    }
    event_ids = [event.event_id for event in all_events]
    sequences = [int(event.sequence or 0) for event in all_events]
    if len(event_ids) != len(set(event_ids)) or len(sequences) != len(set(sequences)):
        checks["event_identity_unique"] = False
        violations.append("event ids and sequences must be unique within a run")
    if not checks["task_received"]:
        violations.append("missing task_received event")
    if require_terminal and not checks["task_finished"]:
        violations.append("missing task_finished event")

    pending_tools = 0
    pending_call_ids: set[str] = set()
    completed_call_ids: set[str] = set()
    tool_seen = False
    for event in timeline:
        if event.event_type == "tool_called":
            if event.call_id:
                if event.call_id in pending_call_ids or event.call_id in completed_call_ids:
                    checks["tool_outcomes_paired"] = False
                    violations.append(f"duplicate logical tool call: {event.call_id}")
                pending_call_ids.add(event.call_id)
            else:
                pending_tools += 1
            tool_seen = True
        elif event.event_type in {"tool_succeeded", "tool_failed"}:
            if event.call_id:
                if event.call_id not in pending_call_ids:
                    checks["tool_outcomes_paired"] = False
                    violations.append(f"{event.event_type} has no pending call_id={event.call_id}")
                else:
                    pending_call_ids.remove(event.call_id)
                    completed_call_ids.add(event.call_id)
            else:
                if pending_tools <= 0:
                    checks["tool_outcomes_paired"] = False
                    violations.append(f"{event.event_type} has no preceding tool_called")
                else:
                    pending_tools -= 1
        elif event.event_type == "verification_state_changed":
            if not tool_seen:
                checks["verification_follows_tool"] = False
                violations.append("verification_state_changed precedes all tool calls")
    if pending_tools or pending_call_ids:
        checks["tool_outcomes_paired"] = False
        violations.append("tool_called is missing a tool outcome")
    raw_ids = {event.event_id for event in all_events if event.layer.value == "raw"}
    all_ids = {event.event_id for event in all_events}
    for event in semantic_events:
        if event.layer.value != "semantic":
            continue
        if not event.source_observation_id or event.source_observation_id not in raw_ids:
            checks["semantic_sources_resolve"] = False
            violations.append(f"semantic event {event.event_id} has no persisted raw source")
        if not event.mapper_version:
            checks["semantic_sources_resolve"] = False
            violations.append(f"semantic event {event.event_id} has no mapper_version")
        elif event.mapper_version not in supported_mappers:
            checks["semantic_sources_resolve"] = False
            violations.append(f"semantic event {event.event_id} uses unsupported mapper_version")
        if event.parent_event_id and event.parent_event_id not in all_ids:
            checks["parent_graph_valid"] = False
            violations.append(f"semantic event {event.event_id} has missing parent_event_id")
        if event.parent_event_id == event.event_id:
            checks["parent_graph_valid"] = False
            violations.append(f"semantic event {event.event_id} is its own parent")
        if (
            event.event_type == "task_finished"
            and bool((event.payload or {}).get("success"))
            and event.authority.value != "verified"
        ):
            checks["authority_valid"] = False
            violations.append("successful task_finished must have verified authority")

    parent_by_id = {
        event.event_id: event.parent_event_id
        for event in semantic_events
        if event.parent_event_id
    }
    for event_id in parent_by_id:
        seen: set[str] = set()
        current = event_id
        while current in parent_by_id:
            if current in seen:
                checks["parent_graph_valid"] = False
                violations.append(f"semantic parent graph contains a cycle at {event_id}")
                break
            seen.add(current)
            current = parent_by_id[current]
    if require_mutation_chain:
        mutation_kinds = {
            str((event.payload or {}).get("action", {}).get("kind"))
            for event in timeline
            if event.event_type == "tool_called"
        }
        has_mutation = mutation_kinds.intersection({"write", "patch"}) or "mutation_requested" in event_types
        checks["mutation_requested"] = not has_mutation or "mutation_requested" in event_types
        checks["mutation_receipt"] = not has_mutation or "mutation_receipt" in event_types
        checks["validation_completed"] = not has_mutation or "validation_completed" in event_types
        checks["verification_event"] = not has_mutation or "verification_state_changed" in event_types
        if has_mutation and not checks["mutation_requested"]:
            violations.append("mutation is missing mutation_requested evidence")
        if has_mutation and not checks["mutation_receipt"]:
            violations.append("mutation is missing mutation_receipt evidence")
        if has_mutation and not checks["validation_completed"]:
            violations.append("mutation is missing validation_completed evidence")
        if has_mutation and not checks["verification_event"]:
            violations.append("mutation is missing verification_state_changed evidence")

    return EvidenceConformanceResult(valid=not violations, checks=checks, violations=violations)
