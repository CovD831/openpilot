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
    assert ("1",) in keys and ("2",) in keys and ("3",) in keys
    assert (Keys.Escape,) in keys
    # no reserved card rows: the layout is the input bar only (constant height)
    assert tui.app.layout.container.children.__len__() < 10


def test_y_binding_routes_answer(tmp_path: Path) -> None:
    tui, registry = _make(tmp_path)
    registry.propose("demo", str(tmp_path / "f.txt"), kind="write")
    tui._approval = {"proposal": registry.pending()[0], "answer": None}
    tui.mode = "waiting-approval"

    y_binding = next(b for b in tui.input_buffer_control.key_bindings.bindings if list(b.keys or []) == ["y"])
    y_binding.call(type("E", (), {"app": tui.app})())

    assert tui._approval["answer"] == "y"


def test_proposal_card_renders_in_flow(tmp_path: Path) -> None:
    """The cc-shaped card: divider + label + action + question + numbered
    options, as transcript text (no bordered panel, no live layout widget)."""
    import re

    from op0.ui import render_proposal_to_str

    registry = AdmissionRegistry(str(tmp_path))
    registry.propose_command("demo goal", "ls -la")
    rendered = render_proposal_to_str(registry.pending()[0])
    clean = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", rendered)
    assert "Do you want to proceed?" in clean
    assert "❯ 1. Yes" in clean and "2. Yes to all" in clean and "3. No" in clean
    assert "$ ls -la" in clean
    assert "╭" not in clean and "╰" not in clean  # no border box


def test_read_paging_and_proposal_dedupe(tmp_path: Path) -> None:
    from op0.bridge import ReadOnlyToolBridge

    tui, registry = _make(tmp_path)
    big = tmp_path / "big.html"
    big.write_text("\n".join(f"line {n}" for n in range(1, 701)), encoding="utf-8")
    bridge = ReadOnlyToolBridge((str(tmp_path),))
    control = tui.input_buffer_control  # ensure TUI built fine

    page1 = bridge._read_scoped(str(big))
    assert "1\tline 1" in page1
    assert "line 400" in page1 and "line 401" not in page1
    assert "offset=401" in page1
    page2 = bridge._read_scoped(str(big), {"offset": 401})
    assert "line 401" in page2 and "line 700" in page2

    # retrying the same bash proposal reuses it — no card pile-up
    p1 = registry.propose_command("g", "ls -la")
    p2 = registry.propose_command("g", "ls -la")
    assert p1.proposal_id == p2.proposal_id
    p3 = registry.propose("g", str(tmp_path / "f.txt"), kind="write")
    p4 = registry.propose("g", str(tmp_path / "f.txt"), kind="write")
    assert p3.proposal_id == p4.proposal_id
