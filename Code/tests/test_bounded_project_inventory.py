from __future__ import annotations

import pytest

from memory.project_inventory import collect_project_files


def test_project_inventory_stops_at_directory_and_file_bounds(tmp_path) -> None:
    for index in range(12):
        directory = tmp_path / f"package_{index:02d}"
        directory.mkdir()
        (directory / f"module_{index}.py").write_text("import pytest\n", encoding="utf-8")

    inventory = collect_project_files(
        tmp_path,
        suffixes={".py"},
        max_files=2,
        max_directories=3,
        max_entries=20,
        max_depth=2,
    )

    assert len(inventory.files) <= 2
    assert inventory.directories_scanned <= 3
    assert inventory.entries_scanned <= 20
    assert inventory.truncated is True


def test_project_inventory_ignores_dependency_and_vcs_directories(tmp_path) -> None:
    (tmp_path / "app.py").write_text("print('ok')\n", encoding="utf-8")
    for name in (".git", ".venv", "node_modules", "__pycache__"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "ignored.py").write_text("raise RuntimeError\n", encoding="utf-8")

    inventory = collect_project_files(tmp_path, suffixes={".py"})

    assert inventory.files == (tmp_path / "app.py",)


def test_project_inventory_rejects_zero_work_bounds(tmp_path) -> None:
    with pytest.raises(ValueError, match="bounds"):
        collect_project_files(tmp_path, max_entries=0)
