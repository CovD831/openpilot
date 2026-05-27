"""Runtime metadata contracts for LLM calls, execution contexts, and logs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from metadata.base import JsonValue, MetadataBase, MetadataKind
from metadata.results import FailureMetadata, ResultStatus, TaskResultMetadata, ToolResultMetadata
from metadata.tooling import ToolContextMetadata, ToolEventMetadata, ToolInputMetadata


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


class ToolExecutionEnvelopeMetadata(MetadataBase):
    kind: Literal[MetadataKind.TOOL_EXECUTION_ENVELOPE] = MetadataKind.TOOL_EXECUTION_ENVELOPE
    tool_name: str
    step_id: str
    status: ResultStatus
    success: bool
    input_metadata: ToolInputMetadata
    output_metadata: ToolResultMetadata | None = None
    failure: FailureMetadata | None = None
    duration_seconds: float = 0.0
    timeout_override: int | None = None
    attempts_used: int = 1
    retry_count: int = 0
    retry_history: list[dict[str, JsonValue]] = Field(default_factory=list)
    call_id: str | None = None
    tool_context: ToolContextMetadata | None = None
    tool_events: list[ToolEventMetadata] = Field(default_factory=list)

    @property
    def output(self) -> MetadataBase | None:
        return self.output_metadata.result if self.output_metadata else None

    @property
    def error_message(self) -> str | None:
        return self.failure.error_message if self.failure else None


class AgentExecutionMetadata(MetadataBase):
    kind: Literal[MetadataKind.AGENT_EXECUTION] = MetadataKind.AGENT_EXECUTION
    agent_name: str
    status: ResultStatus
    success: bool
    result_metadata: TaskResultMetadata | MetadataBase | None = None
    failure: FailureMetadata | None = None
    duration_seconds: float = 0.0
    tool_calls: list[ToolExecutionEnvelopeMetadata] = Field(default_factory=list)


class ModuleExecutionMetadata(MetadataBase):
    kind: Literal[MetadataKind.MODULE_EXECUTION] = MetadataKind.MODULE_EXECUTION
    module_name: str
    status: ResultStatus
    success: bool
    result_metadata: TaskResultMetadata | MetadataBase | None = None
    failure: FailureMetadata | None = None
    duration_seconds: float = 0.0
