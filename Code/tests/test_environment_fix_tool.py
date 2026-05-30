from __future__ import annotations

import pytest

from core.command_approval import CommandApprovalGate
from metadata import ResultStatus, ToolInputMetadata
from tools.command_tool import command_executor
from tools.environment_fix_tool import diagnose_environment_failure, environment_fix_tool_executor


PIP_INVALID_REQUIREMENT_ERROR = """
[notice] A new release of pip is available: 25.3 -> 26.1.1
[notice] To update, run: /tmp/project/.venv/bin/python -m pip install --upgrade pip
ERROR: Invalid requirement: '\"\"\"': Expected package name at the start of dependency specifier
    \"\"\"
    ^ (from line 2 of /tmp/project/requirements.txt)
"""


def test_environment_failure_diagnosis_prefers_error_over_pip_notice(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    requirements = project / "requirements.txt"
    requirements.write_text("rich\n\"\"\"\n", encoding="utf-8")
    error = PIP_INVALID_REQUIREMENT_ERROR.replace("/tmp/project", str(project))

    diagnosis = diagnose_environment_failure(project, error)

    assert diagnosis.error_type == "invalid_requirements_file"
    assert diagnosis.affected_file == str(requirements)
    assert diagnosis.line_number == 2
    assert diagnosis.root_cause.startswith("ERROR: Invalid requirement")
    assert diagnosis.pip_notices
    assert "new release of pip" not in diagnosis.root_cause


def test_environment_fix_tool_sanitizes_invalid_requirements_line(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    requirements = project / "requirements.txt"
    requirements.write_text("rich\n\"\"\"\nrequests>=2\n", encoding="utf-8")
    error = PIP_INVALID_REQUIREMENT_ERROR.replace("/tmp/project", str(project))

    result = environment_fix_tool_executor(
        ToolInputMetadata.from_mapping(
            "environment_fix_tool",
            {"project_path": str(project), "stderr": error},
        )
    )

    assert result.status == ResultStatus.SUCCESS
    assert result.result.applied is True
    assert result.result.changed_files == [str(requirements)]
    assert requirements.read_text(encoding="utf-8") == "rich\nrequests>=2\n"


def test_command_approval_gate_requires_user_for_sudo_and_allows_local_venv_pip(tmp_path) -> None:
    gate = CommandApprovalGate()
    local = gate.evaluate(f"{tmp_path}/.venv/bin/python -m pip install -r requirements.txt", cwd=str(tmp_path))
    risky = gate.evaluate("sudo pip install rich", cwd=str(tmp_path))

    assert local.auto_approved is True
    assert local.requires_confirmation is False
    assert risky.requires_confirmation is True
    assert risky.risk_level == "high"


def test_command_executor_stops_when_user_declines_high_risk_command(tmp_path) -> None:
    approvals = []

    with pytest.raises(PermissionError) as exc:
        command_executor(
            ToolInputMetadata.from_mapping(
                "command_executor",
                {
                    "command": "sudo pip install rich",
                    "mode": "automatic",
                    "cwd": str(tmp_path),
                    "_command_approval_callback": lambda decision: approvals.append(decision.command) or False,
                },
            )
        )

    assert approvals == ["sudo pip install rich"]
    assert "User declined command execution" in str(exc.value)


def test_command_executor_runs_after_user_approves_high_risk_command(tmp_path) -> None:
    approvals = []

    result = command_executor(
        ToolInputMetadata.from_mapping(
            "command_executor",
            {
                "command": "sudo --version",
                "mode": "automatic",
                "cwd": str(tmp_path),
                "_command_approval_callback": lambda decision: approvals.append(decision.command) or True,
            },
        )
    )

    assert approvals == ["sudo --version"]
    assert result.result.attributes["command_approval"]["requires_confirmation"] is True
