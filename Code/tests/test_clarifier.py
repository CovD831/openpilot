from openpilot.clarifier import ClarificationAnswer, Clarifier, TaskBrief


def test_clarifier_detects_missing_deadline_and_deliverables():
    questions = Clarifier().detect("帮我规划项目")

    fields = {question.field for question in questions}

    assert "deadline" in fields
    assert "deliverables" in fields


def test_clarifier_skips_complete_project_goal():
    questions = Clarifier().detect("我要在两周内完成课程项目，包括调研、实现、测试和汇报")

    assert questions == []


def test_clarifier_once_defaults_create_assumptions():
    brief = Clarifier().build_brief("帮我规划项目", assume_defaults=True)

    assert brief.ready_for_planning is True
    assert "deadline unspecified" in brief.assumptions
    assert "deliverables to be clarified" in brief.assumptions
    assert "deadline" in brief.missing_fields


def test_task_brief_serializes_and_builds_constraints():
    brief = TaskBrief(
        goal="Plan a project",
        constraints=["Use concise steps"],
        answers=[ClarificationAnswer(field="deadline", answer="Friday")],
        assumptions=["normal priority assumed"],
    )

    payload = brief.model_dump(mode="json")

    assert payload["answers"][0]["field"] == "deadline"
    assert brief.planning_constraints() == [
        "Use concise steps",
        "deadline: Friday",
        "assumption: normal priority assumed",
    ]
