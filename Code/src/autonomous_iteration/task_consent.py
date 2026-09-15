"""Action-time consent registry for an admitted mutation Run.

The registry is deliberately narrow: it owns only the live state of an already
run-bound ``TaskConsentReference``.  It never grants a new scope or changes an
admission.  Holding the authorization lease through one tool dispatch makes a
revoke effective before the next side effect while never pretending to cancel
one already handed to the executor.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
from threading import RLock
from typing import Iterator

from metadata import TaskConsentReference


class TaskConsentStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    CLOSED = "closed"


@dataclass(frozen=True)
class TaskConsentState:
    consent: TaskConsentReference
    status: TaskConsentStatus
    revision: int


class TaskConsentRegistry:
    """Thread-safe, fail-closed resolver for one or more active Run consents."""

    def __init__(self, *, state_directory: str | Path | None = None) -> None:
        self._lock = RLock()
        self._states: dict[str, TaskConsentState] = {}
        self._state_directory = (
            Path(state_directory).expanduser().absolute()
            if state_directory is not None
            else None
        )

    def activate(self, consent: TaskConsentReference) -> TaskConsentState:
        """Register exactly one immutable consent; revoked references cannot reactivate."""

        with self._lock:
            existing = self._load_state(consent.consent_id)
            if existing is not None:
                if existing.consent != consent:
                    raise PermissionError("consent id is already bound to different task identity")
                if existing.status is TaskConsentStatus.REVOKED:
                    raise PermissionError("revoked consent cannot be reactivated")
                if existing.status is TaskConsentStatus.CLOSED:
                    raise PermissionError("closed consent cannot be reactivated")
                return existing
            state = TaskConsentState(
                consent=consent,
                status=TaskConsentStatus.ACTIVE,
                revision=1,
            )
            self._states[consent.consent_id] = state
            self._persist_state(state)
            return state

    def revoke(
        self,
        consent_id: str,
        *,
        run_id: str | None = None,
        project_root: str | Path | None = None,
    ) -> TaskConsentState:
        """Permanently revoke one active consent reference."""

        with self._lock:
            normalized_id = _consent_id(consent_id)
            state = self._load_state(normalized_id)
            if state is None:
                raise KeyError("unknown task consent")
            _require_run_identity(state, run_id)
            _require_project_identity(state, project_root)
            if state.status is TaskConsentStatus.REVOKED:
                return state
            revoked = TaskConsentState(
                consent=state.consent,
                status=TaskConsentStatus.REVOKED,
                revision=state.revision + 1,
            )
            self._states[normalized_id] = revoked
            self._persist_state(revoked)
            return revoked

    def close(self, consent_id: str, *, run_id: str | None = None) -> TaskConsentState:
        """Close a completed Run's consent so it cannot be reused or reactivated."""

        with self._lock:
            normalized_id = _consent_id(consent_id)
            state = self._load_state(normalized_id)
            if state is None:
                raise KeyError("unknown task consent")
            _require_run_identity(state, run_id)
            if state.status in {TaskConsentStatus.CLOSED, TaskConsentStatus.REVOKED}:
                return state
            closed = TaskConsentState(
                consent=state.consent,
                status=TaskConsentStatus.CLOSED,
                revision=state.revision + 1,
            )
            self._states[normalized_id] = closed
            self._persist_state(closed)
            return closed

    @contextmanager
    def authorize(
        self,
        consent: TaskConsentReference | None,
        *,
        run_id: str,
    ) -> Iterator[TaskConsentState]:
        """Hold one action-time authorization lease through its tool dispatch."""

        if consent is None:
            raise PermissionError("mutation requires an action-time consent")
        with self._lock:
            state = self._load_state(consent.consent_id)
            if state is None:
                raise PermissionError("mutation consent is not active in the action-time resolver")
            if state.consent != consent or state.consent.run_id != str(run_id).strip():
                raise PermissionError("action-time consent identity does not match this Run")
            if state.status is TaskConsentStatus.REVOKED:
                raise PermissionError("mutation consent has been revoked")
            if state.status is TaskConsentStatus.CLOSED:
                raise PermissionError("mutation consent has been closed")
            yield state

    def _load_state(self, consent_id: str) -> TaskConsentState | None:
        normalized_id = _consent_id(consent_id)
        if self._state_directory is None:
            return self._states.get(normalized_id)
        path = self._state_path(normalized_id)
        try:
            if not path.exists():
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
            consent = TaskConsentReference.model_validate(payload["consent"])
            state = TaskConsentState(
                consent=consent,
                status=TaskConsentStatus(str(payload["status"])),
                revision=int(payload["revision"]),
            )
        except OSError as exc:
            raise PermissionError("task consent state is unavailable") from exc
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PermissionError("task consent state is malformed") from exc
        if state.consent.consent_id != normalized_id or state.revision < 1:
            raise PermissionError("task consent state identity is invalid")
        self._states[normalized_id] = state
        return state

    def _persist_state(self, state: TaskConsentState) -> None:
        if self._state_directory is None:
            return
        directory = self._state_directory
        directory.mkdir(parents=True, exist_ok=True)
        destination = self._state_path(state.consent.consent_id)
        temporary = directory / f".{state.consent.consent_id}.{os.getpid()}.tmp"
        payload = {
            "consent": state.consent.model_dump(mode="json"),
            "status": state.status.value,
            "revision": state.revision,
        }
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _state_path(self, consent_id: str) -> Path:
        return self._state_directory / f"{_consent_id(consent_id)}.json"


def _consent_id(value: str) -> str:
    consent_id = str(value).strip()
    if not consent_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in consent_id):
        raise ValueError("invalid task consent id")
    return consent_id


def _require_run_identity(state: TaskConsentState, run_id: str | None) -> None:
    if run_id is not None and state.consent.run_id != str(run_id).strip():
        raise PermissionError("task consent belongs to another Run")


def _require_project_identity(state: TaskConsentState, project_root: str | Path | None) -> None:
    if project_root is None:
        return
    expected = Path(state.consent.project_root).expanduser().resolve(strict=False)
    supplied = Path(project_root).expanduser().resolve(strict=False)
    if expected != supplied:
        raise PermissionError("task consent belongs to another project")


__all__ = ["TaskConsentRegistry", "TaskConsentState", "TaskConsentStatus"]
