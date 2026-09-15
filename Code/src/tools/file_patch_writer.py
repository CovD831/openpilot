"""File Patch Writer Tool - Apply scoped local edits to existing files."""

from __future__ import annotations

import ast
import errno
import json
import os
from pathlib import Path
from typing import Any

from memory.project_path_resolver import ensure_resolved_path
from metadata import (
    FileMutationPrecondition,
    ToolContractMetadata,
    ToolInputMetadata,
    ToolResultMetadata,
    metadata_tool_result,
)

from core.tool_contracts import PermissionLevel, ToolCapability, ToolDefinition, ToolFailureMode
from memory.project_index import ProjectIndexManager
from tools.file_indexing import refresh_after_file_change
from utils.file_mutation_preconditions import (
    FileMutationPreconditionError,
    assert_file_mutation_precondition,
    file_mutation_precondition_from_stat,
)


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
            {
                "when": {"operation_kind": "add_symbol"},
                "required_any_of": [["generated_unit"], ["artifact_ref"]],
            },
            {
                "when": {"operation_kind": "modify_symbol"},
                "required": ["symbol_name"],
                "required_any_of": [["replacement_text"], ["patch"]],
            },
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
    project_path = params.get("project_path")
    file_path = _secure_patch_target_path(params["file_path"], project_path)
    encoding = str(params.get("encoding") or "utf-8")
    expected_precondition = _coerce_file_mutation_precondition(
        params.get("_file_mutation_precondition")
    )

    original, read_stat = _read_text_no_follow(file_path, encoding=encoding)
    if expected_precondition is not None:
        assert_file_mutation_precondition(
            file_path,
            expected_precondition,
            observed=read_stat,
        )
    operation_kind = str(params.get("operation_kind") or params.get("patch_mode") or "modify_symbol")
    patch = params.get("patch") if isinstance(params.get("patch"), dict) else {}
    if patch:
        operation_kind = str(patch.get("operation_kind") or operation_kind)

    if operation_kind in {"add_symbol", "code_unit_generate", "insert"}:
        unit = str(params.get("generated_unit") or params.get("code") or patch.get("generated_unit") or "").rstrip()
        if not unit:
            raise ValueError("file_patch_writer add_symbol requires generated_unit")
        updated, changed_ranges = _insert_unit(original, unit, params | patch)
    elif operation_kind in {"delete_range", "delete_section", "remove_section", "delete_symbol", "remove_symbol"}:
        line_start, line_end = _target_range(original, params | patch, file_path=file_path)
        updated, changed_ranges = _delete_range(original, line_start, line_end)
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
        line_start, line_end = _target_range(original, params | patch, file_path=file_path)
        updated, changed_ranges = _replace_range(original, line_start, line_end, replacement)

    if file_path.suffix == ".py":
        ast.parse(updated)

    bytes_written = _write_text_no_follow(
        file_path,
        updated,
        encoding=encoding,
        expected_precondition=expected_precondition,
        read_stat=read_stat,
    )
    index_update: dict[str, Any] = {}
    warnings: list[str] = []
    post_processing_scope = params.get("_post_processing_write_scope")
    if isinstance(post_processing_scope, (list, tuple, set)):
        manager = ProjectIndexManager.for_path(file_path)
        derived_targets = {
            manager.index_file_for(file_path).resolve(),
            (file_path.parent / ProjectIndexManager.SKETCH_NAME).resolve(),
        }
        authorized_targets = {
            Path(str(item)).expanduser().resolve()
            for item in post_processing_scope
            if str(item or "").strip()
        }
        if not derived_targets.issubset(authorized_targets):
            index_update = {
                "skipped": True,
                "reason": "post_processing_target_outside_declared_write_scope",
            }
            warnings.append(
                "File index and directory sketch refresh skipped because their derived paths "
                "are outside the declared write scope."
            )
        else:
            try:
                index_update = refresh_after_file_change(file_path)
            except Exception as exc:
                warnings.append(f"File index refresh failed: {exc}")
    else:
        try:
            index_update = refresh_after_file_change(file_path)
        except Exception as exc:
            warnings.append(f"File index refresh failed: {exc}")

    return {
        "file_path": str(file_path.absolute()),
        "bytes_written": bytes_written,
        "created": False,
        "operation_kind": operation_kind,
        "changed_ranges": changed_ranges,
        "index_update": index_update,
        "warnings": warnings,
    }


def _secure_patch_target_path(raw_path: Any, project_path: Any) -> Path:
    candidate = Path(str(raw_path)).expanduser()
    if project_path:
        project_root = Path(str(project_path)).expanduser().resolve(strict=False)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        lexical_path = candidate.absolute()
        resolved = ensure_resolved_path(
            lexical_path,
            project_root,
            operation="patch",
            intent_kind="existing_file",
        ).absolute()
        if lexical_path != resolved:
            raise PermissionError(
                "file patch target must be a canonical non-symbolic-link project file"
            )
        return lexical_path
    return candidate.absolute()


