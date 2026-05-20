"""Data-flow metadata exchanged by generated agents and presentation stages."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SerializeAsAny

from metadata.artifacts import (
    CodeArtifactMetadata,
    CommandArtifactMetadata,
    EmbeddingArtifactMetadata,
    FileArtifactMetadata,
    SearchArtifactMetadata,
    TextArtifactMetadata,
)
from metadata.base import JsonValue, MetadataBase, MetadataKind
from metadata.results import ToolResultMetadata


ArtifactPayloadMetadata = (
    TextArtifactMetadata
    | CodeArtifactMetadata
    | FileArtifactMetadata
    | CommandArtifactMetadata
    | SearchArtifactMetadata
    | EmbeddingArtifactMetadata
)


class CollectedDataMetadata(MetadataBase):
    kind: Literal[MetadataKind.COLLECTED_DATA] = MetadataKind.COLLECTED_DATA
    mode: str
    task: str
    tool_name: str
    query: str = ""
    files: list[str] = Field(default_factory=list)
    slot_values: dict[str, JsonValue] = Field(default_factory=dict)
    artifact: SerializeAsAny[MetadataBase]
    tool_result: ToolResultMetadata | None = None
    cleanup_fallback_warning: str | None = None


class ProcessedDataMetadata(MetadataBase):
    kind: Literal[MetadataKind.PROCESSED_DATA] = MetadataKind.PROCESSED_DATA
    task: str
    processing_strategy: str
    output_format: str
    result_format: str
    result_text: str
    processing_instruction: str = ""
    processing_tool: str
    input_artifacts: list[SerializeAsAny[MetadataBase]] = Field(default_factory=list)
    summarizer_result: ToolResultMetadata | None = None
    summarizer_output: dict[str, JsonValue] = Field(default_factory=dict)
    summarizer_attempts: list[dict[str, JsonValue]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PresentationMetadata(MetadataBase):
    kind: Literal[MetadataKind.PRESENTATION] = MetadataKind.PRESENTATION
    title: str = ""
    rendered_text: str = ""
    output_format: str = ""
    source_artifacts: list[str] = Field(default_factory=list)
    presentation_style: str = "markdown"
