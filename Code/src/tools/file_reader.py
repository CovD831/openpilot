"""File Reader Tool - Read contents from a local file."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from core.tool_contracts import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolFailureMode,
    ToolInputSchema,
    ToolOutputSchema,
)

FILE_TYPE_RULES: dict[str, dict[str, Any]] = {
    "code": {
        "extensions": {
            ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".cpp", ".c", ".h",
            ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala",
            ".sh", ".bash", ".zsh", ".fish",
        },
        "read_full": True,
        "max_lines": None,
        "max_size_mb": 5.0,
    },
    "database": {
        "extensions": {".sql", ".db", ".sqlite", ".sqlite3"},
        "read_full": False,
        "max_lines": 50,
        "max_size_mb": 1.0,
    },
    "config": {
        "extensions": {
            ".json", ".yaml", ".yml", ".toml", ".ini", ".conf", ".cfg",
            ".xml", ".env", ".properties",
        },
        "read_full": True,
        "max_lines": None,
        "max_size_mb": 1.0,
    },
    "log": {
        "extensions": {".log", ".out", ".err"},
        "read_full": False,
        "max_lines": 100,
        "max_size_mb": 2.0,
    },
    "data": {
        "extensions": {".csv", ".tsv", ".dat", ".txt"},
        "read_full": False,
        "max_lines": 20,
        "max_size_mb": 1.0,
    },
    "binary": {
        "extensions": {
            ".exe", ".dll", ".so", ".dylib", ".bin",
            ".zip", ".tar", ".gz", ".bz2", ".7z",
            ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".ico",
            ".mp3", ".mp4", ".avi", ".mov", ".wav",
            ".pdf", ".doc", ".docx", ".xls", ".xlsx",
        },
        "read_full": False,
        "max_lines": 0,
        "max_size_mb": 0.0,
    },
}

READ_MODES = {"full", "adaptive", "sample", "tail"}


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
        ),
        ToolInputSchema(
            name="read_mode",
            type="string",
            description="Read mode: full, adaptive, sample, or tail",
            required=False,
            default="full"
        ),
        ToolInputSchema(
            name="max_lines",
            type="integer",
            description="Maximum number of lines for adaptive, sample, or tail modes",
            required=False,
            default=None
        ),
        ToolInputSchema(
            name="offset",
            type="integer",
            description="Line offset for adaptive or sample modes",
            required=False,
            default=0
        )
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="File contents and metadata",
        properties={
            "content": {"type": "string", "description": "File contents"},
            "size_bytes": {"type": "integer", "description": "File size in bytes"},
            "encoding": {"type": "string", "description": "File encoding used"},
            "file_type": {"type": "string", "description": "Detected file type"},
            "lines_read": {"type": "integer", "description": "Number of lines returned"},
            "total_lines": {"type": ["integer", "null"], "description": "Total line count when known"},
            "truncated": {"type": "boolean", "description": "Whether content was truncated"},
            "metadata": {"type": "object", "description": "Additional read metadata"}
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
        params: Tool parameters (file_path, encoding, max_size_mb, read_mode, max_lines, offset)

    Returns:
        Dictionary with content, size_bytes, encoding, file_type, line metadata, and extra metadata

    Raises:
        FileNotFoundError: If file doesn't exist
        PermissionError: If no read permission
        ValueError: If file too large or encoding error
    """
    file_path = Path(params["file_path"])
    encoding = params.get("encoding", "utf-8")
    max_size_mb = params.get("max_size_mb", 10)
    read_mode = str(params.get("read_mode", "full") or "full").lower()
    max_lines = params.get("max_lines")
    offset = int(params.get("offset", 0) or 0)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not file_path.is_file():
        raise ValueError(f"Not a file: {file_path}")
    if read_mode not in READ_MODES:
        raise ValueError(f"Invalid read_mode: {read_mode}. Use full, adaptive, sample, or tail.")

    size_bytes = file_path.stat().st_size
    file_type = _detect_file_type(file_path)
    strategy = _read_strategy(file_type)
    effective_max_size_mb = max_size_mb
    if read_mode == "adaptive" and strategy.get("max_size_mb") is not None:
        effective_max_size_mb = min(float(max_size_mb), float(strategy["max_size_mb"]))
    max_size_bytes = max_size_mb * 1024 * 1024
    if effective_max_size_mb is not None:
        max_size_bytes = float(effective_max_size_mb) * 1024 * 1024
    if size_bytes > max_size_bytes:
        raise ValueError(
            f"File too large: {size_bytes} bytes "
            f"(max: {max_size_bytes} bytes)"
        )

    if file_type == "binary":
        return _binary_result(file_path, size_bytes)

    if read_mode == "adaptive":
        read_full = bool(strategy.get("read_full", False))
        if read_full:
            return _read_text_file(file_path, encoding, size_bytes, file_type)
        limit = _coerce_line_limit(max_lines, strategy.get("max_lines") or 100)
        return _read_text_file(
            file_path,
            encoding,
            size_bytes,
            file_type,
            max_lines=limit,
            offset=offset,
            metadata={"read_mode": "adaptive"},
        )
    if read_mode == "sample":
        return _read_text_file(
            file_path,
            encoding,
            size_bytes,
            file_type,
            max_lines=_coerce_line_limit(max_lines, 10),
            offset=offset,
            metadata={"read_mode": "sample"},
        )
    if read_mode == "tail":
        return _read_text_tail(
            file_path,
            encoding,
            size_bytes,
            file_type,
            max_lines=_coerce_line_limit(max_lines, 100),
        )

    return _read_text_file(file_path, encoding, size_bytes, file_type)


