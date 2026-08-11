"""Typed project-scope admission before autonomous project execution."""

from __future__ import annotations

import hashlib
from pathlib import Path

from autonomous_iteration.pre_task_admission import (
    PreTaskAdmissionKind,
    PreTaskAdmissionReason,
    resolve_pre_task_admission,
)
from metadata import ProjectScopeDecision, ProjectScopeDecisionKind, ProjectScopeReason


class ProjectScopeAdmissionError(RuntimeError):
    def __init__(self, decision: ProjectScopeDecision) -> None:
        super().__init__(f"Select a concrete project directory instead of {decision.source_root}.")
        self.decision = decision


_PROJECT_MARKERS = (
    ".git", "pyproject.toml", "package.json", "Cargo.toml", "go.mod",
    "pom.xml", "build.gradle", "Makefile",
)


def resolve_project_execution_scope(
    goal: str,
    requested_root: str | Path,
    *,
    home_path: str | Path | None = None,
) -> ProjectScopeDecision:
    """Resolve a bounded project identity without creating directories."""

    source = Path(requested_root).expanduser().resolve(strict=False)
    home = Path(home_path or Path.home()).expanduser().resolve(strict=False)
    admission = resolve_pre_task_admission(goal)
    artifact_creation = (
        admission.kind is PreTaskAdmissionKind.PROJECT_EXECUTION
        and admission.reason_code is PreTaskAdmissionReason.ARTIFACT_CREATION
    )
    if admission.kind is not PreTaskAdmissionKind.PROJECT_EXECUTION:
        return _decision(
            ProjectScopeDecisionKind.USE_REQUESTED_ROOT,
            ProjectScopeReason.NON_PROJECT_REQUEST,
            source,
            source,
        )
    special_broad = source == home or source == Path(source.anchor)
    if not special_broad and _has_project_marker(source):
        return _decision(ProjectScopeDecisionKind.USE_REQUESTED_ROOT, ProjectScopeReason.EXISTING_PROJECT_ROOT, source, source)
    broad_root = special_broad or _contains_multiple_projects(source)
    if broad_root and artifact_creation:
        return _decision(
            ProjectScopeDecisionKind.GENERATED_CHILD_PROJECT,
            ProjectScopeReason.BROAD_ROOT_ARTIFACT_CREATION,
            source,
            _available_child(source, _project_name(goal)),
        )
    if broad_root:
        return _decision(
            ProjectScopeDecisionKind.REQUIRE_EXPLICIT_PROJECT,
            ProjectScopeReason.BROAD_ROOT_EXISTING_PROJECT_AMBIGUOUS,
            source,
            source,
        )
    return _decision(ProjectScopeDecisionKind.USE_REQUESTED_ROOT, ProjectScopeReason.SAFE_REQUESTED_ROOT, source, source)


def _decision(
    kind: ProjectScopeDecisionKind,
    reason: ProjectScopeReason,
    source: Path,
    effective: Path,
) -> ProjectScopeDecision:
    return ProjectScopeDecision(kind=kind, reason_code=reason, source_root=str(source), effective_root=str(effective.resolve(strict=False)))


def _has_project_marker(root: Path) -> bool:
    return root.is_dir() and any((root / marker).exists() for marker in _PROJECT_MARKERS)


def _contains_multiple_projects(root: Path) -> bool:
    if not root.is_dir():
        return False
    found = 0
    try:
        for index, child in enumerate(root.iterdir()):
            if index >= 256:
                return True
            if child.is_dir() and _has_project_marker(child):
                found += 1
                if found >= 2:
                    return True
    except OSError:
        return True
    return False


def _project_name(goal: str) -> str:
    lowered = str(goal).casefold()
    for markers, name in (
        (("贪吃蛇", "snake"), "snake-game"),
        (("博客", "blog"), "blog"),
        (("dashboard", "仪表盘"), "dashboard"),
        (("网页", "网站", "website"), "website"),
        (("游戏", "game"), "game"),
    ):
        if any(marker in lowered for marker in markers):
            return name
    return "generated-project"


def _available_child(root: Path, base_name: str) -> Path:
    first = root / base_name
    if not first.exists():
        return first
    for suffix in range(2, 101):
        candidate = root / f"{base_name}-{suffix}"
        if not candidate.exists():
            return candidate
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:8]
    return root / f"{base_name}-{digest}"
