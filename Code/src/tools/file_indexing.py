"""Shared deterministic index refresh helpers for file mutation tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from memory.project_index import ProjectIndexManager


def refresh_after_file_change(file_path: str | Path, *, embedding_service: Any | None = None) -> dict[str, Any]:
    """Refresh sidecar file index and containing directory sketch after a write/modify."""
    return ProjectIndexManager.for_path(file_path, embedding_service=embedding_service).update_after_file_change(file_path)


def refresh_after_file_delete(file_path: str | Path, *, embedding_service: Any | None = None) -> dict[str, Any]:
    """Refresh sidecar file index and containing directory sketch after a delete."""
    return ProjectIndexManager.for_path(file_path, embedding_service=embedding_service).update_after_file_delete(file_path)
