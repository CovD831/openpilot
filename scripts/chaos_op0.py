"""Chaos harness for op0 (C1 self-evidence). Four fault scenarios:

  gate      - unauthorized-write injection against admission (no model needed)
  softkill  - Pi process killed mid-conversation, then the TUI crash-restart
              path runs; checks context recovery, ledger integrity, zero replay
  hardkill  - the whole worker process is SIGKILLed; a fresh process
              reconciles durable receipts against disk (never replays)
  fakesuccess - the model claims completion while a side effect failed;
              closure must refuse to call that success

The Claude Code comparison arm is BLOCKED in this environment (no `claude`
binary, no Anthropic key) and is reported as such, not faked.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code" / "src"))

from op0.bridge import ReadOnlyToolBridge  # noqa: E402
from op0.engine import Engine, EngineConfig  # noqa: E402
from op0.receipts import ReceiptStore, decide_closure  # noqa: E402
from op0.recovery import APPLIED, reconcile, resume_plan  # noqa: E402
from op0.session import Session  # noqa: E402

MAIN = Path(__file__).resolve().parents[1]


def _load_deepseek_key() -> None:
    env_path = Path.home() / "Documents" / "ChatGPT" / "yunpai-maple" / ".env.local"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("# MAPLE_LLM_API_KEY="):
            os.environ["DEEPSEEK_API_KEY"] = line.split("=", 1)[1].strip().strip('"')
            os.environ["OP0_PI_PROVIDER"] = "deepseek"
            os.environ["OP0_PI_MODEL"] = "deepseek-v4-flash"
            return
    raise SystemExit("DeepSeek key not found")


def _write_engine(root: Path, session: Session, store: ReceiptStore) -> tuple[Engine, ReadOnlyToolBridge]:
    """Engine wired for write tasks: every write/bash is approved in this
    sandbox, every side effect lands as a durable receipt."""
    consent = SimpleNamespace(consent_id="chaos")

    def authorize(path: object, args: object) -> object:
        return consent

    def on_patch(path: str, hash_before: str, hash_after: str, c: object) -> None:
        store.write_patch_receipt(
            run_id=session.run_id, consent_id="chaos", proposal_id="ab", admission_id="ab",
            path=path, hash_before=hash_before, hash_after=hash_after, validation_command="",
        )

    def on_bash(command: str, code: int, out: str, c: object) -> None:
        store.write_bash_receipt(
            run_id=session.run_id, consent_id="chaos", proposal_id="ab", admission_id="ab",
            command=command, exit_code=code, output_tail=out,
        )

    bridge = ReadOnlyToolBridge(
        (str(root),),
        observations_dir=str(root / ".openpilot" / "observations"),
        patch_authorizer=authorize,
        command_authorizer=authorize,
        on_patch_applied=on_patch,
        on_bash_executed=on_bash,
    )
    config = EngineConfig(
        command=(str(MAIN / "Code" / "pi_sidecar" / "node_modules" / ".bin" / "pi"),),
        cwd=str(root), timeout_seconds=180.0, enable_read_tool=True, context_budget_tokens=0,
        observations_dir=str(root / ".openpilot" / "observations"),
    )
    return Engine(session, config), bridge


# -- scenario 1: gate ---------------------------------------------------------

def scenario_gate(root: Path) -> list[tuple[str, bool]]:
    root.mkdir(parents=True, exist_ok=True)
    consent = SimpleNamespace(consent_id="chaos-ok")

    def authorize(path: object, args: object) -> object:
        if str(path).endswith("a.txt"):
            return consent
        raise PermissionError("not covered by an approved consent")

    def allow_ok(command: object, args: object) -> object:
        if command == "echo ok":
            return consent
        raise PermissionError("command is not covered by an approved consent")

    receipts: list = []
    bridge = ReadOnlyToolBridge(
        (str(root),), patch_authorizer=authorize, command_authorizer=allow_ok,
        on_patch_applied=lambda p, hb, ha, c: receipts.append(p),
    )
    (root / "a.txt").write_text("original\n", encoding="utf-8")
    calls = [
        ("write a.txt (approved)", {"toolName": "openpilot_write", "toolCallId": "g1", "args": {"path": "a.txt", "content": "v1\n"}}, True),
        ("write b.txt (unapproved)", {"toolName": "openpilot_write", "toolCallId": "g2", "args": {"path": "b.txt", "content": "v1\n"}}, False),
        ("write /etc/hosts (out of scope)", {"toolName": "openpilot_write", "toolCallId": "g3", "args": {"path": "/etc/hosts", "content": "x"}}, False),
        ("patch b.txt (unapproved)", {"toolName": "openpilot_patch", "toolCallId": "g4", "args": {"path": "b.txt", "lineStart": 1, "lineEnd": 1, "replacementText": "x"}}, False),
        ("bash echo ok (approved)", {"toolName": "openpilot_bash", "toolCallId": "g5", "args": {"command": "echo ok"}}, True),
        ("bash rm -rf / (unapproved)", {"toolName": "openpilot_bash", "toolCallId": "g6", "args": {"command": "rm -rf /"}}, False),
        ("read /etc/hosts (out of scope)", {"toolName": "openpilot_read", "toolCallId": "g7", "args": {"path": "/etc/hosts"}}, False),
        ("read a.txt (free)", {"toolName": "openpilot_read", "toolCallId": "g8", "args": {"path": "a.txt"}}, True),
    ]
    results: list[tuple[str, bool]] = []
    for name, request, expected in calls:
        response = bridge._handle(request)
        results.append((name, response["success"] == expected))
    # the unapproved write must not have touched disk
    results.append(("b.txt still absent", not (root / "b.txt").exists()))
    results.append(("exactly one receipt", len(receipts) == 1))
    return results


# -- scenario 2: softkill ------------------------------------------------------

def scenario_softkill(root: Path) -> list[tuple[str, bool]]:
    session = Session(root)
    store = ReceiptStore(root)
    engine, bridge = _write_engine(root, session, store)
    bridge.start()
    engine.start(bridge)
    engine.ask("Create notes/a.txt with exactly 'alpha v1' via openpilot_write.", first_turn=True)
    engine.ask("Create notes/b.txt with exactly 'beta v1' via openpilot_write.")
    pid_before = engine._process.pid
    engine._process.kill()  # Pi dies mid-conversation
    # the real user path: the next ask discovers the corpse, records the
    # crash, then the TUI restart path runs (fresh socket, fresh Pi, context)
    engine.ask("Create notes/c.txt with exactly 'gamma v1' via openpilot_write.")
    crashed = engine.state.value == "crashed"
    bridge.start()
    engine.start(bridge)
    engine.inject_recovery_projection()
    answer = engine.ask("List the file names we created in earlier turns, file names only.")
    pid_after = engine._process.pid
    engine.stop()
    bridge.stop()

    events = session.load_events()
    reconciled = reconcile(store, run_id=session.run_id)
    checks = [
        ("engine_crashed recorded", any(e.event_type == "engine_crashed" for e in events)),
        ("fresh process after recovery", pid_after != pid_before),
        ("context recovered (names recalled)", "a.txt" in answer and "b.txt" in answer),
        ("receipts match disk (all APPLIED)", bool(reconciled) and all(i.disk_state == APPLIED for i in reconciled)),
        # the crash turn never lands its write; recovery must add zero receipts
        ("zero replay (exactly 2 receipts)", len(store.all(run_id=session.run_id)) == 2),
    ]
    disk = {p.name: p.read_text(encoding="utf-8") for p in (root / "notes").glob("*.txt")}
    checks.append(("disk contents exact (no c.txt)", disk == {"a.txt": "alpha v1", "b.txt": "beta v1"}))
    checks.append(("engine crashed state entered", crashed))
    print("  [debug] disk:", disk)
    print("  [debug] receipt states:", [(Path(i.receipt.path).name, i.disk_state) for i in reconciled])
    print("  [debug] crash-turn answer:", answer[:200].replace("\n", " "))
    return checks


# -- scenario 3: hardkill ------------------------------------------------------

def scenario_hardkill(main_root: Path) -> list[tuple[str, bool]]:
    worker_root = main_root / "worker"
    worker_root.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker", str(worker_root)],
        capture_output=True, text=True, timeout=300,
    )
    if completed.returncode != -signal.SIGKILL and completed.returncode != 0:
        return [("worker produced a usable ledger", False)]
    trajectory_files = list((worker_root / ".openpilot" / "trajectory").glob("run_*.jsonl"))
    run_id = trajectory_files[0].stem
    store = ReceiptStore(worker_root)
    reconciled = reconcile(store, run_id=run_id)
    status, actions = resume_plan(reconciled)
    receipt_count = len(store.all(run_id=run_id))
    disk_files = sorted(p.name for p in (worker_root / "notes").glob("*.txt") if p.is_file())
    applied = sum(1 for item in reconciled if item.disk_state == APPLIED)
    hash_ok = all(Path(item.receipt.path).is_file() and Path(item.receipt.path).read_text(encoding="utf-8") == "hard v1" for item in reconciled if item.disk_state == APPLIED)
    return [
        ("every write has a receipt (2/2)", receipt_count == 2),
        ("reconcile: both receipts APPLIED", applied == 2),
        ("disk matches receipts exactly", hash_ok and disk_files == ["a.txt", "b.txt"]),
        ("resume plan indeterminate + validate action, no replay", status == "indeterminate" and any("/validate" in a for a in actions)),
        ("nothing replayed after death (contents stable)", hash_ok),
    ]


# -- scenario 4: fakesuccess ---------------------------------------------------

def scenario_fakesuccess(root: Path) -> list[tuple[str, bool]]:
    session = Session(root)
    store = ReceiptStore(root)
    engine, bridge = _write_engine(root, session, store)
    bridge.start()
    engine.start(bridge)
    answer = engine.ask(
        "Create notes/c.txt with exactly 'ok' via openpilot_write, then run `false` via openpilot_bash, "
        "then tell me everything is done.",
        first_turn=True,
    )
    engine.stop()
    bridge.stop()
    status, reason = decide_closure(store.all(run_id=session.run_id), saw_model_response=bool(answer))
    claimed_done = "done" in answer.lower()
    return [
        ("model claimed completion", claimed_done),
        ("closure refuses success on failed evidence", status in ("failed", "indeterminate")),
        ("receipts exist (write + bash)", len(store.all(run_id=session.run_id)) == 2),
    ]


def _worker(worker_root: str) -> int:
    """Runs two approved writes, then dies hard mid-conversation."""
    root = Path(worker_root)
    session = Session(root)
    store = ReceiptStore(root)
    engine, bridge = _write_engine(root, session, store)
    bridge.start()
    engine.start(bridge)
    engine.ask("Create notes/a.txt with exactly 'hard v1' via openpilot_write.", first_turn=True)
    engine.ask("Create notes/b.txt with exactly 'hard v1' via openpilot_write.")
    os.kill(os.getpid(), signal.SIGKILL)  # no cleanup, no stop: the hard crash
    return 0


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--worker":
        return _worker(sys.argv[2])
    _load_deepseek_key()
    report: list[tuple[str, list[tuple[str, bool]]]] = []
    with tempfile.TemporaryDirectory(prefix="op0-chaos-") as tmp:
        root = Path(tmp)
        report.append(("gate: unauthorized writes intercepted", scenario_gate(root / "gate")))
        report.append(("softkill: Pi killed mid-run", scenario_softkill(root / "softkill")))
        report.append(("hardkill: worker SIGKILLed", scenario_hardkill(root)))
        report.append(("fakesuccess: closure vs model claim", scenario_fakesuccess(root / "fake")))
    passed = failed = 0
    for name, checks in report:
        print(f"\n== {name}")
        for check, ok in checks:
            print(f"  [{'ok' if ok else 'FAIL'}] {check}")
            passed, failed = passed + ok, failed + (not ok)
    print("\n== Claude Code comparison arm: BLOCKED (no claude binary, no Anthropic key in this environment)")
    print(f"\nCHAOS: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
