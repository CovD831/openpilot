from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
import pytest

from evidence_core import (
    ArtifactRecord,
    EventRecord,
    EvidenceStore,
    EvidenceReader,
    RunRecord,
    RunSummaryRecord,
    build_run_summary,
    build_timeline,
    copy_run_bundle,
    dump_json,
    json_safe,
    read_jsonl,
    write_jsonl,
    validate_trajectory_conformance,
)


def _append_events_in_process(data_dir: str, run_id: str, worker: int, count: int) -> None:
    store = EvidenceStore(data_dir)
    for index in range(count):
        store.record_event(
            run_id,
            event_type="model_response",
            payload={"worker": worker, "index": index},
            idempotency_key=f"worker:{worker}:{index}",
        )


def test_record_contracts_and_json_safety() -> None:
    def helper() -> None:
        return None

    payload = {"path": Path("foo/bar"), "callable": helper, "items": {3, 1}}
    payload["self"] = payload

    run = RunRecord(task_id="task-1", session_id="session-1", source="manual", raw_input="hello", goal="goal", route="route")
    event = EventRecord(run_id=run.run_id, sequence=1, event_type="task_received", payload={"value": 1})
    artifact = ArtifactRecord(run_id=run.run_id, kind="stdout", path="/tmp/stdout.txt", bytes=12)
    summary = RunSummaryRecord(run_id=run.run_id)

    safe = json_safe(payload)

    assert run.run_id
    assert run.schema_version == "v1"
    assert run.started_at
    assert event.event_id
    assert event.schema_version == "v1"
    assert artifact.artifact_id
    assert artifact.schema_version == "v1"
    assert summary.final_status == "running"
    assert summary.schema_version == "v1"
    assert safe["path"] == "foo/bar"
    assert safe["callable"] == "<callable:helper>"
    assert safe["items"] == [1, 3]
    assert safe["self"] == "<recursive:dict>"
    assert json.loads(dump_json({"b": 2, "a": 1})) == {"a": 1, "b": 2}


def test_build_timeline_orders_by_sequence_created_at_and_event_id() -> None:
    events = [
        {"run_id": "run-1", "sequence": 2, "event_type": "late", "event_id": "c", "created_at": "2024-01-01T00:00:03+00:00"},
        EventRecord(run_id="run-1", sequence=1, event_type="first", event_id="b", created_at="2024-01-01T00:00:02+00:00"),
        {"run_id": "run-1", "sequence": 1, "event_type": "tie", "event_id": "a", "created_at": "2024-01-01T00:00:02+00:00"},
    ]

    timeline = build_timeline(events)

    assert [item.event_id for item in timeline] == ["a", "b", "c"]
    assert [item.event_type for item in timeline] == ["tie", "first", "late"]


def test_build_run_summary_projects_counts_and_latest_state() -> None:
    run = RunRecord(
        run_id="run-1",
        task_id="task-1",
        session_id="session-1",
        source="manual",
        raw_input="x" * 250,
        goal="goal",
        route="route-a",
        started_at="2024-01-01T00:00:00+00:00",
        finished_at="2024-01-01T00:00:10+00:00",
        final_status="success",
        completion_reason="done",
        success=True,
    )
    events = [
        {"run_id": "run-1", "sequence": 1, "event_type": "tool_called", "event_id": "e1", "phase": "execute", "created_at": "2024-01-01T00:00:01+00:00", "payload": {}},
        {"run_id": "run-1", "sequence": 2, "event_type": "tool_succeeded", "event_id": "e2", "phase": "execute", "created_at": "2024-01-01T00:00:02+00:00", "payload": {}},
        {"run_id": "run-1", "sequence": 3, "event_type": "tool_failed", "event_id": "e3", "phase": "execute", "created_at": "2024-01-01T00:00:03+00:00", "payload": {}},
        {"run_id": "run-1", "sequence": 4, "event_type": "verification_state_changed", "event_id": "e4", "phase": "verify", "created_at": "2024-01-01T00:00:04+00:00", "payload": {}},
        {
            "run_id": "run-1",
            "sequence": 5,
            "event_type": "runtime_phase_changed",
            "event_id": "e5",
            "phase": "review",
            "created_at": "2024-01-01T00:00:05+00:00",
            "payload": {"phase": "review", "verification_status": "passed"},
        },
    ]
    artifacts = [ArtifactRecord(run_id="run-1", kind="stdout", path="/tmp/stdout.txt", bytes=12)]

    summary = build_run_summary(run, events, artifacts)

    assert summary.run_id == "run-1"
    assert summary.event_count == 5
    assert summary.tool_called_count == 1
    assert summary.tool_succeeded_count == 1
    assert summary.tool_failed_count == 1
    assert summary.verification_state_changes == 1
    assert summary.phase_changes == 1
    assert summary.artifact_count == 1
    assert summary.last_phase == "review"
    assert summary.verification_status == "passed"
    assert summary.raw_input_preview == "x" * 200


