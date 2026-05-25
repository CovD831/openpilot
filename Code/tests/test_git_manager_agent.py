from __future__ import annotations

import shutil

import pytest

from memory.agents.git_manager_agent import GitManagerAgent


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def test_git_manager_initializes_repo_and_ignores_venv(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (project / ".venv").mkdir()
    (project / ".venv" / "secret.txt").write_text("ignore me", encoding="utf-8")

    repository, snapshot = GitManagerAgent().ensure_repository(project)

    assert repository.initialized is True
    assert (project / ".git").exists()
    assert ".venv/" in (project / ".gitignore").read_text(encoding="utf-8")
    assert snapshot is not None
    assert snapshot.commit_hash
    assert "app.py" in snapshot.changed_files or ".gitignore" in snapshot.changed_files
    assert not any(".venv" in item for item in snapshot.changed_files)


def test_git_manager_snapshot_and_diff_context(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    app = project / "app.py"
    app.write_text("print('one')\n", encoding="utf-8")
    manager = GitManagerAgent()
    _, baseline = manager.ensure_repository(project)
    app.write_text("print('two')\n", encoding="utf-8")

    diff = manager.diff_context(project, base_ref=baseline.commit_hash, target_files=[str(app)])
    snapshot = manager.snapshot(project, reason="before_test_write", target_files=[str(app)])

    assert "app.py" in diff.diff_stat
    assert "print('two')" in diff.diff_preview
    assert snapshot.created is True
    assert snapshot.commit_hash
    assert "app.py" in snapshot.changed_files


def test_git_manager_snapshot_skips_when_clean(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("print('ok')\n", encoding="utf-8")
    manager = GitManagerAgent()
    manager.ensure_repository(project)

    snapshot = manager.snapshot(project, reason="clean")

    assert snapshot.skipped is True
    assert snapshot.created is False
    assert snapshot.commit_hash
