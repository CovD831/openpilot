"""Project Improvement Tool - Analyze concrete next-step improvements."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from metadata import ToolContractMetadata, ToolInputMetadata, ToolResultMetadata, metadata_tool_result

from core.llm import LLMMessage, LLMRequest
from core.project_stack import load_project_stack_preset
from memory.memory_models import MemoryType
from memory.agents.project_environment_tool import (
    build_dependency_strategy,
    build_project_dependency_context,
    infer_project_dependencies,
)
from core.tool_contracts import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolFailureMode,
)


README_PREVIEW_LIMIT = 1200
VALIDATION_PREVIEW_LIMIT = 1800
PRODUCT_RUBRIC_PREVIEW_LIMIT = 1800
PROJECT_FILE_PREVIEW_LIMIT = 2400
MAX_PROJECT_PREVIEWS = 6


PROJECT_STATE_READER_DEFINITION = ToolDefinition(
    name="project_state_reader",
    display_name="Project State Reader",
    description="Read generated project state, README, safe target files, and relevant memory context",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_READ],
    permission_level=PermissionLevel.LOW,
    contract_metadata=ToolContractMetadata(
        tool_name='project_state_reader',
        input_metadata_type="ToolInputMetadata",
        output_metadata_type="ToolResultMetadata",
        required_input_fields=['project_path'],
        input_defaults={'goal': '', 'written_files': [], 'readme_path': '', 'run_command': '', 'memory_query': '', 'validation_context': {}},
    ),
    timeout_seconds=20,
    max_retries=0,
    failure_modes=[
        ToolFailureMode(
            error_type="invalid_input",
            description="Project path is missing or unreadable",
            recovery_strategy="Provide an existing project_path",
        ),
    ],
    tags=["project", "state", "memory", "iteration"],
    audit_required=False,
)


PROJECT_IMPROVEMENT_TOOL_DEFINITION = ToolDefinition(
    name="project_improvement_tool",
    display_name="Project Improvement Tool",
    description="Analyze a generated project and produce concrete next-iteration improvement goals",
    version="1.0.0",
    capabilities=[ToolCapability.LLM_CALL, ToolCapability.FILE_READ],
    permission_level=PermissionLevel.MEDIUM,
    contract_metadata=ToolContractMetadata(
        tool_name='project_improvement_tool',
        input_metadata_type="ToolInputMetadata",
        output_metadata_type="ToolResultMetadata",
        required_input_fields=['project_path', 'goal'],
        input_defaults={'written_files': [], 'run_command': '', 'iteration': 0, 'validation_result': {}, 'readme_path': '', 'prompt_context': {}},
    ),
    timeout_seconds=420,
    max_retries=0,
    failure_modes=[
        ToolFailureMode(
            error_type="llm_error",
            description="The LLM failed to return a usable improvement analysis",
            recovery_strategy="Use deterministic validation findings as the next iteration goal",
        ),
        ToolFailureMode(
            error_type="invalid_input",
            description="Project path or goal is missing",
            recovery_strategy="Provide project_path and goal",
        ),
    ],
    tags=["project", "improvement", "iteration", "evaluation"],
    audit_required=False,
)


@metadata_tool_result('project_state_reader')
def project_state_reader_executor(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
    params = input_metadata.to_params()
    """Read current project state using a strict tool-style contract."""
    project_path = Path(params["project_path"]).expanduser()
    goal = str(params.get("goal") or "")
    written_files = _coerce_path_list(params.get("written_files", []))
    readme_path = Path(params.get("readme_path") or project_path / "README.md").expanduser()
    run_command = str(params.get("run_command") or "").strip()
    validation_context = params.get("validation_context") or {}
    memory_query = str(params.get("memory_query") or goal or project_path.name)
    memory_store = params.get("_memory_store")

    resolved_files = _resolve_project_files(project_path, written_files)
    readme_text = _read_text(readme_path)
    if not run_command:
        run_command = _extract_run_command(readme_text)

    memory_records: list[dict[str, Any]] = []
    if memory_store and hasattr(memory_store, "query"):
        try:
            query_result = memory_store.query(
                memory_query,
                memory_types=[MemoryType.PROJECT, MemoryType.TASK, MemoryType.FEEDBACK, MemoryType.LONG_TERM, MemoryType.SHORT_TERM],
                limit=8,
            )
            memory_records = [
                {
                    "id": memory.id,
                    "type": memory.memory_type.value,
                    "content": memory.content[:500],
                    "tags": memory.tags,
                    "confidence": memory.confidence,
                    "attributes": memory.attributes,
                }
                for memory in query_result.memories
            ]
            if hasattr(memory_store, "load_all"):
                env_memories = [
                    memory
                    for memory in memory_store.load_all(MemoryType.SHORT_TERM)
                    if "project_environment" in memory.tags and project_path.name in memory.tags
                ][-3:]
                known_ids = {item["id"] for item in memory_records}
                for memory in env_memories:
                    if memory.id in known_ids:
                        continue
                    memory_records.append(
                        {
                            "id": memory.id,
                            "type": memory.memory_type.value,
                            "content": memory.content[:500],
                            "tags": memory.tags,
                            "confidence": memory.confidence,
                            "attributes": memory.attributes,
                        }
                    )
        except Exception:
            memory_records = []

    file_summaries = []
    safe_target_files = []
    for path in resolved_files:
        if not path.exists() or path.is_dir():
            continue
        text = _read_text(path)
        file_summaries.append(
            {
                "path": str(path),
                "name": path.name,
                "suffix": path.suffix,
                "chars": str(len(text)),
                "preview": text[:1200],
            }
        )
        safe_target_files.append(str(path))

    validation_errors = validation_context.get("validation_errors") if isinstance(validation_context, dict) else []
    validation_warnings = validation_context.get("warnings") if isinstance(validation_context, dict) else []
    suffixes = sorted({str(item.get("suffix") or "") for item in file_summaries if item.get("suffix")})
    installed_packages = _latest_environment_packages(memory_records)
    detected_packages = infer_project_dependencies(project_path, [str(path) for path in resolved_files])
    dependencies = build_project_dependency_context(
        project_path=project_path,
        files=[str(path) for path in resolved_files],
        detected_packages=detected_packages,
        installed_packages=installed_packages,
        dependency_source="project_state_reader",
        readme_text=readme_text,
    )
    dependency_strategy = build_dependency_strategy(dependencies)
    stack_preset = load_project_stack_preset(project_path)
    return {
        "project_path": str(project_path),
        "goal": goal,
        "written_files": [str(path) for path in resolved_files],
        "file_summaries": file_summaries,
        "readme_summary": readme_text[:1600],
        "run_command": run_command,
        "memory_records": memory_records,
        "validation_context": validation_context,
        "safe_target_files": safe_target_files,
        "diagnostic_evidence": {
            "readme_present": bool(readme_text.strip()),
            "run_command_known": bool(run_command),
            "file_count": len(file_summaries),
            "safe_target_count": len(safe_target_files),
            "file_suffixes": suffixes,
            "memory_count": len(memory_records),
        },
        "runtime_evidence": [str(item) for item in [run_command, *(validation_errors or []), *(validation_warnings or [])] if str(item)],
        "test_evidence": [str(item) for item in validation_errors or [] if "test" in str(item).lower() or "smoke" in str(item).lower()],
        "module_summaries": [f"{item['name']} ({item['suffix']}, {item['chars']} chars)" for item in file_summaries[:8]],
        "dependencies": [dependency.to_json_dict() for dependency in dependencies],
        "dependency_strategy": dependency_strategy.to_json_dict(),
        "stack_preset": stack_preset.to_json_dict() if stack_preset else None,
    }


@metadata_tool_result('project_improvement_tool')
def project_improvement_tool_executor(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
    params = input_metadata.to_params()
    """Produce a project improvement report using the current LLM when available."""
    project_path = Path(params["project_path"]).expanduser()
    goal = str(params["goal"])
    written_files = _coerce_path_list(params.get("written_files", []))
    run_command = str(params.get("run_command") or "").strip()
    iteration = int(params.get("iteration") or 0)
    validation_result = params.get("validation_result") or {}
    readme_path = Path(params.get("readme_path") or project_path / "README.md").expanduser()
    prompt_context = params.get("prompt_context") if isinstance(params.get("prompt_context"), dict) else {}
    llm_client = params.get("_llm_client")

    file_previews = _read_project_previews(project_path, written_files)
    fallback = _fallback_report(goal, validation_result)
    fallback = _attach_prompt_context(fallback, prompt_context)
    if not llm_client or not hasattr(llm_client, "complete"):
        return _mark_fallback(fallback, "No LLM client available for project_improvement_tool.")

    readme_preview = _truncate_text(_read_text(readme_path), README_PREVIEW_LIMIT)
    product_judgment = prompt_context.get("product_judgment") or {}
    quality_rubric = prompt_context.get("quality_rubric") or []
    stack_preset = prompt_context.get("stack_preset") or {}
    ui_iteration_contract = prompt_context.get("ui_iteration_contract") or {}
    product_rubric_text = _truncate_text(json.dumps(
        {
            "product_judgment": product_judgment,
            "quality_rubric": quality_rubric,
            "stack_preset": stack_preset,
            "ui_iteration_contract": ui_iteration_contract,
        },
        ensure_ascii=False,
        default=str,
    ), PRODUCT_RUBRIC_PREVIEW_LIMIT)
    validation_json = _truncate_text(
        json.dumps(validation_result, ensure_ascii=False, default=str),
        VALIDATION_PREVIEW_LIMIT,
    )
    prompt = f"""You are OpenPilot's Project Improvement Tool.
