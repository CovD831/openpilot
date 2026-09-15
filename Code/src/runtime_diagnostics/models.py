"""Local persistence models for runtime diagnostics."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from evidence_core.records import ArtifactRecord, EventRecord, RunRecord, RunSummaryRecord


class DiagnosticRecord(BaseModel):
    """One persisted diagnostic record.

    The canonical evidence remains the embedded ProblemSignalMetadata and
    ProblemJudgmentMetadata JSON payloads. This wrapper only adds persistence
    metadata for JSONL storage.
    """

    record_id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    task_id: str = ""
    signal: dict[str, Any]
    judgment: dict[str, Any] | None = None

    @property
    def category(self) -> str:
        return str(self.signal.get("category") or "unknown")

    @property
    def severity(self) -> str:
        if not self.judgment:
            return "unjudged"
        return str(self.judgment.get("severity") or "unknown")
