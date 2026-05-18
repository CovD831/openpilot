"""Interactive runner for the Agent Generator CLI command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent_generator.data_collector import collect_data
from agent_generator.data_presenter import present_data
from agent_generator.data_processor import process_data
from agent_generator.models import GeneratedAgentSpec, PipelineSpec, Slot
from agent_generator.pipeline_combiner import combine_pipelines
from agent_generator.slot_generator import generate_slots
from utils.input_utils import read_confirm, read_text


def run_agent_generator(
    task: str,
    *,
    console: Console | None = None,
    output_dir: str | Path | None = None,
    auto_approve: bool = False,
    llm_client = None,
    logger: Any | None = None,
) -> GeneratedAgentSpec:
    """Run the interactive Agent Generator flow."""
    console = console or Console()
    cleaned_task = " ".join(task.strip().split())
    if not cleaned_task:
        raise ValueError("task must not be empty")

    console.print()
    console.print(Panel(cleaned_task, title="[bold green]Agent Generator[/bold green]", border_style="green"))

    _log_agent_event(
        logger,
        phase="slot_generation",
        event_type="info",
        input_summary={"task": _truncate(cleaned_task, 240)},
    )
    slots = generate_slots(cleaned_task, llm_client=llm_client)
    _log_agent_event(
        logger,
        phase="slot_generation",
        event_type="info",
        success=True,
        output_summary=_slot_summary(slots),
    )
    _present_slots(slots, console)
    if _complete_empty_slots(slots, console, auto_approve):
        _present_slots(slots, console)
    slots = _review_slots(cleaned_task, slots, console, auto_approve, llm_client)
    _log_agent_event(
        logger,
        phase="slot_approval",
        event_type="info",
        success=True,
        output_summary=_slot_summary(slots),
    )

    collected_data, collection_pipeline = collect_data(
        cleaned_task,
        slots,
        llm_client=llm_client,
        logger=logger,
    )
    present_data(collected_data, console)
    collection_pipeline = _approve_or_retry_collection(
        cleaned_task,
        slots,
        collection_pipeline,
        collected_data,
        console,
        auto_approve,
        llm_client,
        logger,
    )

    processed_data, processing_pipeline = process_data(cleaned_task, slots, collected_data, llm_client=llm_client)
    present_data(processed_data, console)
    processing_pipeline = _approve_or_retry_processing(
        cleaned_task,
        slots,
        collected_data,
        processing_pipeline,
        processed_data,
        console,
        auto_approve,
        llm_client,
    )

    pipelines = [collection_pipeline, processing_pipeline]
    _present_pipelines(pipelines, console)
    if not _confirm(console, "Generate reusable Python agent from these pipelines?", auto_approve, default=True):
        raise RuntimeError("agent generation cancelled by user")

    spec = combine_pipelines(pipelines, output_dir=output_dir, artifacts=[*collected_data, *processed_data])
    _log_agent_event(
        logger,
        phase="agent_generation",
        event_type="info",
        success=True,
        output_summary={
            "agent_file": spec.agent_file,
            "pipeline_count": len(pipelines),
        },
    )
    console.print()
    console.print("[bold green]Generated agent file:[/bold green] " + spec.agent_file)
    console.print(
        "[dim]Reuse example:[/dim] "
        f"from {Path(spec.agent_file).stem} import run; result = run({slots[0].name}='...')"
    )
    console.print()
    return spec


def _present_slots(slots: list[Slot], console: Console) -> None:
    table = Table(title="Generated Slots", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Kind", style="magenta", no_wrap=True)
    table.add_column("Required", justify="center")
    table.add_column("Value", style="white")
    table.add_column("Description", style="dim")
    for slot in slots:
        table.add_row(
            slot.name,
            str(slot.kind),
            "yes" if slot.required else "no",
            str(slot.value),
            slot.description,
        )
    console.print()
    console.print(table)
    console.print()


def _present_pipelines(pipelines: list[PipelineSpec], console: Console) -> None:
    table = Table(title="Pipeline Summary", show_header=True, header_style="bold cyan")
    table.add_column("Pipeline", style="cyan")
    table.add_column("Purpose", style="white")
    table.add_column("Steps", justify="right")
    table.add_column("Approved", justify="center")
    for pipeline in pipelines:
        table.add_row(
            pipeline.name,
            pipeline.purpose,
            str(len(pipeline.steps)),
            "yes" if pipeline.approved else "no",
        )
    console.print()
    console.print(table)
    console.print()


def _review_slots(
    task: str,
    slots: list[Slot],
    console: Console,
    auto_approve: bool,
    llm_client = None,
) -> list[Slot]:
    while not _confirm(console, "Use these slots?", auto_approve, default=True):
        if _confirm(console, "Regenerate slots?", auto_approve, default=False):
            slots = generate_slots(task, llm_client=llm_client)
            _present_slots(slots, console)
            if _complete_empty_slots(slots, console, auto_approve):
                _present_slots(slots, console)
            continue
        _revise_slots(slots, console)
        _present_slots(slots, console)
    return slots


def _approve_or_retry_collection(
    task: str,
    slots: list[Slot],
    pipeline: PipelineSpec,
    data,
    console: Console,
    auto_approve: bool,
    llm_client = None,
    logger: Any | None = None,
) -> PipelineSpec:
    current_pipeline = pipeline
    while not _confirm(console, "Is the collected data satisfactory?", auto_approve, default=True):
        _add_feedback(slots, console, "collection")
        revised_data, current_pipeline = collect_data(task, slots, llm_client=llm_client, logger=logger)
        data[:] = revised_data
        present_data(data, console)
    return _mark_approved(current_pipeline)


def _approve_or_retry_processing(
    task: str,
    slots: list[Slot],
    collected_data,
    pipeline: PipelineSpec,
    data,
    console: Console,
    auto_approve: bool,
    llm_client = None,
) -> PipelineSpec:
    current_pipeline = pipeline
    while not _confirm(console, "Is the processed result satisfactory?", auto_approve, default=True):
        _add_feedback(slots, console, "processing")
        revised_data, current_pipeline = process_data(task, slots, collected_data, llm_client=llm_client)
        data[:] = revised_data
        present_data(data, console)
    return _mark_approved(current_pipeline)


def _mark_approved(pipeline: PipelineSpec) -> PipelineSpec:
    pipeline.approved = True
    for step in pipeline.steps:
        step.approved = True
    return pipeline


def _revise_slots(slots: list[Slot], console: Console) -> None:
    console.print("[dim]Enter slot revisions as name=value. Submit an empty line when done.[/dim]")
    while True:
        revision = read_text("slot revision> ")
        if not revision:
            return
        if "=" not in revision:
            console.print("[yellow]Use name=value format.[/yellow]")
            continue
        name, value = revision.split("=", 1)
        _set_slot_value(slots, name.strip(), value.strip(), "manual slot revision")


def _complete_empty_slots(slots: list[Slot], console: Console, auto_approve: bool) -> bool:
    empty_slots = [slot for slot in slots if _is_empty_slot_value(slot.value)]
    if not empty_slots:
        return False

    console.print("[yellow]Some generated slots are empty.[/yellow]")
    changed = False
    for slot in empty_slots:
        if auto_approve:
            console.print(f"[dim]{slot.name} skipped[/dim]")
            slot.revision_notes.append("Left empty during auto-approved slot completion.")
            changed = True
            continue
        prompt = f"{slot.name} ({slot.description}) [Enter to skip]> "
        value = read_text(prompt)
        if value:
            slot.value = value
            slot.revision_notes.append("Filled during empty-slot completion.")
        else:
            slot.revision_notes.append("User chose to keep this slot empty.")
        changed = True
    return changed


def _add_feedback(slots: list[Slot], console: Console, stage: str) -> None:
    feedback = read_text(f"{stage} feedback> ")
    if not feedback:
        feedback = f"User requested {stage} revision."
    for slot in slots:
        if slot.kind in {"data_source", "processing", "format", "constraint"}:
            slot.revision_notes.append(feedback)
    console.print("[dim]Feedback captured in reusable slot revision notes.[/dim]")


def _set_slot_value(slots: list[Slot], name: str, value: str, note: str) -> None:
    for slot in slots:
        if slot.name == name:
            slot.value = value
            slot.revision_notes.append(note)
            return


def _is_empty_slot_value(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or value.strip().lower() in {"none", "null"}
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _confirm(console: Console, prompt: str, auto_approve: bool, *, default: bool = True) -> bool:
    if auto_approve:
        value = "yes" if default else "no"
        console.print(f"[dim]{prompt} {value}[/dim]")
        return default
    return read_confirm(prompt, default=default)


def _slot_summary(slots: list[Slot]) -> dict[str, Any]:
    return {
        "slot_count": len(slots),
        "slots": [
            {
                "name": slot.name,
                "kind": str(slot.kind),
                "filled": not _is_empty_slot_value(slot.value),
                "required": slot.required,
            }
            for slot in slots
        ],
    }


def _log_agent_event(
    logger: Any | None,
    *,
    phase: str,
    event_type: str,
    success: bool | None = None,
    input_summary: Any | None = None,
    output_summary: Any | None = None,
    error: str | None = None,
) -> None:
    if not logger or not hasattr(logger, "log_structured_event"):
        return
    try:
        logger.log_structured_event(
            source_type="agent_generator",
            source_name="runner",
            phase=phase,
            event_type=event_type,
            session_id="agent_generator",
            turn_id=1,
            success=success,
            input_summary=input_summary,
            output_summary=output_summary,
            error=error,
            metadata={},
        )
    except Exception:
        pass


def _truncate(value: str, limit: int) -> str:
    cleaned = " ".join(str(value).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)] + "..."
