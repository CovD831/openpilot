"""JSONL audit logging for openpilot validation sessions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class OpenPilotLogger:
    """Append structured openpilot events to a JSON Lines file."""

    def __init__(self, log_file: str | Path) -> None:
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def log_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        session_id: str,
        turn_id: int,
    ) -> None:
        """Write one event without storing secrets or environment values."""

        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "session_id": session_id,
            "turn_id": turn_id,
            "event_type": event_type,
            "payload": payload,
        }
        with self.log_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


