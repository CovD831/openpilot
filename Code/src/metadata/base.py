"""Core metadata contracts for model-harness data exchange."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field


JsonValue: TypeAlias = Any


class MetadataKind(str, Enum):
    """Canonical metadata categories shared across agents and tools."""

    TEXT_ARTIFACT = "text_artifact"
    CODE_ARTIFACT = "code_artifact"
    FILE_ARTIFACT = "file_artifact"
    COMMAND_ARTIFACT = "command_artifact"
    SEARCH_ARTIFACT = "search_artifact"
    EMBEDDING_ARTIFACT = "embedding_artifact"
    WARNING_ITEM = "warning_item"
    WARNING_CHECK_RESULT = "warning_check_result"
    BUG_FIX_ATTEMPT = "bug_fix_attempt"
    BUG_FIX_RESULT = "bug_fix_result"
    TASK_ROUTE = "task_route"
    TOOL_INPUT = "tool_input"
    TOOL_SELECTION = "tool_selection"
    TOOL_CONTRACT = "tool_contract"
    TOOL_CHAIN = "tool_chain"
    TOOL_RESULT = "tool_result"
    TOOL_EXECUTION_ENVELOPE = "tool_execution_envelope"
    TASK_RESULT = "task_result"
    AGENT_EXECUTION = "agent_execution"
    MODULE_EXECUTION = "module_execution"
    FAILURE = "failure"
    COLLECTED_DATA = "collected_data"
    PROCESSED_DATA = "processed_data"
    PRESENTATION = "presentation"
    PRODUCT_INTENT = "product_intent"
    VALIDATION_ISSUE = "validation_issue"
    PROJECT_OBJECTIVE = "project_objective"
    SUCCESS_METRIC = "success_metric"
    PROJECT_DIMENSION_ASSESSMENT = "project_dimension_assessment"
    PROJECT_DEPENDENCY = "project_dependency"
    DEPENDENCY_STRATEGY = "dependency_strategy"
    TASK_FILE_RESOLUTION_REQUEST = "task_file_resolution_request"
    RELATED_PROJECT_FILE = "related_project_file"
    TASK_FILE_RESOLUTION = "task_file_resolution"
    GIT_REPOSITORY = "git_repository"
    GIT_SNAPSHOT = "git_snapshot"
    GIT_DIFF_CONTEXT = "git_diff_context"
    IMPROVEMENT_CANDIDATE = "improvement_candidate"
    PROJECT_DIAGNOSIS = "project_diagnosis"
    REFERENCE_INSIGHT = "reference_insight"
    PROJECT_STATE = "project_state"
    IMPROVEMENT_ANALYSIS = "improvement_analysis"
    ENVIRONMENT_SYNC = "environment_sync"
    AUTONOMY_DECISION = "autonomy_decision"
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    EXECUTION_CONTEXT = "execution_context"
    LOG_EVENT = "log_event"


class MetadataSource(BaseModel):
    """Source that produced or owns a metadata payload."""

    model_config = ConfigDict(extra="forbid")

    source_type: str = "system"
    source_name: str = "openpilot"


class CorrelationInfo(BaseModel):
    """Stable IDs used to connect metadata across model-harness steps."""

    model_config = ConfigDict(extra="forbid")

    session_id: str | None = None
    turn_id: int | None = None
    task_id: str | None = None
    step_id: str | None = None
    execution_id: str | None = None


class MetadataBase(BaseModel):
    """Base class for every strict OpenPilot metadata payload."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True, validate_assignment=True)

    kind: MetadataKind
    schema_version: Literal["1.0"] = "1.0"
    source: MetadataSource = Field(default_factory=MetadataSource)
    correlation: CorrelationInfo = Field(default_factory=CorrelationInfo)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    annotations: dict[str, JsonValue] = Field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dict suitable for logs and model harnesses."""
        return self.model_dump(mode="json")

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        attributes = getattr(self, "attributes", None)
        if isinstance(attributes, dict):
            return attributes.get(key, default)
        return default

    def __getitem__(self, key: str) -> Any:
        value = self.get(key, None)
        if value is None and key not in self:
            raise KeyError(key)
        return value

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        if hasattr(self, key):
            return True
        attributes = getattr(self, "attributes", None)
        return isinstance(attributes, dict) and key in attributes


def ensure_metadata(value: Any, metadata_type: type[MetadataBase]) -> MetadataBase:
    """Validate a value as a concrete metadata type."""
    if isinstance(value, metadata_type):
        return value
    if isinstance(value, MetadataBase):
        raise TypeError(f"Expected {metadata_type.__name__}, got {type(value).__name__}")
    if isinstance(value, dict):
        return metadata_type.model_validate(value)
    raise TypeError(f"Expected {metadata_type.__name__}, got {type(value).__name__}")


def metadata_summary(value: Any) -> Any:
    """Return a compact JSON-safe representation for logging."""
    if isinstance(value, MetadataBase):
        return value.to_json_dict()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): metadata_summary(item) for key, item in value.items() if not str(key).startswith("_")}
    if isinstance(value, list):
        return [metadata_summary(item) for item in value[:20]]
    if isinstance(value, str) and len(value) > 1000:
        return value[:1000] + "...[truncated]"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