def test_jsonl_helpers_round_trip_and_skip_invalid_lines(tmp_path) -> None:
    path = tmp_path / "events.jsonl"

    write_jsonl(path, [{"b": 2, "a": 1}, RunRecord(task_id="task-1").model_dump(mode="python")])
    path.write_text(path.read_text(encoding="utf-8") + "not-json\n\n", encoding="utf-8")

    rows = read_jsonl(path)

    assert rows[0] == {"a": 1, "b": 2}
    assert rows[1]["task_id"] == "task-1"


def test_evidence_store_persists_replays_and_survives_restart(tmp_path) -> None:
    data_dir = tmp_path / "evidence"
    store = EvidenceStore(data_dir)

    run = store.start_run("task-1", source="manual", raw_input="inspect", goal="goal", session_id="session-1", route="route-a")
    received = store.record_event(
        "task-1",
        event_type="task_received",
        payload={
            "task_id": "task-1",
            "session_id": "session-1",
            "input_summary": {"source": "manual", "raw_input": "inspect"},
            "goal": "goal",
        },
        payload_kind="log_event",
    )
    route = store.record_event(
        "session-1",
        event_type="route_selected",
        payload={"task_id": "task-1", "session_id": "session-1", "route": "route-a"},
        idempotency_key="route:1",
    )
    duplicate = store.record_event(
        "session-1",
        event_type="route_selected",
        payload={"task_id": "task-1", "session_id": "session-1", "route": "route-a"},
        idempotency_key="route:1",
    )
    artifact = store.record_artifact(
        "task-1",
        kind="stdout",
        content="hello world",
        filename="stdout.txt",
        source_event_id=route.event_id,
    )
    finished = store.finish_run(
        "task-1",
        success=True,
        reason="done",
        session_id="session-1",
        phase="review",
    )

    reloaded = EvidenceStore(data_dir)
    attached = reloaded.attach_existing_run(run.run_id, expected_task_id="task-1", expected_session_id="session-1")
    verification = reloaded.record_event(
        "session-1",
        event_type="verification_state_changed",
        payload={"task_id": "task-1", "session_id": "session-1", "verification_status": "passed"},
        phase="review",
    )

    loaded_run = reloaded.load_run("session-1")
    events = reloaded.load_trajectory_events("session-1")
    summary = reloaded.load_run_summary(run.run_id)
    replay = reloaded.replay_run("task-1")

    assert attached.run_id == run.run_id
    assert received.payload_kind == "log_event"
    assert route.sequence == 2
    assert duplicate.event_id == route.event_id
    assert duplicate.sequence == route.sequence
    assert finished.sequence == 3
    assert verification.sequence == 4
    assert artifact.bytes == len("hello world".encode("utf-8"))
    assert loaded_run is not None
    assert loaded_run.run_id == run.run_id
    assert loaded_run.route == "route-a"
    assert loaded_run.final_status == "success"
    assert [item.sequence for item in events] == [1, 2, 3, 4]
    assert summary is not None
    assert summary.event_count == 4
    assert summary.artifact_count == 1
    assert summary.final_status == "success"
    assert replay is not None
    assert replay["run"].run_id == run.run_id
    assert replay["events"][-1].event_type == "verification_state_changed"


