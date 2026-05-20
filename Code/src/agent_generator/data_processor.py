"""Data processing stage for generated agents."""

from __future__ import annotations

from typing import Any

from agent_generator.models import DataArtifact, DataArtifactKind, PipelineSpec, PipelineStep, Slot, SlotKind, StepStrategy
from tools.llm_summarizer import llm_summarizer_executor
from metadata import ToolInputMetadata, tool_result_payload


MAX_PROCESSING_CONTEXT_CHARS = 12000
MAX_RETRY_CONTEXT_CHARS = 6000


def process_data(
    task: str,
    slots: list[Slot],
    data: list[DataArtifact],
    *,
    llm_client: Any | None = None,
    logger: Any | None = None,
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
    summarizer_attempts: list[dict[str, Any]] = []
    try:
        summarizer_output = _run_summarizer_attempt(
            text=processing_context,
            instruction=processing_instruction,
            output_format=output_format,
            llm_client=llm_client,
        )
        summarizer_attempts.append(_summarizer_attempt_summary("full_context", summarizer_output))
        result_text = str(summarizer_output.get("summary") or "").strip()
        if not result_text:
            retry_context = _build_retry_processing_context(cleaned_task, slots, data)
            retry_instruction = _build_retry_processing_instruction(
                task=cleaned_task,
                slots=slots,
                output_format=output_format,
                processing=processing,
            )
            summarizer_output = _run_summarizer_attempt(
                text=retry_context,
                instruction=retry_instruction,
                output_format=output_format,
                llm_client=llm_client,
            )
            summarizer_attempts.append(_summarizer_attempt_summary("short_retry", summarizer_output))
            result_text = str(summarizer_output.get("summary") or "").strip()
        if not result_text:
            raise RuntimeError(_empty_summarizer_warning(summarizer_attempts))
    except Exception as exc:
        if not summarizer_attempts:
            summarizer_attempts.append({"attempt": "full_context", "error": str(exc)})
        processing_tool = "rule_based_fallback"
        processing_warning = f"LLM processing failed; used rule-based fallback. Reason: {_truncate(str(exc), 300)}"
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
    if summarizer_attempts:
        content["summarizer_output"] = {
            "tokens_used": summarizer_output.get("tokens_used", 0),
            "model": summarizer_output.get("model", ""),
            "finish_reason": summarizer_output.get("finish_reason"),
            "response_chars": summarizer_output.get("response_chars", 0),
            "prompt_chars": summarizer_output.get("prompt_chars", 0),
            "attempts": summarizer_attempts,
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
            "processing_retry_count": max(0, len(summarizer_attempts) - 1),
            "result_text_chars": len(result_text),
        },
        approved=False,
    )
    _log_processing_event(
        logger,
        processing_tool=processing_tool,
        result_text=result_text,
        warning=processing_warning,
        attempts=summarizer_attempts,
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
    return _build_evidence_brief(task, slots, data, excerpt_limit=700, max_pages=4, max_chars=MAX_PROCESSING_CONTEXT_CHARS)


def _build_retry_processing_context(task: str, slots: list[Slot], data: list[DataArtifact]) -> str:
    return _build_evidence_brief(task, slots, data, excerpt_limit=360, max_pages=2, max_chars=MAX_RETRY_CONTEXT_CHARS)


def _run_summarizer_attempt(
    *,
    text: str,
    instruction: str,
    output_format: str,
    llm_client: Any | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "text": text,
        "instruction": instruction,
        "max_tokens": _processing_max_tokens(output_format),
    }
    if llm_client is not None:
        params["_llm_client"] = llm_client
    return tool_result_payload(llm_summarizer_executor(ToolInputMetadata.from_mapping("llm_summarizer", params)))


def _summarizer_attempt_summary(name: str, output: dict[str, Any]) -> dict[str, Any]:
    internal_attempts = output.get("attempts") if isinstance(output.get("attempts"), list) else []
    last_attempt = internal_attempts[-1] if internal_attempts and isinstance(internal_attempts[-1], dict) else {}
    return {
        "attempt": name,
        "model": output.get("model", ""),
        "tokens_used": output.get("tokens_used", 0),
        "finish_reason": output.get("finish_reason"),
        "response_chars": output.get("response_chars", len(str(output.get("summary") or ""))),
        "prompt_chars": output.get("prompt_chars", 0),
        "max_tokens": last_attempt.get("max_tokens"),
        "summarizer_attempts": internal_attempts,
    }


def _empty_summarizer_warning(attempts: list[dict[str, Any]]) -> str:
    parts = []
    for attempt in attempts:
        parts.append(
            "{attempt}: model={model} finish_reason={finish_reason} response_chars={response_chars} "
            "prompt_chars={prompt_chars} max_tokens={max_tokens}".format(
                attempt=attempt.get("attempt", "unknown"),
                model=attempt.get("model", ""),
                finish_reason=attempt.get("finish_reason"),
                response_chars=attempt.get("response_chars", 0),
                prompt_chars=attempt.get("prompt_chars", 0),
                max_tokens=attempt.get("max_tokens", ""),
            )
        )
    if any(attempt.get("finish_reason") == "length" for attempt in attempts):
        return f"empty length response after {len(attempts)} attempt(s); " + "; ".join(parts)
    return f"empty response after {len(attempts)} attempt(s); " + "; ".join(parts)


def _build_evidence_brief(
    task: str,
    slots: list[Slot],
    data: list[DataArtifact],
    *,
    excerpt_limit: int,
    max_pages: int,
    max_chars: int,
) -> str:
    lines = [
        "# Processing Evidence Brief",
        "",
        f"Task: {task}",
        "",
    ]
    slot_lines = [
        f"- {slot.name} ({slot.kind}): {slot.value}"
        for slot in slots
        if slot.value is not None and str(slot.value).strip()
    ]
    if slot_lines:
        lines.extend(["## User Slots", *slot_lines, ""])

    for artifact in data:
        lines.extend([f"## Artifact: {artifact.name}", f"- Source: {artifact.source}", f"- Preview: {artifact.preview}", ""])
        content = artifact.content if isinstance(artifact.content, dict) else {}
        if content.get("mode") == "web":
            output = content.get("tool_output") if isinstance(content.get("tool_output"), dict) else {}
            summary = str(output.get("research_summary") or "").strip()
            if summary:
                lines.extend(["### Research Summary", _clip(summary, 1800), ""])
            key_points = [str(point).strip() for point in (output.get("key_points") or []) if str(point).strip()]
            if key_points:
                lines.append("### Key Points")
                lines.extend(f"- {_clip(point, 260)}" for point in key_points[:10])
                lines.append("")
            source_notes = output.get("source_notes") or []
            if source_notes:
                lines.append("### Source Notes")
                for note in source_notes[:6]:
                    if isinstance(note, dict):
                        label = note.get("title") or note.get("source") or note.get("url") or "source"
                        text = note.get("note") or note.get("summary") or ""
                        lines.append(f"- {_clip(str(label), 120)}: {_clip(str(text), 260)}")
                    else:
                        lines.append(f"- {_clip(str(note), 320)}")
                lines.append("")
            results = output.get("results") or []
            if results:
                lines.append("### Top Sources")
                for result in results[:5]:
                    if not isinstance(result, dict):
                        continue
                    title = result.get("title") or result.get("url") or "source"
                    url = result.get("url") or ""
                    snippet = result.get("snippet") or ""
                    lines.append(f"- {_clip(str(title), 140)}")
                    if url:
                        lines.append(f"  URL: {url}")
                    if snippet:
                        lines.append(f"  Note: {_clip(str(snippet), 280)}")
                lines.append("")
            pages = output.get("pages") or []
            excerpts = [page for page in pages if isinstance(page, dict) and page.get("content_excerpt")]
            if excerpts:
                lines.append("### Page Excerpts")
                for page in excerpts[:max_pages]:
                    title = page.get("title") or page.get("url") or "page"
                    url = page.get("url") or ""
                    lines.append(f"- {_clip(str(title), 140)}" + (f" ({url})" if url else ""))
                    lines.append(f"  {_clip(str(page.get('content_excerpt') or ''), excerpt_limit)}")
                lines.append("")
        elif content.get("mode") == "file":
            output = content.get("tool_output") if isinstance(content.get("tool_output"), dict) else {}
            file_excerpt = str(output.get("content") or "")[: min(excerpt_limit * 4, 2500)]
            if file_excerpt:
                lines.extend(["### File Excerpt", file_excerpt, ""])
        else:
            lines.extend(["### Content", _clip(str(artifact.content), min(excerpt_limit * 3, 2400)), ""])

    return _clip("\n".join(line for line in lines if line is not None).strip(), max_chars)


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


def _compact_artifact_for_retry(artifact: DataArtifact) -> dict[str, Any]:
    content = artifact.content if isinstance(artifact.content, dict) else {}
    result = {
        "name": artifact.name,
        "preview": artifact.preview,
        "source": artifact.source,
    }
    if content.get("mode") != "web":
        result["content"] = str(artifact.content)[:2200]
        return result
    output = content.get("tool_output") if isinstance(content.get("tool_output"), dict) else {}
    result["web"] = {
        "query": content.get("query") or output.get("query"),
        "research_summary": output.get("research_summary") or "",
        "key_points": output.get("key_points") or [],
        "top_results": (output.get("results") or [])[:5],
        "page_excerpts": [
            {
                "title": page.get("title") or page.get("url"),
                "url": page.get("url"),
                "excerpt": str(page.get("content_excerpt") or "")[:800],
            }
            for page in (output.get("pages") or [])
            if isinstance(page, dict) and page.get("content_excerpt")
        ][:2],
    }
    return result


def _build_processing_instruction(*, task: str, slots: list[Slot], output_format: str, processing: str) -> str:
    slot_lines = "\n".join(
        f"- {slot.name} ({slot.kind}): {slot.value if slot.value is not None else ''}"
        for slot in slots
        if slot.value is not None and str(slot.value).strip()
    )
    return (
        "You are the processing stage of an agent generator. Produce the final user-facing result, "
        "not a plan or internal notes sketch.\n"
        f"Task: {task}\n"
        f"Requested output format: {output_format}\n"
        f"Processing preference: {processing}\n"
        "Respect the user's language and constraints from the slots. Use Markdown. "
        "Write the final answer directly; do not include internal reasoning, planning notes, or schema notes. "
        "Ground claims in the supplied collected data, cite source titles or URLs when useful, "
        "and avoid inventing facts that are not supported by the input.\n"
        "Slot values:\n"
        f"{slot_lines or '- none'}"
    )


def _build_retry_processing_instruction(*, task: str, slots: list[Slot], output_format: str, processing: str) -> str:
    base = _build_processing_instruction(task=task, slots=slots, output_format=output_format, processing=processing)
    return (
        f"{base}\n\n"
        "The previous attempt returned an empty response. You must return non-empty Markdown now. "
        "If the supplied evidence is incomplete, state the limitation briefly and still produce the best supported "
        "result in the requested output format."
    )


def _processing_max_tokens(output_format: str) -> int:
    normalized = output_format.lower()
    if any(marker in normalized for marker in ("报告", "report", "方案", "plan", "详细", "detailed")):
        return 2600
    if any(marker in normalized for marker in ("列表", "资源", "list", "resources")):
        return 1800
    return 1400


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
        "## 处理说明",
        "LLM 处理阶段未返回可用正文，以下内容由已收集证据自动整理生成，供继续判断和修订。",
        "",
    ]
    slot_values = [f"- {slot.name}: {slot.value}" for slot in slots if slot.value is not None and str(slot.value).strip()]
    if slot_values:
        lines.extend(["## 约束与偏好", *slot_values, ""])
    for artifact in data:
        lines.extend([f"## 可用证据：{artifact.name}", artifact.preview, ""])
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
            results = output.get("results") or []
            if results:
                lines.append("### 参考链接")
                for result in results[:5]:
                    if not isinstance(result, dict):
                        continue
                    title = result.get("title") or result.get("url") or "source"
                    url = result.get("url") or ""
                    snippet = result.get("snippet") or ""
                    link_text = f"- {title}"
                    if url:
                        link_text += f": {url}"
                    lines.append(link_text)
                    if snippet:
                        lines.append(f"  - {_clip(str(snippet), 240)}")
                lines.append("")
            pages = output.get("pages") or []
            excerpts = [page for page in pages if isinstance(page, dict) and page.get("content_excerpt")]
            if excerpts:
                lines.append("### 页面摘录")
                for page in excerpts[:3]:
                    title = page.get("title") or page.get("url") or "page"
                    url = page.get("url") or ""
                    lines.append(f"- {title}" + (f": {url}" if url else ""))
                    lines.append(f"  - {_clip(str(page.get('content_excerpt') or ''), 260)}")
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
    lines.extend(
        [
            "## 资料限制",
            "- 该结果是 fallback 汇总，不代表 LLM 已完成最终改写。",
            "- 建议重新运行处理阶段或调整模型输出 token 预算后生成正式版本。",
        ]
    )
    return "\n".join(line for line in lines if line is not None).strip()