def _coerce_file_mutation_precondition(value: Any) -> FileMutationPrecondition | None:
    if value is None:
        return None
    if isinstance(value, FileMutationPrecondition):
        return value
    if isinstance(value, dict):
        try:
            return FileMutationPrecondition.model_validate(value)
        except ValueError as exc:
            raise PermissionError("file mutation precondition is invalid") from exc
    raise PermissionError("file mutation precondition is invalid")


def _read_text_no_follow(file_path: Path, *, encoding: str) -> tuple[str, os.stat_result]:
    descriptor = _open_no_follow(file_path, os.O_RDONLY)
    try:
        observed = os.fstat(descriptor)
        file_mutation_precondition_from_stat(file_path, observed)
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            return handle.read().decode(encoding), observed
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _write_text_no_follow(
    file_path: Path,
    updated: str,
    *,
    encoding: str,
    expected_precondition: FileMutationPrecondition | None,
    read_stat: os.stat_result,
) -> int:
    descriptor = _open_no_follow(file_path, os.O_WRONLY)
    try:
        observed = os.fstat(descriptor)
        read_precondition = file_mutation_precondition_from_stat(file_path, read_stat)
        assert_file_mutation_precondition(
            file_path,
            read_precondition,
            observed=observed,
        )
        if expected_precondition is not None:
            assert_file_mutation_precondition(
                file_path,
                expected_precondition,
                observed=observed,
            )
        payload = updated.encode(encoding)
        os.ftruncate(descriptor, 0)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("file patch write did not make progress")
            view = view[written:]
        os.fsync(descriptor)
        return len(payload)
    finally:
        os.close(descriptor)


def _open_no_follow(file_path: Path, flags: int) -> int:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise PermissionError("secure no-follow file patching is unavailable on this platform")
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    try:
        return os.open(str(file_path), flags | no_follow | close_on_exec)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise PermissionError(
                f"file mutation target must not be a symbolic link: {file_path}"
            ) from exc
        raise


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


def _delete_range(original: str, line_start: int, line_end: int) -> tuple[str, list[dict[str, int]]]:
    lines = _split_lines(original)
    if line_start < 1 or line_end < line_start or line_end > len(lines):
        raise ValueError(f"Invalid delete range: {line_start}-{line_end}")
    updated_lines = lines[: line_start - 1] + lines[line_end:]
    return _with_trailing_newline(updated_lines, original), [{"line_start": line_start, "line_end": line_end}]


def _target_range(original: str, params: dict[str, Any], *, file_path: Path | None = None) -> tuple[int, int]:
    line_start = params.get("line_start")
    line_end = params.get("line_end")
    if isinstance(line_start, int) and isinstance(line_end, int):
        return line_start, line_end
    section_id = str(params.get("section_id") or "")
    section_title = str(params.get("section_title") or params.get("title") or "")
    if file_path is not None and (section_id or section_title):
        indexed_range = _target_range_from_index(file_path, section_id=section_id, section_title=section_title)
        if indexed_range:
            return indexed_range
    symbol_name = str(params.get("symbol_name") or "")
    if symbol_name:
        if file_path is not None and file_path.suffix != ".py":
            indexed_range = _target_range_from_index(file_path, symbol_name=symbol_name)
            if indexed_range:
                return indexed_range
        try:
            return _find_python_symbol_range(original, symbol_name)
        except ValueError:
            if file_path is not None:
                indexed_range = _target_range_from_index(file_path, symbol_name=symbol_name)
                if indexed_range:
                    return indexed_range
            raise
    raise ValueError("file_patch_writer requires line_start/line_end, section_id, section_title, or symbol_name")


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


def _target_range_from_index(
    file_path: Path,
    *,
    section_id: str = "",
    section_title: str = "",
    symbol_name: str = "",
) -> tuple[int, int] | None:
    try:
        manager = ProjectIndexManager.for_path(file_path)
        index = manager.update_file_index(file_path)
        payload = index.to_json_dict()
    except Exception:
        try:
            index_file = ProjectIndexManager.for_path(file_path).index_file_for(file_path)
            payload = json.loads(index_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    title_query = section_title.lower().strip()
    symbol_query = symbol_name.lower().strip()
    for section in payload.get("sections", []) or []:
        if not isinstance(section, dict):
            continue
        if section_id and str(section.get("section_id") or "") == section_id:
            return int(section["line_start"]), int(section["line_end"])
        title = str(section.get("title") or "").lower()
        symbol = str(section.get("symbol_name") or "").lower()
        if title_query and (title == title_query or title_query in title):
            return int(section["line_start"]), int(section["line_end"])
        if symbol_query and symbol == symbol_query:
            return int(section["line_start"]), int(section["line_end"])
    return None
