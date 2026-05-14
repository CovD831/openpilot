"""Directory Lister Tool - List local files in a directory using a glob pattern."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.tool_models import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolFailureMode,
    ToolInputSchema,
    ToolOutputSchema,
)


DIRECTORY_LISTER_DEFINITION = ToolDefinition(
    name="directory_lister",
    display_name="Directory Lister",
    description="List local files in a directory using a glob pattern",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_READ],
    permission_level=PermissionLevel.LOW,
    input_schema=[
        ToolInputSchema(
            name="directory_path",
            type="string",
            description="Absolute or relative directory path",
            required=True
        ),
        ToolInputSchema(
            name="pattern",
            type="string",
            description="Glob pattern for files",
            required=False,
            default="*完成报告*.md"
        ),
        ToolInputSchema(
            name="recursive",
            type="boolean",
            description="Search recursively",
            required=False,
            default=False
        ),
        ToolInputSchema(
            name="max_files",
            type="integer",
            description="Maximum number of files to return",
            required=False,
            default=100
        ),
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="Matched file paths and metadata",
        properties={
            "directory_path": {"type": "string", "description": "Directory searched"},
            "pattern": {"type": "string", "description": "Glob pattern used"},
            "files": {"type": "array", "description": "Matched file paths"},
            "count": {"type": "integer", "description": "Number of matched files"},
            "truncated": {"type": "boolean", "description": "Whether results were truncated"},
        },
    ),
    timeout_seconds=30,
    max_retries=2,
    failure_modes=[
        ToolFailureMode(
            error_type="directory_not_found",
            description="Directory does not exist",
            recovery_strategy="Check directory path and try again"
        ),
        ToolFailureMode(
            error_type="not_a_directory",
            description="Path exists but is not a directory",
            recovery_strategy="Provide a directory path"
        ),
    ],
    tags=["directory", "list", "file", "local", "io"],
    audit_required=True,
)


def directory_lister_executor(params: dict[str, Any]) -> dict[str, Any]:
    """List files in a directory."""
    directory_path = Path(params["directory_path"])
    pattern = params.get("pattern", "*完成报告*.md")
    recursive = params.get("recursive", False)
    max_files = params.get("max_files", 100)

    if not directory_path.exists():
        raise FileNotFoundError(f"Directory not found: {directory_path}")
    if not directory_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory_path}")

    iterator = directory_path.rglob(pattern) if recursive else directory_path.glob(pattern)
    matched = sorted(str(path) for path in iterator if path.is_file())
    truncated = len(matched) > max_files

    return {
        "directory_path": str(directory_path),
        "pattern": pattern,
        "files": matched[:max_files],
        "count": min(len(matched), max_files),
        "total_count": len(matched),
        "truncated": truncated,
    }
