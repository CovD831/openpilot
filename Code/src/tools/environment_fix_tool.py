"""Environment Fix Tool - diagnose and repair project-local setup failures."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.tool_contracts import PermissionLevel, ToolCapability, ToolDefinition, ToolFailureMode
from metadata import (
    EnvironmentFailureMetadata,
    EnvironmentFixResultMetadata,
    FailureMetadata,
    ResultStatus,
    ToolContractMetadata,
    ToolInputMetadata,
    ToolResultMetadata,
    metadata_tool_result,
)
from tools.command_tool import command_executor


ENVIRONMENT_FIX_TOOL_DEFINITION = ToolDefinition(
    name="environment_fix_tool",
    display_name="Environment Fix Tool",
    description="Diagnose and repair project-local Python environment setup failures",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_READ, ToolCapability.FILE_WRITE, ToolCapability.SHELL_EXECUTION],
    permission_level=PermissionLevel.HIGH,
    contract_metadata=ToolContractMetadata(
        tool_name="environment_fix_tool",
        input_metadata_type="ToolInputMetadata",
        output_metadata_type="ToolResultMetadata",
        required_input_fields=["project_path"],
        input_defaults={"encoding": "utf-8"},
    ),
    timeout_seconds=60,
    max_retries=0,
    failure_modes=[
        ToolFailureMode(
            error_type="unsupported_environment_failure",
            description="The setup failure was not recognized as a repairable Python environment issue",
            recovery_strategy="Show the root cause and ask the user for a manual recovery command.",
        ),
    ],
    tags=["environment", "pip", "requirements", "repair"],
    audit_required=True,
)


@metadata_tool_result("environment_fix_tool")
def environment_fix_tool_executor(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
    params = input_metadata.to_params()
    project_path = Path(str(params["project_path"])).expanduser()
    error_text = str(params.get("stderr") or params.get("text") or params.get("context") or "")
    if not error_text:
        error_text = str(params.get("error_message") or "")

    diagnosis = diagnose_environment_failure(project_path, error_text)
    changed_files: list[str] = []
    repair_actions: list[str] = []
    applied = False

    if diagnosis.error_type == "invalid_requirements_file" and diagnosis.affected_file:
        target = Path(diagnosis.affected_file).expanduser()
        if target.exists() and target.is_file():
            original = target.read_text(encoding=str(params.get("encoding") or "utf-8"))
            updated, removed = _sanitize_requirements(original, diagnosis.line_number)
            if updated != original:
                target.write_text(updated, encoding=str(params.get("encoding") or "utf-8"))
                changed_files.append(str(target))
                repair_actions.append(
                    f"Removed invalid requirement line(s) from {target.name}: {', '.join(removed)}"
                )
                applied = True

    command_executed = False
    user_declined = False
    if not applied and diagnosis.suggested_command:
        try:
            command_result = command_executor(
                ToolInputMetadata.from_mapping(
                    "command_executor",
                    {
                        "command": diagnosis.suggested_command,
                        "mode": "automatic",
                        "cwd": str(project_path),
                        "_command_approval_callback": params.get("_command_approval_callback"),
                    },
                )
            )
            command_executed = True
            command_payload = command_result.result
            if getattr(command_payload, "success", False):
                repair_actions.append(f"Executed environment repair command: {diagnosis.suggested_command}")
                applied = True
            else:
                repair_actions.append(
                    "Environment repair command failed: "
                    f"{getattr(command_payload, 'stderr', '') or getattr(command_payload, 'stdout', '')}"
                )
        except PermissionError as exc:
            user_declined = True
            repair_actions.append(str(exc))

    result = EnvironmentFixResultMetadata(
        project_path=str(project_path),
        environment_failure=diagnosis,
        applied=applied,
        changed_files=changed_files,
        repair_actions=repair_actions,
        suggested_command=diagnosis.suggested_command,
        command_executed=command_executed,
        requires_confirmation=diagnosis.requires_confirmation,
        user_declined=user_declined,
    )
    if applied:
        return ToolResultMetadata(tool_name="environment_fix_tool", status=ResultStatus.SUCCESS, result=result)

    return ToolResultMetadata(
        tool_name="environment_fix_tool",
        status=ResultStatus.FAIL,
        result=result,
        failure=FailureMetadata(
            error_type="UnsupportedEnvironmentFailure",
            error_message=diagnosis.root_cause or "Environment setup failed, but no automatic repair was available.",
            recoverable=True,
            retry_recommended=False,
            recovery_strategy=diagnosis.suggested_command or "Inspect the environment error and repair project dependencies manually.",
            details={
                "root_cause": diagnosis.root_cause,
                "affected_file": diagnosis.affected_file,
                "suggested_command": diagnosis.suggested_command,
                "pip_notices": diagnosis.pip_notices,
            },
        ),
    )


def diagnose_environment_failure(project_path: Path, error_text: str) -> EnvironmentFailureMetadata:
    """Extract a useful root cause from pip/venv setup output."""
    lines = [line.rstrip() for line in str(error_text or "").splitlines()]
    pip_notices = [line.strip() for line in lines if line.strip().startswith("[notice]")]
    non_notice_lines = [line for line in lines if line.strip() and not line.strip().startswith("[notice]")]
    root_cause = _first_error_line(non_notice_lines) or "\n".join(non_notice_lines[:3]).strip() or str(error_text).strip()

    invalid_requirement = re.search(
        r"ERROR:\s+Invalid requirement:\s+(?P<requirement>.+?)(?:\n|$).*?\(from line (?P<line>\d+) of (?P<path>[^)]+)\)",
        str(error_text),
        flags=re.DOTALL,
    )
    if invalid_requirement:
        affected_file = invalid_requirement.group("path").strip()
        line_number = int(invalid_requirement.group("line"))
        return EnvironmentFailureMetadata(
            raw_stderr=str(error_text or ""),
            root_cause=_first_error_line(non_notice_lines) or f"Invalid requirement in {affected_file}:{line_number}",
            error_type="invalid_requirements_file",
            affected_file=affected_file,
            line_number=line_number,
            pip_notices=pip_notices,
            suggested_command=f"Fix invalid requirement in {affected_file}, then rerun pip install -r requirements.txt",
            requires_confirmation=False,
        )

    command_match = re.search(r"To update, run:\s*(?P<command>.+)", str(error_text))
    suggested_command = command_match.group("command").strip() if command_match else ""
    return EnvironmentFailureMetadata(
        raw_stderr=str(error_text or ""),
        root_cause=root_cause,
        error_type="environment_setup_failed",
        affected_file=_extract_existing_requirements_path(project_path, str(error_text)),
        pip_notices=pip_notices,
        suggested_command=suggested_command,
        requires_confirmation=bool(suggested_command and _command_needs_confirmation(suggested_command, project_path)),
    )


def _first_error_line(lines: list[str]) -> str:
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("ERROR:"):
            return stripped
    for line in lines:
        stripped = line.strip()
        if "error" in stripped.lower():
            return stripped
    return ""


def _extract_existing_requirements_path(project_path: Path, text: str) -> str:
    match = re.search(r"(/[^\s)]+requirements\.txt)", text)
    if match:
        return match.group(1)
    candidate = project_path / "requirements.txt"
    return str(candidate) if candidate.exists() else ""


def _sanitize_requirements(content: str, line_number: int | None) -> tuple[str, list[str]]:
    lines = content.splitlines(keepends=True)
    removed: list[str] = []
    updated: list[str] = []
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        should_remove = stripped in {'"""', "'''", "```"} or stripped.startswith('"""') or stripped.startswith("'''")
        if line_number is not None and index == line_number and not _looks_like_requirement(stripped):
            should_remove = True
        if should_remove:
            removed.append(f"{index}: {stripped}")
            continue
        updated.append(line)
    return "".join(updated), removed


def _looks_like_requirement(value: str) -> bool:
    if not value or value.startswith("#"):
        return True
    if value.startswith(("-", "--")):
        return True
    if "://" in value or value.startswith(("git+", "file:")):
        return True
    return bool(re.match(r"^[A-Za-z0-9_.-]+(\s*(==|>=|<=|~=|!=|>|<).*)?(\[.*\])?$", value))


def _command_needs_confirmation(command: str, project_path: Path) -> bool:
    lowered = f" {command.lower()} "
    if re.search(r"(^|\s)(sudo|su)\b", lowered):
        return True
    if any(path in lowered for path in (" /usr", " /system", " /library", " /opt/homebrew")):
        return True
    if re.search(r"(^|\s)(brew|apt|apt-get|yum|dnf|pacman)\b", lowered):
        return True
    if " pip install" in lowered and ".venv" not in lowered and str(project_path) not in command:
        return True
    return False
