"""Compaction: obs storage, E1 entry cap, projection build, fail-closed."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from op0.bridge import ReadOnlyToolBridge, _compress_command_output
from op0.compaction import (
    build_handoff,
    build_projection,
    estimate_usage,
    fetch_observation,
    observation_tombstone,
    should_compact,
    store_observation,
    write_handoff,
)
from op0.session import Session


def _session(tmp_path: Path) -> Session:
    return Session(tmp_path)


def _record_turn(session: Session, index: int, prompt: str, reply: str, result: str = "") -> str:
    call_id = f"11111111-0000-4000-8000-{index:012d}"
    session.record("turn_started", {"prompt": prompt, "turn_id": f"turn-{index}"}, producer="pi")
    if result:
        session.record(
            "tool_call",
            {"type": "tool_execution_start", "toolName": "openpilot_bash", "toolCallId": call_id},
            producer="pi",
            call_id=call_id,
        )
        session.record(
            "tool_result",
            {"type": "tool_execution_end", "content": result, "toolCallId": call_id},
            producer="pi",
            call_id=call_id,
        )
    session.record(
        "model_response",
        {
            "message": {
                "role": "assistant",
                "stopReason": "end_turn",
                "content": [{"type": "text", "text": reply}],
            }
        },
        producer="pi",
    )
    session.record("agent_end", {}, producer="pi")
    return call_id


def _model_response_usage(tokens: int) -> dict:
    return {
        "message": {
            "role": "assistant",
            "stopReason": "end_turn",
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": tokens},
        }
    }


def test_obs_roundtrip_keeps_sha256(tmp_path: Path) -> None:
    observations = tmp_path / "observations"
    body = "line\n" * 3000  # ~15k bytes
    call_id = "aaaaaaaa-0000-4000-8000-000000000001"
    meta = store_observation(str(observations), call_id, "openpilot_bash", body)
    assert meta is not None
    assert meta["sha256"] == hashlib.sha256(body.encode()).hexdigest()
    fetched = fetch_observation(str(observations), call_id)
    assert hashlib.sha256(fetched.encode()).hexdigest() == meta["sha256"]


def test_store_is_idempotent_per_call_id(tmp_path: Path) -> None:
    observations = tmp_path / "observations"
    first = store_observation(str(observations), "bbbbbbbb-0000-4000-8000-000000000002", "t", "x" * 9000)
    second = store_observation(str(observations), "bbbbbbbb-0000-4000-8000-000000000002", "t", "y" * 9000)
    # repeated store keeps the first form AND still yields a pointer, so E1
    # never leaks the full text back into the context on a duplicate call
    assert first is not None and second is not None
    assert second["sha256"] == first["sha256"]
    assert (observations / "bbbbbbbb-0000-4000-8000-000000000002.txt").read_text() == "x" * 9000


def test_fetch_rejects_bad_ids(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        fetch_observation(str(tmp_path), "../escape")
    with pytest.raises(ValueError):
        fetch_observation(str(tmp_path), "cccccccc-0000-4000-8000-000000000003")


def test_e1_oversized_result_becomes_tombstone(tmp_path: Path) -> None:
    big = tmp_path / "big.txt"
    # wide rows: a single read page must exceed the E1 threshold (read paging
    # caps lines, so narrow rows would stay under the cap by design)
    body = "".join(f"row {i} " + "x" * 120 + "\n" for i in range(100))
    big.write_text(body, encoding="utf-8")
    observations = tmp_path / ".openpilot" / "observations"
    bridge = ReadOnlyToolBridge((str(tmp_path),), observations_dir=str(observations))
    response = bridge._handle(
        {"toolName": "openpilot_read", "toolCallId": "dddddddd-0000-4000-8000-000000000004", "args": {"path": "big.txt"}}
    )
    assert response["success"] is True
    assert "openpilot_obs(" in response["content"]
    assert "last 400 chars" in response["content"]
    # the tail of the output is preserved inline (errors live at the end)
    assert "row 99 " in response["content"]
    # full text is retrievable: the stored form is the paged view the model
    # would have seen (line numbers included), verbatim
    stored = observations / "dddddddd-0000-4000-8000-000000000004.txt"
    stored_text = stored.read_text(encoding="utf-8")
    assert stored_text.startswith("     1\trow 0")
    assert "row 99 " in stored_text


def test_small_result_passes_through(tmp_path: Path) -> None:
    small = tmp_path / "small.txt"
    small.write_text("tiny", encoding="utf-8")
    bridge = ReadOnlyToolBridge((str(tmp_path),), observations_dir=str(tmp_path / "obs"))
    response = bridge._handle(
        {"toolName": "openpilot_read", "toolCallId": "eeeeeeee-0000-4000-8000-000000000005", "args": {"path": "small.txt"}}
    )
    assert response["content"].strip().endswith("tiny")
    assert "openpilot_obs(" not in response["content"]


def test_bridge_obs_handler_roundtrip(tmp_path: Path) -> None:
    observations = tmp_path / "obs"
    call_id = "ffffffff-0000-4000-8000-000000000006"
    body = "payload\n" * 1500
    meta = store_observation(str(observations), call_id, "openpilot_bash", body)
    assert meta is not None
    bridge = ReadOnlyToolBridge((str(tmp_path),), observations_dir=str(observations))
    response = bridge._handle(
        {"toolName": "openpilot_obs", "toolCallId": "other-id", "args": {"id": call_id}}
    )
    assert response["success"] is True
    assert response["content"] == body
    missing = bridge._handle(
        {"toolName": "openpilot_obs", "toolCallId": "other-id", "args": {"id": "99999999-0000-4000-8000-000000000009"}}
    )
    assert missing["success"] is False
    assert "unknown observation" in missing["content"]


def test_projection_masks_folded_and_keeps_recent(tmp_path: Path) -> None:
    session = _session(tmp_path / "proj")
    observations = tmp_path / "proj" / ".openpilot" / "observations"
    for index in range(1, 6):
        result = "data\n" * 1200 if index == 2 else "small result"  # turn 2 ~6k bytes
        _record_turn(session, index, f"task {index}", f"reply {index}", result=result)
    projection = build_projection(session.load_events(), str(observations))
    assert projection is not None
    assert "3 folded turns" in projection
    assert "2 recent turns verbatim" in projection
    assert "task 3" in projection and "reply 5" in projection  # recent stays verbatim
    assert "task 1" in projection  # folded user intents stay verbatim
    assert "openpilot_obs(" in projection  # the oversized folded result is indexed
    # idempotent: same ledger rebuilds the same projection
    again = build_projection(session.load_events(), str(observations))
    assert again == projection


def test_folded_results_all_stored(tmp_path: Path) -> None:
    """Folded zone is one line per turn; every folded result is stored whole
    and indexed, so anything once seen stays retrievable after folding."""
    session = _session(tmp_path / "proj")
    observations = tmp_path / "proj" / ".openpilot" / "observations"
    mid = "head line\n" + "filler\n" * 300 + "ERROR: the real verdict\n"  # ~2.2k
    _record_turn(session, 1, "task 1", "reply 1", result=mid)
    _record_turn(session, 2, "task 2", "reply 2")
    _record_turn(session, 3, "task 3", "reply 3")
    projection = build_projection(session.load_events(), str(observations))
    assert projection is not None
    assert "### Turn 1: user: task 1 | assistant: reply 1 | 1 tool call(s)" in projection
    assert "filler" not in projection  # folded results never replay inline
    stored = observations / "11111111-0000-4000-8000-000000000001.txt"
    assert "ERROR: the real verdict" in stored.read_text(encoding="utf-8")  # retrievable whole
    assert "openpilot_obs(\"11111111-0000-4000-8000-000000000001\")" in projection


def test_p4_duplicate_results_collapse(tmp_path: Path) -> None:
    session = _session(tmp_path / "proj")
    same = "repeated output\n" * 400  # ~6.8k, masked zone
    for index in (1, 2, 3, 4, 5):
        _record_turn(session, index, f"task {index}", f"reply {index}", result=same)
    observations = tmp_path / "proj" / ".openpilot" / "observations"
    projection = build_projection(session.load_events(), str(observations))
    assert projection is not None
    # five identical results, three folded: the first is stored, the next two collapse
    assert "3 folded turns" in projection
    assert "duplicate" not in projection  # no per-result marker lines in the folded zone
    assert len(list(observations.glob("*.txt"))) == 1


def test_p5_collapses_blank_runs(tmp_path: Path) -> None:
    session = _session(tmp_path / "proj")
    _record_turn(session, 1, "task\n\n\n\nwith blanks   \n", "reply\n\n\n\nwith blanks")
    _record_turn(session, 2, "task 2", "reply 2")
    _record_turn(session, 3, "task 3", "reply 3")
    projection = build_projection(session.load_events(), None)
    assert projection is not None
    assert "\n\n\n" not in projection
    assert "with blanks" in projection


def test_e1_duplicate_store_returns_existing_meta(tmp_path: Path) -> None:
    observations = tmp_path / "obs"
    first = store_observation(str(observations), "aaaaaaaa-0000-4000-8000-00000000000a", "t", "x" * 9000)
    again = store_observation(str(observations), "aaaaaaaa-0000-4000-8000-00000000000a", "t", "x" * 9000)
    assert first is not None and again is not None  # idempotent store still yields a pointer
    assert again["sha256"] == first["sha256"]


def test_projection_none_when_short(tmp_path: Path) -> None:
    session = _session(tmp_path)
    _record_turn(session, 1, "only one", "done")
    assert build_projection(session.load_events(), None) is None


def test_recovery_projection_covers_short_history(tmp_path: Path) -> None:
    """Chaos finding: after a crash even a two-turn conversation must
    survive into the fresh process — no fold threshold on recovery."""
    session = _session(tmp_path)
    _record_turn(session, 1, "create a", "done")
    _record_turn(session, 2, "create b", "done")
    projection = build_projection(session.load_events(), None, recovery=True)
    assert projection is not None
    assert "recovery projection" in projection
    assert "create a" in projection and "create b" in projection  # both verbatim


def test_estimate_usage_prefers_real_tokens(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.record("model_response", _model_response_usage(12345), producer="pi")
    assert estimate_usage(session.load_events()) == 12345


def test_estimate_usage_falls_back_to_characters(tmp_path: Path) -> None:
    session = _session(tmp_path)
    _record_turn(session, 1, "prompt text here", "a reply")
    estimate = estimate_usage(session.load_events())
    assert estimate > 0  # no real usage present, character estimate used


def test_should_compact_requires_budget() -> None:
    assert should_compact(50_000, 100_000) is False  # below the 70% threshold
    assert should_compact(70_000, 100_000) is True   # at the threshold
    assert should_compact(90_000, 0) is False        # budget 0 disables compaction


def test_tombstone_survives_missing_file(tmp_path: Path) -> None:
    meta = {
        "call_id": "dddddddd-0000-4000-8000-000000000004",
        "tool": "openpilot_bash",
        "bytes": 9999,
        "path": str(tmp_path / "gone.txt"),
    }
    text = observation_tombstone(meta)
    assert "openpilot_obs(" in text
    assert "no longer readable" in text


def test_s1_repeat_read_intercepted(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("hello\n" * 50, encoding="utf-8")
    bridge = ReadOnlyToolBridge((str(tmp_path),), observations_dir=str(tmp_path / "obs"))
    first = bridge._handle(
        {"toolName": "openpilot_read", "toolCallId": "aaaaaaaa-0000-4000-8000-0000000000b1", "args": {"path": "note.txt"}}
    )
    assert "hello" in first["content"]
    second = bridge._handle(
        {"toolName": "openpilot_read", "toolCallId": "aaaaaaaa-0000-4000-8000-0000000000b2", "args": {"path": "note.txt"}}
    )
    assert "unchanged repeat-read skipped" in second["content"]
    assert "hello" not in second["content"]
    assert "openpilot_obs(" in second["content"]  # the pointer to the earlier call
    target.write_text("changed\nchanged2\nchanged3\n", encoding="utf-8")
    third = bridge._handle(
        {"toolName": "openpilot_read", "toolCallId": "aaaaaaaa-0000-4000-8000-0000000000b3", "args": {"path": "note.txt"}}
    )
    assert "changed2" in third["content"]  # sha differs -> served again
    fourth = bridge._handle(
        {"toolName": "openpilot_read", "toolCallId": "aaaaaaaa-0000-4000-8000-0000000000b4", "args": {"path": "note.txt", "offset": 2}}
    )
    assert "changed2" in fourth["content"]  # a different page is a different request


def test_s2_test_output_compression() -> None:
    output = "\n".join(f"tests/test_a.py::test_k{i} PASSED [ 50%]" for i in range(40))
    output += "\n=============================== 40 passed in 0.31s ==============================="
    compressed = _compress_command_output("python -m pytest -q", output)
    assert compressed.count("PASSED") == 0  # per-test pass lines are noise
    assert "40 passed in 0.31s" in compressed  # the summary survives
    failing = "FAILED tests/test_a.py::test_k1 - assert 1 == 2\n" + output.replace(
        "40 passed in 0.31s", "38 passed, 2 failed in 0.31s"
    )
    compressed = _compress_command_output("python -m pytest -q", failing)
    assert "FAILED tests/test_a.py::test_k1" in compressed  # failures always kept
    assert compressed.count("PASSED") == 0
    assert _compress_command_output("ls -la", output) == output  # not a test command: untouched


def test_s2_git_compression() -> None:
    entries = []
    for i in range(6):
        entries.append(
            f"commit {'0123456789abcdef' * 2}{i:02d}\nAuthor: boss\nDate:   Mon Sep 9 2026\n\n    fix thing {i}\n\n    long body of commit {i} that nobody re-reads\n"
        )
    log = "\n".join(entries)
    compressed = _compress_command_output("git log -6", log)
    assert compressed.count("long body") == 0
    assert compressed.count("commit 0123456789ab") == 6  # one line per commit
    assert "git show" in compressed
    assert _compress_command_output("git diff HEAD", log) == log  # diffs always full
    status = _compress_command_output(
        "git status", "On branch main\nChanges not staged for commit:\n  (use \"git add\" to update)\n        modified: a.py\n"
    )
    assert "(use" not in status and "modified: a.py" in status


def test_s3_projection_one_liners_and_task_header(tmp_path: Path) -> None:
    session = _session(tmp_path / "proj")
    long_prompt = "task 1 " + "constraint " * 100  # ~910 chars
    long_reply = "reply 1 " + "words " * 100
    _record_turn(session, 1, long_prompt, long_reply)
    _record_turn(session, 2, "t2", "r2")
    _record_turn(session, 3, "t3", "r3")
    projection = build_projection(session.load_events(), None)
    assert projection is not None
    assert "Task: task 1 constraint" in projection  # original task kept near-verbatim
    folded = next(ln for ln in projection.splitlines() if ln.startswith("### Turn 1:"))
    assert len(folded) < 420  # one capped line, not a verbatim replay
    assert folded.count("words") < 100  # assistant gist capped, not verbatim
    assert "### Turn 3 (recent, verbatim)" in projection


def test_s3_handoff_artifact(tmp_path: Path) -> None:
    session = _session(tmp_path)
    _record_turn(session, 1, "goal here", "done")
    _record_turn(session, 2, "t2", "r2")
    handoff = build_handoff(session.run_id, session.load_events(), [], status="success", reason="read-only run")
    assert "closure: success" in handoff and "## Goal" in handoff
    assert "goal here" in handoff  # full goal, not truncated
    assert "### Turn 2: user: t2 | assistant: r2" in handoff
    path = write_handoff(tmp_path, session.run_id, session.load_events(), [], status="success", reason="read-only run")
    assert path.read_text(encoding="utf-8") == handoff
    assert len(handoff.splitlines()) <= 200
