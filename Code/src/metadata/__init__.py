"""OpenPilot metadata protocol exports."""

from metadata.artifacts import (
    CodeArtifactMetadata,
    CommandArtifactMetadata,
    EmbeddingArtifactMetadata,
    FileArtifactMetadata,
    SearchArtifactMetadata,
    TextArtifactMetadata,
)
from metadata.base import (
    CorrelationInfo,
    JsonValue,
    MetadataBase,
    MetadataKind,
    MetadataSource,
    ensure_metadata,
    metadata_summary,
)
from metadata.bugfix import BugFixAttemptMetadata, BugFixResultMetadata
from metadata.data import CollectedDataMetadata, PresentationMetadata, ProcessedDataMetadata
from metadata.project import (
    AutonomyDecisionMetadata,
    EnvironmentSyncMetadata,
    ImprovementAnalysisMetadata,
    ProductIntentMetadata,
    ProjectStateMetadata,
    ValidationIssueMetadata,
)
from metadata.results import (
    ArtifactMetadata,
    FailureMetadata,
    ResultStatus,
    TaskResultMetadata,
    ToolResultMetadata,
    metadata_tool_result,
    payload_to_artifact,
    tool_result_payload,
)
from metadata.routing import ExecutionRoute, TaskRouteMetadata
from metadata.runtime import (
    AgentExecutionMetadata,
    ExecutionContextMetadata,
    LLMRequestMetadata,
    LLMResponseMetadata,
    LogEventMetadata,
    ModuleExecutionMetadata,
    ToolExecutionEnvelopeMetadata,
)
from metadata.tooling import (
    ToolChainMetadata,
    ToolContractMetadata,
    ToolInputMetadata,
    ToolSelectionMetadata,
    artifact_to_tool_input,
)
from metadata.warnings import WarningCheckResultMetadata, WarningItemMetadata

__all__ = [
    "ArtifactMetadata",
    "BugFixAttemptMetadata",
    "BugFixResultMetadata",
    "CodeArtifactMetadata",
    "CommandArtifactMetadata",
    "CorrelationInfo",
    "CollectedDataMetadata",
    "EmbeddingArtifactMetadata",
    "EnvironmentSyncMetadata",
    "ExecutionContextMetadata",
    "FailureMetadata",
    "FileArtifactMetadata",
    "AgentExecutionMetadata",
    "AutonomyDecisionMetadata",
    "ExecutionRoute",
    "ImprovementAnalysisMetadata",
    "JsonValue",
    "LLMRequestMetadata",
    "LLMResponseMetadata",
    "LogEventMetadata",
    "MetadataBase",
    "MetadataKind",
    "MetadataSource",
    "ModuleExecutionMetadata",
    "PresentationMetadata",
    "ProcessedDataMetadata",
    "ProductIntentMetadata",
    "ProjectStateMetadata",
    "payload_to_artifact",
    "ResultStatus",
    "SearchArtifactMetadata",
    "TaskResultMetadata",
    "TaskRouteMetadata",
    "TextArtifactMetadata",
    "ToolChainMetadata",
    "ToolContractMetadata",
    "ToolExecutionEnvelopeMetadata",
    "ToolInputMetadata",
    "ToolResultMetadata",
    "ToolSelectionMetadata",
    "ValidationIssueMetadata",
    "WarningCheckResultMetadata",
    "WarningItemMetadata",
    "artifact_to_tool_input",
    "ensure_metadata",
    "metadata_summary",
]
