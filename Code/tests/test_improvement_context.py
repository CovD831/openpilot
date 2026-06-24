from __future__ import annotations

import json

from autonomous_iteration.improvement_context import ImprovementContextHelper
from core.openpilot_log import OpenPilotLogger
from metadata import ToolInputMetadata
from autonomous_iteration.tool.project_improvement_tool import project_improvement_tool_executor


def test_improvement_context_target_file_and_generic_product_fit(tmp_path) -> None:
    app = tmp_path / "app.py"
    app.write_text("import curses\n", encoding="utf-8")
    helper = ImprovementContextHelper(
        environment_context_getter=lambda path: {"run_command": "python app.py"} if path else {}
    )

    target = helper.select_iteration_target_file([str(app)], ["Improve app.py"])
    judgment = helper.infer_product_judgment(
        original_goal="Build a snake game",
        project_path=tmp_path,
        written_files=[str(app)],
    )
    rubric = helper.quality_rubric_for_product(judgment)
    context = helper.build_prompt_context(
        original_goal="Build a snake game",
        project_path=tmp_path,
        written_files=[str(app)],
        tool_task="Improve game",
        code_context="print('small')",
    )

    assert target == app
    assert judgment["project_type"] == "interactive_software"
    assert judgment["preferred_stack"] == "project_native"
    assert judgment["current_runtime"] == "terminal_curses"
    assert any("diagnosed success metric" in item for item in rubric)
    assert context["product_intent"]["runtime_mode"] == "interactive"
    assert context["product_intent"]["delivery_surface"] == "project_native"
    assert context["project_context"]["environment"]["run_command"] == "python app.py"
    assert helper.prompt_context_layer_summary(context)["has_product_intent"] is True
    assert helper.prompt_context_layer_summary(context)["code_context_chars"] == len("print('small')")


def test_product_intent_is_generic_for_non_game_goal(tmp_path) -> None:
    helper = ImprovementContextHelper()
    intent = helper.infer_product_intent(
        original_goal="Create a CSV analysis report script",
        project_path=tmp_path,
        written_files=[],
    )

    assert intent.experience_type == "general_project"
    assert intent.runtime_mode == "best_fit_for_goal"
    assert intent.delivery_surface == "project_native"
    assert "structured_output" in intent.core_capabilities


def test_improvement_context_requires_ui_impact_review_from_stack_preset(tmp_path) -> None:
    helper = ImprovementContextHelper(
        environment_context_getter=lambda path: {
            "stack_preset": {
                "revision": 2,
                "delivery_surface": "browser",
                "architecture": "frontend_backend_split",
                "frontend_language": "html_css_javascript",
                "backend_language": "python",
                "ui_strategy": "browser_application",
                "ui_review_required": True,
            }
        }
    )

    context = helper.build_prompt_context(
        original_goal="Build a personal digital assistant",
        project_path=tmp_path,
        written_files=[],
        tool_task="Add reminder creation",
    )

    assert context["stack_preset"]["revision"] == 2
    assert context["ui_iteration_contract"]["assessment_required"] is True
    assert context["ui_iteration_contract"]["implementation_required_for_user_facing_change"] is True
    assert any("UI impact is mandatory" in item for item in context["quality_rubric"])
    assert helper.prompt_context_layer_summary(context)["stack_preset_revision"] == 2


def test_improvement_context_flags_terminal_preset_conflict_for_user_facing_assistant(tmp_path) -> None:
    helper = ImprovementContextHelper(
        environment_context_getter=lambda path: {
            "stack_preset": {
                "revision": 1,
                "preset_source": "initial_inference",
                "delivery_surface": "terminal",
                "architecture": "terminal_application",
                "frontend_language": "terminal_text",
                "backend_language": "python",
                "ui_strategy": "terminal_ui",
                "ui_review_required": True,
            }
        }
    )

    context = helper.build_prompt_context(
        original_goal="帮我做一个个人数字助手",
        project_path=tmp_path,
        written_files=[],
        tool_task="Improve the assistant",
    )

    judgment = context["product_judgment"]
    assert judgment["preferred_runtime"] == "browser"
    assert judgment["preferred_surface"] == "browser"
    assert judgment["recommended_stack_preset_update"]["delivery_surface"] == "browser"


def test_project_improvement_tool_carries_deterministic_stack_revision_without_llm(tmp_path) -> None:
    result = project_improvement_tool_executor(
        ToolInputMetadata.from_mapping(
            "project_improvement_tool",
            {
                "project_path": str(tmp_path),
                "goal": "帮我做一个个人数字助手",
                "prompt_context": {
                    "product_judgment": {
                        "recommended_stack_preset_update": {
                            "delivery_surface": "browser",
                            "architecture": "frontend_backend_split",
                            "frontend_language": "html_css_javascript",
                            "ui_strategy": "browser_application",
                            "ui_review_required": True,
                        }
                    }
                },
            },
        )
    )

    assert result.result.stack_preset_update["delivery_surface"] == "browser"


def test_improvement_context_structured_logs_are_jsonl(tmp_path) -> None:
    log_file = tmp_path / "context.jsonl"
    logger = OpenPilotLogger(log_file)
    helper = ImprovementContextHelper(logger=logger, session_id_getter=lambda: "session")

    judgment = helper.infer_product_judgment(
        original_goal="Build a terminal tool",
        project_path=None,
        written_files=[],
    )
    helper.quality_rubric_for_product(judgment)

    events = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]

    assert events
    assert {event["payload"]["source_type"] for event in events} == {"function"}
    assert all(event["payload"]["phase"] == "improvement_context" for event in events)
