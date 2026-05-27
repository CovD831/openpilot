"""Multi File Reader Tool - Read and combine contents from multiple local files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from metadata import ToolContractMetadata, ToolInputMetadata, ToolResultMetadata, metadata_tool_result

from core.tool_contracts import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolFailureMode,
)


MULTI_FILE_READER_DEFINITION = ToolDefinition(
    name="multi_file_reader",
    display_name="Multi File Reader",
    description="Read and combine contents from multiple local files",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_READ],
    permission_level=PermissionLevel.LOW,
    contract_metadata=ToolContractMetadata(
        tool_name='multi_file_reader',
        input_metadata_type="ToolInputMetadata",
        output_metadata_type="ToolResultMetadata",
        required_input_fields=[],
        required_any_of=[["file_paths"], ["directory_path"]],
        input_defaults={'pattern': '*完成报告*.md', 'encoding': 'utf-8', 'max_total_chars': 50000},
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


@metadata_tool_result('multi_file_reader')
def multi_file_reader_executor(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
    params = input_metadata.to_params()
    """Read multiple files and combine them into one text payload."""
    file_paths = params.get("file_paths") or params.get("files")
    if not file_paths:
        directory_path_value = params.get("directory_path")
        if not directory_path_value:
            raise ValueError("multi_file_reader requires file_paths or directory_path")
        directory_path = Path(directory_path_value)
        if not directory_path.exists():
            raise FileNotFoundError(f"Directory not found: {directory_path}")
        if not directory_path.is_dir():
            raise NotADirectoryError(f"Not a directory: {directory_path}")

        pattern = params.get("pattern", "*完成报告*.md")
        recursive = params.get("recursive", False)
        max_files = params.get("max_files", 100)
        iterator = directory_path.rglob(pattern) if recursive else directory_path.glob(pattern)
        file_paths = sorted(str(path) for path in iterator if path.is_file())[:max_files]

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
