"""Memory Context Tool - Build structured context for agent prompts."""

from __future__ import annotations

from typing import Any

from memory.context_builder import MemoryContextBuilder
from core.tool_contracts import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolFailureMode,
    ToolInputSchema,
    ToolOutputSchema,
)


MEMORY_CONTEXT_TOOL_DEFINITION = ToolDefinition(
    name="memory_context",
    display_name="Memory Context",
    description="Build dialog, memory, project file, and environment context for an agent query",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_READ],
    permission_level=PermissionLevel.LOW,
    input_schema=[
        ToolInputSchema(
            name="query",
            type="string",
            description="Query used to retrieve relevant memory and files",
            required=True,
        ),
        ToolInputSchema(
            name="project_path",
            type="string",
            description="Project directory to sketch and search",
            required=False,
            default=".",
        ),
        ToolInputSchema(
            name="include_environment",
            type="boolean",
            description="Include project environment memories",
            required=False,
            default=True,
        ),
        ToolInputSchema(
            name="limit",
            type="integer",
            description="Maximum memories/files/messages to include",
            required=False,
            default=10,
        ),
        ToolInputSchema(
            name="system_prompt",
            type="string",
            description="Optional system prompt to prepend to prompt_text",
            required=False,
            default="",
        ),
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="Structured memory context and prompt text",
        properties={
            "system_prompt": {"type": "string"},
            "dialog_context": {"type": "array"},
            "related_memories": {"type": "array"},
            "related_files": {"type": "array"},
            "environment_context": {"type": "array"},
            "prompt_text": {"type": "string"},
        },
    ),
    timeout_seconds=30,
    max_retries=1,
    failure_modes=[
        ToolFailureMode(
            error_type="invalid_input",
            description="Context query or project path is invalid",
            recovery_strategy="Provide a non-empty query and an existing project directory when project context is needed",
        ),
        ToolFailureMode(
            error_type="context_build_failed",
            description="Memory context could not be built",
            recovery_strategy="Check MemoryStore data files and project path permissions",
        ),
    ],
    tags=["memory", "context", "project", "environment"],
    audit_required=True,
)


def memory_context_executor(params: dict[str, Any]) -> dict[str, Any]:
    """Execute the memory context builder tool."""
    query = str(params.get("query") or "").strip()
    if not query:
        raise ValueError("Invalid input: query is required")

    builder = params.get("_memory_context_builder")
    if builder is None:
        builder = MemoryContextBuilder(
            short_memory=params.get("_short_memory"),
            memory_store=params.get("_memory_store"),
            memory_vault_agent=params.get("_memory_vault_agent"),
            project_manager=params.get("_project_manager"),
        )

    return builder.build(
        query,
        project_path=params.get("project_path") or ".",
        include_environment=bool(params.get("include_environment", True)),
        limit=int(params.get("limit", 10)),
        system_prompt=str(params.get("system_prompt") or ""),
    )
