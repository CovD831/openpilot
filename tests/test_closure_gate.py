"""Closure gate: with closure_requires_spec, a run whose ledger lacks
spec_assumptions gets ONE corrective turn (openpilot_spec), then closes
WITH the miss marked - never an infinite loop. Already-recorded runs
close at zero cost."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code" / "src"))

from op0.engine import Engine, EngineConfig, EngineState  # noqa: E402
from op0.session import Session  # noqa: E402


def _engine_with_ledger(tmp_path: Path, *, with_spec: bool) -> Engine:
    session = Session(tmp_path)
    if with_spec:
        session.record("spec_assumptions", {"goal": "g", "assumptions": ["a"]}, producer="agent")
    config = EngineConfig(closure_requires_spec=True, timeout_seconds=180.0)
    engine = Engine(session, config)
    engine.state = EngineState.RUNNING  # not driving a real Pi sidecar here
    return engine, session


def test_already_recorded_closes_at_zero_cost(tmp_path):
    engine, session = _engine_with_ledger(tmp_path, with_spec=True)
    with mock.patch.object(Engine, "ask", return_value="done"), \
         mock.patch.object(session, "last_model_response", return_value="done"):
        result = Engine._enforce_spec_closure(engine)
    assert result == "done"
    # no gate event: an already-recorded run pays nothing
    assert not any(e.event_type == "closure_gate" for e in session.load_events())


def test_missing_record_gets_one_corrective_turn(tmp_path):
    engine, session = _engine_with_ledger(tmp_path, with_spec=False)
    corrective_calls = []

    def fake_ask(prompt, **kwargs):
        corrective_calls.append(prompt)
        assert kwargs.get("_closure_gate") is True  # the retry cannot re-gate
        session.record("spec_assumptions", {"goal": "g", "assumptions": ["late"]},
                       producer="agent")  # the model complies
        return "recorded via gate"

    with mock.patch.object(Engine, "ask", side_effect=fake_ask), \
         mock.patch.object(session, "last_model_response", return_value="pre-gate answer"):
        result = Engine._enforce_spec_closure(engine)
    assert result == "recorded via gate"
    assert len(corrective_calls) == 1 and "closure gate" in corrective_calls[0]
    results = [e.payload["result"] for e in session.load_events() if e.event_type == "closure_gate"]
    assert results == ["blocked", "passed_after_retry"]


def test_refusal_closes_with_miss_marked(tmp_path):
    engine, session = _engine_with_ledger(tmp_path, with_spec=False)
    with mock.patch.object(Engine, "ask", return_value="still nothing"), \
         mock.patch.object(session, "last_model_response", return_value="still nothing"):
        result = Engine._enforce_spec_closure(engine)
    assert result == "still nothing"  # the run closes, never an infinite loop
    results = [e.payload["result"] for e in session.load_events() if e.event_type == "closure_gate"]
    assert results == ["blocked", "closed_with_miss"]


def test_corrective_turn_crash_still_closes_with_miss(tmp_path):
    engine, session = _engine_with_ledger(tmp_path, with_spec=False)
    with mock.patch.object(Engine, "ask", side_effect=RuntimeError("Pi died in the gate")), \
         mock.patch.object(session, "last_model_response", return_value="pre-gate answer"):
        result = Engine._enforce_spec_closure(engine)
    assert result == "pre-gate answer"  # the pre-gate answer survives the gate crash
    results = [e.payload["result"] for e in session.load_events() if e.event_type == "closure_gate"]
    assert results == ["blocked", "closed_with_miss"]


def test_gate_disabled_by_default(tmp_path):
    session = Session(tmp_path)
    config = EngineConfig(timeout_seconds=180.0)  # closure_requires_spec unset
    assert config.closure_requires_spec is False  # callers opt in per task kind
