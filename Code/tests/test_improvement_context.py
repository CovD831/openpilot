from __future__ import annotations

import json

from autonomous_iteration.improvement_context import ImprovementContextHelper
from core.openpilot_log import OpenPilotLogger


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
