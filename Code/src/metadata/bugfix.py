"""Metadata contracts for runtime bug fixing."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SerializeAsAny

from metadata.artifacts import CommandArtifactMetadata
from metadata.base import JsonValue, MetadataBase, MetadataKind


class BugFixAttemptMetadata(MetadataBase):
    kind: Literal[MetadataKind.BUG_FIX_ATTEMPT] = MetadataKind.BUG_FIX_ATTEMPT
    iteration: int
    command_result: SerializeAsAny[CommandArtifactMetadata] | None = None
    error_summary: str = ""
    modified_files: list[str] = Field(default_factory=list)
    rationale: str = ""
    llm_payload: dict[str, JsonValue] = Field(default_factory=dict)


class BugFixResultMetadata(MetadataBase):
    kind: Literal[MetadataKind.BUG_FIX_RESULT] = MetadataKind.BUG_FIX_RESULT
    command: str
    cwd: str = ""
    target_files: list[str] = Field(default_factory=list)
    fixed: bool = False
    iterations_used: int = 0
    max_iterations: int = 5
    continuation_iterations: int = 3
    attempts: list[BugFixAttemptMetadata] = Field(default_factory=list)
    final_command_result: SerializeAsAny[CommandArtifactMetadata] | None = None
    requires_user_decision: bool = False
    user_terminated: bool = False
