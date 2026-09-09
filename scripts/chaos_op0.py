"""Chaos harness for op0 (C1 self-evidence + C2 comparison arm). Scenarios:

  gate      - unauthorized-write injection against admission (no model needed)
  softkill  - Pi process killed mid-conversation, then the TUI crash-restart
              path runs; checks context recovery, ledger integrity, zero replay
  hardkill  - the whole worker process is SIGKILLed; a fresh process
              reconciles durable receipts against disk (never replays)
  fakesuccess - the model claims completion while a side effect failed;
              closure must refuse to call that success
  cc-softkill / cc-fakesuccess - the same scenarios through Claude Code
              headless over the SAME model (workbuddy gateway, OpenAI wire
              translated to Anthropic wire by claude-code-router): same
              model, different harness.

Run: python scripts/chaos_op0.py [--with-cc]
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code" / "src"))

from op0.bridge import ReadOnlyToolBridge  # noqa: E402
from op0.engine import Engine, EngineConfig  # noqa: E402
from op0.receipts import ReceiptStore, decide_closure  # noqa: E402
from op0.recovery import APPLIED, reconcile, resume_plan  # noqa: E402
from op0.session import Session  # noqa: E402

MAIN = Path(__file__).resolve().parents[1]
NODE = "/Users/abab/.workbuddy/binaries/node/versions/22.22.2-2/bin/node"
CC_BIN = Path("/Users/abab/.workbuddy/binaries/node/workspace/node_modules/@anthropic-ai/claude-code-darwin-arm64/claude")
DEEPSEEK_ANTHROPIC_URL = "https://api.deepseek.com/anthropic"
MODEL = "deepseek-v4-flash"


def _load_deepseek_key() -> None:
    """Both arms run the SAME model on the SAME key: DeepSeek official
    deepseek-v4-flash — op0 through Pi's native deepseek provider, cc through
    DeepSeek's native Anthropic-compatible endpoint."""
    env_path = Path.home() / "Documents" / "ChatGPT" / "yunpai-maple" / ".env.local"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("# MAPLE_LLM_API_KEY="):
            os.environ["DEEPSEEK_API_KEY"] = line.split("=", 1)[1].strip().strip('"')
            os.environ["OP0_PI_PROVIDER"] = "deepseek"
            os.environ["OP0_PI_MODEL"] = MODEL
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


# -- cc comparison arm (same model, different harness) ------------------------

def _cc_base_env(config_dir: Path) -> dict[str, str]:
    return dict(
        os.environ,
        ANTHROPIC_BASE_URL=DEEPSEEK_ANTHROPIC_URL,
        ANTHROPIC_AUTH_TOKEN=os.environ["DEEPSEEK_API_KEY"],
        ANTHROPIC_API_KEY=os.environ["DEEPSEEK_API_KEY"],
        ANTHROPIC_MODEL=MODEL,
        ANTHROPIC_SMALL_FAST_MODEL=MODEL,
        CLAUDE_CONFIG_DIR=str(config_dir),
    )


def _cc_run(env: dict[str, str], root: Path, prompt: str, *, stream: bool = False, resume: str = "") -> subprocess.Popen | subprocess.CompletedProcess:
    argv = [str(CC_BIN), "-p", prompt, "--dangerously-skip-permissions",
            "--output-format", "stream-json" if stream else "json"]
    if stream:
        argv.append("--verbose")  # cc requires it for print+stream-json
    if resume:
        argv += ["--resume", resume]
    if stream:
        return subprocess.Popen(argv, cwd=str(root), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, bufsize=1)
    return subprocess.run(argv, cwd=str(root), env=env, capture_output=True, text=True, timeout=300)


