"""Tool-call-time approval gate (claude-code semantics).

The bridge blocks the tool call the moment it is proposed; the card prints
into the transcript flow and the human's answer releases the blocked call.
Approved -> consent now and the same call executes; denied -> the model sees
a refusal telling it to adapt instead of retrying."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from op0.admission import AdmissionRegistry
from op0.cli import _make_bridge
from op0.receipts import ReceiptStore
from op0.session import Session
from op0.tui import TuiSession


def _make_tui(tmp_path: Path):
    registry = AdmissionRegistry(str(tmp_path))
    store = ReceiptStore(tmp_path)
    state = {"goal": "", "saw_response": False, "verbose": False}
    engine = type("E", (), {"state": type("S", (), {"value": "idle"})(), "stop": lambda self: None})()
    tui = TuiSession(
        tmp_path,
        Session(tmp_path),
        registry,
        store,
        None,
        engine,
        version="0.1.0",
        on_command=lambda t: None,
        state=state,
    )
    return tui, registry


def test_approval_gate_blocks_until_answered(tmp_path: Path) -> None:
    tui, registry = _make_tui(tmp_path)
    registry.propose_command("demo", "ls -la")
    proposal = registry.pending()[0]

    result: dict = {}
    gate_thread = threading.Thread(target=lambda: result.update(value=tui.approval_gate(proposal)), daemon=True)
    gate_thread.start()
    time.sleep(0.3)  # let the gate block
    assert gate_thread.is_alive(), "gate must block the tool call until the human answers"
    assert tui.mode == "waiting-approval"

    y_binding = next(b for b in tui.input_buffer_control.key_bindings.bindings if list(b.keys or []) == ["y"])
    y_binding.call(type("E", (), {"app": tui.app})())
    gate_thread.join(timeout=2.0)

    assert not gate_thread.is_alive(), "the answer must release the blocked call"
    assert result["value"] is True
    assert tui.mode == "working"  # turn still running; spinner resumes
    # approve/deny bookkeeping lives in the cli layer (_gate_consent), which
    # consumes this boolean — covered by test_gate_consent_approves_and_denies.


def test_gate_consent_approves_and_denies(tmp_path: Path) -> None:
    registry = AdmissionRegistry(str(tmp_path))
    session = Session(tmp_path)
    store = ReceiptStore(tmp_path)

    approve_gate = {"fn": lambda proposal: True}
    bridge = _make_bridge(
        session, registry, store, str(tmp_path), goal_state={"goal": "g"}, gate_holder=approve_gate
    )
    consent = bridge.command_authorizer("echo approved", {})
    assert consent.consent_id
    assert session.load_events()[-1].event_type == "consent_bound"

    deny_gate = {"fn": lambda proposal: False}
    bridge = _make_bridge(
        session, registry, store, str(tmp_path), goal_state={"goal": "g"}, gate_holder=deny_gate
    )
    registry.propose_command("g", "echo denied")
    try:
        bridge.command_authorizer("echo denied", {})
        raise AssertionError("denied gate must raise PermissionError")
    except PermissionError as exc:
        assert "do not retry" in str(exc)
    assert registry.pending() == []
    assert any(
        e.event_type == "proposal_denied" and e.payload.get("gate") for e in session.load_events()
    )