def _detect_file_type(file_path: Path) -> str:
    extension = file_path.suffix.lower()
    for file_type, rules in FILE_TYPE_RULES.items():
        if extension in rules["extensions"]:
            return file_type

    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type:
        if mime_type.startswith("text/"):
            return "text"
        if mime_type.startswith("application/"):
            return "binary"
    return "unknown"


def _read_strategy(file_type: str) -> dict[str, Any]:
    return FILE_TYPE_RULES.get(
        file_type,
        {"read_full": False, "max_lines": 100, "max_size_mb": 1.0},
    )


def _coerce_line_limit(value: Any, default: int) -> int:
    if value is None:
        return default
    limit = int(value)
    if limit < 0:
        raise ValueError("max_lines must be greater than or equal to 0")
    return limit


def _read_text_file(
    file_path: Path,
    encoding: str,
    size_bytes: int,
    file_type: str,
    *,
    max_lines: int | None = None,
    offset: int = 0,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if offset < 0:
        raise ValueError("offset must be greater than or equal to 0")

    try:
        lines, used_encoding, fallback = _read_lines_with_fallback(file_path, encoding)
    except PermissionError as e:
        raise PermissionError(f"No permission to read file: {file_path}") from e
    except UnicodeDecodeError as e:
        raise ValueError(
            f"Cannot decode file with encoding '{encoding}': {e}"
        ) from e

    total_lines = len(lines)
    selected_lines = lines[offset:] if offset else lines
    truncated = False
    if max_lines is not None and len(selected_lines) > max_lines:
        selected_lines = selected_lines[:max_lines]
        truncated = True
    if offset and offset < total_lines:
        truncated = True
    content = "".join(selected_lines)
    result_metadata = dict(metadata or {})
    if fallback:
        result_metadata["encoding_fallback"] = True

    return {
        "content": content,
        "size_bytes": size_bytes,
        "encoding": used_encoding,
        "file_type": file_type,
        "lines_read": len(selected_lines),
        "total_lines": total_lines,
        "truncated": truncated,
        "metadata": result_metadata,
    }


def _read_text_tail(
    file_path: Path,
    encoding: str,
    size_bytes: int,
    file_type: str,
    *,
    max_lines: int,
) -> dict[str, Any]:
    try:
        lines, used_encoding, fallback = _read_lines_with_fallback(file_path, encoding)
    except PermissionError as e:
        raise PermissionError(f"No permission to read file: {file_path}") from e
    except UnicodeDecodeError:
        return {
            "content": "[Cannot decode file - possibly binary]",
            "size_bytes": size_bytes,
            "encoding": "unknown",
            "file_type": "binary",
            "lines_read": 0,
            "total_lines": 0,
            "truncated": False,
            "metadata": {"read_mode": "tail"},
        }

    total_lines = len(lines)
    selected_lines = lines[-max_lines:] if max_lines and total_lines > max_lines else lines
    metadata = {"read_mode": "tail"}
    if fallback:
        metadata["encoding_fallback"] = True
    return {
        "content": "".join(selected_lines),
        "size_bytes": size_bytes,
        "encoding": used_encoding,
        "file_type": file_type,
        "lines_read": len(selected_lines),
        "total_lines": total_lines,
        "truncated": total_lines > len(selected_lines),
        "metadata": metadata,
    }


def _read_lines_with_fallback(file_path: Path, encoding: str) -> tuple[list[str], str, bool]:
    encodings = [encoding, "latin-1", "cp1252", "iso-8859-1"]
    tried = set()
    first_error: UnicodeDecodeError | None = None
    for candidate in encodings:
        if candidate in tried:
            continue
        tried.add(candidate)
        try:
            return file_path.read_text(encoding=candidate).splitlines(keepends=True), candidate, candidate != encoding
        except UnicodeDecodeError as e:
            if first_error is None:
                first_error = e
            continue
    if first_error is not None:
        raise first_error
    return [], encoding, False


def _binary_result(file_path: Path, size_bytes: int) -> dict[str, Any]:
    return {
        "content": "[Binary file - content not displayed]",
        "size_bytes": size_bytes,
        "encoding": "binary",
        "file_type": "binary",
        "lines_read": 0,
        "total_lines": 0,
        "truncated": False,
        "metadata": {"mime_type": mimetypes.guess_type(str(file_path))[0]},
    }
