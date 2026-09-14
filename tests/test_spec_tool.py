"""Typed spec assumptions: openpilot_spec records the acceptance-assertion
variants the agent derived into the ledger (spec_assumptions, strict
contract) - the audit exit for the spec-derivation contract."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code" / "src"))

from op0.bridge import ReadOnlyToolBridge  # noqa: E402
from op0.session import Session  # noqa: E402


def _bridge(recorder) -> ReadOnlyToolBridge:
    return ReadOnlyToolBridge(("/tmp",), spec_recorder=recorder)


def _call(bridge: ReadOnlyToolBridge, args: dict) -> dict:
    return bridge._handle({"toolCallId": "t1", "toolName": "openpilot_spec", "args": args})


def test_spec_tool_records_into_ledger(tmp_path):
    session = Session(tmp_path)
    recorded = []
    bridge = _bridge(lambda payload: (recorded.append(payload),
                                      session.record("spec_assumptions", payload, producer="agent")))
    response = _call(bridge, {
        "goal": "add subdomain info to routes",
        "assumptions": ["column header reads Subdomain when SERVER_NAME is set",
                        "column header reads Host when host_matching is enabled"],
    })
    assert response["success"] is True
    assert "2 spec assumption(s)" in response["content"]
    events = [e for e in session.load_events() if e.event_type == "spec_assumptions"]
    assert len(events) == 1
    assert events[0].payload["goal"].startswith("add subdomain")
    assert len(events[0].payload["assumptions"]) == 2


def test_spec_tool_without_recorder_says_unavailable(tmp_path):
    bridge = _bridge(None)
    response = _call(bridge, {"goal": "g", "assumptions": ["a"]})
    assert response["success"] is True
    assert "not available" in response["content"]


def test_spec_tool_rejects_malformed_assumptions(tmp_path):
    bridge = _bridge(lambda payload: None)
    for bad in ({}, {"assumptions": []}, {"assumptions": "not-a-list"},
                {"assumptions": [42]}, {"assumptions": [""]}):
        response = _call(bridge, bad)
        assert response["success"] is False, bad


def test_spec_assumptions_contract_is_strict(tmp_path):
    """The registry must fail-closed on a malformed payload (metadata
    discipline: an assumptions list that is not a list is a ledger lie)."""
    session = Session(tmp_path)
    session.record("spec_assumptions", {"goal": "g", "assumptions": ["a"]}, producer="agent")
    assert any(e.event_type == "spec_assumptions" for e in session.load_events())
