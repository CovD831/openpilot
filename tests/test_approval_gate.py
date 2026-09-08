"""Tool-call-time approval gate (claude-code semantics).

The bridge blocks the tool call the moment it is proposed; the card prints
into the transcript flow and the human's answer releases the blocked call.
Approved -> consent now and the same call executes; denied -> the model sees
a refusal telling it to adapt instead of retrying."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from prompt_toolkit.keys import Keys

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
    assert result["value"] == "y"
    assert tui.mode == "working"  # turn still running; spinner resumes
    # approve/deny bookkeeping lives in the cli layer (_gate_consent), which
    # consumes this answer — covered by test_gate_consent_approves_and_denies.


def test_approval_gate_arrow_selection(tmp_path: Path) -> None:
    """↑↓ move the selection (mirrored in the status line), enter confirms it."""
    tui, registry = _make_tui(tmp_path)
    registry.propose_command("demo", "ls -la")
    proposal = registry.pending()[0]

    result: dict = {}
    gate_thread = threading.Thread(target=lambda: result.update(value=tui.approval_gate(proposal)), daemon=True)
    gate_thread.start()
    time.sleep(0.3)

    bindings = {
        tuple(b.keys or []): b for b in tui.input_buffer_control.key_bindings.bindings
    }
    event = type("E", (), {"app": tui.app})()
    bindings[("down",)].call(event)
    bindings[("down",)].call(event)  # wraps to 3. No
    assert tui._approval["selected"] == 2
    status = tui._get_status()
    assert "3. No" in str(status.value if hasattr(status, "value") else status)
    bindings[("up",)].call(event)
    assert tui._approval["selected"] == 1
    bindings[(Keys.ControlM,)].call(event)  # enter is stored as ControlM
    gate_thread.join(timeout=2.0)
    assert result["value"] == "a"  # selection 2 = Yes to all


def test_gate_timeout_keeps_proposal_pending(tmp_path: Path) -> None:
    """A gate that times out returns "" and must NOT deny the proposal —
    the human simply hasn't answered yet."""
    tui, registry = _make_tui(tmp_path)
    registry.propose_command("demo", "ls -la")
    answer = tui.approval_gate(registry.pending()[0], timeout=0.2)
    assert answer == ""
    assert len(registry.pending()) == 1  # still pending, not denied


def test_blocked_gate_does_not_stall_other_calls(tmp_path: Path) -> None:
    """Regression: a single-threaded _serve turned one blocked approval into
    a dead gateway — every later tool call timed out. Each connection must
    be served on its own thread."""
    import json
    import socket as socket_module

    registry = AdmissionRegistry(str(tmp_path))
    session = Session(tmp_path)
    store = ReceiptStore(tmp_path)
    release = threading.Event()
    gate = {"fn": lambda proposal: (release.wait(5), "y")[1]}
    bridge = _make_bridge(
        session, registry, store, str(tmp_path), goal_state={"goal": "g"}, gate_holder=gate
    )
    bridge.start()
    try:
        registry.propose_command("g", "echo gated")

        def blocked_bash() -> None:
            bridge._run_bash({"command": "echo gated"})

        bash_thread = threading.Thread(target=blocked_bash, daemon=True)
        bash_thread.start()
        time.sleep(0.3)  # bash is now blocked inside the gate

        # a plain read over a second connection must still be served
        target = tmp_path / "r.txt"
        target.write_text("hello gate", encoding="utf-8")
        client = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
        client.settimeout(5)
        client.connect(bridge.socket_path)
        client.sendall(
            (
                json.dumps(
                    {"type": "tool_call", "toolName": "openpilot_read",
                     "toolCallId": "r1", "args": {"path": str(target)}}
                )
                + "\n"
            ).encode()
        )
        buffer = b""
        while b"\n" not in buffer:
            chunk = client.recv(4096)
            if not chunk:
                break
            buffer += chunk
        client.close()
        response = json.loads(buffer.split(b"\n", 1)[0])
        assert response["success"] is True
        assert "hello gate" in response["content"]

        release.set()
        bash_thread.join(timeout=3)
        assert not bash_thread.is_alive()
        assert registry.pending() == []  # approved at gate time, bash executed
    finally:
        bridge.stop()


def test_gate_consent_approves_and_denies(tmp_path: Path) -> None:
    registry = AdmissionRegistry(str(tmp_path))
    session = Session(tmp_path)
    store = ReceiptStore(tmp_path)

    approve_gate = {"fn": lambda proposal: "y"}
    bridge = _make_bridge(
        session, registry, store, str(tmp_path), goal_state={"goal": "g"}, gate_holder=approve_gate
    )
    consent = bridge.command_authorizer("echo approved", {})
    assert consent.consent_id
    assert session.load_events()[-1].event_type == "consent_bound"

    deny_gate = {"fn": lambda proposal: "n"}
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
