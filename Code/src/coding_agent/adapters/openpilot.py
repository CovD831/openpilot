"""A tiny workspace adapter for the OpenPilot checkout."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Sequence


class OpenPilotWorkspaceAdapter:
    """Local filesystem and command adapter bound to one workspace root."""

    def __init__(self, workspace_root: str | Path):
        self.root = Path(workspace_root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    def read_text(self, path: str) -> str:
        return self._resolve(path).read_text(encoding="utf-8")

    def write_text(self, path: str, content: str, *, overwrite: bool = True) -> str:
        target = self._resolve(path)
        if target.exists() and not overwrite:
            raise FileExistsError(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target.read_text(encoding="utf-8")

    def replace_text(
        self,
        path: str,
        content: str,
        *,
        line_start: int | None = None,
        line_end: int | None = None,
        overwrite: bool = True,
    ) -> str:
        target = self._resolve(path)
        if not target.exists():
            return self.write_text(path, content, overwrite=overwrite)
        if line_start is None or line_end is None:
            return self.write_text(path, content, overwrite=overwrite)
        original = target.read_text(encoding="utf-8")
        lines = original.splitlines()
        if line_start < 1 or line_end < line_start or line_end > len(lines):
            raise ValueError(f"invalid replacement range: {line_start}-{line_end}")
        replacement_lines = content.splitlines()
        updated_lines = lines[: line_start - 1] + replacement_lines + lines[line_end:]
        updated = "\n".join(updated_lines)
        if original.endswith("\n") or updated:
            updated += "\n"
        target.write_text(updated, encoding="utf-8")
        return target.read_text(encoding="utf-8")

    def run_command(self, command: Sequence[str], *, cwd: str | None = None) -> tuple[int, str, str]:
        if not command:
            raise ValueError("command must not be empty")
        working_dir = self.root if cwd is None else self._resolve(cwd)
        completed = subprocess.run(
            list(command),
            cwd=str(working_dir),
            check=False,
            capture_output=True,
            text=True,
        )
        return completed.returncode, completed.stdout, completed.stderr

    def _resolve(self, path: str | Path) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise ValueError(f"path escapes workspace root: {path}")
        return resolved
