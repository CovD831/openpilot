"""Approval keys must be control-level bindings: while the card is up, 'y'
approves instead of typing a letter into the input bar.

prompt_toolkit processes focused-control bindings before default character
insertion; app-level bindings never fire for char keys. So the structural
guarantee is: approval_kb registered on the focused BufferControl, gated by
the waiting-approval condition."""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit.keys import Keys

from op0.admission import AdmissionRegistry
from op0.bridge import ReadOnlyToolBridge
from op0.engine import Engine, EngineConfig
from op0.receipts import ReceiptStore
from op0.session import Session
from op0.tui import TuiSession


def _make(tmp_path: Path):
    registry = AdmissionRegistry(str(tmp_path))
    store = ReceiptStore(tmp_path)
    state = {"goal": "", "saw_response": False, "verbose": False}
    bridge = ReadOnlyToolBridge((str(tmp_path),))
    engine = Engine(Session(tmp_path), EngineConfig(cwd=str(tmp_path), enable_read_tool=False))
    tui = TuiSession(
        tmp_path,
        traj := Session(tmp_path),
        registry,
        store,
        bridge,
        engine,
        version="0.1.0",
        on_command=lambda t: None,
        state=state,
    )
    return tui, registry


def test_approval_keys_live_on_focused_control(tmp_path: Path) -> None:
    tui, registry = _make(tmp_path)
    control = tui.app.layout.current_window.content
    assert control.__class__.__name__ == "BufferControl"
    assert control.buffer is tui.input_buffer
    keys = {tuple(b.keys or []) for b in control.key_bindings.bindings}
    assert ("y",) in keys and ("n",) in keys and ("a",) in keys
    assert ("up",) in keys and ("down",) in keys and (Keys.ControlM,) in keys


def test_y_binding_routes_answer(tmp_path: Path) -> None:
    tui, registry = _make(tmp_path)
    registry.propose("demo", str(tmp_path / "f.txt"), kind="write")
    tui._approval = {"proposal": registry.pending()[0], "pending_count": 1, "selected": 0, "answer": None}
    tui.mode = "waiting-approval"

    y_binding = next(b for b in tui.input_buffer_control.key_bindings.bindings if list(b.keys or []) == ["y"])
    y_binding.call(type("E", (), {"app": tui.app})())

    assert tui._approval["answer"] == "y"
    tui._approval = None  # what _post_turn does with the answer
    assert tui._get_approval_card() == ""
