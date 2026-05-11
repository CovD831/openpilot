"""File Reader Tool - Read contents from a local file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from models.tool_models import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolFailureMode,
    ToolInputSchema,
    ToolOutputSchema,
)


FILE_READER_DEFINITION = ToolDefinition(
    name="file_reader",
    display_name="File Reader",
    description="Read contents from a local file",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_READ],
    permission_level=PermissionLevel.LOW,
    input_schema=[
        ToolInputSchema(
            name="file_path",
            type="string",
            description="Absolute or relative path to the file",
            required=True
        ),
        ToolInputSchema(
            name="encoding",
            type="string",
            description="File encoding (default: utf-8)",
            required=False,
            default="utf-8"
        ),
        ToolInputSchema(
            name="max_size_mb",
            type="integer",
            description="Maximum file size in MB (default: 10)",
            required=False,
            default=10
        )
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="File contents and metadata",
        properties={
            "content": {"type": "string", "description": "File contents"},
            "size_bytes": {"type": "integer", "description": "File size in bytes"},
            "encoding": {"type": "string", "description": "File encoding used"}
        }
    ),
    timeout_seconds=30,
    max_retries=2,
    failure_modes=[
        ToolFailureMode(
            error_type="file_not_found",
            description="File does not exist",
            recovery_strategy="Check file path and try again"
        ),
        ToolFailureMode(
            error_type="permission_denied",
            description="No permission to read file",
            recovery_strategy="Check file permissions"
        ),
        ToolFailureMode(
            error_type="file_too_large",
            description="File exceeds maximum size",
            recovery_strategy="Increase max_size_mb or read file in chunks"
        ),
        ToolFailureMode(
            error_type="encoding_error",
            description="Cannot decode file with specified encoding",
            recovery_strategy="Try different encoding (e.g., latin-1, gbk)"
        )
    ],
    tags=["file", "read", "local", "io"],
    audit_required=True
)


def file_reader_executor(params: dict[str, Any]) -> dict[str, Any]:
    """
    Execute file reader tool.

    Args:
        params: Tool parameters (file_path, encoding, max_size_mb)

    Returns:
        Dictionary with content, size_bytes, encoding

    Raises:
        FileNotFoundError: If file doesn't exist
        PermissionError: If no read permission
        ValueError: If file too large or encoding error
    """
    file_path = Path(params["file_path"])
    encoding = params.get("encoding", "utf-8")
    max_size_mb = params.get("max_size_mb", 10)

    # Check file exists
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Check file size
    size_bytes = file_path.stat().st_size
    max_size_bytes = max_size_mb * 1024 * 1024
    if size_bytes > max_size_bytes:
        raise ValueError(
            f"File too large: {size_bytes} bytes "
            f"(max: {max_size_bytes} bytes)"
        )

    # Read file
    try:
        content = file_path.read_text(encoding=encoding)
    except PermissionError as e:
        raise PermissionError(f"No permission to read file: {file_path}") from e
    except UnicodeDecodeError as e:
        raise ValueError(
            f"Cannot decode file with encoding '{encoding}': {e}"
        ) from e

    return {
        "content": content,
        "size_bytes": size_bytes,
        "encoding": encoding
    }
