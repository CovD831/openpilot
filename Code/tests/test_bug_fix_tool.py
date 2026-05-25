from __future__ import annotations

import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

from metadata import BugFixResultMetadata, ResultStatus, ToolInputMetadata
from tools import bug_fix_tool as bug_fix_tool_module
from tools.bug_fix_tool import bug_fix_tool_executor
from tools.builtin_tools import register_builtin_tools
from tools.terminal_smoke import TerminalSmokeResult
from tools.tool_executor import ToolExecutor
from tools.tool_registry import ToolRegistry
from tools.tool_selection import ToolSelection


class FakeBugFixLLM:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        if not self.payloads:
            raise AssertionError("No fake LLM payloads left")
        return SimpleNamespace(parsed_json=self.payloads.pop(0), content="")


def _python_file_command(path: Path) -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(path.name)}"


def _input(command: str, tmp_path: Path, file_paths: list[str], **extra) -> ToolInputMetadata:
    return ToolInputMetadata.from_mapping(
        "bug_fix_tool",
        {
            "command": command,
            "cwd": str(tmp_path),
            "file_paths": file_paths,
            "timeout": 10,
            **extra,
        },
    )


def test_bug_fix_tool_returns_success_without_reading_when_command_already_runs(tmp_path) -> None:
    llm = FakeBugFixLLM([])

    result = bug_fix_tool_executor(
        _input(
            f"{shlex.quote(sys.executable)} -c {shlex.quote('print(\"ok\")')}",
            tmp_path,
            ["missing.py"],
            _llm_client=llm,
        )
    )

    assert result.status == ResultStatus.SUCCESS
    assert isinstance(result.result, BugFixResultMetadata)
    assert result.result.fixed is False
    assert result.result.iterations_used == 0
    assert len(result.result.attempts) == 1
    assert llm.requests == []


def test_bug_fix_tool_repairs_python_syntax_error_and_verifies_command(tmp_path) -> None:
    app = tmp_path / "app.py"
    app.write_text("print('broken'\n", encoding="utf-8")
    llm = FakeBugFixLLM(
        [
            {
                "rationale": "Close the missing parenthesis.",
                "files": [{"file_path": "app.py", "content": "print('fixed')\n"}],
            }
        ]
    )

    result = bug_fix_tool_executor(_input(_python_file_command(app), tmp_path, ["app.py"], _llm_client=llm))

    assert result.status == ResultStatus.SUCCESS
    assert result.result.fixed is True
    assert result.result.iterations_used == 1
    assert result.result.final_command_result.success is True
    assert app.read_text(encoding="utf-8") == "print('fixed')\n"


def test_bug_fix_tool_warning_mode_does_not_stop_on_exit_zero(tmp_path) -> None:
    app = tmp_path / "app.py"
    app.write_text(
        "import sys\n"
        "print(\"/site-packages/pygame/sysfont.py:226: UserWarning: Process running '/usr/X11/bin/fc-list' timed-out! System fonts cannot be loaded on your platform\", file=sys.stderr)\n",
        encoding="utf-8",
    )
    llm = FakeBugFixLLM(
        [
            {
                "rationale": "Use a local fallback font path and stop touching pygame sysfont.",
                "files": [{"file_path": "app.py", "content": "print('ok')\n"}],
            }
        ]
    )

    result = bug_fix_tool_executor(
        _input(
            _python_file_command(app),
            tmp_path,
            ["app.py"],
            warning_check_required=True,
            _llm_client=llm,
        )
    )

    assert result.status == ResultStatus.SUCCESS
    assert result.result.fixed is True
    assert result.result.iterations_used == 1
    assert llm.requests
    assert app.read_text(encoding="utf-8") == "print('ok')\n"


