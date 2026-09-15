"""Context projection for the minimal coding agent."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from coding_agent.contract import CodingTask


class CodingContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    goal: str
    workspace_root: str = ""
    target_path: str = ""
    target_exists: bool = False
    current_text: str = ""
    current_text_preview: str = ""
    validation_command: list[str] = Field(default_factory=list)
    recent_event_types: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_coding_context(
    task: CodingTask,
    *,
    current_text: str = "",
    target_exists: bool = False,
    recent_event_types: Sequence[str] | None = None,
    evidence: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    preview_chars: int = 800,
) -> CodingContext:
    text = current_text or ""
    return CodingContext(
        task_id=task.task_id,
        goal=task.goal,
        workspace_root=task.workspace_root,
        target_path=task.target_path,
        target_exists=target_exists,
        current_text=text,
        current_text_preview=text[:preview_chars],
        validation_command=list(task.validation_command),
        recent_event_types=[str(item) for item in (recent_event_types or []) if str(item).strip()],
        evidence=dict(evidence or {}),
        metadata={**task.context, **dict(metadata or {})},
    )