def _result_preview(result_text: str, output_format: str) -> str:
    excerpt = " ".join(result_text.split())
    if len(excerpt) > 180:
        excerpt = excerpt[:177] + "..."
    return f"Generated {output_format} result: {excerpt}"


def _clip(value: str, limit: int) -> str:
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _truncate(value: str, limit: int) -> str:
    cleaned = " ".join(str(value).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)] + "..."


def _log_processing_event(
    logger: Any | None,
    *,
    processing_tool: str,
    result_text: str,
    warning: str,
    attempts: list[dict[str, Any]],
) -> None:
    if not logger or not hasattr(logger, "log_structured_event"):
        return
    try:
        logger.log_structured_event(
            source_type="agent_generator",
            source_name="data_processor",
            phase="data_processing",
            event_type="warning" if warning else "info",
            session_id="agent_generator",
            turn_id=1,
            success=not bool(warning),
            input_summary={
                "attempt_count": len(attempts),
                "used_retry": len(attempts) > 1,
                "used_summarizer_internal_retry": any(
                    len(attempt.get("summarizer_attempts") or []) > 1 for attempt in attempts
                ),
            },
            output_summary={
                "processing_tool": processing_tool,
                "fallback_used": processing_tool == "rule_based_fallback",
                "result_text_chars": len(result_text),
                "warning": _truncate(warning, 240) if warning else None,
                "attempts": attempts,
            },
            error=warning or None,
            annotations={},
        )
    except Exception:
        pass


def _summarize_slot_values(slots: list[Slot]) -> str:
    values = [str(slot.value).strip() for slot in slots if slot.value is not None and str(slot.value).strip()]
    if values:
        return "; ".join(values)
    names = [slot.name for slot in slots]
    return "; ".join(names)
