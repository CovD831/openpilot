"""Built-in tools for OpenPilot Phase 2."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from openpilot.llm import LLMClient
from openpilot.tool_models import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolExecutionResult,
    ToolFailureMode,
    ToolInputSchema,
    ToolOutputSchema,
)


# ============================================================================
# File Reader Tool
# ============================================================================

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


# ============================================================================
# File Writer Tool
# ============================================================================

FILE_WRITER_DEFINITION = ToolDefinition(
    name="file_writer",
    display_name="File Writer",
    description="Write contents to a local file",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_WRITE],
    permission_level=PermissionLevel.MEDIUM,
    input_schema=[
        ToolInputSchema(
            name="file_path",
            type="string",
            description="Absolute or relative path to the file",
            required=True
        ),
        ToolInputSchema(
            name="content",
            type="string",
            description="Content to write to file",
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
            name="create_dirs",
            type="boolean",
            description="Create parent directories if they don't exist",
            required=False,
            default=True
        ),
        ToolInputSchema(
            name="overwrite",
            type="boolean",
            description="Overwrite file if it exists",
            required=False,
            default=True
        )
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="Write result and metadata",
        properties={
            "file_path": {"type": "string", "description": "Path to written file"},
            "bytes_written": {"type": "integer", "description": "Number of bytes written"},
            "created": {"type": "boolean", "description": "Whether file was newly created"}
        }
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


def file_writer_executor(params: dict[str, Any]) -> dict[str, Any]:
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

    # Check if file exists
    file_existed = file_path.exists()
    if file_existed and not overwrite:
        raise FileExistsError(
            f"File exists and overwrite=False: {file_path}"
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


# ============================================================================
# LLM Summarizer Tool
# ============================================================================

LLM_SUMMARIZER_DEFINITION = ToolDefinition(
    name="llm_summarizer",
    display_name="LLM Summarizer",
    description="Generate summary or analysis using LLM",
    version="1.0.0",
    capabilities=[ToolCapability.LLM_CALL],
    permission_level=PermissionLevel.LOW,
    input_schema=[
        ToolInputSchema(
            name="text",
            type="string",
            description="Text to summarize or analyze",
            required=True
        ),
        ToolInputSchema(
            name="instruction",
            type="string",
            description="Instruction for the LLM (e.g., 'Summarize in 3 sentences')",
            required=False,
            default="Summarize the following text concisely."
        ),
        ToolInputSchema(
            name="max_tokens",
            type="integer",
            description="Maximum tokens in response",
            required=False,
            default=500
        )
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="LLM response and metadata",
        properties={
            "summary": {"type": "string", "description": "Generated summary"},
            "tokens_used": {"type": "integer", "description": "Number of tokens used"},
            "model": {"type": "string", "description": "Model used"}
        }
    ),
    timeout_seconds=60,
    max_retries=3,
    failure_modes=[
        ToolFailureMode(
            error_type="llm_timeout",
            description="LLM request timed out",
            recovery_strategy="Retry with shorter text or higher timeout"
        ),
        ToolFailureMode(
            error_type="llm_error",
            description="LLM returned error",
            recovery_strategy="Check LLM configuration and API key"
        ),
        ToolFailureMode(
            error_type="text_too_long",
            description="Input text exceeds model context limit",
            recovery_strategy="Split text into chunks or use longer context model"
        )
    ],
    tags=["llm", "summarize", "analysis", "text"],
    audit_required=True
)


def llm_summarizer_executor(params: dict[str, Any]) -> dict[str, Any]:
    """
    Execute LLM summarizer tool.

    Args:
        params: Tool parameters (text, instruction, max_tokens)

    Returns:
        Dictionary with summary, tokens_used, model

    Raises:
        ValueError: If text too long or invalid parameters
        Exception: If LLM call fails
    """
    text = params["text"]
    instruction = params.get("instruction", "Summarize the following text concisely.")
    max_tokens = params.get("max_tokens", 500)

    # Build prompt
    prompt = f"{instruction}\n\n{text}"

    # Call LLM
    try:
        from openpilot.config import LLMSettings
        settings = LLMSettings()
        client = LLMClient(settings)

        response = client.complete(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=0.3  # Lower temperature for more focused summaries
        )

        return {
            "summary": response.content,
            "tokens_used": response.usage.get("total_tokens", 0) if response.usage else 0,
            "model": settings.model
        }
    except Exception as e:
        raise Exception(f"LLM summarizer failed: {e}") from e


# ============================================================================
# Registration Helper
# ============================================================================

def register_builtin_tools(registry) -> None:
    """
    Register all built-in tools to a registry.

    Args:
        registry: ToolRegistry instance
    """
    registry.register(FILE_READER_DEFINITION, file_reader_executor)
    registry.register(FILE_WRITER_DEFINITION, file_writer_executor)
    registry.register(LLM_SUMMARIZER_DEFINITION, llm_summarizer_executor)
