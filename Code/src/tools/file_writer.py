"""File Writer Tool - Write contents to a local file."""

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


FILE_WRITER_DEFINITION = ToolDefinition(
    name="file_writer",
    display_name="File Writer",
    description="Write contents to a local file",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_WRITE],
    permission_level=PermissionLevel.MEDIUM,
    contract_metadata=ToolContractMetadata(
        tool_name='file_writer',
        input_metadata_type="ToolInputMetadata",
        output_metadata_type="ToolResultMetadata",
        required_input_fields=['file_path', 'content'],
        input_defaults={'encoding': 'utf-8', 'create_dirs': True, 'overwrite': True, 'operation_kind': 'create_file'},
    ),
    timeout_seconds=30,
    max_retries=2,
    failure_modes=[
        ToolFailureMode(
            error_type="permission_denied",
            description="No permission to write file",
            recovery_strategy="Check file/directory permissions"
        ),
        ToolFailureMode(
            error_type="file_exists",
            description="File exists and overwrite=False",
            recovery_strategy="Set overwrite=True or choose different path"
        ),
        ToolFailureMode(
            error_type="disk_full",
            description="Not enough disk space",
            recovery_strategy="Free up disk space or write to different location"
        )
    ],
    tags=["file", "write", "local", "io"],
    audit_required=True
)


@metadata_tool_result('file_writer')
def file_writer_executor(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
    params = input_metadata.to_params()
    """
    Execute file writer tool.

    Args:
        params: Tool parameters (file_path, content, encoding, create_dirs, overwrite)

    Returns:
        Dictionary with file_path, bytes_written, created

    Raises:
        PermissionError: If no write permission
        FileExistsError: If file exists and overwrite=False
        OSError: If disk full or other OS error
    """
    file_path = Path(params["file_path"])
    content = params["content"]
    encoding = params.get("encoding", "utf-8")
    create_dirs = params.get("create_dirs", True)
    overwrite = params.get("overwrite", True)
    operation_kind = str(params.get("operation_kind") or "create_file").lower()

    # Check if file exists
    file_existed = file_path.exists()
    if file_existed and not overwrite:
        raise FileExistsError(
            f"File exists and overwrite=False: {file_path}"
        )
    if file_existed and operation_kind not in {"file_replace", "full_file_replace", "replace_file"}:
        raise FileExistsError(
            "file_writer refuses to overwrite an existing file without "
            f"operation_kind=file_replace: {file_path}"
        )

    # Create parent directories if needed
    if create_dirs and not file_path.parent.exists():
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise PermissionError(
                f"No permission to create directory: {file_path.parent}"
            ) from e

    # Write file
    try:
        file_path.write_text(content, encoding=encoding)
        bytes_written = file_path.stat().st_size
    except PermissionError as e:
        raise PermissionError(
            f"No permission to write file: {file_path}"
        ) from e
    except OSError as e:
        # Could be disk full or other OS error
        raise OSError(f"Failed to write file: {e}") from e

    return {
        "file_path": str(file_path.absolute()),
        "bytes_written": bytes_written,
        "created": not file_existed
    }
