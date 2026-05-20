"""Project Improvement Tool - Analyze concrete next-step improvements."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from metadata import ToolContractMetadata, ToolInputMetadata, ToolResultMetadata, metadata_tool_result

from core.llm import LLMMessage, LLMRequest
from memory.memory_models import MemoryType
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
        if path.suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".md"}:
            safe_target_files.append(str(path))

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
    if _should_prefer_pygame(goal, prompt_context, file_previews):
        fallback = _pygame_migration_report(goal, prompt_context, fallback)
    fallback = _attach_prompt_context(fallback, prompt_context)
    if not llm_client or not hasattr(llm_client, "complete"):
        return _mark_fallback(fallback, "No LLM client available for project_improvement_tool.")

    readme_preview = _truncate_text(_read_text(readme_path), README_PREVIEW_LIMIT)
    product_judgment = prompt_context.get("product_judgment") or {}
    quality_rubric = prompt_context.get("quality_rubric") or []
    product_rubric_text = _truncate_text(json.dumps(
        {
            "product_judgment": product_judgment,
            "quality_rubric": quality_rubric,
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

Product-fit rule:
- For interactive games/apps, compare terminal/curses against a standalone GUI/window experience.
- For a Python snake game, unless the user explicitly requested terminal/curses/CLI, prefer a standalone pygame GUI.
- If the current project is terminal/curses and terminal was not requested, prioritize migrating/rebuilding the playable experience in pygame over adding terminal resize, pause, or small terminal-only polish.

Return JSON with exactly these keys:
{{
  "summary": "short public assessment",
  "improvement_opportunities": ["specific opportunity"],
  "recommended_actions": ["prioritized concrete action"],
  "next_iteration_goal": "one focused goal for the next implementation iteration",
  "must_implement_next": ["observable acceptance point for the next implementation"],
  "blocking_risks": ["risk or empty"]
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

    report = {
        "summary": str(payload.get("summary") or fallback["summary"]),
        "improvement_opportunities": _coerce_string_list(payload.get("improvement_opportunities")) or fallback["improvement_opportunities"],
        "recommended_actions": _coerce_string_list(payload.get("recommended_actions")) or fallback["recommended_actions"],
        "next_iteration_goal": str(payload.get("next_iteration_goal") or fallback["next_iteration_goal"]),
        "must_implement_next": _coerce_string_list(payload.get("must_implement_next")) or fallback["must_implement_next"],
        "blocking_risks": _coerce_string_list(payload.get("blocking_risks")) or fallback["blocking_risks"],
        "source": "llm",
    }
    if _should_prefer_pygame(goal, prompt_context, file_previews) and not _report_mentions_gui_pygame(report):
        report = _pygame_migration_report(goal, prompt_context, report)
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
    }


def _should_prefer_pygame(goal: str, prompt_context: dict[str, Any], file_previews: list[str]) -> bool:
    text = " ".join([goal, json.dumps(prompt_context, ensure_ascii=False, default=str), "\n".join(file_previews)]).lower()
    goal_text = goal.lower()
    explicit_terminal = any(term in goal_text for term in ("terminal", "curses", "cli", "shell", "命令行", "终端", "控制台"))
    snake_or_game = any(term in goal_text for term in ("snake", "贪吃蛇", "game", "游戏"))
    current_pygame = "import pygame" in text or "pygame." in text
    current_curses = "import curses" in text or "curses." in text or "stdscr" in text
    current_tkinter = "import tkinter" in text or "from tkinter" in text or "tk." in text or "tkinter." in text
    product_judgment = prompt_context.get("product_judgment") or {}
    preferred_stack = str(product_judgment.get("preferred_stack") or "").lower()
    preferred_runtime = str(product_judgment.get("preferred_runtime") or "").lower()
    current_runtime = str(product_judgment.get("current_runtime") or "").lower()
    context_prefers_gui = preferred_stack == "pygame" or preferred_runtime == "standalone_gui"
    default_prefers_pygame = context_prefers_gui or snake_or_game
    if explicit_terminal or current_pygame:
        return False
    if not default_prefers_pygame:
        return False
    return bool(
        default_prefers_pygame
        and (
            current_curses
            or current_tkinter
            or current_runtime in {"terminal_curses", "tkinter_gui", "unknown", ""}
        )
    )


def _pygame_migration_report(goal: str, prompt_context: dict[str, Any], base_report: dict[str, Any]) -> dict[str, Any]:
    risks = _coerce_string_list(base_report.get("blocking_risks"))
    if "pygame must be installed in the runtime environment." not in risks:
        risks.append("pygame must be installed in the runtime environment.")
    product_judgment = prompt_context.get("product_judgment") or {}
    current_runtime = str(product_judgment.get("current_runtime") or "current implementation")
    return {
        "summary": (
            f"Product-fit improvement: the {current_runtime} implementation is not the preferred target for the "
            "default Python snake-game expectation; use a standalone playable pygame GUI unless terminal was explicitly requested."
        ),
        "improvement_opportunities": [
            "Migrate the playable snake experience to a standalone pygame window.",
            "Use product-fit as the primary improvement criterion before implementation-specific polish.",
            *_coerce_string_list(base_report.get("improvement_opportunities"))[:2],
        ],
        "recommended_actions": [
            "Rebuild main.py as a pygame snake game with a window, visual snake/food, score display, collision, game over, restart, and quit controls.",
            "Update README dependencies and run command for pygame.",
            *_coerce_string_list(base_report.get("recommended_actions"))[:2],
        ],
        "next_iteration_goal": "Migrate the snake game to a standalone pygame GUI",
        "must_implement_next": [
            "The game opens in a pygame window without requiring a terminal UI.",
            "Snake movement, food, scoring, collision, game-over, restart, and quit controls are playable in the GUI.",
            "README includes pygame installation guidance and the correct run command.",
        ],
        "blocking_risks": risks,
        "prompt_context": prompt_context,
        "product_judgment": prompt_context.get("product_judgment") or {},
    }


def _report_mentions_gui_pygame(report: dict[str, Any]) -> bool:
    text = json.dumps(report, ensure_ascii=False, default=str).lower()
    return any(term in text for term in ("pygame", "standalone", "gui", "window", "独立窗口", "图形"))


def _attach_prompt_context(report: dict[str, Any], prompt_context: dict[str, Any]) -> dict[str, Any]:
    if not prompt_context:
        return report
    return {
        **report,
        "prompt_context": prompt_context,
        "product_judgment": prompt_context.get("product_judgment") or report.get("product_judgment") or {},
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
