"""Multi File Reader Tool - Read and combine contents from multiple local files."""

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


MULTI_FILE_READER_DEFINITION = ToolDefinition(
    name="multi_file_reader",
    display_name="Multi File Reader",
    description="Read and combine contents from multiple local files",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_READ],
    permission_level=PermissionLevel.LOW,
    input_schema=[
        ToolInputSchema(
            name="file_paths",
            type="array",
            description="List of file paths to read",
            required=False
        ),
        ToolInputSchema(
            name="directory_path",
            type="string",
            description="Directory to scan if file_paths is omitted",
            required=False
        ),
        ToolInputSchema(
            name="pattern",
            type="string",
            description="Glob pattern used with directory_path",
            required=False,
            default="*完成报告*.md"
        ),
        ToolInputSchema(
            name="encoding",
            type="string",
            description="File encoding",
            required=False,
            default="utf-8"
        ),
        ToolInputSchema(
            name="max_total_chars",
            type="integer",
            description="Maximum combined content length",
            required=False,
            default=50000
        ),
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="Combined file contents and metadata",
        properties={
            "content": {"type": "string", "description": "Combined file contents"},
            "files": {"type": "array", "description": "Read file paths"},
            "count": {"type": "integer", "description": "Number of files read"},
            "truncated": {"type": "boolean", "description": "Whether content was truncated"},
        },
    ),
    timeout_seconds=60,
    max_retries=2,
    failure_modes=[
        ToolFailureMode(
            error_type="file_not_found",
            description="One or more files do not exist",
            recovery_strategy="Check file paths and retry"
        ),
        ToolFailureMode(
            error_type="encoding_error",
            description="Cannot decode a file with specified encoding",
            recovery_strategy="Try a different encoding"
        ),
    ],
    tags=["file", "read", "batch", "local", "io"],
    audit_required=True,
)


def multi_file_reader_executor(params: dict[str, Any]) -> dict[str, Any]:
    """Read multiple files and combine them into one text payload."""
    from tools.directory_lister import directory_lister_executor

    file_paths = params.get("file_paths") or params.get("files")
    if not file_paths:
        directory_path = params.get("directory_path")
        if not directory_path:
            raise ValueError("multi_file_reader requires file_paths or directory_path")
        pattern = params.get("pattern", "*完成报告*.md")
        directory_result = directory_lister_executor(
            {
                "directory_path": directory_path,
                "pattern": pattern,
                "recursive": params.get("recursive", False),
                "max_files": params.get("max_files", 100),
            }
        )
        file_paths = directory_result["files"]

    encoding = params.get("encoding", "utf-8")
    max_total_chars = params.get("max_total_chars", 50000)
    combined_parts: list[str] = []
    read_files: list[str] = []
    total_chars = 0
    truncated = False

    for file_path_value in file_paths:
        file_path = Path(file_path_value)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        if not file_path.is_file():
            continue

        content = file_path.read_text(encoding=encoding)
        header = f"\n\n# Source: {file_path}\n\n"
        remaining = max_total_chars - total_chars
        if remaining <= 0:
            truncated = True
            break

        chunk = header + content
        if len(chunk) > remaining:
            chunk = chunk[:remaining]
            truncated = True

        combined_parts.append(chunk)
        read_files.append(str(file_path))
        total_chars += len(chunk)

        if truncated:
            break

    return {
        "content": "".join(combined_parts).strip(),
        "files": read_files,
        "count": len(read_files),
        "truncated": truncated,
        "encoding": encoding,
    }
