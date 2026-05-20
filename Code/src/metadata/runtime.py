"""Runtime metadata contracts for LLM calls, execution contexts, and logs."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from metadata.base import JsonValue, MetadataBase, MetadataKind


class LLMRequestMetadata(MetadataBase):
    kind: MetadataKind = MetadataKind.LLM_REQUEST
    task: str | None = None
    purpose: str | None = None
    trace_info: dict[str, JsonValue] = Field(default_factory=dict)


class LLMResponseMetadata(MetadataBase):
    kind: MetadataKind = MetadataKind.LLM_RESPONSE
    model: str = ""
    provider: str = ""
    usage: dict[str, JsonValue] = Field(default_factory=dict)
    finish_reason: str | None = None
    provider_details: dict[str, JsonValue] = Field(default_factory=dict)


class ExecutionContextMetadata(MetadataBase):
    kind: MetadataKind = MetadataKind.EXECUTION_CONTEXT
    execution_id: str
    tool_name: str
    step_id: str
    timeout_seconds: int = 300
    max_retries: int = 3
    permission_level: str = "low"
    depends_on: list[str] = Field(default_factory=list)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class LogEventMetadata(MetadataBase):
    kind: MetadataKind = MetadataKind.LOG_EVENT
    source_type: str
    source_name: str
    phase: str
    event_type: str
    success: bool | None = None
    duration_ms: int | None = None
    input_summary: Any | None = None
    output_summary: Any | None = None
    error: str | None = None
    trace_info: dict[str, JsonValue] = Field(default_factory=dict)
