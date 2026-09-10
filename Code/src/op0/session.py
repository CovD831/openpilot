"""Run session: id, lifecycle, and the durable JSONL trajectory.

Every trajectory file starts with a schema header line (the Semantic
Kernel's version anchor): future format changes bump metadata.SCHEMA_VERSION
and old ledgers stay replayable because the header declares what wrote them.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from op0 import metadata
from op0.contracts import EventRecord


class Session:
    """Owns one run id and appends every event to <project>/.openpilot/trajectory/."""

    def __init__(self, project_root: Path, *, run_id: str = "", resume: bool = False) -> None:
        self.project_root = project_root
        self.trajectory_dir = project_root / ".openpilot" / "trajectory"
        self.trajectory_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or f"run_{uuid4().hex}"
        self.path = self.trajectory_dir / f"{self.run_id}.jsonl"
        self._index = len(self.load_events()) if resume else 0
        if not resume:
            self._write_header()

    @classmethod
    def resume(cls, project_root: Path, run_id: str) -> "Session":
        """Continue an existing run in place: the ledger is appended, never
        rewritten, and the projection rebuilds from it."""
        return cls(project_root, run_id=run_id, resume=True)

    def _write_header(self) -> None:
        if self.path.exists():
            return
        header = {
            "record": "schema",
            "schema_version": metadata.SCHEMA_VERSION,
            "run_id": self.run_id,
            "opened": datetime.now(UTC).isoformat(),
        }
        self.path.write_text(json.dumps(header) + "\n", encoding="utf-8")

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
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                if position != len(lines) - 1:
                    raise  # only torn tails are legal: a concurrent append owns the last line
                continue
            if raw.get("record") == "schema":
                continue  # the version header is metadata, not an event
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

    @staticmethod
    def unfinished_runs(project_root: Path) -> list[Path]:
        """Trajectory files that never reached run_finished — the resume
        candidates, newest first. A classmethod-style helper on the module's
        central type keeps the detection rules in one place."""
        directory = project_root / ".openpilot" / "trajectory"
        if not directory.is_dir():
            return []
        unfinished = []
        for path in sorted(directory.glob("run_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            text = path.read_text(encoding="utf-8")
            if '"run_finished"' not in text:
                unfinished.append(path)
        return unfinished

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
