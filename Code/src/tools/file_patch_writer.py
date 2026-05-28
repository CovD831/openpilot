"""File Patch Writer Tool - Apply scoped local edits to existing files."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from metadata import ToolContractMetadata, ToolInputMetadata, ToolResultMetadata, metadata_tool_result

from core.tool_contracts import PermissionLevel, ToolCapability, ToolDefinition, ToolFailureMode


FILE_PATCH_WRITER_DEFINITION = ToolDefinition(
    name="file_patch_writer",
    display_name="File Patch Writer",
    description="Apply generated code units or localized replacements without rewriting an entire existing file",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_WRITE],
    permission_level=PermissionLevel.MEDIUM,
    contract_metadata=ToolContractMetadata(
        tool_name="file_patch_writer",
        input_metadata_type="ToolInputMetadata",
        output_metadata_type="ToolResultMetadata",
        required_input_fields=["file_path"],
        input_defaults={"encoding": "utf-8", "operation_kind": "modify_symbol"},
        conditional_requirements=[
            {"when": {"operation_kind": "add_symbol"}, "required": ["generated_unit"]},
            {"when": {"operation_kind": "modify_symbol"}, "required_any_of": [["replacement_text"], ["patch"]]},
        ],
    ),
    timeout_seconds=30,
    max_retries=1,
    failure_modes=[
        ToolFailureMode(
            error_type="symbol_not_found",
            description="A requested Python symbol could not be located",
            recovery_strategy="Read the file and provide symbol_name or line_start/line_end",
        ),
        ToolFailureMode(
            error_type="invalid_patch",
            description="Patch input is missing replacement text or a valid target range",
            recovery_strategy="Provide generated_unit, replacement_text, or a structured patch",
        ),
    ],
    tags=["file", "patch", "code", "local-edit"],
    audit_required=True,
)


@metadata_tool_result("file_patch_writer")
def file_patch_writer_executor(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
    params = input_metadata.to_params()
    file_path = Path(str(params["file_path"])).expanduser()
    encoding = str(params.get("encoding") or "utf-8")
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"Patch target file not found: {file_path}")

    original = file_path.read_text(encoding=encoding)
    operation_kind = str(params.get("operation_kind") or params.get("patch_mode") or "modify_symbol")
    patch = params.get("patch") if isinstance(params.get("patch"), dict) else {}
    if patch:
        operation_kind = str(patch.get("operation_kind") or operation_kind)

    if operation_kind in {"add_symbol", "code_unit_generate", "insert"}:
        unit = str(params.get("generated_unit") or params.get("code") or patch.get("generated_unit") or "").rstrip()
        if not unit:
            raise ValueError("file_patch_writer add_symbol requires generated_unit")
        updated, changed_ranges = _insert_unit(original, unit, params | patch)
    else:
        replacement = str(
            params.get("replacement_text")
            or params.get("content")
            or patch.get("replacement_text")
            or patch.get("content")
            or ""
        ).rstrip()
        if not replacement:
            raise ValueError("file_patch_writer modify_symbol requires replacement_text or patch.replacement_text")
        line_start, line_end = _target_range(original, params | patch)
        updated, changed_ranges = _replace_range(original, line_start, line_end, replacement)

    if file_path.suffix == ".py":
        ast.parse(updated)

    file_path.write_text(updated, encoding=encoding)
    return {
        "file_path": str(file_path.absolute()),
        "bytes_written": file_path.stat().st_size,
        "created": False,
        "operation_kind": operation_kind,
        "changed_ranges": changed_ranges,
    }


def _split_lines(text: str) -> list[str]:
    return text.splitlines()


def _with_trailing_newline(lines: list[str], original: str) -> str:
    result = "\n".join(lines)
    if original.endswith("\n") or result:
        result += "\n"
    return result


def _insert_unit(original: str, unit: str, params: dict[str, Any]) -> tuple[str, list[dict[str, int]]]:
    lines = _split_lines(original)
    insert_at = len(lines)
    insertion_hint = str(params.get("insertion_hint") or "end_of_file")
    symbol_name = str(params.get("symbol_name") or "")
    if insertion_hint == "before_symbol" and symbol_name:
        insert_at, _ = _find_python_symbol_range(original, symbol_name)
        insert_at -= 1
    elif insertion_hint == "after_symbol" and symbol_name:
        _, insert_at = _find_python_symbol_range(original, symbol_name)

    unit_lines = unit.splitlines()
    spacer_before = [""] if lines and lines[max(0, insert_at - 1)].strip() else []
    spacer_after = [""] if insert_at < len(lines) and unit_lines else []
    updated_lines = lines[:insert_at] + spacer_before + unit_lines + spacer_after + lines[insert_at:]
    start = insert_at + len(spacer_before) + 1
    end = start + len(unit_lines) - 1
    return _with_trailing_newline(updated_lines, original), [{"line_start": start, "line_end": end}]


def _replace_range(original: str, line_start: int, line_end: int, replacement: str) -> tuple[str, list[dict[str, int]]]:
    lines = _split_lines(original)
    if line_start < 1 or line_end < line_start or line_end > len(lines):
        raise ValueError(f"Invalid replacement range: {line_start}-{line_end}")
    replacement_lines = replacement.splitlines()
    updated_lines = lines[: line_start - 1] + replacement_lines + lines[line_end:]
    end = line_start + len(replacement_lines) - 1
    return _with_trailing_newline(updated_lines, original), [{"line_start": line_start, "line_end": end}]


def _target_range(original: str, params: dict[str, Any]) -> tuple[int, int]:
    line_start = params.get("line_start")
    line_end = params.get("line_end")
    if isinstance(line_start, int) and isinstance(line_end, int):
        return line_start, line_end
    symbol_name = str(params.get("symbol_name") or "")
    if symbol_name:
        return _find_python_symbol_range(original, symbol_name)
    raise ValueError("file_patch_writer requires line_start/line_end or symbol_name for modify_symbol")


def _find_python_symbol_range(source: str, symbol_name: str) -> tuple[int, int]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"Cannot locate symbol in invalid Python source: {exc}") from exc
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol_name:
            end_lineno = getattr(node, "end_lineno", None)
            if not end_lineno:
                raise ValueError(f"Python runtime did not provide end_lineno for symbol: {symbol_name}")
            return int(node.lineno), int(end_lineno)
    raise ValueError(f"Python symbol not found: {symbol_name}")
