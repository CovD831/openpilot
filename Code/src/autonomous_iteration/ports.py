"""Stable Harness ports for UI, CLI, legacy adapters, and future Pi engines."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from autonomous_iteration.run_coordinator import RunHandle
from evidence_core import EventRecord


@runtime_checkable
class EnginePort(Protocol):
    def start(self, run: RunHandle) -> Any: ...


@runtime_checkable
class ActionPort(Protocol):
    def execute(self, run: RunHandle, request: Any) -> Any: ...


@runtime_checkable
class EvidencePort(Protocol):
    def start_run(self, task_id: str, **metadata: Any) -> RunHandle: ...
    def record_observation(self, run: RunHandle | str, **observation: Any) -> EventRecord: ...


@runtime_checkable
class VerificationPort(Protocol):
    def verify(self, run: RunHandle, result: Any) -> Any: ...


@runtime_checkable
class SupervisorPort(Protocol):
    def new_resume_attempt_id(self) -> str: ...
    def try_acquire_run_lease(self, run_id: str) -> Any | None: ...
    def release_run_lease(self, handle: Any | None) -> None: ...
    def save(self, checkpoint: Any, *, expected_generation: int | None = None) -> Any: ...
    def load(self, run_id: str, checkpoint_id: str) -> Any | None: ...


@runtime_checkable
class ApplicationPort(Protocol):
    def start(self, task_id: str, **metadata: Any) -> RunHandle: ...
    def observe(self, run: RunHandle | str, **observation: Any) -> EventRecord: ...
    def finish(self, run: RunHandle | str, *, success: bool, reason: str = "", **payload: Any) -> EventRecord: ...
