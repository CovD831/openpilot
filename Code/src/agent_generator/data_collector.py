"""Data collection stage for generated agents."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_generator.models import DataArtifact, DataArtifactKind, PipelineSpec, PipelineStep, Slot, StepStrategy
from tools.file_reader import file_reader_executor
from tools.multi_file_reader import multi_file_reader_executor
from tools.web_searcher import web_searcher_executor


def collect_data(
    task: str,
    slots: list[Slot],
    *,
    llm_client: Any | None = None,
    max_results: int = 5,
    max_pages: int = 3,
) -> tuple[list[DataArtifact], PipelineSpec]:
    """Collect concrete task data from user files or the public web."""
    cleaned_task = " ".join(task.strip().split())
    if not cleaned_task:
        raise ValueError("task must not be empty")

    file_paths = _find_existing_file_paths(slots)
    if file_paths:
        artifact, step = _collect_from_files(cleaned_task, slots, file_paths)
    else:
        artifact, step = _collect_from_web(
            cleaned_task,
            slots,
            llm_client=llm_client,
            max_results=max_results,
            max_pages=max_pages,
        )

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
    return [artifact], pipeline


def _collect_from_files(
    task: str,
    slots: list[Slot],
    file_paths: list[Path],
) -> tuple[DataArtifact, PipelineStep]:
    if len(file_paths) == 1:
        params = {
            "file_path": str(file_paths[0]),
            "read_mode": "adaptive",
            "max_lines": 200,
            "max_size_mb": 10,
        }
        output = file_reader_executor(params)
        selected_tool = "file_reader"
        files = [str(file_paths[0])]
    else:
        params = {
            "file_paths": [str(path) for path in file_paths],
            "encoding": "utf-8",
            "max_total_chars": 50000,
        }
        output = multi_file_reader_executor(params)
        selected_tool = "multi_file_reader"
        files = output.get("files", [str(path) for path in file_paths])

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
) -> tuple[DataArtifact, PipelineStep]:
    query = _build_search_query(task, slots)
    params: dict[str, Any] = {
        "query": query,
        "max_results": max_results,
        "max_pages": max_pages,
        "max_page_chars": 4000,
        "llm_cleanup": llm_client is not None,
        "cleanup_instruction": (
            "Organize the findings for an agent-generation data preview. "
            "Keep concrete facts, source-specific notes, and follow-up query suggestions."
        ),
    }
    if llm_client is not None:
        params["_llm_client"] = llm_client

    output, cleanup_fallback_warning = _execute_web_search_with_cleanup_fallback(params)
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
            "tool_input": {key: value for key, value in params.items() if not key.startswith("_")},
            "llm_cleanup": llm_client is not None,
            "cleanup_fallback_warning": cleanup_fallback_warning,
        },
        approved=False,
    )
    return artifact, step


def _execute_web_search_with_cleanup_fallback(params: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    try:
        return web_searcher_executor(params), None
    except RuntimeError as exc:
        if not params.get("llm_cleanup") or not _is_socks_dependency_error(exc):
            raise
        fallback_params = dict(params)
        fallback_params["llm_cleanup"] = False
        fallback_params.pop("_llm_client", None)
        output = web_searcher_executor(fallback_params)
        warning = (
            "LLM cleanup disabled because the current SOCKS proxy setup is missing "
            "the httpx socks extra / socksio dependency. Install httpx[socks] to enable cleanup."
        )
        warnings = output.setdefault("warnings", [])
        if isinstance(warnings, list):
            warnings.append(warning)
        return output, warning


def _is_socks_dependency_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "socks proxy" in text and ("socksio" in text or "httpx[socks]" in text)


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
    values = []
    for slot in slots:
        if _is_empty_value(slot.value):
            continue
        values.append(f"{slot.name}: {slot.value}")
    if not values:
        return task
    return f"{task} " + " ".join(values)


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
