"""E2E for checkpoint resume: run A works two turns and exits without
closure; a fresh process detects the unfinished run, resumes it, rebuilds
context from the ledger, and continues appending to the same file."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code" / "src"))

from op0.bridge import ReadOnlyToolBridge  # noqa: E402
from op0.engine import Engine, EngineConfig  # noqa: E402
from op0.session import Session  # noqa: E402

MAIN = Path(__file__).resolve().parents[1]
FAKE = MAIN / "scripts" / "fake_pi_compaction.py"


def _engine(root: Path, session: Session, reply: str, *, echo_marker: bool = False) -> tuple[Engine, ReadOnlyToolBridge]:
    command = [sys.executable, str(FAKE), "--reply", reply] + (["--echo-marker"] if echo_marker else [])
    config = EngineConfig(
        command=tuple(command),
        cwd=str(root),
        enable_read_tool=False,
        context_budget_tokens=0,
        observations_dir=str(root / ".openpilot" / "observations"),
    )
    engine = Engine(session, config)
    bridge = ReadOnlyToolBridge((str(root),), observations_dir=str(root / ".openpilot" / "observations"))
    return engine, bridge


def main() -> int:
    checks: list[tuple[str, bool]] = []
    with tempfile.TemporaryDirectory(prefix="op0-resume-e2e-") as tmp:
        root = Path(tmp)

        # run A: two turns, then the process "dies" without closure
        session_a = Session(root)
        engine_a, bridge_a = _engine(root, session_a, "the deployment marker is MARKER-ALPHA-42")
        bridge_a.start()
        engine_a.start(bridge_a)
        engine_a.ask("Deploy and tell me the marker.", first_turn=True)
        engine_a.stop()
        bridge_a.stop()
        ledger_a = session_a.path
        turns_before = len(session_a.load_events())

        # a fresh process detects the unfinished run
        candidates = Session.unfinished_runs(root)
        checks.append(("unfinished run detected", ledger_a in candidates))

        # resume: same ledger, context rebuilt, conversation continues
        session_b = Session.resume(root, candidates[0].stem)
        checks.append(("resumed session appends the same ledger", session_b.path == ledger_a))
        checks.append(("resumed index continues after existing events", session_b._index == turns_before))
        engine_b, bridge_b = _engine(root, session_b, "echo", echo_marker=True)
        bridge_b.start()
        engine_b.start(bridge_b)
        engine_b.inject_recovery_projection()
        answer = engine_b.ask("What is the deployment marker? Answer with the marker only.")
        engine_b.stop()
        bridge_b.stop()
        checks.append(("context restored (marker recalled)", "MARKER-ALPHA-42" in answer))

        # the resumed run keeps appending to the same ledger
        session_b.record("checkpoint_recorded", {"checkpoint_id": "ckpt-e2e", "note": "post-resume"}, producer="op0")
        ledger_lines = ledger_a.read_text(encoding="utf-8").count("\n")
        checks.append(("resumed events append to the same ledger", ledger_lines > turns_before))
        checks.append(("schema header present once", ledger_a.read_text(encoding="utf-8").count('"record": "schema"') == 1))

    for check, ok in checks:
        print(f"  [{'ok' if ok else 'FAIL'}] {check}")
    failed = sum(not ok for _, ok in checks)
    print(f"\nE2E RESUME: {len(checks) - failed}/{len(checks)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
