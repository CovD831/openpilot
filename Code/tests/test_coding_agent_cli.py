from __future__ import annotations

from pathlib import Path

from coding_agent.cli import build_parser, run


def test_cli_demo_runs_and_prints_evidence(capsys) -> None:
    args = build_parser().parse_args(["--demo", "--show-events"])

    assert run(args) == 0
    output = capsys.readouterr().out
    assert "status=success" in output
    assert "trajectory=" in output
    assert "task_received" in output
    assert "task_finished" in output


def test_cli_runs_against_workspace_with_draft_file(tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "hello.py").write_text("print('old')\n", encoding="utf-8")
    draft = tmp_path / "draft.py"
    draft.write_text("print('new')\n", encoding="utf-8")
    evidence = tmp_path / "evidence"
    args = build_parser().parse_args(
        [
            "--workspace",
            str(workspace),
            "--file",
            "hello.py",
            "--draft-file",
            str(draft),
            "--validate",
            "python -c \"from pathlib import Path; assert Path('hello.py').read_text() == \\\"print('new')\\\\n\\\"\"",
            "--evidence-dir",
            str(evidence),
        ]
    )

    assert run(args) == 0
    assert (workspace / "hello.py").read_text(encoding="utf-8") == "print('new')\n"
    assert list((evidence / "task_trajectory").iterdir())
    assert "verification=passed" in capsys.readouterr().out
