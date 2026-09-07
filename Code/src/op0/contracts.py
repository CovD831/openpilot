"""Typed contracts for the L0 execution base (std-lib dataclasses only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TaskSpec:
    """One admitted-shape task at L0: a goal plus a read-only scope.

    L0 keeps the scope explicit but unguarded: there is no admission grant
    yet (L1). The read scope still bounds every tool call the bridge serves.
    """

    goal: str
    project_root: str
    read_paths: tuple[str, ...] = ()
    timeout_seconds: float = 600.0

    def resolved_root(self) -> Path:
        return Path(self.project_root).expanduser().resolve(strict=False)

    def scoped_paths(self) -> tuple[str, ...]:
        root = self.resolved_root()
        return tuple(str(root / p) for p in self.read_paths) or (str(root),)


@dataclass(frozen=True)
class EventRecord:
    """One trajectory event; the JSONL line is the durable form."""

    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    producer: str = "op0"
    call_id: str = ""
    idempotency_key: str = ""
    timestamp: str = ""

    def to_jsonl(self) -> str:
        import json

        return json.dumps(
            {
                "event_type": self.event_type,
                "payload": self.payload,
                "producer": self.producer,
                "call_id": self.call_id,
                "idempotency_key": self.idempotency_key,
                "timestamp": self.timestamp,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
