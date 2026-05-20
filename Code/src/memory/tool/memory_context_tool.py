"""Memory Context Tool - Build structured context for agent prompts."""

from __future__ import annotations

from typing import Any

from metadata import ToolContractMetadata, ToolInputMetadata, ToolResultMetadata, metadata_tool_result

from memory.context_builder import MemoryContextBuilder
from core.tool_contracts import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolFailureMode,
)


MEMORY_CONTEXT_TOOL_DEFINITION = ToolDefinition(
    name="memory_context",
    display_name="Memory Context",
    description="Build dialog, memory, project file, and environment context for an agent query",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_READ],
    permission_level=PermissionLevel.LOW,
    contract_metadata=ToolContractMetadata(
        tool_name='memory_context',
        input_metadata_type="ToolInputMetadata",
        output_metadata_type="ToolResultMetadata",
        required_input_fields=['query'],
        input_defaults={'project_path': '.', 'include_environment': True, 'limit': 10, 'system_prompt': ''},
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


@metadata_tool_result('memory_context')
def memory_context_executor(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
    params = input_metadata.to_params()
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
