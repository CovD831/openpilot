"""Context Loader agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from memory.context_builder import MemoryContextBuilder


DEFAULT_AUTONOMOUS_ITERATION_SYSTEM_PROMPT = (
    "You are OpenPilot's Autonomous Iteration Context Loader. Build a complete, "
    "project-wise context for the iteration pipeline. Preserve the user's original "
    "intent, prefer module-owned agents and standard tools, and include compressed "
    "dialog history, related project files, related memories, and virtual environment "
    "information before any goal, task design, decomposition, or execution step."
)


class ContextLoaderAgent:
    """Load related context from the Memory module."""

    def __init__(
        self,
        memory_context_builder: Any | None = None,
        *,
        system_prompt: str | None = None,
    ) -> None:
        self.memory_context_builder = memory_context_builder
        self.system_prompt = (
            DEFAULT_AUTONOMOUS_ITERATION_SYSTEM_PROMPT
            if system_prompt is None
            else system_prompt
        )

    def run(self, goal: str, project_path: str | Path, iteration: int = 0) -> dict[str, Any]:
        builder = self.memory_context_builder or MemoryContextBuilder()
        return builder.build(
            f"{goal} autonomous iteration {iteration}",
            project_path=project_path,
            include_environment=True,
            limit=10,
            system_prompt=self.system_prompt,
        )
