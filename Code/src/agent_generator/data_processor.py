"""Data processing stage for generated agents."""

from __future__ import annotations

from agent_generator.models import DataArtifact, DataArtifactKind, PipelineSpec, PipelineStep, Slot, SlotKind, StepStrategy


def process_data(
    task: str,
    slots: list[Slot],
    data: list[DataArtifact],
) -> tuple[list[DataArtifact], PipelineSpec]:
    """Process collected data and return processed artifacts plus pipeline."""
    cleaned_task = " ".join(task.strip().split())
    if not cleaned_task:
        raise ValueError("task must not be empty")
    if not data:
        raise ValueError("data must contain at least one artifact")

    slot_values = {slot.name: slot.value for slot in slots}
    processing = _summarize_slot_values([slot for slot in slots if slot.kind == SlotKind.PROCESSING])
    output_format = _summarize_slot_values([slot for slot in slots if slot.kind == SlotKind.FORMAT])
    if not processing:
        processing = "llm_generated_processing_plan"
    if not output_format:
        output_format = "slot_defined_output"
    source_ids = [artifact.id for artifact in data]

    processed = DataArtifact(
        id="artifact_processed_result",
        name="Processed agent result sketch",
        kind=DataArtifactKind.PROCESSED,
        content={
            "task": cleaned_task,
            "processing_strategy": processing,
            "output_format": output_format,
            "input_artifacts": [artifact.model_dump(mode="json") for artifact in data],
        },
        source="agent_generator.data_processor",
        confidence=min(0.95, max(artifact.confidence for artifact in data) + 0.1),
        preview=(
            f"Processed {len(data)} artifact(s) using {processing}; "
            f"target output format is {output_format}."
        ),
        lineage=source_ids,
    )

    step = PipelineStep(
        id="step_process_data",
        name="Process collected data",
        strategy=StepStrategy.FUNCTION,
        inputs=source_ids + [slot.name for slot in slots],
        outputs=[processed.id],
        parameters={
            "function": "agent_generator.data_processor.process_data",
            "processing_slots": [slot.model_dump(mode="json") for slot in slots if slot.kind == SlotKind.PROCESSING],
            "format_slots": [slot.model_dump(mode="json") for slot in slots if slot.kind == SlotKind.FORMAT],
        },
        approved=False,
    )
    pipeline = PipelineSpec(
        id="pipeline_data_processing",
        name="Data processing pipeline",
        purpose="Transform collected data into reusable agent output behavior.",
        steps=[step],
        artifacts=[processed.id],
        approved=False,
        task_summary=cleaned_task,
        slots=slots,
    )
    return [processed], pipeline


def _summarize_slot_values(slots: list[Slot]) -> str:
    values = [str(slot.value).strip() for slot in slots if slot.value is not None and str(slot.value).strip()]
    if values:
        return "; ".join(values)
    names = [slot.name for slot in slots]
    return "; ".join(names)
