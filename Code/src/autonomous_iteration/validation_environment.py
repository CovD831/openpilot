"""Read-only virtual-environment binding for exact mutation validation."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
from typing import Any

from metadata import EnvironmentReadiness, EnvironmentSyncMetadata, TaskAdmissionGrant


def require_ready_validation_environment(
    admission: TaskAdmissionGrant,
    *,
    command: str,
    cwd: str,
    environment_preflight: Any,
) -> EnvironmentSyncMetadata:
    """Return a project-matching READY environment or fail closed before mutation."""

    try:
        environment = environment_preflight(
            project_path=admission.project_root,
            written_files=list(admission.write_files),
            run_command=command,
        )
    except Exception as exc:
        raise PermissionError("mutation validation requires a ready project environment") from exc
    if not isinstance(environment, EnvironmentSyncMetadata):
        raise PermissionError("mutation validation requires typed project environment evidence")
    if environment.readiness != EnvironmentReadiness.READY:
        raise PermissionError("mutation validation requires a ready project environment")
    try:
        project_root = Path(admission.project_root).expanduser().resolve(strict=False)
        requested_cwd = Path(cwd).expanduser().resolve(strict=False)
        environment_project = Path(environment.project_path).expanduser().resolve(strict=False)
        environment_cwd = Path(environment.command_cwd).expanduser().resolve(strict=False)
        python_executable = Path(environment.python_executable).expanduser().absolute()
        python_directory = python_executable.parent.absolute()
    except (TypeError, ValueError) as exc:
        raise PermissionError("mutation validation environment binding is invalid") from exc
    if environment_project != project_root or environment_cwd != requested_cwd:
        raise PermissionError("mutation validation environment does not match the admitted project")
    if not python_executable.is_file():
        raise PermissionError("mutation validation environment has no ready Python executable")
    path_value = environment.command_env.get("PATH") if isinstance(environment.command_env, dict) else ""
    path_entries = {
        str(Path(entry).expanduser().absolute())
        for entry in str(path_value or "").split(os.pathsep)
        if entry.strip()
    }
    if str(python_directory) not in path_entries:
        raise PermissionError("mutation validation environment does not bind its virtualenv PATH")
    return environment


def effective_validation_command(
    requested_command: str,
    environment: EnvironmentSyncMetadata,
) -> str:
    """Validate a command shape that the controlled virtualenv PATH will execute."""

    try:
        argv = shlex.split(requested_command, posix=True)
    except ValueError as exc:
        raise PermissionError("exact validation command cannot be bound to the project environment") from exc
    if not argv:
        raise PermissionError("exact validation command cannot be bound to the project environment")
    executable = Path(argv[0]).name.casefold()
    if executable not in {"python", "python3", "pytest"}:
        raise PermissionError("exact validation command is not supported by the project environment binding")
    # A virtualenv interpreter may itself be a legitimate symlink to the system
    # Python. Keep the exact admitted argv and bind execution through the
    # preflight-owned PATH rather than passing a resolved absolute executable to
    # the general command path guard.
    return requested_command


__all__ = ["effective_validation_command", "require_ready_validation_environment"]
