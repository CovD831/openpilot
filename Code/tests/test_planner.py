import pytest

from openpilot.exceptions import InvalidLLMResponseError
from openpilot.llm import LLMRequest, LLMResponse
from openpilot.planner import TaskPlanner
from openpilot.planner_models import RiskLevel, TaskNode, TaskStatus, TimelinePlan


VALID_PAYLOAD = {
    "task_card": {
        "goal": "Research AI agent tools",
        "task_type": "research",
        "priority": "normal",
        "risk_level": "low",
        "required_resources": ["web search"],
        "expected_deliverables": ["research brief"],
        "constraints": [],
    },
    "steps": [
        {
            "id": "step-1",
            "title": "Define research questions",
            "description": "Clarify scope and questions.",
            "risk_level": "low",
            "required_resources": [],
            "expected_output": "Question list",
            "dependencies": [],
            "confirmation_required": False,
        }
    ],
    "fallbacks": ["Use saved sources if search is unavailable."],
    "confirmation_points": [],
    "success_criteria": ["A structured brief is produced."],
}


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[LLMRequest] = []

    def complete(self, request):
        self.requests.append(request)
        return self.responses.pop(0)


def response(payload):
    return LLMResponse(
        content="",
        parsed_json=payload,
        model="fake-model",
        provider="fake",
    )


def test_planner_validates_output():
    planner = TaskPlanner(FakeClient([response(VALID_PAYLOAD)]))

    plan = planner.plan("Research AI agent tools")

    assert plan.task_card.task_type == "research"
    assert plan.steps[0].id == "step-1"
    assert plan.timeline is not None
    assert plan.timeline.task_tree[0].id == "step-1"


def test_timeline_models_serialize():
    node = TaskNode(
        id="step-1",
        title="Clarify scope",
        description="Define the project scope.",
        risk_level=RiskLevel.LOW,
        expected_output="Scope note",
    )
    timeline = TimelinePlan(
        goal="Ship a project",
        time_horizon="within two weeks",
        task_tree=[node],
        milestones=["step-1: Scope note"],
    )

    payload = timeline.model_dump(mode="json")

    assert payload["task_tree"][0]["status"] == TaskStatus.PLANNED.value
    assert payload["time_horizon"] == "within two weeks"


def test_planner_generates_task_progress_timeline():
    payload = VALID_PAYLOAD | {
        "task_card": VALID_PAYLOAD["task_card"] | {
            "goal": "我要在两周内完成一个项目",
            "task_type": "project_planning",
            "required_resources": ["timeline", "reminder_plan", "task_log"],
            "expected_deliverables": ["task tree", "timeline"],
        },
        "steps": [
            VALID_PAYLOAD["steps"][0] | {
                "id": "step-1",
                "title": "Clarify scope and deadline",
                "expected_output": "Confirmed scope",
            },
            VALID_PAYLOAD["steps"][0] | {
                "id": "step-2",
                "title": "Build delivery timeline",
                "expected_output": "Two-week timeline",
                "dependencies": ["step-1"],
            },
        ],
    }
    planner = TaskPlanner(FakeClient([response(payload)]))

    plan = planner.plan("我要在两周内完成一个项目")

    assert plan.task_card.task_type == "planning"  # project_planning mapped to planning
    assert plan.timeline is not None
    assert plan.timeline.time_horizon == "within two weeks"
    assert [node.status for node in plan.timeline.task_tree] == [
        TaskStatus.PLANNED,
        TaskStatus.PLANNED,
    ]
    assert plan.timeline.task_tree[1].dependencies == ["step-1"]
    assert plan.timeline.reminder_plan


def test_risk_policy_upgrades_high_risk_goal():
    payload = VALID_PAYLOAD | {
        "task_card": VALID_PAYLOAD["task_card"] | {
            "goal": "Send email to my professor with the final draft",
            "risk_level": "low",
        }
    }
    planner = TaskPlanner(FakeClient([response(payload)]))

    plan = planner.plan("Send email to my professor with the final draft")

    assert plan.task_card.risk_level == RiskLevel.HIGH
    assert "task" in plan.confirmation_points


def test_malformed_json_retries_once():
    planner = TaskPlanner(
        FakeClient(
            [
                LLMResponse(content="not json", model="fake-model", provider="fake"),
                response(VALID_PAYLOAD),
            ]
        )
    )

    plan = planner.plan("Research AI agent tools")

    assert plan.task_card.goal == "Research AI agent tools"


def test_malformed_json_errors_after_retry():
    planner = TaskPlanner(
        FakeClient(
            [
                LLMResponse(content="not json", model="fake-model", provider="fake"),
                LLMResponse(content="still not json", model="fake-model", provider="fake"),
            ]
        )
    )

    with pytest.raises(InvalidLLMResponseError):
        planner.plan("Research AI agent tools")


