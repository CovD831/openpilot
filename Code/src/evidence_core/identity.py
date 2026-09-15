"""Identity helpers for evidence-core records."""

from __future__ import annotations

from uuid import uuid4


def new_run_id() -> str:
    return uuid4().hex


def new_event_id() -> str:
    return uuid4().hex


def new_artifact_id() -> str:
    return uuid4().hex
