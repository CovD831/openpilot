"""Timeline reconstruction for evidence-core runs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from evidence_core.records import EventRecord


def build_timeline(events: Iterable[EventRecord | Mapping[str, Any]]) -> list[EventRecord]:
    normalized = [
        event if isinstance(event, EventRecord) else EventRecord.model_validate(event)
        for event in events
    ]
    return sorted(
        normalized,
        key=lambda event: (
            int(event.sequence or 0),
            str(event.created_at or ""),
            str(event.event_id or ""),
        ),
    )