Analyze the generated project after a successful hard validation pass.
Return ONLY valid JSON. Do not include markdown.
Do not reveal hidden chain-of-thought or private reasoning; provide concise public assessment only.

Original goal: {goal}
Project path: {project_path}
Completed successful iteration: {iteration}
Run command: {run_command}
Validation result JSON: {validation_json}
Parent Prompt Context product rubric JSON: {product_rubric_text}

README preview:
{readme_preview}

Project file previews:
{chr(10).join(file_previews)}

If a preview says it is truncated, do not assume the project file is incomplete merely because the preview ended.

Evaluate improvement space comprehensively across:
- functional completeness against the original goal
- usability and user experience
- runtime robustness and error handling
- code structure, maintainability, and clarity
- documentation, setup, and run instructions
- installation/runtime environment risks
- product fit: runtime shape, target platform, and whether the result matches normal expectations for this project type
- UI impact: whether each user-facing capability has coherent controls, visible states, feedback, and navigation on the planned surface
- technology-stack fit: whether frontend/backend languages and frameworks still match the persisted project stack preset

Product-fit rule:
- Treat the parent project objective, success metrics, and diagnosed evidence as the source of truth.
- Prefer improvements with clear user or maintainer value over low-signal polish.
- Do not replace the delivery surface or interaction model just because another implementation is easier.
- Treat UI as part of a user-facing feature, not as optional polish after backend behavior is complete.
- If the best next improvement changes delivery surface, frontend/backend languages, or frameworks, state that the project stack preset must be explicitly revised.

