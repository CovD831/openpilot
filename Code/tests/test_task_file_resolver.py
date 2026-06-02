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


def test_task_file_resolver_prefers_validation_issue_target_over_sketch_match(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    assistant = project / "assistant.py"
    personal = project / "personal_assistant.py"
    assistant.write_text("{{code_generator.output}}\n", encoding="utf-8")
    personal.write_text("def personal_assistant():\n    return 'ready'\n", encoding="utf-8")

    result = task_file_resolver_executor(
        ToolInputMetadata.from_mapping(
            "task_file_resolver",
            {
                "project_path": str(project),
                "task_description": "Replace placeholder content with real implementation for personal assistant",
                "file_paths": [str(personal)],
                "prompt_context": {
                    "failing_files": [str(assistant)],
                    "validation_issues": [
                        {
                            "kind": "validation_issue",
                            "category": "code_quality",
                            "severity": "blocking",
                            "message": "Generated content in assistant.py still contains template placeholders.",
                            "target_files": [str(assistant)],
                        }
                    ],
                },
            },
        )
    )

    assert result.result.primary_file.name == "assistant.py"
    assert result.result.primary_file.relation_source == "validation_issue"


def test_task_file_resolver_fails_when_validation_issue_target_is_missing(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("print('ok')\n", encoding="utf-8")

    try:
        task_file_resolver_executor(
            ToolInputMetadata.from_mapping(
                "task_file_resolver",
                {
                    "project_path": str(project),
                    "task_description": "Fix failing file",
                    "prompt_context": {
                        "failing_files": ["missing.py"],
                        "validation_issues": [
                            {
                                "category": "runtime_error",
                                "severity": "blocking",
                                "message": "missing.py failed",
                                "target_files": ["missing.py"],
                            }
                        ],
                    },
                },
            )
        )
    except FileNotFoundError as exc:
        assert "Validation issue target file(s) were not found" in str(exc)
    else:
        raise AssertionError("resolver should fail when validation issue target file is missing")


def test_task_file_resolver_uses_written_files_only_as_last_resort(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    app = project / "app.py"
    app.write_text("print('ok')\n", encoding="utf-8")

    result = task_file_resolver_executor(
        ToolInputMetadata.from_mapping(
            "task_file_resolver",
            {
                "project_path": str(project),
                "task_description": "",
                "written_files": [str(app)],
                "prompt_context": {},
            },
        )
    )

    assert result.result.primary_file.name == "app.py"
    assert result.result.primary_file.relation_source == "written_files_fallback"


def test_task_file_resolver_accepts_explicit_planned_frontend_file_inside_project(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "assistant.py").write_text("print('assistant')\n", encoding="utf-8")

    result = task_file_resolver_executor(
        ToolInputMetadata.from_mapping(
            "task_file_resolver",
            {
                "project_path": str(project),
                "task_description": "Create the planned browser user interface",
                "file_paths": ["index.html"],
                "written_files": ["assistant.py"],
            },
        )
    )

    assert result.result.primary_file.name == "index.html"
    assert result.result.primary_file.relation_source == "planned_target"
    assert not (project / "index.html").exists()


def test_task_file_resolver_extracts_nested_planned_file_from_task_text(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "assistant.py").write_text("print('assistant')\n", encoding="utf-8")

    result = task_file_resolver_executor(
        ToolInputMetadata.from_mapping(
            "task_file_resolver",
            {
                "project_path": str(project),
                "task_description": "Enhance the frontend template (templates/index.html) with a polished chat interface.",
                "written_files": ["assistant.py"],
            },
        )
    )

    assert result.result.primary_file.file_path == str(project / "templates" / "index.html")
    assert result.result.primary_file.relation_source == "planned_target"
    assert not (project / "templates").exists()


def test_task_file_resolver_prefers_specific_nested_planned_path_over_bare_hint(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "assistant.py").write_text("print('assistant')\n", encoding="utf-8")

    result = task_file_resolver_executor(
        ToolInputMetadata.from_mapping(
            "task_file_resolver",
            {
                "project_path": str(project),
                "task_description": "Enhance templates/index.html with conversation history.",
                "file_paths": ["index.html"],
                "written_files": ["assistant.py"],
            },
        )
    )

    assert result.result.primary_file.file_path == str(project / "templates" / "index.html")


def test_task_file_resolver_rejects_planned_file_outside_project(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    app = project / "assistant.py"
    app.write_text("print('assistant')\n", encoding="utf-8")

    result = task_file_resolver_executor(
        ToolInputMetadata.from_mapping(
            "task_file_resolver",
            {
                "project_path": str(project),
                "task_description": "",
                "file_paths": ["../outside.html"],
                "written_files": ["assistant.py"],
            },
        )
    )

    assert result.result.primary_file.name == "assistant.py"
    assert result.result.primary_file.relation_source == "written_files_fallback"
