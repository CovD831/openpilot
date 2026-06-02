"""Persistent project technology-stack and UI-surface presets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from metadata import ProjectStackPresetMetadata


STACK_PRESET_RELATIVE_PATH = Path(".openpilot") / "project_stack.json"
MUTABLE_STACK_FIELDS = {
    "delivery_surface",
    "architecture",
    "frontend_language",
    "frontend_frameworks",
    "backend_language",
    "backend_frameworks",
    "ui_strategy",
    "ui_review_required",
    "rationale",
    "evidence",
}


def load_project_stack_preset(project_path: Path) -> ProjectStackPresetMetadata | None:
    """Load the persisted preset when the project already has one."""
    preset_file = project_path.expanduser() / STACK_PRESET_RELATIVE_PATH
    if not preset_file.is_file():
        return None
    try:
        return ProjectStackPresetMetadata.model_validate(json.loads(preset_file.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def load_or_create_project_stack_preset(
    project_path: Path,
    *,
    goal: str = "",
    files: list[str] | None = None,
    dependencies: list[str] | None = None,
    preset_update: dict[str, Any] | None = None,
) -> ProjectStackPresetMetadata:
    """Create the initial preset once, then apply explicit revision updates only."""
    project_path = project_path.expanduser()
    preset_file = project_path / STACK_PRESET_RELATIVE_PATH
    preset = load_project_stack_preset(project_path)
    if preset is None:
        preset = infer_project_stack_preset(
            project_path,
            goal=goal,
            files=files or [],
            dependencies=dependencies or [],
        )
    elif not preset_update:
        aligned = _goal_alignment_update(
            project_path,
            preset,
            goal=goal,
            dependencies=dependencies or [],
        )
        if aligned:
            preset = preset.model_copy(
                update={
                    **aligned,
                    "revision": preset.revision + 1,
                    "preset_source": "deterministic_goal_alignment",
                }
            )
    if isinstance(preset_update, dict) and preset_update:
        updates = {key: value for key, value in preset_update.items() if key in MUTABLE_STACK_FIELDS}
        if updates:
            updates["revision"] = preset.revision + 1
            updates["preset_source"] = "explicit_iteration_update"
            preset = preset.model_copy(update=updates)
    preset = preset.model_copy(
        update={
            "project_path": str(project_path),
            "preset_file": str(preset_file),
        }
    )
    preset_file.parent.mkdir(parents=True, exist_ok=True)
    preset_file.write_text(json.dumps(preset.to_json_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return preset


def infer_project_stack_preset(
    project_path: Path,
    *,
    goal: str,
    files: list[str],
    dependencies: list[str],
) -> ProjectStackPresetMetadata:
    """Infer a conservative initial delivery stack from goal and project evidence."""
    goal_text = str(goal or "").lower()
    evidence_text = _project_evidence_text(project_path, files)
    combined = f"{goal_text}\n{evidence_text}".lower()
    dependency_text = " ".join(str(item) for item in dependencies).lower()
    explicit_terminal = _goal_explicitly_requests_terminal(goal_text) or (
        not goal_text.strip()
        and _contains_any(evidence_text.lower(), ("terminal", "cli", "command line", "命令行", "终端", "控制台"))
    )
    browser_surface = _contains_any(
        combined,
        ("web", "website", "browser", "dashboard", "网页", "网站", "仪表盘", ".html", "react", "vue", "svelte"),
    )
    assistant_surface = _contains_any(goal_text, ("assistant", "助手", "planner", "tracker", "管理器", "管理系统"))
    native_interactive = _contains_any(combined, ("game", "游戏", "pygame", "tkinter", "desktop", "桌面"))
    api_or_library = _contains_any(combined, ("library", "sdk", "package api", "rest api", "fastapi", "flask", "库", "接口"))
    frontend_frameworks = _frontend_frameworks(combined)
    backend_frameworks = _backend_frameworks(f"{combined}\n{dependency_text}")
    backend_language = _backend_language(project_path, files)
    rationale: list[str] = []

    if explicit_terminal:
        delivery_surface = "terminal"
        architecture = "terminal_application"
        frontend_language = "terminal_text"
        ui_strategy = "terminal_ui"
        ui_review_required = True
        rationale.append("The project explicitly requests a terminal or CLI interaction surface.")
    elif browser_surface or assistant_surface:
        delivery_surface = "browser"
        architecture = "frontend_backend_split"
        frontend_language = "html_css_javascript"
        frontend_frameworks = frontend_frameworks or ["vanilla_web"]
        ui_strategy = "browser_application"
        ui_review_required = True
        rationale.append("The project is user-facing and benefits from a browser UI with a distinct backend boundary.")
    elif native_interactive:
        delivery_surface = "interactive_runtime"
        architecture = "single_runtime"
        frontend_language = backend_language
        ui_strategy = "native_interactive_ui"
        ui_review_required = True
        rationale.append("The project is an interactive native runtime; UI belongs in the primary application loop.")
    elif api_or_library:
        delivery_surface = "api_or_library"
        architecture = "backend_or_library"
        frontend_language = "none"
        ui_strategy = "no_forced_ui"
        ui_review_required = False
        rationale.append("The requested artifact is API- or library-oriented, so a visual UI is not forced.")
    else:
        delivery_surface = "project_native"
        architecture = "single_runtime"
        frontend_language = "best_fit_for_surface"
        ui_strategy = "evaluate_user_facing_ui"
        ui_review_required = False
        rationale.append("No stronger surface signal exists; preserve the native shape and reassess UI impact during iteration.")

    return ProjectStackPresetMetadata(
        project_path=str(project_path),
        preset_file=str(project_path / STACK_PRESET_RELATIVE_PATH),
        delivery_surface=delivery_surface,
        architecture=architecture,
        frontend_language=frontend_language,
        frontend_frameworks=frontend_frameworks,
        backend_language=backend_language,
        backend_frameworks=backend_frameworks,
        ui_strategy=ui_strategy,
        ui_review_required=ui_review_required,
        rationale=rationale,
        evidence=[
            f"goal:{goal[:240]}",
            f"files:{', '.join(Path(item).name for item in files[:8])}",
            f"dependencies:{', '.join(str(item) for item in dependencies[:8])}",
        ],
    )


def _project_evidence_text(project_path: Path, files: list[str]) -> str:
    chunks = []
    for raw_path in files[:10]:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = project_path / path
        chunks.append(path.name)
        if path.is_file() and path.suffix.lower() in {".py", ".html", ".js", ".jsx", ".ts", ".tsx"}:
            try:
                chunks.append(path.read_text(encoding="utf-8")[:2400])
            except OSError:
                continue
    return "\n".join(chunks)


def _backend_language(project_path: Path, files: list[str]) -> str:
    suffixes = []
    for raw_path in files:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = project_path / path
        suffixes.append(path.suffix.lower())
    if any(suffix in {".ts", ".tsx"} for suffix in suffixes):
        return "typescript"
    if any(suffix in {".js", ".jsx"} for suffix in suffixes):
        return "javascript"
    return "python"


def _frontend_frameworks(text: str) -> list[str]:
    return [name for name in ("react", "vue", "svelte") if name in text]


def _backend_frameworks(text: str) -> list[str]:
    return [name for name in ("fastapi", "flask", "django", "express") if name in text]


def _goal_alignment_update(
    project_path: Path,
    preset: ProjectStackPresetMetadata,
    *,
    goal: str,
    dependencies: list[str],
) -> dict[str, Any]:
    """Return a deterministic preset repair when an initial inference conflicts with the goal."""
    if not goal.strip() or not preset.mutable:
        return {}
    if preset.revision != 1 or preset.preset_source != "initial_inference":
        return {}

    goal_text = goal.lower()
    if _goal_explicitly_requests_terminal(goal_text):
        return {}

    goal_only = infer_project_stack_preset(
        project_path,
        goal=goal,
        files=[],
        dependencies=dependencies,
    )
    if not goal_only.ui_review_required:
        return {}
    if goal_only.delivery_surface == preset.delivery_surface:
        return {}
    if preset.delivery_surface != "terminal":
        return {}

    return {
        "delivery_surface": goal_only.delivery_surface,
        "architecture": goal_only.architecture,
        "frontend_language": goal_only.frontend_language,
        "frontend_frameworks": goal_only.frontend_frameworks,
        "backend_language": goal_only.backend_language,
        "backend_frameworks": goal_only.backend_frameworks,
        "ui_strategy": goal_only.ui_strategy,
        "ui_review_required": goal_only.ui_review_required,
        "rationale": [
            "Corrected an initial terminal inference because the original goal is user-facing but does not explicitly request a terminal interface.",
            *goal_only.rationale[:2],
        ],
        "evidence": [
            f"goal:{goal[:240]}",
            f"previous_preset:r{preset.revision} {preset.delivery_surface} via {preset.architecture}",
            "correction:generated implementation evidence must not override the user's requested surface.",
        ],
    }


def _goal_explicitly_requests_terminal(goal_text: str) -> bool:
    return _contains_any(goal_text, ("terminal", "cli", "command line", "命令行", "终端", "控制台"))


def _contains_any(text: str, values: tuple[str, ...]) -> bool:
    return any(value in text for value in values)
