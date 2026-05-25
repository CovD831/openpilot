from __future__ import annotations

from metadata import ToolInputMetadata
from autonomous_iteration.tool.task_file_resolver import task_file_resolver_executor


def test_task_file_resolver_prefers_readme_for_documentation_task(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("# Game\n", encoding="utf-8")
    (project / "main.py").write_text("def game_loop():\n    pass\n", encoding="utf-8")

    result = task_file_resolver_executor(
        ToolInputMetadata.from_mapping(
            "task_file_resolver",
            {
                "project_path": str(project),
                "task_description": "在README中添加控制键说明和游戏规则简介",
                "file_paths": ["README.md"],
                "prompt_context": {"acceptance_criteria": ["README包含完整控制键说明"]},
            },
        )
    )

    assert result.result.primary_file.name == "README.md"
    assert result.result.recommended_edit_kind == "documentation"
    assert (project / "sketch.json").exists()


def test_task_file_resolver_finds_source_file_from_sketch_query(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("# Game\n", encoding="utf-8")
    (project / "main.py").write_text("def game_loop():\n    update_snake_direction()\n", encoding="utf-8")

    result = task_file_resolver_executor(
        ToolInputMetadata.from_mapping(
            "task_file_resolver",
            {
                "project_path": str(project),
                "task_description": "修复 snake direction game_loop 的运行逻辑",
                "prompt_context": {"acceptance_criteria": ["game_loop handles direction"]},
            },
        )
    )

    assert result.result.primary_file.name == "main.py"
    assert result.result.recommended_edit_kind == "source_code"
