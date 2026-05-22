from __future__ import annotations

import subprocess
from types import SimpleNamespace

from autonomous_iteration.agents.iteration_agent import AutonomousIterationAgent
from autonomous_iteration.agents.project_evaluator import ProjectEvaluatorAgent
from autonomous_iteration.models import IterationResult


def _write_project(tmp_path, code: str) -> tuple[str, str]:
    app = tmp_path / "main.py"
    readme = tmp_path / "README.md"
    app.write_text(code, encoding="utf-8")
    readme.write_text("## Run\n\n```bash\npython main.py\n```\n", encoding="utf-8")
    return str(app), str(readme)


def test_interactive_guarded_slow_import_is_warning_not_failure(tmp_path, monkeypatch) -> None:
    app, readme = _write_project(
        tmp_path,
        """
import pygame

def main():
    pygame.init()

if __name__ == "__main__":
    main()
""",
    )

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=kwargs.get("args") or args[0], timeout=kwargs.get("timeout"), output="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = ProjectEvaluatorAgent(smoke_timeout_seconds=1).evaluate_project(
        goal="build snake game",
        project_path=tmp_path,
        written_files=[app],
        readme_path=readme,
        static_review={"approved": True, "issues": [], "syntax_errors": []},
    )

    assert result.validation_passed is True
    assert any("interactive import was slow" in warning for warning in result.warnings)


def test_interactive_unprotected_startup_timeout_is_failure(tmp_path, monkeypatch) -> None:
    app, readme = _write_project(
        tmp_path,
        """
import pygame

while True:
    pygame.init()
""",
    )

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=kwargs.get("args") or args[0], timeout=kwargs.get("timeout"), output="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = ProjectEvaluatorAgent(smoke_timeout_seconds=1).evaluate_project(
        goal="build snake game",
        project_path=tmp_path,
        written_files=[app],
        readme_path=readme,
        static_review={"approved": True, "issues": [], "syntax_errors": []},
    )

    assert result.validation_passed is False
    assert any("top-level event loop" in error for error in result.validation_errors)


def test_import_only_traceback_remains_failure(tmp_path, monkeypatch) -> None:
    app, readme = _write_project(
        tmp_path,
        """
import pygame

def main():
    pass

if __name__ == "__main__":
    main()
""",
    )

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="Traceback (most recent call last):\\nImportError: boom")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = ProjectEvaluatorAgent(smoke_timeout_seconds=1).evaluate_project(
        goal="build snake game",
        project_path=tmp_path,
        written_files=[app],
        readme_path=readme,
        static_review={"approved": True, "issues": [], "syntax_errors": []},
    )

    assert result.validation_passed is False
    assert any("ImportError: boom" in error for error in result.validation_errors)


def test_modification_evaluator_failure_defaults_to_project_evaluator_tool() -> None:
    agent = AutonomousIterationAgent(ProjectEvaluatorAgent())
    iteration_result = IterationResult(
        iteration=1,
        validation_passed=False,
        completed_successful_iteration=False,
        success=False,
        changed_files=["main.py"],
        failure_reason="Hard validation did not pass after modification.",
    )

    context = agent._failure_context(
        iteration_result,
        iteration=1,
        stage="Modification Evaluator",
        actions=["Validate main.py"],
        improvement_report={},
        completed_improvements=0,
    )

    assert context["failed_tool"] == "project_evaluator"
    assert iteration_result.failed_tool == "project_evaluator"
