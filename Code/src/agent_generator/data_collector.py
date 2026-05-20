"""Data collection stage for generated agents."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_generator.models import DataArtifact, DataArtifactKind, PipelineSpec, PipelineStep, Slot, StepStrategy
from tools.file_reader import file_reader_executor
from tools.multi_file_reader import multi_file_reader_executor
from tools.web_searcher import web_searcher_executor
from metadata import ToolInputMetadata, tool_result_payload


def collect_data(
    task: str,
    slots: list[Slot],
    *,
    llm_client: Any | None = None,
    max_results: int = 5,
    max_pages: int = 3,
    logger: Any | None = None,
) -> tuple[list[DataArtifact], PipelineSpec]:
    """Collect concrete task data from user files or the public web."""
    cleaned_task = " ".join(task.strip().split())
    if not cleaned_task:
        raise ValueError("task must not be empty")

    _log_agent_event(
        logger,
        phase="data_collection",
        event_type="info",
        input_summary={
            "task": _truncate(cleaned_task, 240),
            "slot_count": len(slots),
            "filled_slot_count": sum(0 if _is_empty_value(slot.value) else 1 for slot in slots),
        },
    )
    try:
        file_paths = _find_existing_file_paths(slots)
        if file_paths:
            artifact, step = _collect_from_files(cleaned_task, slots, file_paths, logger=logger)
        else:
            artifact, step = _collect_from_web(
                cleaned_task,
                slots,
                llm_client=llm_client,
                max_results=max_results,
                max_pages=max_pages,
                logger=logger,
            )
    except Exception as exc:
        _log_agent_event(
            logger,
            phase="data_collection",
            event_type="error",
            success=False,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise

    pipeline = PipelineSpec(
        id="pipeline_data_collection",
        name="Data collection pipeline",
        purpose="Collect data required to build the generated agent.",
        steps=[step],
        artifacts=[artifact.id],
        approved=False,
        task_summary=cleaned_task,
        slots=slots,
    )
    _log_agent_event(
        logger,
        phase="data_collection",
        event_type="info",
        success=True,
        output_summary={
            "artifact_ids": [artifact.id],
            "step_ids": [step.id],
            "strategy": str(step.strategy),
            "selected_tool": step.parameters.get("selected_tool"),
        },
    )
    return [artifact], pipeline


def _collect_from_files(
    task: str,
    slots: list[Slot],
    file_paths: list[Path],
    *,
    logger: Any | None = None,
) -> tuple[DataArtifact, PipelineStep]:
    if len(file_paths) == 1:
        params = {
            "file_path": str(file_paths[0]),
            "read_mode": "adaptive",
            "max_lines": 200,
            "max_size_mb": 10,
        }
        output = tool_result_payload(file_reader_executor(ToolInputMetadata.from_mapping("file_reader", params)))
        selected_tool = "file_reader"
        files = [str(file_paths[0])]
    else:
        params = {
            "file_paths": [str(path) for path in file_paths],
            "encoding": "utf-8",
            "max_total_chars": 50000,
        }
        output = tool_result_payload(multi_file_reader_executor(ToolInputMetadata.from_mapping("multi_file_reader", params)))
        selected_tool = "multi_file_reader"
        files = output.get("files", [str(path) for path in file_paths])

    _log_agent_event(
        logger,
        phase="file_collection",
        event_type="info",
        success=True,
        input_summary={"selected_tool": selected_tool, "file_count": len(files)},
    )

    content = {
        "mode": "file",
        "task": task,
        "tool": selected_tool,
        "files": files,
        "tool_output": output,
        "slot_values": _slot_values(slots),
    }
    text = str(output.get("content", ""))
    preview = f"Read {len(files)} file(s). Content excerpt: {_truncate(text, 180)}"
    artifact = DataArtifact(
        id="artifact_collected_files",
        name="Collected file data",
        kind=DataArtifactKind.COLLECTED,
        content=content,
        source=", ".join(files),
        confidence=0.9,
        preview=preview,
        lineage=[slot.name for slot in slots],
    )
    step = PipelineStep(
        id="step_collect_files",
        name="Collect data from user files",
        strategy=StepStrategy.TOOL,
        inputs=[slot.name for slot in slots],
        outputs=[artifact.id],
        parameters={
            "selected_tool": selected_tool,
            "tool_input": params,
            "file_paths": files,
        },
        approved=False,
    )
    return artifact, step


def _collect_from_web(
    task: str,
    slots: list[Slot],
    *,
    llm_client: Any | None,
    max_results: int,
    max_pages: int,
    logger: Any | None = None,
) -> tuple[DataArtifact, PipelineStep]:
    query = _build_search_query(task, slots)
    llm_cleanup_requested = llm_client is not None
    params: dict[str, Any] = {
        "query": query,
        "max_results": max_results,
        "max_pages": max_pages,
        "max_page_chars": 4000,
        "llm_cleanup": llm_cleanup_requested,
        "_cleanup_failure_policy": "return_raw",
        "cleanup_instruction": (
            "Organize the findings for an agent-generation data preview. "
            "Keep concrete facts, source-specific notes, and follow-up query suggestions."
        ),
    }
    if llm_client is not None:
        params["_llm_client"] = llm_client

    _log_agent_event(
        logger,
        phase="web_collection",
        event_type="info",
        input_summary={
            "query": _truncate(query, 300),
            "max_results": max_results,
            "max_pages": max_pages,
            "llm_cleanup_requested": llm_cleanup_requested,
        },
    )
    if llm_cleanup_requested:
        _log_agent_event(logger, phase="web_cleanup", event_type="info", input_summary={"query": _truncate(query, 300)})

    output, cleanup_fallback_warning = _execute_web_search_with_cleanup_fallback(params, logger=logger)
    _raise_for_unusable_web_search_output(output)
    content = {
        "mode": "web",
        "task": task,
        "tool": "web_searcher",
        "query": query,
        "tool_output": output,
        "slot_values": _slot_values(slots),
    }
    source = f"web_search:{query}"
    key_points = output.get("key_points") or []
    summary = output.get("research_summary") or ""
    if key_points:
        preview = f"Web search found {output.get('count', 0)} result(s). First point: {_truncate(str(key_points[0]), 160)}"
    elif summary:
        preview = f"Web search found {output.get('count', 0)} result(s). Summary: {_truncate(summary, 160)}"
    else:
        preview = f"Web search found {output.get('count', 0)} result(s) for query: {query}"

    artifact = DataArtifact(
        id="artifact_collected_web",
        name="Collected web research data",
        kind=DataArtifactKind.COLLECTED,
        content=content,
        source=source,
        confidence=0.75 if output.get("count", 0) else 0.45,
        preview=preview,
        lineage=[slot.name for slot in slots],
    )
    step = PipelineStep(
        id="step_collect_web",
        name="Collect data from web search",
        strategy=StepStrategy.MIXED if llm_client is not None else StepStrategy.TOOL,
        inputs=[slot.name for slot in slots],
        outputs=[artifact.id],
        parameters={
            "selected_tool": "web_searcher",
            "selected_strategy": str(StepStrategy.MIXED if llm_client is not None else StepStrategy.TOOL),
            "tool_input": {key: value for key, value in params.items() if not key.startswith("_")},
            "llm_cleanup": llm_cleanup_requested,
            "llm_cleanup_requested": llm_cleanup_requested,
            "llm_cleanup_executed": bool(output.get("llm_cleanup")),
            "cleanup_fallback_warning": cleanup_fallback_warning,
            "query": query,
            "result_count": output.get("count", 0),
            "produced_artifact_ids": [artifact.id],
        },
        approved=False,
    )
    return artifact, step


def _execute_web_search_with_cleanup_fallback(
    params: dict[str, Any],
    *,
    logger: Any | None = None,
) -> tuple[dict[str, Any], str | None]:
    try:
        output = tool_result_payload(web_searcher_executor(ToolInputMetadata.from_mapping("web_searcher", params)))
        cleanup_fallback_warning = _cleanup_fallback_warning(output)
        _log_agent_event(
            logger,
            phase="web_cleanup" if params.get("llm_cleanup") else "web_collection",
            event_type="warning" if cleanup_fallback_warning else "info",
            success=not bool(cleanup_fallback_warning),
            output_summary={
                "result_count": output.get("count", 0),
                "page_count": len(output.get("pages") or []),
                "llm_cleanup_executed": bool(output.get("llm_cleanup")),
                "warning": cleanup_fallback_warning,
            },
            error=output.get("llm_cleanup_error"),
        )
        return output, cleanup_fallback_warning
    except RuntimeError as exc:
        if not params.get("llm_cleanup") or not _is_socks_dependency_error(exc):
            raise
        fallback_params = dict(params)
        fallback_params["llm_cleanup"] = False
        fallback_params.pop("_llm_client", None)
        output = tool_result_payload(web_searcher_executor(ToolInputMetadata.from_mapping("web_searcher", fallback_params)))
        warning = (
            "LLM cleanup disabled because the current SOCKS proxy setup is missing "
            "the socksio dependency. Install with: conda install -n openpilot -c conda-forge socksio."
        )
        warnings = output.setdefault("warnings", [])
        if isinstance(warnings, list):
            warnings.append(warning)
        _log_agent_event(
            logger,
            phase="web_cleanup",
            event_type="warning",
            success=False,
            output_summary={
                "result_count": output.get("count", 0),
                "page_count": len(output.get("pages") or []),
                "llm_cleanup_executed": False,
                "warning": warning,
            },
            error=f"{type(exc).__name__}: {exc}",
        )
        return output, warning


def _raise_for_unusable_web_search_output(output: dict[str, Any]) -> None:
    if int(output.get("count", 0) or 0) != 0:
        return
    attempts = output.get("search_attempts")
    if not isinstance(attempts, list) or not attempts:
        return
    failure_statuses = {"network_error", "blocked", "timeout"}
    if any(str(attempt.get("status", "")) not in failure_statuses for attempt in attempts if isinstance(attempt, dict)):
        return

    diagnostics = output.get("network_diagnostics") if isinstance(output.get("network_diagnostics"), dict) else {}
    proxy_vars = diagnostics.get("proxy_env_vars") or []
    proxy_hint = (
        f"Detected proxy env vars: {', '.join(str(name) for name in proxy_vars)}."
        if proxy_vars
        else "No HTTP_PROXY/HTTPS_PROXY/ALL_PROXY env vars were detected."
    )
    attempt_lines = []
    for attempt in attempts[:6]:
        if not isinstance(attempt, dict):
            continue
        provider = str(attempt.get("provider", "unknown"))
        query = _truncate(str(attempt.get("query", "")), 80)
        status = str(attempt.get("status", "unknown"))
        error = _truncate(str(attempt.get("error", "")), 180)
        attempt_lines.append(f"- {provider} query={query!r} status={status} error={error}")
    detail = "\n".join(attempt_lines)
    raise RuntimeError(
        "Web search could not reach usable Google/Bing results. This looks like a network, proxy, "
        "timeout, or search-provider blocking problem rather than an empty query result.\n\n"
        f"{proxy_hint}\n"
        "Check the shell that starts OpenPilot and make sure it inherits HTTP_PROXY, HTTPS_PROXY, "
        "or ALL_PROXY, or add standard proxy variables to .env.\n\n"
        f"Attempts:\n{detail}"
    )


def _is_socks_dependency_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "socks proxy" in text and ("socksio" in text or "httpx[socks]" in text)


def _cleanup_fallback_warning(output: dict[str, Any]) -> str | None:
    cleanup_error = output.get("llm_cleanup_error")
    if cleanup_error:
        warnings = output.get("warnings")
        if isinstance(warnings, list):
            for warning in warnings:
                if "LLM cleanup failed" in str(warning):
                    return str(warning)
        return f"LLM cleanup failed, so Agent Generator continued with raw web search results. Reason: {cleanup_error}"
    return None


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
            source_name="data_collector",
            phase=phase,
            event_type=event_type,
            session_id="agent_generator",
            turn_id=1,
            success=success,
            input_summary=_json_safe_summary(input_summary),
            output_summary=_json_safe_summary(output_summary),
            error=error,
            annotations={},
        )
    except Exception:
        pass


def _json_safe_summary(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe_summary(item) for key, item in value.items() if not str(key).startswith("_")}
    if isinstance(value, list):
        return [_json_safe_summary(item) for item in value[:20]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > 1000:
            return value[:1000] + "...[truncated]"
        return value
    return str(value)


def _find_existing_file_paths(slots: list[Slot]) -> list[Path]:
    candidates: list[Path] = []
    for slot in slots:
        for value in _flatten_values(slot.value):
            if not isinstance(value, str):
                continue
            for part in _split_path_candidates(value):
                path = Path(part).expanduser()
                if path.exists():
                    if path.is_file():
                        candidates.append(path.resolve())
                    elif path.is_dir():
                        candidates.extend(sorted(item.resolve() for item in path.iterdir() if item.is_file())[:20])
    return _dedupe_paths(candidates)


def _build_search_query(task: str, slots: list[Slot]) -> str:
    slot_values: dict[str, str] = {}
    for slot in slots:
        if _is_empty_value(slot.value):
            continue
        slot_values[slot.name.lower()] = " ".join(str(item) for item in _flatten_values(slot.value) if item)

    subject = slot_values.get("subject") or slot_values.get("topic") or slot_values.get("主题") or ""
    modifiers = []
    depth = slot_values.get("depth") or slot_values.get("scope") or ""
    if _contains_any(depth, ("overview", "概述", "整体", "intro", "入门")):
        modifiers.append("概述")
    time_focus = slot_values.get("time_focus") or slot_values.get("time") or ""
    if _contains_any(time_focus, ("latest", "最新", "recent", "current")):
        modifiers.append("最新")
    language = slot_values.get("language") or ""
    if _contains_any(language, ("中文", "chinese", "zh")):
        modifiers.append("中文")

    query = " ".join([subject, *modifiers]).strip()
    return query or task


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(needle.lower() in lowered for needle in needles)


def _slot_values(slots: list[Slot]) -> dict[str, Any]:
    return {slot.name: slot.value for slot in slots}


def _flatten_values(value: Any) -> list[Any]:
    if isinstance(value, dict):
        flattened: list[Any] = []
        for item in value.values():
            flattened.extend(_flatten_values(item))
        return flattened
    if isinstance(value, (list, tuple, set)):
        flattened = []
        for item in value:
            flattened.extend(_flatten_values(item))
        return flattened
    return [value]


def _split_path_candidates(value: str) -> list[str]:
    cleaned = value.strip().strip("'\"")
    if not cleaned:
        return []
    parts = re.split(r"[,;\n]+", cleaned)
    return [part.strip().strip("'\"") for part in parts if part.strip()]


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen = set()
    deduped = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or value.strip().lower() in {"none", "null"}
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _truncate(value: str, limit: int) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)] + "..."
