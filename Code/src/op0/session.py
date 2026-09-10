"""Run session: id, lifecycle, and the durable JSONL trajectory."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from op0 import metadata
from op0.contracts import EventRecord


class Session:
    """Owns one run id and appends every event to <project>/.openpilot/trajectory/."""

    def __init__(self, project_root: Path) -> None:
        self.run_id = f"run_{uuid4().hex}"
        self.project_root = project_root
        self.trajectory_dir = project_root / ".openpilot" / "trajectory"
        self.trajectory_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.trajectory_dir / f"{self.run_id}.jsonl"
        self._index = 0

    def record(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        producer: str = "op0",
        call_id: str = "",
    ) -> EventRecord:
        problem = metadata.violation(event_type, payload or {})
        if problem:
            raise ValueError(f"ledger contract violation: {problem}")
        self._index += 1
        record = EventRecord(
            event_type=event_type,
            payload=payload or {},
            producer=producer,
            call_id=call_id,
            idempotency_key=f"{self.run_id}:{self._index}",
            timestamp=datetime.now(UTC).isoformat(),
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record.to_jsonl() + "\n")
        return record

    def load_events(self) -> list[EventRecord]:
        if not self.path.exists():
            return []
        events: list[EventRecord] = []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        for position, line in enumerate(lines):
            if not line.strip():
                continue
            import json

            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                if position != len(lines) - 1:
                    raise  # only torn tails are legal: a concurrent append owns the last line
                continue
            events.append(
                EventRecord(
                    event_type=str(raw.get("event_type", "")),
                    payload=dict(raw.get("payload") or {}),
                    producer=str(raw.get("producer", "op0")),
                    call_id=str(raw.get("call_id", "")),
                    idempotency_key=str(raw.get("idempotency_key", "")),
                    timestamp=str(raw.get("timestamp", "")),
                )
            )
        return events

    def last_model_response(self) -> str:
        from op0.response import assistant_text_from_payload
        for event in reversed(self.load_events()):
            if event.event_type != "model_response":
                continue
            text = assistant_text_from_payload(event.payload)
            if text:
                return text
        return ""

    def last_model_error(self) -> str:
        """Provider error from the latest failed model call; callers guard on an empty last_model_response."""
        from op0.response import error_message_from_payload
        for event in reversed(self.load_events()):
            if event.event_type == "model_response" and (error := error_message_from_payload(event.payload)):
                return error
        return ""
