"""Run session: id, lifecycle, and the durable JSONL trajectory."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

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
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            import json

            raw = json.loads(line)
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
