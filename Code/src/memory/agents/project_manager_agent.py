"""Project Manager agent facade."""

from __future__ import annotations

from pathlib import Path

from memory.project_manager import ProjectManager


class ProjectManagerAgent:
    """Expose project sketch update and search functions."""

    def __init__(self, manager: ProjectManager | None = None, root_path: str | Path = ".") -> None:
        self.manager = manager or ProjectManager(root_path)

    def update(self, modified_path: str | Path) -> dict:
        """Update sketch.json for a modified file or directory."""
        return self.manager.update(modified_path)

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search related project files."""
        return self.manager.search(query, limit=limit)