Return JSON with exactly these keys:
{{
  "summary": "short public assessment",
  "improvement_opportunities": ["specific opportunity"],
  "recommended_actions": ["prioritized concrete action"],
  "next_iteration_goal": "one focused goal for the next implementation iteration",
  "must_implement_next": ["observable acceptance point for the next implementation"],
  "blocking_risks": ["risk or empty"],
  "stack_preset_update": {{"optional_field": "only include when an explicit architecture, language, framework, or UI-surface revision is necessary"}}
}}
"""

    try:
        response = llm_client.complete(
            LLMRequest(
                messages=[LLMMessage(role="user", content=prompt)],
                response_format="json_object",
                temperature=0.2,
            ),
            max_retries=2,
            use_cache=False,
        )
    except Exception as exc:
        return _mark_fallback(fallback, f"LLM improvement analysis failed: {type(exc).__name__}: {str(exc)[:300]}")

    payload = response.parsed_json if isinstance(response.parsed_json, dict) else None
    if payload is None:
        try:
            payload = json.loads(response.content)
        except (TypeError, json.JSONDecodeError):
            return _mark_fallback(fallback, "LLM improvement analysis returned non-JSON content.")

    deterministic_stack_update = (
        product_judgment.get("recommended_stack_preset_update")
        if isinstance(product_judgment, dict) and isinstance(product_judgment.get("recommended_stack_preset_update"), dict)
        else {}
    )
    llm_stack_update = payload.get("stack_preset_update") if isinstance(payload.get("stack_preset_update"), dict) else {}
    report = {
        "summary": str(payload.get("summary") or fallback["summary"]),
        "improvement_opportunities": _coerce_string_list(payload.get("improvement_opportunities")) or fallback["improvement_opportunities"],
        "recommended_actions": _coerce_string_list(payload.get("recommended_actions")) or fallback["recommended_actions"],
        "next_iteration_goal": str(payload.get("next_iteration_goal") or fallback["next_iteration_goal"]),
        "must_implement_next": _coerce_string_list(payload.get("must_implement_next")) or fallback["must_implement_next"],
        "blocking_risks": _coerce_string_list(payload.get("blocking_risks")) or fallback["blocking_risks"],
        "stack_preset_update": llm_stack_update or deterministic_stack_update,
        "source": "llm",
    }
    report = _attach_prompt_context(report, prompt_context)
    return _sanitize_public_report(report)


def _fallback_report(goal: str, validation_result: Any) -> dict[str, Any]:
    validation = validation_result if isinstance(validation_result, dict) else {}
    errors = _coerce_string_list(validation.get("validation_errors"))
    warnings = _coerce_string_list(validation.get("warnings"))
    actions = _coerce_string_list(validation.get("recommended_actions"))
    opportunities = _coerce_string_list(validation.get("improvement_opportunities")) or warnings
    next_goal = validation.get("next_iteration_goal") or (actions[0] if actions else f"Improve the project for the original goal: {goal}")
    return {
        "summary": "Generated deterministic improvement report from validation context.",
        "improvement_opportunities": opportunities or ["Improve functional polish, runtime robustness, and user-facing documentation."],
        "recommended_actions": actions or ["Apply one focused improvement that better satisfies the original goal."],
        "next_iteration_goal": str(next_goal),
        "must_implement_next": actions[:2] or ["The next version should include at least one visible behavior improvement."],
        "blocking_risks": errors,
        "stack_preset_update": {},
    }


def _attach_prompt_context(report: dict[str, Any], prompt_context: dict[str, Any]) -> dict[str, Any]:
    if not prompt_context:
        return report
    product_judgment = prompt_context.get("product_judgment") if isinstance(prompt_context.get("product_judgment"), dict) else {}
    deterministic_stack_update = (
        product_judgment.get("recommended_stack_preset_update")
        if isinstance(product_judgment.get("recommended_stack_preset_update"), dict)
        else {}
    )
    stack_preset_update = report.get("stack_preset_update") if isinstance(report.get("stack_preset_update"), dict) else {}
    return {
        **report,
        "prompt_context": prompt_context,
        "product_judgment": product_judgment or report.get("product_judgment") or {},
        "stack_preset": prompt_context.get("stack_preset") or report.get("stack_preset") or {},
        "stack_preset_update": stack_preset_update or deterministic_stack_update,
        "ui_iteration_contract": prompt_context.get("ui_iteration_contract") or report.get("ui_iteration_contract") or {},
    }


def _read_project_previews(project_path: Path, written_files: list[str]) -> list[str]:
    previews: list[str] = []
    for raw_path in written_files[:MAX_PROJECT_PREVIEWS]:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = project_path / path
        if not path.exists() or path.is_dir():
            continue
        text = _read_text(path)
        preview = _truncate_text(
            text,
            PROJECT_FILE_PREVIEW_LIMIT,
            suffix="\n[Preview truncated; inspect the actual file before concluding code is missing.]",
        )
        previews.append(f"FILE: {path.name}\n{preview}")
    return previews


def _truncate_text(text: str, limit: int, suffix: str = "\n[Truncated.]") -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + suffix


def _mark_fallback(report: dict[str, Any], reason: str) -> dict[str, Any]:
    return _sanitize_public_report(
        {
            **report,
            "source": "fallback",
            "fallback_reason": reason,
        }
    )


def _resolve_project_files(project_path: Path, written_files: list[str]) -> list[Path]:
    if written_files:
        files = []
        for raw_path in written_files:
            path = Path(raw_path).expanduser()
            if not path.is_absolute():
                path = project_path / path
            files.append(path)
        return files

    if not project_path.exists():
        return []
    return [
        path
        for path in sorted(project_path.iterdir())
        if path.is_file() and path.name != "README.md"
    ][:12]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _extract_run_command(readme_text: str) -> str:
    for line in readme_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("python ") or stripped.startswith("npm ") or stripped.startswith("uv "):
            return stripped
        if stripped.startswith("`") and stripped.endswith("`"):
            inner = stripped.strip("`").strip()
            if inner.startswith(("python ", "npm ", "uv ")):
                return inner
    return ""


def _coerce_path_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [str(value)]
    if isinstance(value, list):
        return [str(item.get("file_path") or item.get("path") or item) if isinstance(item, dict) else str(item) for item in value if item]
    return []


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value)]


def _latest_environment_packages(memory_records: list[dict[str, Any]]) -> list[str]:
    packages: list[str] = []
    for record in memory_records:
        attributes = record.get("attributes") if isinstance(record, dict) else None
        if not isinstance(attributes, dict):
            continue
        candidate = attributes.get("installed_packages") or attributes.get("detected_packages")
        if isinstance(candidate, list) and candidate:
            packages = [str(item) for item in candidate if str(item)]
    return packages


def _sanitize_public_report(report: dict[str, Any]) -> dict[str, Any]:
    forbidden = ("chain-of-thought", "hidden reasoning")
    sanitized = {}
    for key, value in report.items():
        if isinstance(value, list):
            sanitized[key] = [item for item in value if not any(term in item.lower() for term in forbidden)]
        elif isinstance(value, str):
            sanitized[key] = "" if any(term in value.lower() for term in forbidden) else value
        else:
            sanitized[key] = value
    return sanitized
