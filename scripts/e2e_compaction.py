"""E2E: budget trigger -> compaction event -> Pi restart -> projection first
message, over the real Engine/Session/Bridge stack with a fake Pi process.
No provider key needed; the fake logs every prompt message it receives."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code" / "src"))

from op0.bridge import ReadOnlyToolBridge
from op0.engine import Engine, EngineConfig
from op0.session import Session


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="op0-compact-e2e-"))
    fake_log = tmp / "fake_pi_prompts.jsonl"
    fake_pi = Path(__file__).resolve().parent / "fake_pi_compaction.py"
    session = Session(tmp)

    def bridge_factory():
        return ReadOnlyToolBridge((str(tmp),), observations_dir=str(tmp / ".openpilot" / "observations"))

    bridge = bridge_factory()
    config = EngineConfig(
        # fake-pi takes its config as argv: the engine hands subprocesses a
        # strict env allowlist, so OP0_FAKE_* variables would never arrive
        command=(sys.executable, str(fake_pi), "--log", str(fake_log), "--usage", "30000"),
        cwd=str(tmp),
        enable_read_tool=False,
        context_budget_tokens=100_000,
        observations_dir=str(tmp / ".openpilot" / "observations"),
    )
    engine = Engine(session, config)
    bridge.start()
    engine.start(bridge)
    pid_before = engine._process.pid
    for turn in range(1, 6):
        engine.ask(f"task {turn}: do something")
    pid_after = engine._process.pid

    events = session.load_events()
    compactions = [e for e in events if e.event_type == "compaction"]
    prompts = [json.loads(line)["message"] for line in fake_log.read_text(encoding="utf-8").splitlines() if line.strip()]

    checks = {
        "compaction recorded": len(compactions) >= 1,
        "process restarted": pid_before != pid_after,
        "projection delivered": any("compact projection" in p for p in prompts),
        "projection carries folded turns": any("folded turns" in p and "### Turn 1" in p for p in prompts),
        "contract repinned after restart": any("This contract holds" in p and "compact projection" in p for p in prompts),
        "latest request on last prompt": "task 5" in prompts[-1],
    }
    for name, ok in checks.items():
        print(f"[{'ok' if ok else 'FAIL'}] {name}")
    engine.stop()
    bridge.stop()
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
