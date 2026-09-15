"""Typed contracts for the minimal coding agent."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class CodingActionKind(str, Enum):
    READ = "read"
    WRITE = "write"
    PATCH = "patch"
    RUN = "run"
    STOP = "stop"


class CodingTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    goal: str
    workspace_root: str = ""
    session_id: str = ""
    route: str = "coding_agent"
    target_path: str = ""
    draft_text: str = ""
    patch_text: str = ""
    line_start: int | None = None
    line_end: int | None = None
    validation_command: list[str] = Field(default_factory=list)
    max_turns: int = Field(default=3, ge=1)
    constraints: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class CodingAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(default_factory=lambda: uuid4().hex)
    kind: CodingActionKind
    path: str = ""
    content: str = ""
    command: list[str] = Field(default_factory=list)
    line_start: int | None = None
    line_end: int | None = None
    reason: str = ""
    overwrite: bool = True


class CodingActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: CodingAction
    success: bool
    summary: str = ""
    text: str = ""
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None


class CodingRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    task_id: str
    status: Literal[
        "running", "paused", "blocked", "aborted", "failed", "crashed",
        "evidence_gap", "indeterminate", "success",
    ] = "running"
    success: bool = False
    reason: str = ""
    turns_used: int = 0
    verification_status: str = ""
    trajectory_dir: str = ""
    actions: list[CodingActionResult] = Field(default_factory=list)
