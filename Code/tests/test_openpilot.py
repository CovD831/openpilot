import io
import json

from openpilot.openpilot_log import OpenPilotLogger
from openpilot.openpilot_session import OpenPilotSession
from openpilot.cli import main
from openpilot.config import LLMSettings
from openpilot.llm import LLMResponse
from openpilot.planner import TaskPlanner

from test_planner import FakeClient, VALID_PAYLOAD, response


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_logger_creates_parent_directory_and_writes_jsonl(tmp_path):
    log_file = tmp_path / "nested" / "openpilot.jsonl"
    logger = OpenPilotLogger(log_file)

    logger.log_event(
        "goal_received",
        {"goal": "Research AI agents"},
        session_id="session-1",
        turn_id=1,
    )

    events = read_jsonl(log_file)
    assert log_file.exists()
    assert events[0]["event_type"] == "goal_received"
    assert events[0]["payload"]["goal"] == "Research AI agents"


def test_handle_goal_logs_success_events(tmp_path):
    log_file = tmp_path / "openpilot.jsonl"
    planner = TaskPlanner(FakeClient([response(VALID_PAYLOAD)]))
    session = OpenPilotSession(
        planner,
        OpenPilotLogger(log_file),
        constraints=["Use concise steps"],
        session_id="session-1",
    )

    result = session.handle_goal("Research AI agent tools")

    events = read_jsonl(log_file)
    assert result.ok is True
    assert result.plan is not None
    assert [event["event_type"] for event in events] == [
        "goal_received",
        "planner_started",
        "planner_succeeded",
        "reminders_planned",
    ]
    assert events[-2]["payload"]["task_card"]["goal"] == "Research AI agent tools"
    assert events[-2]["payload"]["steps"][0]["id"] == "step-1"
    assert events[-2]["payload"]["timeline"]["task_tree"][0]["id"] == "step-1"
    assert events[-2]["payload"]["reminder_plan"]["items"]
    assert events[-1]["event_type"] == "reminders_planned"


def test_handle_goal_logs_planner_failure(tmp_path):
    log_file = tmp_path / "openpilot.jsonl"
    planner = TaskPlanner(
        FakeClient(
            [
                LLMResponse(content="bad", model="fake", provider="fake"),
                LLMResponse(content="still bad", model="fake", provider="fake"),
            ]
        )
    )
    session = OpenPilotSession(planner, OpenPilotLogger(log_file), session_id="session-1")

    result = session.handle_goal("Research AI agent tools")

    events = read_jsonl(log_file)
    assert result.ok is False
    assert result.plan is None
    assert events[-1]["event_type"] == "planner_failed"
    assert events[-1]["payload"]["error_type"] == "InvalidLLMResponseError"


def test_interactive_loop_exits_on_exit_commands(tmp_path):
    for command in ("exit", "quit", ":q"):
        log_file = tmp_path / f"{command.replace(':', '')}.jsonl"
        planner = TaskPlanner(FakeClient([]))
        session = OpenPilotSession(
            planner,
            OpenPilotLogger(log_file),
            session_id="session-1",
            settings=LLMSettings(api_key="test-key"),
        )
        output = io.StringIO()

        exit_code = session.run(input_stream=io.StringIO(f"{command}\n"), output_stream=output)

        assert exit_code == 0
        assert "bye" in output.getvalue()


def test_openpilot_startup_prints_api_guidance(tmp_path):
    log_file = tmp_path / "openpilot.jsonl"
    planner = TaskPlanner(FakeClient([]))
    session = OpenPilotSession(
        planner,
        OpenPilotLogger(log_file),
        session_id="session-1",
        settings=LLMSettings(api_key=None),
    )
    output = io.StringIO()

    exit_code = session.run(input_stream=io.StringIO("exit\n"), output_stream=output)

    text = output.getvalue()
    assert exit_code == 0
    assert "OpenPilot API setup" in text
    assert "OPENPILOT_LLM_API_KEY" in text
    assert "your-secret-key" in text


