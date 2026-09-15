from __future__ import annotations

import json
from pathlib import Path

import pytest

from evidence_core import EvidenceStore
from evidence_core.cli import build_parser, run


def _seed_store(tmp_path: Path) -> EvidenceStore:
    store = EvidenceStore(tmp_path / "evidence")
    store.start_run("task-cli", source="test", goal="inspect fixture")
    store.record_event("task-cli", event_type="task_received", payload={"goal": "inspect fixture"})
    store.record_event("task-cli", event_type="tool_called", payload={"tool": "file_reader"})
    store.record_event("task-cli", event_type="tool_succeeded", payload={"tool": "file_reader"})
    store.record_event(
        "task-cli",
        event_type="verification_state_changed",
        payload={"verification_status": "passed"},
    )
    store.record_artifact("task-cli", kind="stdout", content="hello", filename="stdout.txt")
    store.finish_run("task-cli", success=True, reason="done")
    return store


def test_evidence_cli_lists_and_shows_json(tmp_path: Path, capsys) -> None:
    store = _seed_store(tmp_path)

    assert run(build_parser().parse_args(["--data-dir", str(store.data_dir), "list", "--json"])) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed[0]["task_id"] == "task-cli"

    assert run(build_parser().parse_args(["--data-dir", str(store.data_dir), "show", "task-cli", "--json"])) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["summary"]["final_status"] == "success"
    assert shown["artifacts"][0]["kind"] == "stdout"


def test_evidence_cli_timeline_and_safe_export(tmp_path: Path, capsys) -> None:
    store = _seed_store(tmp_path)
    output = tmp_path / "bundle"
    args = build_parser().parse_args(["--data-dir", str(store.data_dir), "timeline", "task-cli"])

    assert run(args) == 0
    timeline = capsys.readouterr().out
    assert "task_received" in timeline
    assert "task_finished" in timeline

    assert run(
        build_parser().parse_args(
            ["--data-dir", str(store.data_dir), "export", "task-cli", "--output", str(output)]
        )
    ) == 0
    assert (output / store.load_run("task-cli").run_id / "events.jsonl").exists()
    capsys.readouterr()

    with pytest.raises(ValueError, match="pass --force"):
        run(
            build_parser().parse_args(
                ["--data-dir", str(store.data_dir), "export", "task-cli", "--output", str(output)]
            )
        )