def test_bug_fix_tool_warning_mode_requests_decision_when_warning_remains(tmp_path) -> None:
    app = tmp_path / "app.py"
    warning_source = (
        "import sys\n"
        "print(\"/site-packages/pygame/sysfont.py:226: UserWarning: Process running '/usr/X11/bin/fc-list' timed-out! System fonts cannot be loaded on your platform\", file=sys.stderr)\n"
    )
    app.write_text(warning_source, encoding="utf-8")
    llm = FakeBugFixLLM(
        [
            {
                "rationale": "Still emits the warning.",
                "files": [{"file_path": "app.py", "content": warning_source}],
            }
        ]
    )

    result = bug_fix_tool_executor(
        _input(
            _python_file_command(app),
            tmp_path,
            ["app.py"],
            max_iterations=1,
            warning_check_required=True,
            _llm_client=llm,
        )
    )

    assert result.status == ResultStatus.FAIL
    assert result.failure.error_type == "MaxBugFixIterationsReached"
    assert "Runtime warning still requires repair" in result.failure.error_message
    assert result.result.requires_user_decision is True


def test_bug_fix_tool_uses_terminal_smoke_for_curses_runtime(tmp_path, monkeypatch) -> None:
    app = tmp_path / "app.py"
    app.write_text(
        "import curses\n"
        "import sys\n"
        "if not sys.stdout.isatty():\n"
        "    sys.exit(0)\n"
        "def main(stdscr):\n"
        "    stdscr.addstr(25, 0, 'too low')\n"
        "if __name__ == '__main__':\n"
        "    curses.wrapper(main)\n",
        encoding="utf-8",
    )
    llm = FakeBugFixLLM(
        [
            {
                "rationale": "Add terminal bounds handling.",
                "files": [
                    {
                        "file_path": "app.py",
                        "content": (
                            "import curses\n"
                            "def main(stdscr):\n"
                            "    max_y, max_x = stdscr.getmaxyx()\n"
                            "    if max_y > 0 and max_x > 0:\n"
                            "        stdscr.addstr(0, 0, 'ok'[:max_x])\n"
                            "if __name__ == '__main__':\n"
                            "    curses.wrapper(main)\n"
                        ),
                    }
                ],
            }
        ]
    )
    calls = []

    def fake_terminal_smoke(command, **kwargs):
        calls.append(command)
        source = app.read_text(encoding="utf-8")
        if "too low" in source or "sys.stdout.isatty" in source:
            return TerminalSmokeResult(
                command=str(command),
                success=False,
                stdout="",
                stderr="Traceback (most recent call last):\n_curses.error: addwstr() returned ERR",
                exit_code=1,
                duration=0.1,
            )
        return TerminalSmokeResult(
            command=str(command),
            success=True,
            stdout="ok",
            stderr="",
            exit_code=0,
            duration=0.1,
        )

    monkeypatch.setattr(bug_fix_tool_module, "run_terminal_command", fake_terminal_smoke)

    result = bug_fix_tool_executor(_input(_python_file_command(app), tmp_path, ["app.py"], _llm_client=llm))

    assert len(calls) == 2
    assert result.status == ResultStatus.SUCCESS
    assert result.result.fixed is True
    assert result.result.final_command_result.attributes["terminal_smoke"] is True


def test_bug_fix_tool_rejects_non_tty_bypass_for_curses_runtime(tmp_path, monkeypatch) -> None:
    app = tmp_path / "app.py"
    bypass_source = (
        "import curses\n"
        "import sys\n"
        "if not sys.stdout.isatty():\n"
        "    sys.exit(0)\n"
        "def main(stdscr):\n"
        "    stdscr.addstr(25, 0, 'too low')\n"
        "if __name__ == '__main__':\n"
        "    curses.wrapper(main)\n"
    )
    app.write_text(bypass_source, encoding="utf-8")
    llm = FakeBugFixLLM(
        [
            {
                "rationale": "Keep the non-TTY bypass.",
                "files": [{"file_path": "app.py", "content": bypass_source}],
            }
        ]
    )

    def fake_terminal_smoke(command, **kwargs):
        return TerminalSmokeResult(
            command=str(command),
            success=False,
            stdout="",
            stderr="Traceback (most recent call last):\n_curses.error: addwstr() returned ERR",
            exit_code=1,
            duration=0.1,
        )

    monkeypatch.setattr(bug_fix_tool_module, "run_terminal_command", fake_terminal_smoke)

    result = bug_fix_tool_executor(
        _input(_python_file_command(app), tmp_path, ["app.py"], max_iterations=1, _llm_client=llm)
    )

    assert result.status == ResultStatus.FAIL
    assert result.failure.error_type == "MaxBugFixIterationsReached"
    assert result.result.requires_user_decision is True


