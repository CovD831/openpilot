"""Contracts for the Agent Generator module."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SlotKind(str, Enum):
    """Kinds of reusable user-demand placeholders."""

    TASK = "task"
    CONSTRAINT = "constraint"
    DATA_SOURCE = "data_source"
    FORMAT = "format"
    PROCESSING = "processing"
    INTERACTION = "interaction"


class DataArtifactKind(str, Enum):
    """Kinds of data artifacts produced by the generator."""

    COLLECTED = "collected"
    PROCESSED = "processed"
    PREVIEW = "preview"


class StepStrategy(str, Enum):
    """Replay strategy for a pipeline step."""

    TOOL = "tool"
    LLM = "llm"
    FUNCTION = "function"
    MIXED = "mixed"


class Slot(BaseModel):
    """A typed placeholder that can be revised and reused."""

    name: str
    kind: SlotKind
    description: str
    value: Any = None
    required: bool = True
    revision_notes: list[str] = Field(default_factory=list)

    model_config = ConfigDict(use_enum_values=True)


class DataArtifact(BaseModel):
    """Collected or processed data plus presentation metadata."""

    id: str
    name: str
    kind: DataArtifactKind
    content: Any
    source: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    preview: str
    lineage: list[str] = Field(default_factory=list)

    model_config = ConfigDict(use_enum_values=True)


class PipelineStep(BaseModel):
    """One replayable stage in a generated agent pipeline."""

    id: str
    name: str
    strategy: StepStrategy
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False

    model_config = ConfigDict(use_enum_values=True)


class PipelineSpec(BaseModel):
    """Ordered pipeline returned by collection or processing."""

    id: str
    name: str
    purpose: str
    steps: list[PipelineStep] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    approved: bool = False
    task_summary: str = ""
    slots: list[Slot] = Field(default_factory=list)


class GeneratedAgentSpec(BaseModel):
    """Final reusable Python agent definition."""

    name: str
    task_summary: str
    slots: list[Slot] = Field(default_factory=list)
    pipelines: list[PipelineSpec] = Field(default_factory=list)
    artifacts: list[DataArtifact] = Field(default_factory=list)
    entry_function: str = "run"
    dependencies: list[str] = Field(default_factory=list)
    agent_file: str
