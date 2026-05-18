"""Data processing stage for generated agents."""

from __future__ import annotations

import json
from typing import Any

from agent_generator.models import DataArtifact, DataArtifactKind, PipelineSpec, PipelineStep, Slot, SlotKind, StepStrategy
from tools.llm_summarizer import llm_summarizer_executor


MAX_PROCESSING_CONTEXT_CHARS = 18000


def process_data(
    task: str,
    slots: list[Slot],
    data: list[DataArtifact],
    *,
    llm_client: Any | None = None,
) -> tuple[list[DataArtifact], PipelineSpec]:
    """Process collected data into the user-requested final artifact."""
    cleaned_task = " ".join(task.strip().split())
    if not cleaned_task:
        raise ValueError("task must not be empty")
    if not data:
        raise ValueError("data must contain at least one artifact")

    processing = _summarize_slot_values([slot for slot in slots if slot.kind == SlotKind.PROCESSING])
    output_format = _summarize_slot_values([slot for slot in slots if slot.kind == SlotKind.FORMAT])
    if not processing:
        processing = "llm_summarizer_finalization"
    if not output_format:
        output_format = "user_requested_output"
    source_ids = [artifact.id for artifact in data]

    processing_context = _build_processing_context(cleaned_task, slots, data)
    processing_instruction = _build_processing_instruction(
        task=cleaned_task,
        slots=slots,
        output_format=output_format,
        processing=processing,
    )
    processing_tool = "llm_summarizer"
    processing_warning = ""
    summarizer_output: dict[str, Any] = {}
    try:
        params: dict[str, Any] = {
            "text": processing_context,
            "instruction": processing_instruction,
            "max_tokens": _processing_max_tokens(output_format),
        }
        if llm_client is not None:
            params["_llm_client"] = llm_client
        summarizer_output = llm_summarizer_executor(params)
        result_text = str(summarizer_output.get("summary") or "").strip()
        if not result_text:
            raise RuntimeError("llm_summarizer returned an empty summary")
    except Exception as exc:
        processing_tool = "rule_based_fallback"
        processing_warning = f"LLM processing failed; used rule-based fallback. Reason: {exc}"
        result_text = _fallback_result_text(
            task=cleaned_task,
            slots=slots,
            data=data,
            output_format=output_format,
        )

    content = {
        "task": cleaned_task,
        "processing_strategy": processing,
        "output_format": output_format,
        "result_format": output_format,
        "result_text": result_text,
        "processing_instruction": processing_instruction,
        "processing_tool": processing_tool,
        "input_artifacts": [artifact.model_dump(mode="json") for artifact in data],
    }
    if summarizer_output:
        content["summarizer_output"] = {
            "tokens_used": summarizer_output.get("tokens_used", 0),
            "model": summarizer_output.get("model", ""),
        }
    if processing_warning:
        content["warnings"] = [processing_warning]

    processed = DataArtifact(
        id="artifact_processed_result",
        name="Processed agent result",
        kind=DataArtifactKind.PROCESSED,
        content=content,
        source="agent_generator.data_processor",
        confidence=min(0.95, max(artifact.confidence for artifact in data) + (0.1 if not processing_warning else 0.0)),
        preview=_result_preview(result_text, output_format),
        lineage=source_ids,
    )

    step = PipelineStep(
        id="step_process_data",
        name="Process collected data",
        strategy=StepStrategy.LLM if processing_tool == "llm_summarizer" else StepStrategy.FUNCTION,
        inputs=source_ids + [slot.name for slot in slots],
        outputs=[processed.id],
        parameters={
            "function": "agent_generator.data_processor.process_data",
            "processing_tool": processing_tool,
            "processing_slots": [slot.model_dump(mode="json") for slot in slots if slot.kind == SlotKind.PROCESSING],
            "format_slots": [slot.model_dump(mode="json") for slot in slots if slot.kind == SlotKind.FORMAT],
            "result_format": output_format,
            "processing_warning": processing_warning or None,
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


def _build_processing_context(task: str, slots: list[Slot], data: list[DataArtifact]) -> str:
    payload = {
        "task": task,
        "slots": [
            {
                "name": slot.name,
                "kind": str(slot.kind),
                "value": slot.value,
                "description": slot.description,
                "revision_notes": slot.revision_notes,
            }
            for slot in slots
        ],
        "artifacts": [_compact_artifact_for_processing(artifact) for artifact in data],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)[:MAX_PROCESSING_CONTEXT_CHARS]


def _compact_artifact_for_processing(artifact: DataArtifact) -> dict[str, Any]:
    content = artifact.content if isinstance(artifact.content, dict) else {}
    result = {
        "id": artifact.id,
        "name": artifact.name,
        "kind": str(artifact.kind),
        "source": artifact.source,
        "confidence": artifact.confidence,
        "preview": artifact.preview,
    }
    if content.get("mode") == "web":
        output = content.get("tool_output") if isinstance(content.get("tool_output"), dict) else {}
        result["web"] = {
            "query": content.get("query") or output.get("query"),
            "provider": output.get("provider"),
            "effective_query": output.get("effective_query"),
            "research_summary": output.get("research_summary") or "",
            "key_points": output.get("key_points") or [],
            "source_notes": output.get("source_notes") or [],
            "top_results": (output.get("results") or [])[:5],
            "page_excerpts": [
                {
                    "title": page.get("title") or page.get("url"),
                    "url": page.get("url"),
                    "excerpt": str(page.get("content_excerpt") or "")[:1200],
                }
                for page in (output.get("pages") or [])
                if isinstance(page, dict) and page.get("content_excerpt")
            ][:4],
        }
    elif content.get("mode") == "file":
        output = content.get("tool_output") if isinstance(content.get("tool_output"), dict) else {}
        result["file"] = {
            "files": output.get("files") or content.get("files") or [],
            "content_excerpt": str(output.get("content") or "")[:5000],
        }
    else:
        result["content"] = content if content else str(artifact.content)[:5000]
    return result


def _build_processing_instruction(*, task: str, slots: list[Slot], output_format: str, processing: str) -> str:
    slot_lines = "\n".join(
        f"- {slot.name} ({slot.kind}): {slot.value if slot.value is not None else ''}"
        for slot in slots
        if slot.value is not None and str(slot.value).strip()
    )
    return (
        "You are the processing stage of an agent generator. Produce the final user-facing result, "
        "not a plan or metadata sketch.\n"
        f"Task: {task}\n"
        f"Requested output format: {output_format}\n"
        f"Processing preference: {processing}\n"
        "Respect the user's language and constraints from the slots. Use Markdown. "
        "Ground claims in the supplied collected data, cite source titles or URLs when useful, "
        "and avoid inventing facts that are not supported by the input.\n"
        "Slot values:\n"
        f"{slot_lines or '- none'}"
    )


def _processing_max_tokens(output_format: str) -> int:
    normalized = output_format.lower()
    if any(marker in normalized for marker in ("报告", "report", "方案", "plan", "详细", "detailed")):
        return 1600
    if any(marker in normalized for marker in ("列表", "资源", "list", "resources")):
        return 1200
    return 900


def _fallback_result_text(
    *,
    task: str,
    slots: list[Slot],
    data: list[DataArtifact],
    output_format: str,
) -> str:
    lines = [
        f"# {task}",
        "",
        f"目标输出格式：{output_format}",
        "",
    ]
    slot_values = [f"- {slot.name}: {slot.value}" for slot in slots if slot.value is not None and str(slot.value).strip()]
    if slot_values:
        lines.extend(["## 约束与偏好", *slot_values, ""])
    for artifact in data:
        lines.extend([f"## {artifact.name}", artifact.preview, ""])
        content = artifact.content if isinstance(artifact.content, dict) else {}
        if content.get("mode") == "web":
            output = content.get("tool_output") if isinstance(content.get("tool_output"), dict) else {}
            summary = str(output.get("research_summary") or "").strip()
            if summary:
                lines.extend(["### 摘要", summary, ""])
            key_points = output.get("key_points") or []
            if key_points:
                lines.append("### 要点")
                lines.extend(f"- {point}" for point in key_points[:8])
                lines.append("")
            source_notes = output.get("source_notes") or []
            if source_notes:
                lines.append("### 来源")
                for note in source_notes[:6]:
                    if isinstance(note, dict):
                        label = note.get("title") or note.get("source") or note.get("url") or "source"
                        text = note.get("note") or note.get("summary") or ""
                        lines.append(f"- {label}: {text}")
                    else:
                        lines.append(f"- {note}")
                lines.append("")
    return "\n".join(line for line in lines if line is not None).strip()


def _result_preview(result_text: str, output_format: str) -> str:
    excerpt = " ".join(result_text.split())
    if len(excerpt) > 180:
        excerpt = excerpt[:177] + "..."
    return f"Generated {output_format} result: {excerpt}"


def _summarize_slot_values(slots: list[Slot]) -> str:
    values = [str(slot.value).strip() for slot in slots if slot.value is not None and str(slot.value).strip()]
    if values:
        return "; ".join(values)
    names = [slot.name for slot in slots]
    return "; ".join(names)