def test_bug_fix_tool_rejects_llm_changes_outside_declared_files(tmp_path) -> None:
    app = tmp_path / "app.py"
    app.write_text("print('broken'\n", encoding="utf-8")
    outside = tmp_path / "outside.py"
    llm = FakeBugFixLLM(
        [
            {
                "rationale": "Attempt to edit an undeclared file.",
                "files": [{"file_path": str(outside), "content": "print('nope')\n"}],
            }
        ]
    )

    result = bug_fix_tool_executor(_input(_python_file_command(app), tmp_path, ["app.py"], _llm_client=llm))

    assert result.status == ResultStatus.FAIL
    assert result.failure.error_type == "InvalidBugFixPayload"
    assert "undeclared file" in result.failure.error_message
    assert not outside.exists()


def test_bug_fix_tool_default_max_iterations_requests_user_decision(tmp_path) -> None:
    app = tmp_path / "app.py"
    app.write_text("print('broken'\n", encoding="utf-8")
    llm = FakeBugFixLLM(
        [
            {"rationale": "Still broken.", "files": [{"file_path": "app.py", "content": "print('broken'\n"}]}
            for _ in range(5)
        ]
    )

    result = bug_fix_tool_executor(_input(_python_file_command(app), tmp_path, ["app.py"], _llm_client=llm))

    assert result.status == ResultStatus.FAIL
    assert result.failure.error_type == "MaxBugFixIterationsReached"
    assert result.result.requires_user_decision is True
    assert result.result.iterations_used == 5
    assert len(result.result.attempts) == 6


def test_bug_fix_tool_continues_after_user_approval(tmp_path) -> None:
    app = tmp_path / "app.py"
    app.write_text("print('broken'\n", encoding="utf-8")
    approvals = []
    llm = FakeBugFixLLM(
        [
            {"rationale": "Still broken 1.", "files": [{"file_path": "app.py", "content": "print('broken'\n"}]},
            {"rationale": "Still broken 2.", "files": [{"file_path": "app.py", "content": "print('broken'\n"}]},
            {"rationale": "Now fixed.", "files": [{"file_path": "app.py", "content": "print('fixed')\n"}]},
        ]
    )

    result = bug_fix_tool_executor(
        _input(
            _python_file_command(app),
            tmp_path,
            ["app.py"],
            max_iterations=1,
            continuation_iterations=2,
            _llm_client=llm,
            _ask_user_to_continue=lambda metadata: approvals.append(metadata.iterations_used) or True,
        )
    )

    assert result.status == ResultStatus.SUCCESS
    assert result.result.iterations_used == 3
    assert approvals == [1]


def test_bug_fix_tool_stops_when_user_declines_more_iterations(tmp_path) -> None:
    app = tmp_path / "app.py"
    app.write_text("print('broken'\n", encoding="utf-8")
    llm = FakeBugFixLLM(
        [{"rationale": "Still broken.", "files": [{"file_path": "app.py", "content": "print('broken'\n"}]}]
    )

    result = bug_fix_tool_executor(
        _input(
            _python_file_command(app),
            tmp_path,
            ["app.py"],
            max_iterations=1,
            _llm_client=llm,
            _ask_user_to_continue=lambda metadata: False,
        )
    )

    assert result.status == ResultStatus.FAIL
    assert result.failure.error_type == "BugFixTerminatedByUser"
    assert result.result.user_terminated is True
    assert result.result.requires_user_decision is False


def test_bug_fix_tool_is_registered_and_requires_command_and_files() -> None:
    registry = ToolRegistry()
    register_builtin_tools(registry)
    assert registry.get("bug_fix_tool") is not None
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="bugfix",
                tool_name="bug_fix_tool",
                reason="capability_match",
                input_metadata={},
            )
        )
    finally:
        executor.shutdown()

    assert result.success is False
    assert "Missing required metadata field: command" in result.error.error_message
    assert "Missing required metadata field: file_paths" in result.error.error_message