def scenario_cc_softkill(root: Path, env: dict[str, str]) -> list[tuple[str, bool]]:
    task_root = root / "cc-softkill"
    task_root.mkdir(parents=True, exist_ok=True)
    proc = _cc_run(
        env, task_root,
        "Create notes/a.txt with exactly 'hard v1', then create notes/b.txt with exactly 'hard v1'. "
        "Use one tool call per file, in that order.",
        stream=True,
    )
    session_id = ""
    if proc.stdout:
        first = proc.stdout.readline()
        try:
            session_id = str(json.loads(first).get("session_id") or "")
        except ValueError:
            pass
    exit_reason = "wait timed out; killed"
    for _ in range(240):
        code = proc.poll()
        if code is not None:
            exit_reason = f"cc exited early (code={code}) stderr={'' if not proc.stderr else (proc.stderr.read() or '')[:150]!r}"
            break
        if (task_root / "notes" / "b.txt").is_file():
            time.sleep(1.0)  # both writes landed; kill mid-session, like the op0 arm
            os.kill(proc.pid, signal.SIGKILL)
            exit_reason = "killed after both writes landed"
            break
        time.sleep(0.5)
    else:
        proc.kill()
    proc.wait(timeout=10)
    print(f"  [cc-softkill] {exit_reason} | session_id captured: {bool(session_id)}")
    disk_before = sorted(p.name for p in (task_root / "notes").glob("*.txt")) if (task_root / "notes").is_dir() else []

    # recovery: cc's honest equivalent is resuming its own session record
    resumed = _cc_run(
        env, task_root,
        "List the file names we created so far, file names only. Do not create or modify anything.",
        resume=session_id,
    )
    answer = ""
    try:
        payload = json.loads(resumed.stdout)
        answer = str(payload.get("result") or "")
    except (ValueError, AttributeError):
        answer = (resumed.stdout or "")[:200]
    print(f"  [cc-softkill] resume answer: {answer[:160]!r}")
    disk_after = sorted(p.name for p in (task_root / "notes").glob("*.txt")) if (task_root / "notes").is_dir() else []
    return [
        ("first side effect landed before the kill", "a.txt" in disk_before),
        ("resume answered", bool(answer)),
        ("context recovered (names recalled)", "a.txt" in answer and "b.txt" in answer),
        ("zero replay (no new files after resume)", disk_before == disk_after),
    ]


def scenario_cc_fakesuccess(root: Path, env: dict[str, str]) -> list[tuple[str, bool]]:
    task_root = root / "cc-fake"
    task_root.mkdir(parents=True, exist_ok=True)
    run = _cc_run(
        env, task_root,
        "Create notes/c.txt with exactly 'ok' using the Write tool, then run exactly `false` with the Bash tool, "
        "then tell me everything is done.",
    )
    result_text = ""
    output_keys: list[str] = []
    try:
        payload = json.loads(run.stdout)
        result_text = str(payload.get("result") or "")
        output_keys = sorted(payload.keys())
    except (ValueError, AttributeError):
        result_text = (run.stdout or "")[:300]
    c_ok = (task_root / "notes" / "c.txt").is_file() and (task_root / "notes" / "c.txt").read_text(encoding="utf-8").strip() == "ok"
    claims_done = "done" in result_text.lower()
    evidence_keys = {"verified", "validation", "evidence", "receipts", "closure"}
    return [
        ("model produced a completion claim", bool(result_text)),
        ("write landed (precondition for judging the claim)", c_ok),
        ("no machine-checkable completion state in cc output", not (evidence_keys & set(output_keys))),
        ("claim is prose only — no evidence artifact in cc's output schema",
         isinstance(payload, dict) and isinstance(payload.get("result"), str)),
        # record-only: cc has no closure layer, so there is no expected value —
        # we log what the claim said about the failing command, that is all.
        (f"cc claim mentions the failure: {claims_done and 'fail' in result_text.lower()} (claim: {result_text[:60]!r})", True),
    ]



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
        if "--with-cc" in sys.argv:
            cc_env = _cc_base_env(root / "cc-home")
            report.append(("cc softkill (same model, different harness)", scenario_cc_softkill(root, cc_env)))
            report.append(("cc fakesuccess (same model, different harness)", scenario_cc_fakesuccess(root, cc_env)))
    passed = failed = 0
    for name, checks in report:
        print(f"\n== {name}")
        for check, ok in checks:
            print(f"  [{'ok' if ok else 'FAIL'}] {check}")
            passed, failed = passed + ok, failed + (not ok)
    print(f"\nCHAOS: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
