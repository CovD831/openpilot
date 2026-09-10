"""Phase 3 separation: each run binds its OWN authorizer set, so admission
events land in the ledger of the run they govern — a child's proposals,
consents and receipts never leak into the parent ledger (and vice versa),
while registry and human gate stay shared."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code" / "src"))

from op0.admission import AdmissionRegistry  # noqa: E402
from op0.cli import _bind_authorizers  # noqa: E402
from op0.receipts import ReceiptStore  # noqa: E402
from op0.session import Session  # noqa: E402


def _event_types(session: Session) -> set[str]:
    return {e.event_type for e in session.load_events()}


def test_admission_events_land_in_bound_ledger(tmp_path):
    registry = AdmissionRegistry(str(tmp_path))
    gate = {"fn": None}
    goal_state = {"goal": "g", "approval_mode": "auto"}

    parent_session = Session(tmp_path)
    parent_store = ReceiptStore(tmp_path)
    p_authorize, _p_cmd, _p_patch, _p_bash = _bind_authorizers(
        parent_session, parent_store, registry, gate, str(tmp_path), goal_state
    )
    p_authorize(str(tmp_path / "f.txt"), {"content": "x"})

    parent_types = _event_types(parent_session)
    assert "patch_proposed" in parent_types
    assert "consent_bound" in parent_types
    assert "patch_authorized" in parent_types


def test_parent_and_child_ledgers_do_not_leak(tmp_path):
    registry = AdmissionRegistry(str(tmp_path))
    gate = {"fn": None}
    goal_state = {"goal": "g", "approval_mode": "auto"}

    parent_session = Session(tmp_path)
    parent_store = ReceiptStore(tmp_path)
    _bind_authorizers(parent_session, parent_store, registry, gate, str(tmp_path), goal_state)

    child_session = Session(tmp_path)
    child_store = ReceiptStore(tmp_path)
    c_authorize, _c_cmd, _c_patch, _c_bash = _bind_authorizers(
        child_session, child_store, registry, gate, str(tmp_path), goal_state
    )
    c_authorize(str(tmp_path / "child.txt"), {"content": "x"})

    child_types = _event_types(child_session)
    parent_types = _event_types(parent_session)
    # the child's admission chain is fully in the child ledger...
    assert {"patch_proposed", "consent_bound", "patch_authorized"} <= child_types
    # ...and nothing of it leaked into the parent ledger
    assert not (child_types & {"patch_proposed", "consent_bound", "patch_authorized"}) & parent_types


def test_bash_receipt_lands_in_bound_ledger(tmp_path):
    registry = AdmissionRegistry(str(tmp_path))
    gate = {"fn": None}
    goal_state = {"goal": "g", "approval_mode": "auto"}

    session = Session(tmp_path)
    store = ReceiptStore(tmp_path)
    _authorize, authorize_cmd, _patch, on_bash = _bind_authorizers(
        session, store, registry, gate, str(tmp_path), goal_state
    )
    consent = authorize_cmd("echo hi", {})
    on_bash("echo hi", 0, "hi", consent)

    types = _event_types(session)
    assert "command_authorized" in types
    assert "bash_receipt_written" in types
    assert len(store.all(run_id=session.run_id)) == 1
