from __future__ import annotations

import pytest
from pydantic import ValidationError

from autonomous_iteration.project_scope_admission import (
    ProjectScopeDecision,
    ProjectScopeDecisionKind,
    ProjectScopeReason,
    resolve_project_execution_scope,
)


def _repo(path) -> None:
    path.mkdir(parents=True)
    (path / ".git").mkdir()


def test_creation_from_home_uses_generated_child_project(tmp_path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    decision = resolve_project_execution_scope(
        "帮我做一个贪吃蛇游戏",
        home,
        home_path=home,
    )

    assert decision.kind is ProjectScopeDecisionKind.GENERATED_CHILD_PROJECT
    assert decision.reason_code is ProjectScopeReason.BROAD_ROOT_ARTIFACT_CREATION
    assert decision.source_root == str(home.resolve())
    assert decision.effective_root == str((home / "snake-game").resolve())


def test_generated_child_name_never_reuses_existing_directory(tmp_path) -> None:
    home = tmp_path / "home"
    (home / "snake-game").mkdir(parents=True)

    decision = resolve_project_execution_scope(
        "帮我做一个贪吃蛇游戏",
        home,
        home_path=home,
    )

    assert decision.effective_root == str((home / "snake-game-2").resolve())


def test_existing_project_at_home_requires_explicit_scope(tmp_path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    decision = resolve_project_execution_scope(
        "修复当前项目里的登录问题",
        home,
        home_path=home,
    )

    assert decision.kind is ProjectScopeDecisionKind.REQUIRE_EXPLICIT_PROJECT
    assert decision.reason_code is ProjectScopeReason.BROAD_ROOT_EXISTING_PROJECT_AMBIGUOUS


def test_existing_repository_keeps_requested_root(tmp_path) -> None:
    project = tmp_path / "calculator"
    _repo(project)

    decision = resolve_project_execution_scope("修复 calculator.py", project, home_path=tmp_path)

    assert decision.kind is ProjectScopeDecisionKind.USE_REQUESTED_ROOT
    assert decision.effective_root == str(project.resolve())


def test_multi_project_container_is_treated_as_broad_root(tmp_path) -> None:
    workspace = tmp_path / "Developer"
    _repo(workspace / "one")
    _repo(workspace / "two")

    decision = resolve_project_execution_scope(
        "build a dashboard",
        workspace,
        home_path=tmp_path / "home",
    )

    assert decision.kind is ProjectScopeDecisionKind.GENERATED_CHILD_PROJECT
    assert decision.effective_root == str((workspace / "dashboard").resolve())


def test_non_project_response_is_not_blocked_by_broad_root(tmp_path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    decision = resolve_project_execution_scope("你好", home, home_path=home)

    assert decision.kind is ProjectScopeDecisionKind.USE_REQUESTED_ROOT
    assert decision.reason_code is ProjectScopeReason.NON_PROJECT_REQUEST


def test_project_scope_decision_rejects_noncanonical_or_illegal_roots(tmp_path) -> None:
    source = tmp_path / "workspace"
    child = source / "child"

    with pytest.raises(ValidationError, match="canonical"):
        ProjectScopeDecision(
            kind=ProjectScopeDecisionKind.USE_REQUESTED_ROOT,
            reason_code=ProjectScopeReason.SAFE_REQUESTED_ROOT,
            source_root=str(source / ".." / "workspace"),
            effective_root=str(source.resolve()),
        )
    with pytest.raises(ValidationError, match="preserve"):
        ProjectScopeDecision(
            kind=ProjectScopeDecisionKind.USE_REQUESTED_ROOT,
            reason_code=ProjectScopeReason.SAFE_REQUESTED_ROOT,
            source_root=str(source.resolve()),
            effective_root=str(child.resolve()),
        )
    with pytest.raises(ValidationError, match="child"):
        ProjectScopeDecision(
            kind=ProjectScopeDecisionKind.GENERATED_CHILD_PROJECT,
            reason_code=ProjectScopeReason.BROAD_ROOT_ARTIFACT_CREATION,
            source_root=str(source.resolve()),
            effective_root=str(tmp_path.resolve()),
        )
