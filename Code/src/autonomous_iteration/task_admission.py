"""Deterministic admission of designer-proposed CLI task scopes.

The designer may suggest task scopes, but this module is the only producer of
the immutable task admission snapshot consumed by the Pi entry path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex
from typing import Iterable, Sequence
from uuid import uuid4

from autonomous_iteration.task_models import Task
from metadata import TaskAdmissionGrant, TaskGraphNodeMetadata, ValidationGrant
from utils.file_mutation_preconditions import (
    FileMutationPreconditionError,
    capture_file_mutation_precondition,
)
from utils.path_boundary import PathBoundaryError, resolve_project_path, resolve_within_project


class TaskAdmissionError(ValueError):
    """Raised when candidate task scopes cannot become executable authority."""


@dataclass(frozen=True)
class TaskAdmission:
    """One admitted root task plus its owned immutable grant."""

    task: TaskGraphNodeMetadata

    @property
    def grant(self) -> TaskAdmissionGrant:
        assert self.task.admission is not None
        return self.task.admission

    @property
    def is_mutation(self) -> bool:
        return self.grant.is_mutation


_SHELL_CONTROL_CHARACTERS = frozenset(";|&><\n\r")
_DISALLOWED_VALIDATION_EXECUTABLES = frozenset(
    {
        "bash",
        "curl",
        "dd",
        "env",
        "git",
        "nc",
        "rm",
        "scp",
        "sh",
        "ssh",
        "wget",
        "zsh",
    }
)
_PYTHON_VALIDATION_MODULES = frozenset({"compileall", "pytest", "unittest"})


def admit_task_plan(
    *,
    task_id: str,
    goal: str,
    tasks: Sequence[Task],
    project_root: str | Path,
    policy_revision: int = 1,
) -> TaskAdmission:
    """Validate a designer task list and issue one canonical CLI task grant.

    The admission is intentionally conservative: only existing, non-symlink
    files under the declared root are admissible, every write requires prior
    declared read evidence, and mutation work requires exactly one safe exact
    validation command.
    """

    root = resolve_project_path(project_root)
    if not str(task_id).strip():
        raise TaskAdmissionError("task_id is required")
    if not str(goal).strip():
        raise TaskAdmissionError("goal is required")
    if not tasks:
        raise TaskAdmissionError("task design produced no tasks")

    read_files = _canonical_scope(
        _paths_from_tasks(tasks, "read_files"),
        root,
        label="read scope",
    )
    write_files = _canonical_scope(
        _paths_from_tasks(tasks, "write_files"),
        root,
        label="write scope",
    )
    if write_files and not set(write_files).issubset(set(read_files)):
        raise TaskAdmissionError("mutation task admission requires declared read-before-write evidence")
    if not read_files:
        raise TaskAdmissionError("task admission requires a non-empty read scope")

    validation_commands = _unique(
        str(getattr(task, "validation_command", "") or "").strip()
        for task in tasks
        if str(getattr(task, "validation_command", "") or "").strip()
    )
    validation: ValidationGrant | None = None
    if write_files:
        if len(validation_commands) != 1:
            raise TaskAdmissionError("mutation task admission requires one exact validation command")
        validation = ValidationGrant(
            command=_admit_validation_command(validation_commands[0]),
            cwd=str(root),
        )
    elif validation_commands:
        raise TaskAdmissionError("read-only task admission must not request validation execution")

    grant = TaskAdmissionGrant(
        admission_id=f"admission_{uuid4().hex}",
        task_id=task_id,
        project_root=str(root),
        policy_revision=policy_revision,
        read_files=read_files,
        write_files=write_files,
        validation=validation,
        write_preconditions=_capture_mutation_preconditions(write_files),
    )
    task = TaskGraphNodeMetadata(
        task_id=task_id,
        description=goal,
        task_kind="implement" if grant.is_mutation else "inspect",
        read_files=read_files,
        write_files=write_files,
        validation_command=validation.command if validation else "",
        can_run_parallel=not grant.is_mutation,
        admission=grant,
    )
    return TaskAdmission(task=task)


def _paths_from_tasks(tasks: Sequence[Task], field_name: str) -> Iterable[str]:
    for task in tasks:
        for raw_path in getattr(task, field_name, ()) or ():
            text = str(raw_path or "").strip()
            if text:
                yield text


def _canonical_scope(raw_paths: Iterable[str], root: Path, *, label: str) -> list[str]:
    resolved: list[str] = []
    for raw_path in _unique(raw_paths):
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        if candidate.is_symlink():
            raise TaskAdmissionError(f"{label} rejects symlink path: {candidate}")
        try:
            resolved_path = resolve_within_project(raw_path, root)
        except PathBoundaryError as exc:
            raise TaskAdmissionError(f"{label} path is outside the project: {raw_path}") from exc
        if not resolved_path.exists() or not resolved_path.is_file():
            raise TaskAdmissionError(f"{label} requires an existing regular file: {raw_path}")
        resolved.append(str(resolved_path))
    return resolved


def _unique(values: Iterable[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            ordered.append(text)
            seen.add(text)
    return ordered


def _capture_mutation_preconditions(write_files: Sequence[str]) -> list:
    snapshots = []
    for path in write_files:
        try:
            snapshots.append(capture_file_mutation_precondition(path))
        except FileMutationPreconditionError as exc:
            raise TaskAdmissionError(
                f"mutation write target cannot receive a file precondition: {path}"
            ) from exc
    return snapshots


def _admit_validation_command(command: str) -> str:
    if not command or any(character in command for character in _SHELL_CONTROL_CHARACTERS):
        raise TaskAdmissionError("validation command is not an admitted exact command")
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as exc:
        raise TaskAdmissionError("validation command is not parseable") from exc
    if not argv:
        raise TaskAdmissionError("validation command is required")
    executable = Path(argv[0]).name.casefold()
    if executable in _DISALLOWED_VALIDATION_EXECUTABLES:
        raise TaskAdmissionError("validation command executable is not allowed")
    if executable in {"python", "python3"}:
        if len(argv) < 3 or argv[1] != "-m" or argv[2] not in _PYTHON_VALIDATION_MODULES:
            raise TaskAdmissionError("validation command is not an admitted Python validation module")
    elif executable not in {"pytest"}:
        raise TaskAdmissionError("validation command executable is not allowed")
    return command
