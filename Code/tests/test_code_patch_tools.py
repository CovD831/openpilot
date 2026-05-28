from __future__ import annotations

import pytest

from metadata import ToolInputMetadata
from tools.code_editor import code_editor_executor
from tools.file_patch_writer import file_patch_writer_executor
from tools.file_writer import file_writer_executor


def test_file_writer_rejects_existing_file_without_explicit_replace(tmp_path) -> None:
    target = tmp_path / "app.py"
    target.write_text("print('old')\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="operation_kind=file_replace"):
        file_writer_executor(
            ToolInputMetadata.from_mapping(
                "file_writer",
                {
                    "file_path": str(target),
                    "content": "print('new')\n",
                    "overwrite": True,
                },
            )
        )

    result = file_writer_executor(
        ToolInputMetadata.from_mapping(
            "file_writer",
            {
                "file_path": str(target),
                "content": "print('new')\n",
                "overwrite": True,
                "operation_kind": "file_replace",
            },
        )
    )

    assert result.result.file_path == str(target.absolute())
    assert target.read_text(encoding="utf-8") == "print('new')\n"


def test_file_patch_writer_inserts_generated_unit_without_rewriting_existing_content(tmp_path) -> None:
    target = tmp_path / "app.py"
    target.write_text("def existing():\n    return 1\n", encoding="utf-8")

    result = file_patch_writer_executor(
        ToolInputMetadata.from_mapping(
            "file_patch_writer",
            {
                "file_path": str(target),
                "operation_kind": "add_symbol",
                "generated_unit": "def added():\n    return 2",
            },
        )
    )

    updated = target.read_text(encoding="utf-8")
    assert "def existing():" in updated
    assert "def added():" in updated
    assert result.result.attributes["changed_ranges"] == [{"line_start": 4, "line_end": 5}]


def test_code_editor_and_patch_writer_replace_only_target_symbol(tmp_path) -> None:
    target = tmp_path / "app.py"
    target.write_text(
        "def keep():\n"
        "    return 'keep'\n\n"
        "def change():\n"
        "    return 'old'\n",
        encoding="utf-8",
    )

    edit_result = code_editor_executor(
        ToolInputMetadata.from_mapping(
            "code_editor",
            {
                "file_path": str(target),
                "task_description": "Return the new value from change",
                "language": "python",
                "symbol_name": "change",
                "replacement_text": "def change():\n    return 'new'",
            },
        )
    )
    patch_result = file_patch_writer_executor(
        ToolInputMetadata.from_mapping(
            "file_patch_writer",
            {
                "file_path": str(target),
                "operation_kind": "modify_symbol",
                "patch": edit_result.result.attributes["patch"],
            },
        )
    )

    updated = target.read_text(encoding="utf-8")
    assert "def keep():\n    return 'keep'" in updated
    assert "def change():\n    return 'new'" in updated
    assert "return 'old'" not in updated
    assert patch_result.result.attributes["changed_ranges"] == [{"line_start": 4, "line_end": 5}]


def test_code_editor_fails_when_python_symbol_cannot_be_located(tmp_path) -> None:
    target = tmp_path / "app.py"
    target.write_text("def existing():\n    return 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Python symbol not found"):
        code_editor_executor(
            ToolInputMetadata.from_mapping(
                "code_editor",
                {
                    "file_path": str(target),
                    "task_description": "Change missing",
                    "language": "python",
                    "symbol_name": "missing",
                    "replacement_text": "def missing():\n    return 2",
                },
            )
        )
