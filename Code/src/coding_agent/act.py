"""Action execution for the standalone coding agent."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Protocol, Sequence

from coding_agent.contract import CodingAction, CodingActionKind, CodingActionResult


class WorkspaceAdapter(Protocol):
    root: Path

    def exists(self, path: str) -> bool:
        ...

    def read_text(self, path: str) -> str:
        ...

    def write_text(self, path: str, content: str, *, overwrite: bool = True) -> str:
        ...

    def replace_text(
        self,
        path: str,
        content: str,
        *,
        line_start: int | None = None,
        line_end: int | None = None,
        overwrite: bool = True,
    ) -> str:
        ...

    def run_command(self, command: Sequence[str], *, cwd: str | None = None) -> tuple[int, str, str]:
        ...


def _execute_action(adapter: WorkspaceAdapter, action: CodingAction) -> CodingActionResult:
    if action.kind == CodingActionKind.READ:
        if not action.path:
            return CodingActionResult(action=action, success=False, summary="missing path")
        text = adapter.read_text(action.path)
        return CodingActionResult(action=action, success=True, summary=f"read {len(text)} chars", text=text)

    if action.kind == CodingActionKind.WRITE:
        if not action.path:
            return CodingActionResult(action=action, success=False, summary="missing path")
        if not action.content:
            return CodingActionResult(action=action, success=False, summary="missing content")
        text = adapter.write_text(action.path, action.content, overwrite=action.overwrite)
        return CodingActionResult(action=action, success=True, summary=f"wrote {len(text)} chars", text=text)

    if action.kind == CodingActionKind.PATCH:
        if not action.path:
            return CodingActionResult(action=action, success=False, summary="missing path")
        if not action.content:
            return CodingActionResult(action=action, success=False, summary="missing patch content")
        text = adapter.replace_text(
            action.path,
            action.content,
            line_start=action.line_start,
            line_end=action.line_end,
            overwrite=action.overwrite,
        )
        return CodingActionResult(action=action, success=True, summary=f"patched {len(text)} chars", text=text)

    if action.kind == CodingActionKind.RUN:
        if not action.command:
            return CodingActionResult(action=action, success=False, summary="missing command")
        exit_code, stdout, stderr = adapter.run_command(action.command, cwd=None)
        success = exit_code == 0
        summary = "command passed" if success else f"command failed with exit code {exit_code}"
        return CodingActionResult(
            action=action,
            success=success,
            summary=summary,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
        )

    return CodingActionResult(action=action, success=True, summary=action.reason or "stopped")


def execute_action(adapter: WorkspaceAdapter, action: CodingAction) -> CodingActionResult:
    """Execute one action while preserving boundary failures as evidence."""
    try:
        return _execute_action(adapter, action)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return CodingActionResult(
            action=action,
            success=False,
            summary=f"blocked: {exc}",
            stderr=str(exc),
        )
