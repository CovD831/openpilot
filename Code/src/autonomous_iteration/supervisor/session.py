from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import uuid

from autonomous_iteration.checkpoint_store import RuntimeCheckpointStore
from autonomous_iteration.run_coordinator import RunHandle

_NOOP_LEASE = object()


@dataclass
class RuntimeSupervisor:
    """Own all checkpoint, recovery-artifact, lease, and resume identity I/O."""

    store: RuntimeCheckpointStore | Any

    def new_resume_attempt_id(self) -> str:
        return uuid.uuid4().hex

    def try_acquire_run_lease(self, run_id: str) -> Any | None:
        acquire = getattr(self.store, "try_acquire_run_lease", None)
        return acquire(run_id) if callable(acquire) else _NOOP_LEASE

    def release_run_lease(self, handle: Any | None) -> None:
        if handle is _NOOP_LEASE:
            return
        release = getattr(self.store, "release_run_lease", None)
        if callable(release):
            release(handle)

    def save(self, checkpoint: Any, *, expected_generation: int | None = None) -> Any:
        return self.store.save(checkpoint, expected_generation=expected_generation)

    def load(self, run_id: str, checkpoint_id: str) -> Any | None:
        return self.store.load(run_id, checkpoint_id)

    def load_latest(self, run_id: str) -> Any | None:
        return self.store.load_latest(run_id)

    def checkpoint_exists(self, run_id: str, checkpoint_id: str) -> bool:
        return bool(self.store.checkpoint_exists(run_id, checkpoint_id))

    def save_recovery_artifact(
        self,
        run_id: str,
        *,
        kind: str,
        payload: dict[str, Any],
    ) -> Any:
        return self.store.save_recovery_artifact(run_id, kind=kind, payload=payload)

    def load_recovery_artifact(self, run_id: str, reference: Any) -> dict[str, Any] | None:
        return self.store.load_recovery_artifact(run_id, reference)


@dataclass
class SupervisorSession:
    """Owns checkpoint and lease operations for one root Run."""

    supervisor: RuntimeSupervisor
    run: RunHandle
    lease: Any | None = None

    def acquire(self) -> bool:
        if self.lease is not None:
            return True
        self.lease = self.supervisor.try_acquire_run_lease(self.run.run_id)
        return self.lease is not None

    def release(self) -> None:
        self.supervisor.release_run_lease(self.lease)
        self.lease = None

    def load_latest(self) -> Any | None:
        return self.supervisor.load_latest(self.run.run_id)
