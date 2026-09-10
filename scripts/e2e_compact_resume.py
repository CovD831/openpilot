"""E2E: compaction meets checkpoint resume. Run A folds its context
(budget trigger fires, Pi restarts mid-run) and dies without closure; a
fresh process detects the unfinished run, resumes it, rebuilds context
from the folded ledger, and the model recalls the marker that only ever
existed in the conversation. Proves the folded ledger is a sufficient
recovery source — compaction does not orphan a resumed run."""

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


def _engine(root: Path, session: Session, *, echo_marker: bool) -> tuple[Engine, ReadOnlyToolBridge, object]:
    if echo_marker:
        command = [sys.executable, str(FAKE), "--usage", "30000", "--echo-marker"]
    else:
        command = [sys.executable, str(FAKE), "--usage", "30000", "--reply", "the deployment marker is MARKER-ALPHA-42"]
    config = EngineConfig(
        command=tuple(command),
        cwd=str(root),
        enable_read_tool=False,
        context_budget_tokens=100_000,
        observations_dir=str(root / ".openpilot" / "observations"),
    )
    engine = Engine(session, config)
    bridge = ReadOnlyToolBridge((str(root),), observations_dir=str(root / ".openpilot" / "observations"))
    return engine, bridge, config


def main() -> int:
    checks: list[tuple[str, bool]] = []
    with tempfile.TemporaryDirectory(prefix="op0-compact-resume-") as tmp:
        root = Path(tmp)

        # run A: fold happens mid-run (budget trigger), then the process dies
        session_a = Session(root)
        engine_a, bridge_a, _ = _engine(root, session_a, echo_marker=False)
        bridge_a.start()
        engine_a.start(bridge_a)
        for turn in range(1, 6):
            engine_a.ask(f"task {turn}: do something")
        engine_a.stop()
        bridge_a.stop()
        ledger = session_a.path
        turns_before = len(session_a.load_events())

        events = session_a.load_events()
        checks.append(("compaction happened in run A", any(e.event_type == "compaction" for e in events)))
        checks.append(("run A died without closure", ledger in Session.unfinished_runs(root)))

        # resume: fresh process, folded ledger as the recovery source
        resumed = Session.resume(root, ledger.stem)
        checks.append(("resumed session appends the same ledger", resumed.path == ledger))
        engine_b, bridge_b, _ = _engine(root, resumed, echo_marker=True)
        bridge_b.start()
        engine_b.start(bridge_b)
        engine_b.inject_recovery_projection()
        answer = engine_b.ask("What is the deployment marker? Answer with the marker only.")
        engine_b.stop()
        bridge_b.stop()
        checks.append(("folded context recalled after resume", "MARKER-ALPHA-42" in answer))
        checks.append(("schema header present exactly once", ledger.read_text(encoding="utf-8").count('"record": "schema"') == 1))
        checks.append(("resumed events append to the folded ledger", len(resumed.load_events()) > turns_before))

    for check, ok in checks:
        print(f"  [{'ok' if ok else 'FAIL'}] {check}")
    failed = sum(not ok for _, ok in checks)
    print(f"\nE2E COMPACT-RESUME: {len(checks) - failed}/{len(checks)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
