"""Resolve task-related project files from sketch.json."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.tool_contracts import PermissionLevel, ToolCapability, ToolDefinition, ToolFailureMode
from memory.project_manager import ProjectManager
from metadata import (
    RelatedProjectFileMetadata,
    TaskFileResolutionMetadata,
    TaskFileResolutionRequestMetadata,
    ToolContractMetadata,
    ToolInputMetadata,
    ToolResultMetadata,
    metadata_tool_result,
)


TASK_FILE_RESOLVER_DEFINITION = ToolDefinition(
    name="task_file_resolver",
    display_name="Task File Resolver",
    description="Resolve files related to an autonomous-iteration task using project sketch metadata",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_READ],
    permission_level=PermissionLevel.LOW,
    contract_metadata=ToolContractMetadata(
        tool_name="task_file_resolver",
        input_metadata_type="ToolInputMetadata",
        output_metadata_type="ToolResultMetadata",
        required_input_fields=["project_path", "task_description"],
        input_defaults={"file_paths": [], "prompt_context": {}},
    ),
    timeout_seconds=30,
    max_retries=0,
    failure_modes=[
        ToolFailureMode(
            error_type="no_related_file",
            description="No project file could be associated with the task",
            recovery_strategy="Provide a clearer task or explicit target file hint",
        )
    ],
    tags=["project", "sketch", "files", "iteration"],
    audit_required=False,
)


@metadata_tool_result("task_file_resolver")
def task_file_resolver_executor(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
    params = input_metadata.to_params()
    request = _request_from_input(input_metadata, params)
    project_path = Path(request.project_path).expanduser()
    if not project_path.exists() or not project_path.is_dir():
        raise FileNotFoundError(f"Project path not found: {project_path}")

    manager = input_metadata.runtime_handles.get("_project_manager") or ProjectManager(project_path)
    manager.update(project_path)

    explicit = _explicit_file_matches(project_path, request)
    query = _resolution_query(request)
    searched = _search_matches(manager, query)
    related = _merge_related_files(explicit, searched)
    if not related:
        raise FileNotFoundError(f"No related project file found for task: {request.task_description[:160]}")

    primary = related[0]
    edit_kind = _edit_kind(primary.file_path)
    return TaskFileResolutionMetadata(
        task_description=request.task_description,
        project_path=str(project_path),
        related_files=related,
        primary_file=primary,
        recommended_edit_kind=edit_kind,
        resolution_reason=f"Selected {primary.name or Path(primary.file_path).name} from sketch evidence and target hints.",
    )


def _request_from_input(input_metadata: ToolInputMetadata, params: dict[str, Any]) -> TaskFileResolutionRequestMetadata:
    raw = input_metadata.attributes.get("request_metadata") if isinstance(input_metadata.attributes, dict) else None
    if isinstance(raw, TaskFileResolutionRequestMetadata):
        return raw
    if isinstance(raw, dict):
        return TaskFileResolutionRequestMetadata.model_validate(raw)
    prompt_context = params.get("prompt_context") if isinstance(params.get("prompt_context"), dict) else {}
    selected_candidate = prompt_context.get("selected_candidate") if isinstance(prompt_context.get("selected_candidate"), dict) else {}
    diagnosis = prompt_context.get("diagnosis") if isinstance(prompt_context.get("diagnosis"), dict) else {}
    criteria = _string_list(prompt_context.get("acceptance_criteria"))
    if not criteria and isinstance(prompt_context.get("improvement_report"), dict):
        criteria = _string_list(prompt_context["improvement_report"].get("must_implement_next"))
    return TaskFileResolutionRequestMetadata(
        project_path=str(params.get("project_path") or ""),
        task_description=str(params.get("task_description") or params.get("task") or ""),
        acceptance_criteria=criteria,
        target_file_hints=_string_list(params.get("file_paths") or params.get("written_files")),
        diagnosis=diagnosis,
        selected_candidate=selected_candidate,
        goal=str(params.get("goal") or ""),
    )


def _explicit_file_matches(project_path: Path, request: TaskFileResolutionRequestMetadata) -> list[RelatedProjectFileMetadata]:
    matches = []
    for raw_path in request.target_file_hints:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = project_path / path
        if not path.exists() or path.is_dir():
            continue
        matches.append(
            RelatedProjectFileMetadata(
                file_path=str(path),
                name=path.name,
                suffix=path.suffix,
                description=f"Explicit target hint for task: {request.task_description[:220]}",
                role=_role_for_path(path),
                relevance_score=1.0,
                evidence=["explicit target file hint", request.task_description[:220]],
                relation_source="target_hint",
            )
        )
    return matches


def _search_matches(manager: ProjectManager, query: str) -> list[RelatedProjectFileMetadata]:
    matches = []
    for item in manager.search(query, limit=8):
        path = Path(str(item.get("path") or ""))
        if _should_ignore_project_file(path):
            continue
        matches.append(
            RelatedProjectFileMetadata(
                file_path=str(path),
                name=str(item.get("name") or path.name),
                suffix=str(item.get("suffix") or path.suffix),
                description=str(item.get("description") or ""),
                role=_role_for_path(path),
                relevance_score=float(item.get("score") or 0.0),
                evidence=[query[:300], str(item.get("description") or "")[:300]],
                relation_source="sketch",
            )
        )
    return matches


def _should_ignore_project_file(path: Path) -> bool:
    if path.name == ProjectManager.SKETCH_NAME:
        return True
    if path.suffix.lower() in {".jsonl", ".log"}:
        return True
    if path.name.startswith("."):
        return True
    return False


def _merge_related_files(*groups: list[RelatedProjectFileMetadata]) -> list[RelatedProjectFileMetadata]:
    merged: dict[str, RelatedProjectFileMetadata] = {}
    for group in groups:
        for item in group:
            key = str(Path(item.file_path).expanduser())
            previous = merged.get(key)
            if previous is None or item.relevance_score > previous.relevance_score:
                merged[key] = item
            elif previous is not None:
                previous.evidence = _dedupe([*previous.evidence, *item.evidence])
    return sorted(merged.values(), key=lambda item: (item.relevance_score, item.relation_source == "target_hint"), reverse=True)


def _resolution_query(request: TaskFileResolutionRequestMetadata) -> str:
    chunks = [
        request.task_description,
        request.goal,
        " ".join(request.acceptance_criteria),
        str(request.selected_candidate.get("title") or ""),
        str(request.selected_candidate.get("rationale") or ""),
    ]
    return " ".join(chunk for chunk in chunks if chunk).strip()


def _edit_kind(file_path: str) -> str:
    suffix = Path(file_path).suffix.lower()
    if suffix in {".md", ".markdown", ".rst", ".txt"}:
        return "documentation"
    if suffix in {".json", ".yaml", ".yml", ".toml", ".ini"}:
        return "config"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico"}:
        return "asset_manifest"
    return "source_code"


def _role_for_path(path: Path) -> str:
    kind = _edit_kind(str(path))
    if kind == "documentation":
        return "documentation"
    if kind == "config":
        return "configuration"
    if kind == "asset_manifest":
        return "asset"
    return "implementation"


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, dict):
                item = item.get("file_path") or item.get("path") or item.get("name")
            text = str(item or "").strip()
            if text:
                result.append(text)
        return result
    return [str(value)]


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result
