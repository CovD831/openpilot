"""Contract registry: metadata cannot enter the ledger without a contract."""

from __future__ import annotations

import pytest

from op0 import metadata
from op0.session import Session


def test_registered_payload_passes(tmp_path: Path) -> None:
    session = Session(tmp_path)
    record = session.record("turn_started", {"prompt": "hi", "turn_id": "turn-1"}, producer="pi")
    assert record.event_type == "turn_started"


def test_missing_required_field_rejected(tmp_path: Path) -> None:
    session = Session(tmp_path)
    with pytest.raises(ValueError, match="missing required field"):
        session.record("turn_started", {"prompt": "hi"})


def test_wrong_type_rejected_and_bool_is_not_int(tmp_path: Path) -> None:
    session = Session(tmp_path)
    with pytest.raises(ValueError, match="must be str"):
        session.record("turn_started", {"prompt": 42, "turn_id": "t"})
    with pytest.raises(ValueError, match="must be int"):
        session.record("run_finished", {"response_chars": True})


def test_unregistered_type_fails_closed(tmp_path: Path) -> None:
    session = Session(tmp_path)
    with pytest.raises(ValueError, match="unregistered event type"):
        session.record("some_new_thing", {"x": 1})


def test_passthrough_and_admission_variants_not_enforced(tmp_path: Path) -> None:
    session = Session(tmp_path)
    # Pi wire payloads are declared but not strictly validated
    session.record("model_response", {"type": "message_end", "message": {"x": 1}}, producer="pi")
    session.record("consent_bound", {"consent_id": "c"}, producer="admission")


def test_producer_and_consumers_are_declared() -> None:
    spec = metadata.contract_of("task_spawned")
    assert spec["producer"] == "task"
    assert "audit" in spec["consumers"] and "recovery" in spec["consumers"]
    assert metadata.contract_of("unregistered_thing") is None