def test_start_run_never_reuses_task_or_session_alias(tmp_path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    first = store.start_run("same-task", session_id="same-session")
    second = store.start_run("same-task", session_id="same-session")

    assert first.run_id != second.run_id
    with pytest.raises(ValueError, match="ambiguous run alias"):
        store.load_run("same-task")
    assert store.load_run(first.run_id).run_id == first.run_id
    assert store.load_run(second.run_id).run_id == second.run_id


def test_alias_lookup_uses_persisted_index_without_run_directory_scan(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "evidence"
    run = EvidenceStore(data_dir).start_run("indexed-alias", session_id="indexed-session")
    restarted = EvidenceStore(data_dir)
    original_iterdir = Path.iterdir

    def reject_trajectory_scan(path: Path):
        if path == restarted.trajectory_dir:
            raise AssertionError("trajectory scan is not allowed on indexed lookup")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", reject_trajectory_scan)

    assert restarted.load_run("indexed-alias").run_id == run.run_id


def test_attach_existing_run_records_explicit_resume_attempt(tmp_path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    run = store.start_run("resume-task")
    resumed = EvidenceStore(tmp_path / "evidence").attach_existing_run(run.run_id, resume_attempt_id="resume-1")

    assert resumed.run_id == run.run_id
    assert resumed.resume_attempt_id == "resume-1"


def test_terminal_state_machine_rejects_reopening_successful_run(tmp_path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    run = store.start_run("terminal-state")
    store.update_run(run.run_id, final_status="success", success=True)

    with pytest.raises(ValueError, match="invalid terminal status transition"):
        store.update_run(run.run_id, final_status="running")


def test_event_payload_is_redacted_and_bounded_before_persistence(tmp_path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    run = store.start_run("safe-task")
    event = store.record_event(
        run.run_id,
        event_type="model_response",
        payload={"authorization": "Bearer secret", "stdout": "x" * 30_000},
        idempotency_key="response:1",
    )

    persisted = store.events_file(run.run_id).read_text(encoding="utf-8")
    assert "Bearer secret" not in persisted
    assert len(persisted.encode("utf-8")) < 20_000
    assert event.payload["authorization"] == "<redacted>"
    assert event.payload["stdout"].endswith("<truncated>")


def test_run_metadata_and_text_artifacts_are_redacted_and_bounded(tmp_path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    run = store.start_run(
        "safe-run-metadata",
        raw_input="Authorization: Bearer super-secret-token",
        goal="use api_key=super-secret-key safely",
    )
    artifact = store.record_artifact(
        run.run_id,
        kind="stdout",
        content="Bearer artifact-secret\n" + ("x" * 1_100_000),
        filename="stdout.txt",
    )

    persisted_run = store.run_file(run.run_id).read_text(encoding="utf-8")
    persisted_artifact = Path(artifact.path).read_text(encoding="utf-8")

    assert "super-secret-token" not in persisted_run
    assert "super-secret-key" not in persisted_run
    assert "artifact-secret" not in persisted_artifact
    assert artifact.bytes <= 1_048_576
    assert persisted_artifact.endswith("<truncated>")


def test_oversized_binary_artifact_is_rejected_before_persistence(tmp_path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    run = store.start_run("bounded-binary-artifact")

    with pytest.raises(ValueError, match="artifact exceeds"):
        store.record_artifact(
            run.run_id,
            kind="binary",
            content=b"x" * 1_048_577,
            filename="large.bin",
            content_type="application/octet-stream",
        )

    assert not store.artifacts_index_file(run.run_id).exists()


def test_semantic_event_must_reference_persisted_raw_observation() -> None:
    raw = EventRecord(run_id="run-1", sequence=1, event_type="tool_result", payload={})
    semantic = EventRecord(
        run_id="run-1", sequence=2, event_type="task_finished", layer="semantic",
        authority="verified", source_observation_id="missing", payload={},
    )
    result = validate_trajectory_conformance([raw, semantic])

    assert result.valid is False
    assert result.checks["semantic_sources_resolve"] is False


def test_semantic_conformance_rejects_parent_cycle_and_unverified_success() -> None:
    raw_one = EventRecord(run_id="run-1", sequence=1, event_type="completion_observed")
    raw_two = EventRecord(run_id="run-1", sequence=2, event_type="task_received")
    task_received = EventRecord(
        event_id="semantic-received",
        run_id="run-1",
        sequence=3,
        event_type="task_received",
        layer="semantic",
        authority="derived",
        source_observation_id=raw_two.event_id,
        parent_event_id="semantic-finished",
        mapper_version="semantic-mapper-v1",
    )
    task_finished = EventRecord(
        event_id="semantic-finished",
        run_id="run-1",
        sequence=4,
        event_type="task_finished",
        layer="semantic",
        authority="derived",
        source_observation_id=raw_one.event_id,
        parent_event_id="semantic-received",
        mapper_version="semantic-mapper-v1",
        payload={"success": True},
    )

    result = validate_trajectory_conformance(
        [raw_one, raw_two, task_received, task_finished]
    )

    assert result.valid is False
    assert result.checks["parent_graph_valid"] is False
    assert result.checks["authority_valid"] is False


def test_semantic_conformance_rejects_duplicate_sequence_and_unknown_mapper() -> None:
    raw = EventRecord(run_id="run-1", sequence=1, event_type="task_received")
    semantic = EventRecord(
        run_id="run-1",
        sequence=1,
        event_type="task_received",
        layer="semantic",
        source_observation_id=raw.event_id,
        mapper_version="unknown-mapper",
    )

    result = validate_trajectory_conformance([raw, semantic], require_terminal=False)

    assert result.checks["event_identity_unique"] is False
    assert result.checks["semantic_sources_resolve"] is False


def test_idempotency_index_and_sequence_survive_restart(tmp_path) -> None:
    data_dir = tmp_path / "evidence"
    run = EvidenceStore(data_dir).start_run("indexed-task")
    first = EvidenceStore(data_dir).record_event(run.run_id, event_type="tool_called", payload={}, idempotency_key="call:1")
    second_store = EvidenceStore(data_dir)
    duplicate = second_store.record_event(run.run_id, event_type="tool_called", payload={"changed": True}, idempotency_key="call:1")
    next_event = second_store.record_event(run.run_id, event_type="tool_result", payload={})

    assert duplicate.event_id == first.event_id
    assert next_event.sequence == first.sequence + 1


def test_event_state_rebuilds_after_append_before_checkpoint(tmp_path) -> None:
    data_dir = tmp_path / "evidence"
    store = EvidenceStore(data_dir)
    run = store.start_run("crash-window-task")
    first = store.record_event(run.run_id, event_type="task_received", payload={})
    interrupted = EventRecord(
        run_id=run.run_id,
        sequence=first.sequence + 1,
        event_type="tool_called",
        idempotency_key="call:interrupted",
        payload={},
    )
    with store.events_file(run.run_id).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(interrupted.model_dump(mode="json"), sort_keys=True) + "\n")

    restarted = EvidenceStore(data_dir)
    duplicate = restarted.record_event(
        run.run_id,
        event_type="tool_called",
        idempotency_key="call:interrupted",
        payload={"duplicate": True},
    )
    next_event = restarted.record_event(run.run_id, event_type="tool_succeeded", payload={})
    summary = restarted.load_run_summary(run.run_id)

    assert duplicate.event_id == interrupted.event_id
    assert next_event.sequence == interrupted.sequence + 1
    assert summary is not None
    assert summary.event_count == 3
    assert summary.last_sequence == next_event.sequence


def test_steady_state_append_does_not_rescan_the_event_stream(tmp_path, monkeypatch) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    run = store.start_run("linear-append")

    def reject_scan(*_args, **_kwargs):
        raise AssertionError("steady-state append must not scan the trajectory")

    monkeypatch.setattr(store, "load_trajectory_events", reject_scan)
    for index in range(100):
        store.record_event(
            run.run_id,
            event_type="model_response",
            payload={"index": index},
            idempotency_key=f"event:{index}",
        )

    assert json.loads(store.event_state_file(run.run_id).read_text(encoding="utf-8"))["last_sequence"] == 100


def test_multiprocess_append_assigns_unique_contiguous_sequences(tmp_path) -> None:
    data_dir = tmp_path / "evidence"
    run = EvidenceStore(data_dir).start_run("multiprocess-append")
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(
            target=_append_events_in_process,
            args=(str(data_dir), run.run_id, worker, 20),
        )
        for worker in range(4)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    events = EvidenceStore(data_dir).load_trajectory_events(run.run_id)
    assert [event.sequence for event in events] == list(range(1, 81))
    assert len({event.idempotency_key for event in events}) == 80


def test_evidence_reader_discovers_and_replays_mixed_new_and_legacy_runs(tmp_path) -> None:
    data_dir = tmp_path / "evidence"
    store = EvidenceStore(data_dir)
    current = store.start_run("current-task")
    store.record_event(current.run_id, event_type="task_received", payload={})
    legacy_rows = [
        {
            "run_id": "legacy-run",
            "task_id": "legacy-task",
            "session_id": "legacy-session",
            "sequence": 1,
            "event_id": "legacy-event-1",
            "event": "task_received",
            "payload": {"raw_input": "legacy input"},
        },
        {
            "run_id": "legacy-run",
            "task_id": "legacy-task",
            "session_id": "legacy-session",
            "sequence": 2,
            "event_id": "legacy-event-2",
            "event": "task_finished",
            "payload": {"success": True},
        },
    ]
    (data_dir / "runs.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in legacy_rows),
        encoding="utf-8",
    )

    reader = EvidenceReader(store)
    replay = reader.replay("legacy-run")

    assert {summary.run_id for summary in reader.list_runs()} == {
        current.run_id,
        "legacy-run",
    }
    assert replay is not None
    assert replay["run"].task_id == "legacy-task"
    assert [event.event_type for event in replay["events"]] == [
        "task_received",
        "task_finished",
    ]


def test_incremental_summary_projects_only_semantic_events_after_layer_switch(tmp_path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    run = store.start_run("layered-summary")
    raw_call = store.record_event(
        run.run_id,
        event_type="tool_called",
        layer="raw",
        payload={},
    )
    store.record_event(
        run.run_id,
        event_type="tool_called",
        layer="semantic",
        authority="derived",
        source_observation_id=raw_call.event_id,
        mapper_version="semantic-mapper-v1",
        payload={},
    )
    store.record_event(
        run.run_id,
        event_type="model_response",
        layer="raw",
        payload={},
    )
    raw_result = store.record_event(
        run.run_id,
        event_type="tool_succeeded",
        layer="raw",
        payload={},
    )
    store.record_event(
        run.run_id,
        event_type="tool_succeeded",
        layer="semantic",
        authority="derived",
        source_observation_id=raw_result.event_id,
        mapper_version="semantic-mapper-v1",
        payload={},
    )

    summary = store.load_run_summary(run.run_id)

    assert summary is not None
    assert summary.projection_layer.value == "semantic"
    assert summary.event_count == 2
    assert summary.tool_called_count == 1
    assert summary.tool_succeeded_count == 1
    assert summary.last_sequence == 5


def test_corrupt_summary_is_rebuilt_with_artifact_and_event_counts(tmp_path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    run = store.start_run("corrupt-summary")
    store.record_event(run.run_id, event_type="task_received", payload={})
    store.record_artifact(run.run_id, kind="stdout", content="hello", filename="stdout.txt")
    store.summary_file(run.run_id).write_text("not-json", encoding="utf-8")

    summary = store.load_run_summary(run.run_id)

    assert summary is not None
    assert summary.event_count == 1
    assert summary.artifact_count == 1
    assert json.loads(store.summary_file(run.run_id).read_text(encoding="utf-8"))["run_id"] == run.run_id


def test_copy_run_bundle_copies_files_and_artifacts(tmp_path) -> None:
    source = tmp_path / "run-123"
    source.mkdir()
    (source / "run.json").write_text('{"run_id":"run-123"}', encoding="utf-8")
    (source / "events.jsonl").write_text('{"sequence":1}\n', encoding="utf-8")
    (source / "summary.json").write_text('{"run_id":"run-123"}', encoding="utf-8")
    (source / "artifacts.jsonl").write_text('{"artifact_id":"a1"}\n', encoding="utf-8")
    artifacts_dir = source / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "stdout.txt").write_text("hello", encoding="utf-8")

    bundle = copy_run_bundle(source, tmp_path / "bundle")

    assert bundle == tmp_path / "bundle" / "run-123"
    assert (bundle / "run.json").read_text(encoding="utf-8") == '{"run_id":"run-123"}'
    assert (bundle / "events.jsonl").read_text(encoding="utf-8") == '{"sequence":1}\n'
    assert (bundle / "summary.json").read_text(encoding="utf-8") == '{"run_id":"run-123"}'
    assert (bundle / "artifacts.jsonl").read_text(encoding="utf-8") == '{"artifact_id":"a1"}\n'
    assert (bundle / "artifacts" / "stdout.txt").read_text(encoding="utf-8") == "hello"


def test_common_trajectory_conformance_accepts_runtime_style_events() -> None:
    events = [
        {"run_id": "run-1", "sequence": 1, "event_type": "task_received", "payload": {}},
        {"run_id": "run-1", "sequence": 2, "event_type": "tool_called", "payload": {}},
        {"run_id": "run-1", "sequence": 3, "event_type": "tool_succeeded", "payload": {}},
        {"run_id": "run-1", "sequence": 4, "event_type": "verification_state_changed", "payload": {}},
        {"run_id": "run-1", "sequence": 5, "event_type": "task_finished", "payload": {}},
    ]

    result = validate_trajectory_conformance(events)

    assert result.valid is True
    assert result.violations == []


def test_common_conformance_accepts_read_only_terminal_without_verification_event() -> None:
    events = [
        {"run_id": "run-1", "sequence": 1, "event_type": "task_received", "payload": {}},
        {"run_id": "run-1", "sequence": 2, "event_type": "tool_called", "payload": {}},
        {"run_id": "run-1", "sequence": 3, "event_type": "tool_succeeded", "payload": {}},
        {"run_id": "run-1", "sequence": 4, "event_type": "task_finished", "payload": {"success": True}},
    ]

    result = validate_trajectory_conformance(events)

    assert result.valid is True


def test_mutation_conformance_requires_explicit_receipt_and_validation() -> None:
    events = [
        {"run_id": "run-1", "sequence": 1, "event_type": "task_received", "payload": {}},
        {
            "run_id": "run-1",
            "sequence": 2,
            "event_type": "tool_called",
            "payload": {"action": {"kind": "write"}},
        },
        {"run_id": "run-1", "sequence": 3, "event_type": "tool_succeeded", "payload": {}},
        {"run_id": "run-1", "sequence": 4, "event_type": "verification_state_changed", "payload": {}},
        {"run_id": "run-1", "sequence": 5, "event_type": "task_finished", "payload": {}},
    ]

    result = validate_trajectory_conformance(events, require_mutation_chain=True)

    assert result.valid is False
    assert "mutation is missing mutation_requested evidence" in result.violations
    assert "mutation is missing mutation_receipt evidence" in result.violations
    assert "mutation is missing validation_completed evidence" in result.violations
