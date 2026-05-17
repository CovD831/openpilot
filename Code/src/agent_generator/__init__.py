"""Agent Generator public API."""

from agent_generator.data_collector import collect_data
from agent_generator.data_presenter import present_data
from agent_generator.data_processor import process_data
from agent_generator.models import (
    DataArtifact,
    GeneratedAgentSpec,
    PipelineSpec,
    PipelineStep,
    Slot,
    SlotKind,
    StepStrategy,
)
from agent_generator.pipeline_combiner import combine_pipelines
from agent_generator.slot_generator import generate_slots

__all__ = [
    "DataArtifact",
    "GeneratedAgentSpec",
    "PipelineSpec",
    "PipelineStep",
    "Slot",
    "SlotKind",
    "StepStrategy",
    "collect_data",
    "combine_pipelines",
    "generate_slots",
    "present_data",
    "process_data",
]
