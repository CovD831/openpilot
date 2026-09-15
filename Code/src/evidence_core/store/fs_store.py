"""Filesystem-backed evidence store."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evidence_core.export.jsonl import read_jsonl
from evidence_core.records import (
    ArtifactRecord,
    EvidenceLayer,
    EventRecord,
    RunRecord,
    RunSummaryRecord,
    terminal_status_transition_allowed,
)
from evidence_core.replay.summary import build_run_summary
from evidence_core.replay.timeline import build_timeline
from evidence_core.serialization import (
    MAX_ARTIFACT_BYTES,
    json_safe,
    sanitize_payload,
    sanitize_text,
)


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "evidence_core"


class EvidenceStore:
    """Persist runs as append-only per-run trajectory directories."""

    def __init__(self, data_dir: Path | str = DEFAULT_DATA_DIR, *, create: bool = True):
        self.data_dir = Path(data_dir)
        self.trajectory_dir = self.data_dir / "task_trajectory"
        self._run_ids_by_key: dict[str, str] = {}
        self._event_sequences: dict[str, int] = {}
        if create:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.trajectory_dir.mkdir(parents=True, exist_ok=True)
        elif not self.data_dir.is_dir() or not self.trajectory_dir.is_dir():
            raise FileNotFoundError("Evidence store does not exist")

    def start_run(
        self,
        task_id: str,
        *,
        source: str = "",
        raw_input: str = "",
        goal: str = "",
        session_id: str = "",
        route: str = "",
    ) -> RunRecord:
        # A new execution is always a new durable container. Callers that are
        # resuming an existing execution must use attach_existing_run().
        normalized_task_id = str(task_id or "").strip() or "unknown"
        run = RunRecord(
            task_id=normalized_task_id,
            root_task_id=normalized_task_id,
            session_id=str(session_id or ""),
            source=sanitize_text(source),
            raw_input=sanitize_text(raw_input),
            goal=sanitize_text(goal),
            route=sanitize_text(route),
        )
        self.run_dir(run.run_id).mkdir(parents=True, exist_ok=True)
        self._write_json(self.run_file(run.run_id), run.model_dump(mode="python"))
        self._persist_run_aliases(run)
        self._register_run_alias(run.run_id, run.run_id)
        self._register_run_alias(run.run_id, run.task_id)
        if run.session_id:
            self._register_run_alias(run.run_id, run.session_id)
        self._event_sequences.setdefault(run.run_id, 0)
        self._refresh_summary(run.run_id)
        return run

    def ensure_run(
        self,
        task_id: str,
        *,
        source: str = "",
        raw_input: str = "",
        goal: str = "",
        session_id: str = "",
        route: str = "",
    ) -> RunRecord:
        task_id = str(task_id or "").strip() or "unknown"
        existing_run_id = self._resolve_run_id(task_id)
        if existing_run_id is None and session_id:
            existing_run_id = self._resolve_run_id(session_id)
        if existing_run_id:
            run = self.load_run(existing_run_id)
            if run is not None:
                self._register_run_alias(run.run_id, run.run_id)
                self._register_run_alias(run.run_id, run.task_id)
                if run.session_id:
                    self._register_run_alias(run.run_id, run.session_id)
                if task_id:
                    self._register_run_alias(run.run_id, task_id)
                if session_id:
                    self._register_run_alias(run.run_id, str(session_id))
                return self.update_run(
                    run.run_id,
                    source=source or run.source,
                    raw_input=raw_input or run.raw_input,
                    goal=goal or run.goal,
                    session_id=session_id or run.session_id,
                    route=route or run.route,
                )
            self._run_ids_by_key.pop(task_id, None)
            if session_id:
                self._run_ids_by_key.pop(str(session_id), None)

        run = RunRecord(
            task_id=task_id,
            root_task_id=task_id,
            session_id=str(session_id or ""),
            source=sanitize_text(source),
            raw_input=sanitize_text(raw_input),
            goal=sanitize_text(goal),
            route=sanitize_text(route),
        )
        self.run_dir(run.run_id).mkdir(parents=True, exist_ok=True)
        self._write_json(self.run_file(run.run_id), run.model_dump(mode="python"))
        self._persist_run_aliases(run)
        self._register_run_alias(run.run_id, run.run_id)
        self._register_run_alias(run.run_id, task_id)
        if session_id:
            self._register_run_alias(run.run_id, str(session_id))
        self._event_sequences.setdefault(run.run_id, 0)
        self._refresh_summary(run.run_id)
        return run

    def update_run(self, run_key: str, **fields: Any) -> RunRecord:
        run_id = self._resolve_run_id(run_key)
        if run_id is None:
            run = self.ensure_run(str(run_key))
            run_id = run.run_id
        run = self.load_run(run_id) or RunRecord(run_id=run_id, task_id=str(run_key))
        data = run.model_dump(mode="python")
        requested_status = fields.get("final_status")
        if requested_status not in (None, "") and not terminal_status_transition_allowed(
            run.final_status,
            requested_status,
        ):
            raise ValueError(
                f"invalid terminal status transition: {run.final_status.value} -> {requested_status}"
            )
        for key, value in fields.items():
            if value in (None, ""):
                continue
            data[key] = (
                sanitize_text(str(value))
                if key in {"source", "raw_input", "goal", "route", "completion_reason"}
                else value
            )
        updated = RunRecord.model_validate(data)
        self._write_json(self.run_file(run_id), updated.model_dump(mode="python"))
        self._persist_run_aliases(updated)
        self._register_run_alias(run_id, updated.run_id)
        self._register_run_alias(run_id, updated.task_id)
        if updated.session_id:
            self._register_run_alias(run_id, updated.session_id)
        self._sync_summary_from_run(updated)
        return updated

    def attach_existing_run(
        self,
        run_id: str,
        *,
        expected_task_id: str = "",
        expected_session_id: str = "",
        resume_attempt_id: str = "",
    ) -> RunRecord:
        run = self.load_run(run_id)
        if run is None or run.run_id != str(run_id):
            raise ValueError(f"existing run not found: {run_id}")
        if expected_task_id and run.task_id != str(expected_task_id):
            raise ValueError("existing run task identity does not match")
        if expected_session_id and run.session_id != str(expected_session_id):
            raise ValueError("existing run session identity does not match")
        if resume_attempt_id:
            run = self.update_run(run.run_id, resume_attempt_id=str(resume_attempt_id))
        self._register_run_alias(run.run_id, run.run_id)
        self._register_run_alias(run.run_id, run.task_id)
        if run.session_id:
            self._register_run_alias(run.run_id, run.session_id)
        return run

    def load_run(self, run_key: str) -> RunRecord | None:
        run_id = self._resolve_run_id(run_key) or str(run_key)
        path = self.run_file(run_id)
        if not path.exists():
            return None
        try:
            run = RunRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, ValueError):
            return None
        self._register_run_alias(run.run_id, run.run_id)
        self._register_run_alias(run.run_id, run.task_id)
        if run.session_id:
            self._register_run_alias(run.run_id, run.session_id)
        return run

    def append_event(
        self,
        run_key: str,
        *,
        event_type: str,
        payload: Any = None,
        payload_kind: str = "",
        source: str = "",
        raw_input: str = "",
        goal: str = "",
        route: str = "",
        task_id: str = "",
        session_id: str = "",
        phase: str = "",
        summary: str = "",
        idempotency_key: str = "",
        layer: str = "raw",
        authority: str = "observed",
        source_observation_id: str = "",
        parent_event_id: str = "",
        mapper_version: str = "",
        producer: str = "",
        call_id: str = "",
    ) -> EventRecord:
        run = self.load_run(run_key)
        if run is None:
            run = self.ensure_run(
                task_id or str(run_key),
                source=source,
                raw_input=raw_input,
                goal=goal,
                session_id=session_id,
                route=route,
            )
        else:
            updates = {
                key: value
                for key, value, current in (
                    ("source", source, run.source),
                    ("raw_input", raw_input, run.raw_input),
                    ("goal", goal, run.goal),
                    ("session_id", session_id, run.session_id),
                    ("route", route, run.route),
                )
                if value not in (None, "") and value != current
            }
            if updates:
                run = self.update_run(run.run_id, **updates)
            if task_id:
                self._register_run_alias(run.run_id, task_id)
            if session_id:
                self._register_run_alias(run.run_id, session_id)

        normalized_payload = sanitize_payload(payload if payload is not None else {})
        if not isinstance(normalized_payload, dict):
            normalized_payload = {"value": normalized_payload}
        normalized_kind = self._normalize_payload_kind(payload_kind, payload, normalized_payload)

        with self._event_write_lock(run.run_id):
            state = self._load_event_state(run.run_id)
            event = self._find_idempotent_event_in_state(state, event_type, idempotency_key)
            if event is None:
                sequence = int(state.get("last_sequence") or 0) + 1
                event = EventRecord(
                    run_id=run.run_id,
                    sequence=sequence,
                    event_type=event_type,
                    idempotency_key=idempotency_key,
                    task_id=task_id or run.task_id,
                    session_id=session_id or run.session_id,
                    phase=phase or str(normalized_payload.get("phase") or ""),
                    summary=summary or event_type,
                    payload_kind=normalized_kind,
                    payload=normalized_payload,
                    layer=layer,
                    authority=authority,
                    source_observation_id=source_observation_id,
                    parent_event_id=parent_event_id,
                    mapper_version=mapper_version,
                    producer=producer,
                    call_id=call_id,
                )
                self._append_jsonl(self.events_file(run.run_id), event.model_dump(mode="python"))
                state["last_sequence"] = sequence
                state["events_size"] = self.events_file(run.run_id).stat().st_size
                if idempotency_key:
                    idempotency = dict(state.get("idempotency") or {})
                    idempotency[f"{event_type}:{idempotency_key}"] = event.model_dump(mode="python")
                    state["idempotency"] = idempotency
                self._write_json(self.event_state_file(run.run_id), state)
                self._apply_event_to_summary(run.run_id, event)
        return event

    def record_event(self, *args: Any, **kwargs: Any) -> EventRecord:
        return self.append_event(*args, **kwargs)

    def finish_run(
        self,
        run_key: str,
        *,
        success: bool,
        reason: str = "",
        session_id: str = "",
        phase: str = "",
        payload: dict[str, Any] | None = None,
    ) -> EventRecord:
        event_payload = dict(payload or {})
        event_payload.setdefault("success", success)
        if reason and "completion_reason" not in event_payload:
            event_payload["completion_reason"] = reason
        event_payload.setdefault("final_status", "success" if success else "failed")
        event = self.append_event(
            run_key,
            event_type="task_finished",
            payload=event_payload,
            session_id=session_id,
            phase=phase,
            summary=reason or event_payload.get("completion_reason") or f"success={success}",
        )
        self.update_run(
            event.run_id,
            finished_at=event.created_at,
            success=success,
            final_status="success" if success else "failed",
            completion_reason=str(reason or event_payload.get("completion_reason") or ("task finished" if success else "task failed")),
        )
        return event

    def record_artifact(
        self,
        run_key: str,
        *,
        kind: str,
        content: str | bytes,
        filename: str | None = None,
        content_type: str = "text/plain",
        source_event_id: str = "",
    ) -> ArtifactRecord:
        run = self.load_run(run_key)
        if run is None:
            run = self.ensure_run(str(run_key))
        artifact_name = Path(filename).name if filename else f"{kind}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}"
        artifact_path = self.artifacts_dir(run.run_id) / artifact_name
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            if len(content) > MAX_ARTIFACT_BYTES:
                raise ValueError(f"artifact exceeds {MAX_ARTIFACT_BYTES} bytes")
            persisted_content: str | bytes = content
        else:
            persisted_content = sanitize_text(content, max_bytes=MAX_ARTIFACT_BYTES)
        if isinstance(persisted_content, bytes):
            artifact_path.write_bytes(persisted_content)
            byte_count = len(persisted_content)
        else:
            artifact_path.write_text(persisted_content, encoding="utf-8")
            byte_count = len(persisted_content.encode("utf-8"))
        artifact_path.chmod(0o600)
        artifact = ArtifactRecord(
            run_id=run.run_id,
            kind=kind,
            path=str(artifact_path),
            content_type=content_type,
            bytes=byte_count,
            source_event_id=source_event_id,
        )
        with self._event_write_lock(run.run_id):
            self._append_jsonl(self.artifacts_index_file(run.run_id), artifact.model_dump(mode="python"))
            try:
                summary = RunSummaryRecord.model_validate(
                    json.loads(self.summary_file(run.run_id).read_text(encoding="utf-8"))
                )
            except (json.JSONDecodeError, OSError, ValueError):
                self._refresh_summary(run.run_id)
            else:
                summary.artifact_count += 1
                self._write_json(self.summary_file(run.run_id), summary.model_dump(mode="python"))
        return artifact

    def attach_artifact(self, *args: Any, **kwargs: Any) -> ArtifactRecord:
        return self.record_artifact(*args, **kwargs)

    def load_trajectory_events(self, run_key: str, limit: int = 0) -> list[EventRecord]:
        run_id = self._resolve_run_id(run_key) or str(run_key)
        path = self.events_file(run_id)
        if not path.exists():
            return []
        events: list[EventRecord] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                events.append(EventRecord.model_validate(json.loads(stripped)))
            except (json.JSONDecodeError, ValueError):
                continue
        ordered = build_timeline(events)
        return ordered[-limit:] if limit > 0 else ordered

    def load_run_artifacts(self, run_key: str) -> list[ArtifactRecord]:
        run_id = self._resolve_run_id(run_key) or str(run_key)
        artifacts = [ArtifactRecord.model_validate(row) for row in read_jsonl(self.artifacts_index_file(run_id))]
        return sorted(
            artifacts,
            key=lambda artifact: (
                str(artifact.created_at or ""),
                str(artifact.artifact_id or ""),
            ),
        )

    def load_run_summary(self, run_key: str) -> RunSummaryRecord | None:
        run_id = self._resolve_run_id(run_key) or str(run_key)
        path = self.summary_file(run_id)
        if path.exists():
            try:
                summary = RunSummaryRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
                state = self._load_event_state(run_id)
                if summary.last_sequence == int(state.get("last_sequence") or 0):
                    return summary
            except (json.JSONDecodeError, OSError, ValueError):
                pass
        summary = self._current_summary(run_id)
        if summary is not None:
            self._write_json(path, summary.model_dump(mode="python"))
        return summary

    def list_runs(self) -> list[RunSummaryRecord]:
        summaries: list[RunSummaryRecord] = []
        for run_dir in sorted(self.trajectory_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            summary = self.load_run_summary(run_dir.name)
            if summary is not None:
                summaries.append(summary)
        return sorted(
            summaries,
            key=lambda summary: (
                str(summary.started_at or ""),
                str(summary.run_id or ""),
            ),
            reverse=True,
        )

    def replay_run(self, run_key: str) -> dict[str, Any] | None:
        run = self.load_run(run_key)
        if run is None:
            return None
        events = self.load_trajectory_events(run.run_id)
        artifacts = self.load_run_artifacts(run.run_id)
        summary = self.load_run_summary(run.run_id) or self._current_summary(run.run_id)
        if summary is None:
            return None
        return {
            "run": run,
            "events": events,
            "artifacts": artifacts,
            "summary": summary,
        }

    def run_dir(self, run_id: str) -> Path:
        return self.trajectory_dir / str(run_id)

    def run_file(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "run.json"

    def events_file(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "events.jsonl"

    def artifacts_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "artifacts"

    def artifacts_index_file(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "artifacts.jsonl"

    def summary_file(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "summary.json"

    def event_state_file(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "event_state.json"

    def aliases_file(self) -> Path:
        return self.data_dir / "aliases.json"

    def _current_summary(self, run_id: str) -> RunSummaryRecord | None:
        run = self.load_run(run_id)
        if run is None:
            return None
        events = self.load_trajectory_events(run.run_id)
        artifacts = self.load_run_artifacts(run.run_id)
        return build_run_summary(run, events, artifacts)

    def _refresh_summary(self, run_id: str) -> None:
        summary = self._current_summary(run_id)
        if summary is not None:
            self._write_json(self.summary_file(run_id), summary.model_dump(mode="python"))

    def _sync_summary_from_run(self, run: RunRecord) -> None:
        path = self.summary_file(run.run_id)
        try:
            summary = RunSummaryRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, ValueError):
            self._refresh_summary(run.run_id)
            return
        summary.task_id = run.task_id
        summary.session_id = run.session_id
        summary.source = run.source
        summary.route = run.route
        summary.goal = run.goal
        summary.raw_input_preview = (run.raw_input or "")[:200]
        summary.started_at = run.started_at
        summary.finished_at = run.finished_at
        summary.success = run.success
        summary.final_status = run.final_status
        summary.completion_reason = run.completion_reason
        self._write_json(path, summary.model_dump(mode="python"))

    def _find_idempotent_event(self, run_id: str, event_type: str, idempotency_key: str) -> EventRecord | None:
        if not idempotency_key:
            return None
        with self._event_write_lock(run_id):
            return self._find_idempotent_event_in_state(
                self._load_event_state(run_id), event_type, idempotency_key
            )

    def find_event(self, run_id: str, event_type: str, idempotency_key: str) -> EventRecord | None:
        return self._find_idempotent_event(run_id, event_type, idempotency_key)

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(json_safe(payload), ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _resolve_run_id(self, run_key: str) -> str | None:
        key = str(run_key or "").strip()
        if not key:
            return None
        direct_path = self.run_file(key)
        if direct_path.exists():
            return key
        with self._alias_lock():
            aliases = self._load_alias_index()
        matches = [run_id for run_id in aliases.get(key, []) if self.run_file(run_id).exists()]
        if len(matches) > 1:
            raise ValueError(f"ambiguous run alias: {key} ({len(matches)} runs)")
        if matches:
            return matches[0]
        return None

    def _register_run_alias(self, run_id: str, key: str) -> None:
        key = str(key or "").strip()
        if key:
            self._run_ids_by_key[key] = run_id

    def _persist_run_aliases(self, run: RunRecord) -> None:
        with self._alias_lock():
            aliases = self._load_alias_index()
            for key in (run.run_id, run.task_id, run.session_id):
                normalized = str(key or "").strip()
                if not normalized:
                    continue
                run_ids = list(aliases.get(normalized, []))
                if run.run_id not in run_ids:
                    run_ids.append(run.run_id)
                aliases[normalized] = sorted(run_ids)
            self._write_json(self.aliases_file(), aliases)

    def _load_alias_index(self) -> dict[str, list[str]]:
        path = self.aliases_file()
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    return {
                        str(key): [str(run_id) for run_id in value if str(run_id)]
                        for key, value in payload.items()
                        if isinstance(value, list)
                    }
            except (json.JSONDecodeError, OSError, ValueError):
                pass
        aliases: dict[str, list[str]] = {}
        for candidate in sorted(self.trajectory_dir.iterdir()):
            run_path = candidate / "run.json"
            if not candidate.is_dir() or not run_path.exists():
                continue
            try:
                run = RunRecord.model_validate(json.loads(run_path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError, ValueError):
                continue
            for key in (run.run_id, run.task_id, run.session_id):
                normalized = str(key or "").strip()
                if normalized:
                    aliases.setdefault(normalized, []).append(run.run_id)
        self._write_json(path, {key: sorted(set(value)) for key, value in aliases.items()})
        return aliases

    def _load_event_state(self, run_id: str) -> dict[str, Any]:
        path = self.event_state_file(run_id)
        events_path = self.events_file(run_id)
        current_size = events_path.stat().st_size if events_path.exists() else 0
        try:
            state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (json.JSONDecodeError, OSError, ValueError):
            state = {}
        if int(state.get("events_size") or 0) == current_size:
            state.setdefault("last_sequence", 0)
            state.setdefault("idempotency", {})
            return state
        return self._rebuild_event_state(run_id)

    def _rebuild_event_state(self, run_id: str) -> dict[str, Any]:
        events = self.load_trajectory_events(run_id)
        idempotency: dict[str, Any] = {}
        for event in events:
            if event.idempotency_key:
                idempotency[f"{event.event_type}:{event.idempotency_key}"] = event.model_dump(mode="python")
        events_path = self.events_file(run_id)
        state = {
            "last_sequence": max((int(event.sequence or 0) for event in events), default=0),
            "events_size": events_path.stat().st_size if events_path.exists() else 0,
            "idempotency": idempotency,
        }
        self._write_json(self.event_state_file(run_id), state)
        return state

    @staticmethod
    def _find_idempotent_event_in_state(
        state: dict[str, Any], event_type: str, idempotency_key: str
    ) -> EventRecord | None:
        if not idempotency_key:
            return None
        row = (state.get("idempotency") or {}).get(f"{event_type}:{idempotency_key}")
        try:
            return EventRecord.model_validate(row) if row else None
        except ValueError:
            return None

    def _apply_event_to_summary(self, run_id: str, event: EventRecord) -> None:
        path = self.summary_file(run_id)
        try:
            summary = RunSummaryRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, ValueError):
            summary = self._current_summary(run_id)
            if summary is not None:
                self._write_json(path, summary.model_dump(mode="python"))
            return
        if summary.last_sequence != int(event.sequence or 0) - 1:
            summary = self._current_summary(run_id)
            if summary is not None:
                self._write_json(path, summary.model_dump(mode="python"))
            return
        if summary is None:
            return
        if summary.projection_layer is EvidenceLayer.RAW and event.layer is EvidenceLayer.SEMANTIC:
            summary = self._current_summary(run_id)
            if summary is not None:
                self._write_json(path, summary.model_dump(mode="python"))
            return
        if summary.projection_layer is EvidenceLayer.SEMANTIC and event.layer is EvidenceLayer.RAW:
            summary.last_sequence = int(event.sequence or 0)
            self._write_json(path, summary.model_dump(mode="python"))
            return
        summary.event_count += 1
        summary.last_sequence = int(event.sequence or 0)
        counters = {"tool_called": "tool_called_count", "tool_succeeded": "tool_succeeded_count", "tool_failed": "tool_failed_count", "verification_state_changed": "verification_state_changes", "runtime_phase_changed": "phase_changes"}
        field = counters.get(event.event_type)
        if field:
            setattr(summary, field, getattr(summary, field) + 1)
        payload = event.payload or {}
        summary.last_phase = str(event.phase or payload.get("phase") or summary.last_phase)
        if payload.get("verification_status") not in (None, "", [], {}):
            summary.verification_status = str(payload["verification_status"])
        self._write_json(self.summary_file(run_id), summary.model_dump(mode="python"))

    @contextmanager
    def _event_write_lock(self, run_id: str):
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        with (run_dir / ".events.lock").open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _alias_lock(self):
        with (self.data_dir / ".aliases.lock").open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(json_safe(payload), ensure_ascii=False, sort_keys=True, indent=2)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _normalize_payload_kind(self, requested_kind: str, payload: Any, normalized_payload: dict[str, Any]) -> str:
        kind = str(requested_kind or "").strip()
        if kind:
            return kind
        embedded = normalized_payload.get("kind")
        if embedded not in (None, ""):
            return str(embedded)
        return "none" if payload is None else type(payload).__name__