def test_interactive_loop_repeats_warning_when_config_incomplete(tmp_path):
    log_file = tmp_path / "openpilot.jsonl"
    planner = TaskPlanner(FakeClient([]))
    session = OpenPilotSession(
        planner,
        OpenPilotLogger(log_file),
        session_id="session-1",
        settings=LLMSettings(api_key=None),
    )
    output = io.StringIO()

    exit_code = session.run(input_stream=io.StringIO("\nexit\n"), output_stream=output)

    text = output.getvalue()
    assert exit_code == 0
    assert text.count("WARNING: LLM config incomplete") >= 2


def test_interactive_loop_clarifies_then_plans(tmp_path):
    log_file = tmp_path / "openpilot.jsonl"
    planner = TaskPlanner(FakeClient([response(VALID_PAYLOAD)]))
    session = OpenPilotSession(
        planner,
        OpenPilotLogger(log_file),
        session_id="session-1",
        settings=LLMSettings(api_key="test-key"),
    )
    output = io.StringIO()

    exit_code = session.run(
        input_stream=io.StringIO(
            "帮我规划项目\n"
            "两周内\n"
            "课程项目原型和展示材料\n"
            "高优先级\n"
            "每天两小时\n"
            "需要老师反馈\n"
            "只包含原型和汇报\n"
            "exit\n"
        ),
        output_stream=output,
    )

    events = read_jsonl(log_file)
    event_types = [event["event_type"] for event in events]
    assert exit_code == 0
    assert "OpenPilot needs a few details" in output.getvalue()
    assert "clarification_started" in event_types
    assert "clarification_answered" in event_types
    assert "clarification_completed" in event_types
    completed = next(
        event for event in events if event["event_type"] == "clarification_completed"
    )
    assert completed["payload"]["task_brief"]["answers"][0]["field"] == "deadline"


def test_cli_run_once_logs_and_prints_modern_plan(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("OPENPILOT_LLM_API_KEY", "")
    log_file = tmp_path / "openpilot.jsonl"

    exit_code = main(
        [
            "run",
            "--once",
            "Research AI agent tools",
            "--log-file",
            str(log_file),
        ],
        llm_client=FakeClient([response(VALID_PAYLOAD)]),
    )

    captured = capsys.readouterr()
    events = read_jsonl(log_file)
    assert exit_code == 0
    assert "OpenPilot" in captured.out
    assert "Reading goal" in captured.out
    assert "Checking missing details" in captured.out
    assert "Calling planner" in captured.out
    assert "Timeline" in captured.out
    assert "Reminder plan" in captured.out
    assert "Planned steps" in captured.out
    assert "Define research questions" in captured.out
    assert "WARNING: LLM config incomplete" in captured.out
    assert events[-2]["event_type"] == "planner_succeeded"
    assert events[-1]["event_type"] == "reminders_planned"


def test_cli_run_once_uses_assumptions_for_vague_goal(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("OPENPILOT_LLM_API_KEY", "")
    log_file = tmp_path / "openpilot.jsonl"

    exit_code = main(
        [
            "run",
            "--once",
            "帮我规划项目",
            "--log-file",
            str(log_file),
        ],
        llm_client=FakeClient([response(VALID_PAYLOAD)]),
    )

    captured = capsys.readouterr()
    events = read_jsonl(log_file)
    assert exit_code == 0
    assert "Assumptions" in captured.out
    assert "deadline unspecified" in captured.out
    assert "clarification_started" in [event["event_type"] for event in events]
    assert events[-2]["payload"]["assumptions"]


def test_cli_openpilot_alias_once_still_works(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("OPENPILOT_LLM_API_KEY", "")
    log_file = tmp_path / "openpilot.jsonl"

    exit_code = main(
        [
            "openpilot",
            "--once",
            "Research AI agent tools",
            "--log-file",
            str(log_file),
        ],
        llm_client=FakeClient([response(VALID_PAYLOAD)]),
    )

    captured = capsys.readouterr()
    events = read_jsonl(log_file)
    assert exit_code == 0
    assert "planned and logged" in captured.out
    assert "Timeline" in captured.out
    assert "Reminder plan" in captured.out
    assert "Define research questions" in captured.out
    assert events[-2]["event_type"] == "planner_succeeded"
    assert events[-1]["event_type"] == "reminders_planned"
