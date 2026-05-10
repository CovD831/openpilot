"""Pydantic models for the four-layer memory system."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    """Four-layer memory architecture."""
    SHORT_TERM = "short_term"  # Current session context
    LONG_TERM = "long_term"    # User preferences and habits
    TASK = "task"              # Historical task execution records
    SKILL = "skill"            # Reusable process templates


class MemoryRecord(BaseModel):
    """A single memory entry."""
    id: str
    memory_type: MemoryType
    content: str
    tags: list[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    usage_count: int = Field(default=0, ge=0)
    last_used: str | None = None
    metadata: dict = Field(default_factory=dict)


class MemoryQueryResult(BaseModel):
    """Result of memory retrieval."""
    query: str
    memories: list[MemoryRecord] = Field(default_factory=list)
    match_scores: dict[str, float] = Field(default_factory=dict)  # memory_id -> score


class MemoryUpdateProposal(BaseModel):
    """Proposal for updating memory."""
    action: str  # "add", "update", "delete"
    memory_id: str | None = None
    memory_type: MemoryType
    content: str
    tags: list[str] = Field(default_factory=list)
    reason: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
