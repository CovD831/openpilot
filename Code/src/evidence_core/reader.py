"""Read-only Evidence Core consumer interface."""

from __future__ import annotations

import json
from typing import Any

from evidence_core.records import ArtifactRecord, EventRecord, RunRecord, RunSummaryRecord
from evidence_core.replay.summary import build_run_summary
from evidence_core.store.fs_store import EvidenceStore


class EvidenceReader:
    """Explicit read-only facade for diagnostics, viewers, and benchmarks."""

    def __init__(self, store: EvidenceStore):
        self._store = store

    def list_runs(self) -> list[RunSummaryRecord]:
        current = self._store.list_runs()
        known = {summary.run_id for summary in current}
        legacy = [
            self._legacy_replay(run_id)["summary"]
            for run_id in self._legacy_run_ids()
            if run_id not in known
        ]
        return sorted(
            [*current, *legacy],
            key=lambda summary: (str(summary.started_at or ""), summary.run_id),
            reverse=True,
        )

    def load_run(self, run_key: str) -> RunRecord | None:
        run = self._store.load_run(run_key)
        if run is not None:
            return run
        replay = self._legacy_replay_for_key(run_key)
        return replay["run"] if replay is not None else None

    def events(self, run_key: str, *, limit: int = 0) -> list[EventRecord]:
        run = self._store.load_run(run_key)
        if run is not None:
            return self._store.load_trajectory_events(run.run_id, limit=limit)
        replay = self._legacy_replay_for_key(run_key)
        events = replay["events"] if replay is not None else []
        return events[-limit:] if limit > 0 else events

    def artifacts(self, run_key: str) -> list[ArtifactRecord]:
        return (
            self._store.load_run_artifacts(run_key)
            if self._store.load_run(run_key) is not None
            else []
        )

    def replay(self, run_key: str) -> dict[str, Any] | None:
        replay = self._store.replay_run(run_key)
        return replay if replay is not None else self._legacy_replay_for_key(run_key)

    @property
    def _legacy_file(self):
        return self._store.data_dir / "runs.jsonl"

    def _legacy_rows(self) -> list[dict[str, Any]]:
        if not self._legacy_file.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self._legacy_file.read_text(encoding="utf-8").splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def _legacy_run_ids(self) -> list[str]:
        return sorted(
            {
                str(row.get("run_id") or row.get("task_id") or row.get("session_id") or "")
                for row in self._legacy_rows()
                if row.get("run_id") or row.get("task_id") or row.get("session_id")
            }
        )

    def _legacy_replay_for_key(self, run_key: str) -> dict[str, Any] | None:
        key = str(run_key or "")
        matches = {
            str(row.get("run_id") or row.get("task_id") or row.get("session_id") or "")
            for row in self._legacy_rows()
            if key
            in {
                str(row.get("run_id") or ""),
                str(row.get("task_id") or ""),
                str(row.get("session_id") or ""),
            }
        }
        matches.discard("")
        if len(matches) > 1:
            raise ValueError(f"ambiguous legacy run alias {key!r}: {sorted(matches)}")
        return self._legacy_replay(next(iter(matches))) if matches else None

    def _legacy_replay(self, run_id: str) -> dict[str, Any]:
        rows = [
            row
            for row in self._legacy_rows()
            if str(row.get("run_id") or row.get("task_id") or row.get("session_id") or "")
            == run_id
        ]
        first = rows[0]
        events = [
            EventRecord(
                event_id=str(row.get("event_id") or f"legacy:{run_id}:{index}"),
                run_id=run_id,
                sequence=int(row.get("sequence") or index),
                event_type=str(row.get("event") or row.get("event_type") or "legacy_event"),
                task_id=str(row.get("task_id") or first.get("task_id") or run_id),
                session_id=str(row.get("session_id") or first.get("session_id") or ""),
                phase=str(row.get("phase") or ""),
                created_at=str(row.get("created_at") or "1970-01-01T00:00:00+00:00"),
                payload_kind=str(row.get("payload_kind") or "legacy"),
                payload=row.get("payload") if isinstance(row.get("payload"), dict) else {},
                producer="legacy_runs_jsonl",
            )
            for index, row in enumerate(rows, start=1)
        ]
        terminal = next(
            (event for event in reversed(events) if event.event_type == "task_finished"),
            None,
        )
        success = bool((terminal.payload or {}).get("success")) if terminal else None
        run = RunRecord(
            run_id=run_id,
            task_id=str(first.get("task_id") or run_id),
            root_task_id=str(first.get("task_id") or run_id),
            session_id=str(first.get("session_id") or ""),
            source=str(first.get("source") or "legacy"),
            raw_input=str(first.get("raw_input") or ""),
            goal=str(first.get("goal") or ""),
            route=str(first.get("route") or "legacy"),
            started_at=str(first.get("created_at") or "1970-01-01T00:00:00+00:00"),
            finished_at=terminal.created_at if terminal else None,
            final_status=("success" if success else "failed") if terminal else "running",
            success=success,
        )
        return {
            "run": run,
            "events": events,
            "artifacts": [],
            "summary": build_run_summary(run, events, []),
        }
