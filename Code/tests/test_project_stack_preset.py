from __future__ import annotations

import json

from core.project_stack import load_or_create_project_stack_preset, load_project_stack_preset
from metadata import ProjectStackPresetMetadata
from tools.code_generator import CodeGenerator
from tools.code_models import CodeGenerationRequest


def test_project_stack_preset_is_created_once_for_user_facing_assistant(tmp_path) -> None:
    app = tmp_path / "assistant.py"
    app.write_text("def main():\n    print('assistant')\n", encoding="utf-8")

    created = load_or_create_project_stack_preset(
        tmp_path,
        goal="帮我做一个个人数字助手",
        files=["assistant.py"],
    )
    reused = load_or_create_project_stack_preset(
        tmp_path,
        goal="后来提到终端，但没有显式要求更新预设",
        files=["assistant.py"],
    )

    assert created.delivery_surface == "browser"
    assert created.architecture == "frontend_backend_split"
    assert created.frontend_language == "html_css_javascript"
    assert created.backend_language == "python"
    assert created.ui_review_required is True
    assert reused.to_json_dict() == created.to_json_dict()
    persisted = json.loads((tmp_path / ".openpilot" / "project_stack.json").read_text(encoding="utf-8"))
    assert persisted["revision"] == 1


def test_project_stack_preset_does_not_let_generated_cli_code_override_user_facing_goal(tmp_path) -> None:
    app = tmp_path / "assistant.py"
    app.write_text(
        "#!/usr/bin/env python3\n"
        '"""Personal Digital Assistant - CLI version."""\n'
        "import argparse\n"
        "def main():\n"
        "    print('assistant')\n",
        encoding="utf-8",
    )

    created = load_or_create_project_stack_preset(
        tmp_path,
        goal="帮我做一个个人数字助手",
        files=["assistant.py"],
    )

    assert created.delivery_surface == "browser"
    assert created.architecture == "frontend_backend_split"
    assert created.ui_strategy == "browser_application"
    assert "terminal" not in created.rationale[0].lower()


def test_project_stack_preset_repairs_bad_initial_terminal_inference(tmp_path) -> None:
    preset_dir = tmp_path / ".openpilot"
    preset_dir.mkdir()
    bad = ProjectStackPresetMetadata(
        project_path=str(tmp_path),
        preset_file=str(preset_dir / "project_stack.json"),
        revision=1,
        preset_source="initial_inference",
        delivery_surface="terminal",
        architecture="terminal_application",
        frontend_language="terminal_text",
        backend_language="python",
        ui_strategy="terminal_ui",
        ui_review_required=True,
        rationale=["The project explicitly requests a terminal or CLI interaction surface."],
        evidence=["generated assistant.py contained CLI scaffold text"],
    )
    (preset_dir / "project_stack.json").write_text(
        json.dumps(bad.to_json_dict(), ensure_ascii=False),
        encoding="utf-8",
    )

    repaired = load_or_create_project_stack_preset(
        tmp_path,
        goal="帮我做一个个人数字助手",
        files=["assistant.py"],
    )

    assert repaired.revision == 2
    assert repaired.preset_source == "deterministic_goal_alignment"
    assert repaired.delivery_surface == "browser"
    assert repaired.architecture == "frontend_backend_split"
    assert repaired.ui_review_required is True


def test_project_stack_preset_explicit_update_increments_revision(tmp_path) -> None:
    load_or_create_project_stack_preset(
        tmp_path,
        goal="Build a browser dashboard",
        files=["app.py"],
    )

    updated = load_or_create_project_stack_preset(
        tmp_path,
        preset_update={
            "delivery_surface": "terminal",
            "architecture": "terminal_application",
            "frontend_language": "terminal_text",
            "ui_strategy": "terminal_ui",
            "ignored_field": "not persisted",
        },
    )
    reloaded = load_project_stack_preset(tmp_path)

    assert updated.revision == 2
    assert updated.preset_source == "explicit_iteration_update"
    assert updated.delivery_surface == "terminal"
    assert updated.architecture == "terminal_application"
    assert reloaded is not None
    assert reloaded.to_json_dict() == updated.to_json_dict()
    assert "ignored_field" not in updated.to_json_dict()


def test_contextual_code_generator_prompt_treats_ui_and_stack_as_contract() -> None:
    prompt = CodeGenerator()._build_contextual_prompt(
        CodeGenerationRequest(
            request_id="stack-preset",
            task_description="Add reminder creation.",
            prompt_context={
                "stack_preset": {
                    "revision": 3,
                    "delivery_surface": "browser",
                    "architecture": "frontend_backend_split",
                    "frontend_language": "html_css_javascript",
                    "backend_language": "python",
                    "ui_strategy": "browser_application",
                    "ui_review_required": True,
                },
                "ui_iteration_contract": {
                    "assessment_required": True,
                    "implementation_required_for_user_facing_change": True,
                },
            },
        )
    )

    assert "Persisted project stack preset" in prompt
    assert "Assess UI impact for this iteration" in prompt
    assert "UI implementation is required for user-facing behavior changes" in prompt
    assert "Do not silently change architecture" in prompt
