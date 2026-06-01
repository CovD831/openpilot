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


class EnvironmentFailureMetadata(MetadataBase):
    """Structured diagnosis for project environment setup failures."""

    kind: Literal[MetadataKind.ENVIRONMENT_FAILURE] = MetadataKind.ENVIRONMENT_FAILURE
    raw_stderr: str = ""
    raw_stdout: str = ""
    root_cause: str = ""
    error_type: str = ""
    affected_file: str = ""
    line_number: int | None = None
    failed_requirement: str = ""
    pip_notices: list[str] = Field(default_factory=list)
    suggested_command: str = ""
    requires_confirmation: bool = False


class EnvironmentFixResultMetadata(MetadataBase):
    """Result of an environment repair attempt."""

    kind: Literal[MetadataKind.ENVIRONMENT_FIX_RESULT] = MetadataKind.ENVIRONMENT_FIX_RESULT
    project_path: str = ""
    environment_failure: EnvironmentFailureMetadata
    applied: bool = False
    changed_files: list[str] = Field(default_factory=list)
    repair_actions: list[str] = Field(default_factory=list)
    replacement_requirement: str = ""
    research_queries: list[str] = Field(default_factory=list)
    research_results: list[dict[str, JsonValue]] = Field(default_factory=list)
    memory_record_ids: list[str] = Field(default_factory=list)
    suggested_command: str = ""
    command_executed: bool = False
    requires_confirmation: bool = False
    user_declined: bool = False
