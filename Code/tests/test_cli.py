from openpilot.cli import main
from openpilot.llm import LLMResponse

from test_planner import FakeClient, VALID_PAYLOAD, response


def test_config_check_missing_key_does_not_crash(monkeypatch, capsys):
    monkeypatch.setenv("OPENPILOT_LLM_API_KEY", "")

    exit_code = main(["config", "check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "api_key" in captured.out
    assert "OPENPILOT_LLM_API_KEY" in captured.out


def test_config_check_reports_blank_base_url_without_secret(monkeypatch, capsys):
    monkeypatch.setenv("OPENPILOT_LLM_BASE_URL", " ")
    monkeypatch.setenv("OPENPILOT_LLM_API_KEY", "super-secret-key")

    exit_code = main(["config", "check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "OPENPILOT_LLM_BASE_URL" in captured.out
    assert "super-secret-key" not in captured.out


def test_plan_json_with_mocked_client(capsys):
    exit_code = main(
        ["plan", "Research AI agent tools", "--json"],
        llm_client=FakeClient([response(VALID_PAYLOAD)]),
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Research AI agent tools" in captured.out


def test_plan_reports_llm_error(capsys):
    exit_code = main(
        ["plan", "Research AI agent tools", "--json"],
        llm_client=FakeClient(
            [
                LLMResponse(content="bad", model="fake", provider="fake"),
                LLMResponse(content="still bad", model="fake", provider="fake"),
            ]
        ),
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Planning failed" in captured.err


def test_run_once_reports_planner_failure(tmp_path, capsys):
    log_file = tmp_path / "openpilot.jsonl"

    exit_code = main(
        [
            "run",
            "--once",
            "Research AI agent tools",
            "--log-file",
            str(log_file),
        ],
        llm_client=FakeClient(
            [
                LLMResponse(content="bad", model="fake", provider="fake"),
                LLMResponse(content="still bad", model="fake", provider="fake"),
            ]
        ),
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "planning failed and logged" in captured.out

