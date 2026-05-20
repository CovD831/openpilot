"""Pydantic models for the four-layer memory system."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    """Memory type taxonomy aligned with Claude Code.

    These types capture context NOT derivable from current project state.
    Code patterns, architecture, git history are derivable and should NOT be saved.
    """
    USER = "user"              # User's role, preferences, knowledge, communication style
    FEEDBACK = "feedback"      # Guidance on approach - corrections and confirmations
    PROJECT = "project"        # Ongoing work, goals, initiatives, deadlines
    REFERENCE = "reference"    # Pointers to external systems and resources

    # Legacy types for backward compatibility
    SHORT_TERM = "short_term"  # Current session context (deprecated)
    LONG_TERM = "long_term"    # User preferences and habits (deprecated)
    TASK = "task"              # Historical task execution records (deprecated)
    SKILL = "skill"            # Reusable process templates (deprecated)


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
    attributes: dict = Field(default_factory=dict)

    # For semantic search
    embedding: list[float] | None = None

    # For graph-based memory vault
    related_memory_ids: list[str] = Field(default_factory=list)
    recall_frequency: float = Field(default=0.0, ge=0.0)  # How often this memory is recalled


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
