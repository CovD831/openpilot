"""Checkpoint resume primitives: schema header, unfinished-run detection,
in-place continuation."""

from __future__ import annotations

import json

from op0.metadata import SCHEMA_VERSION
from op0.session import Session


def test_trajectory_carries_a_schema_header(tmp_path) -> None:
    session = Session(tmp_path)
    session.record("turn_started", {"prompt": "hi", "turn_id": "t1"})
    first = json.loads(session.path.read_text(encoding="utf-8").splitlines()[0])
    assert first["record"] == "schema" and first["schema_version"] == SCHEMA_VERSION
    assert first["run_id"] == session.run_id


def test_load_skips_header_and_reads_legacy_ledgers(tmp_path) -> None:
    # a legacy ledger without a header must stay replayable
    legacy = tmp_path / ".openpilot" / "trajectory"
    legacy.mkdir(parents=True)
    event = {"event_type": "turn_started", "payload": {"prompt": "p", "turn_id": "t"},
             "producer": "pi", "call_id": "", "idempotency_key": "k", "timestamp": "t"}
    (legacy / "run_legacy.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
    session = Session.resume(tmp_path, "run_legacy")
    assert len(session.load_events()) == 1  # no header, still loads

    session.record("turn_started", {"prompt": "p2", "turn_id": "t2"})
    assert len(session.load_events()) == 2  # appends continue after legacy events


def test_unfinished_runs_finds_open_ledgers(tmp_path) -> None:
    finished = Session(tmp_path)
    finished.record("turn_started", {"prompt": "a", "turn_id": "t1"})
    finished.record("run_finished", {"response_chars": 3})
    open_run = Session(tmp_path)
    open_run.record("turn_started", {"prompt": "b", "turn_id": "t2"})

    candidates = Session.unfinished_runs(tmp_path)
    assert open_run.path in candidates and finished.path not in candidates


def test_resume_continues_idempotency_chain(tmp_path) -> None:
    first = Session(tmp_path)
    first.record("turn_started", {"prompt": "a", "turn_id": "t1"})
    resumed = Session.resume(tmp_path, first.run_id)
    record = resumed.record("turn_started", {"prompt": "b", "turn_id": "t2"})
    assert record.idempotency_key.endswith(":2")  # the chain continues, not restarts
