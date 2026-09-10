"""Real-provider smoke for subagent delegation (DeepSeek direct, v4-flash).

The parent model must autonomously call openpilot_task; the child run
(with its own ledger) reads a file only it knows about and reports back;
the parent answers from the child's structured report."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code" / "src"))

from op0.bridge import ReadOnlyToolBridge  # noqa: E402
from op0.engine import Engine, EngineConfig  # noqa: E402
from op0.receipts import ReceiptStore  # noqa: E402
from op0.session import Session  # noqa: E402

SMOKE = Path(__file__).resolve().parent


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


def _engine(root: Path, session: Session, spawner) -> tuple[Engine, ReadOnlyToolBridge]:
    config = EngineConfig(
        cwd=str(root),
        timeout_seconds=180.0,
        enable_read_tool=True,
        context_budget_tokens=0,
        observations_dir=str(root / ".openpilot" / "observations"),
    )
    engine = Engine(session, config)
    consent = type("C", (), {"consent_id": "smoke"})()
    bridge = ReadOnlyToolBridge(
        (str(root),),
        observations_dir=str(root / ".openpilot" / "observations"),
        patch_authorizer=lambda p, a: consent,
        command_authorizer=lambda c, a: consent,
        task_spawner=spawner,
    )
    return engine, bridge


def main() -> int:
    _load_deepseek_key()
    with tempfile.TemporaryDirectory(prefix="op0-task-real-") as tmp:
        root = Path(tmp)
        secret_dir = root / "notes"
        secret_dir.mkdir()
        (secret_dir / "secret2.txt").write_text(
            "The second code is SECRET-TWO-9042.\n", encoding="utf-8"
        )
        session = Session(root)
        store = ReceiptStore(root)

        def spawn(task_prompt: str) -> dict:
            child_session = Session(root)
            child_store = ReceiptStore(root)
            child_engine, child_bridge = _engine(root, child_session, None)
            session.record(
                "task_spawned",
                {"task_run_id": child_session.run_id, "task": task_prompt[:200], "depth": 1},
                producer="task",
            )
            status, summary = "indeterminate", ""
            try:
                child_bridge.start()
                child_engine.start(child_bridge)
                answer = child_engine.ask(
                    "You are an op0 subagent. Complete the task and report concisely.\n" + task_prompt,
                    first_turn=True,
                )
                if answer.strip():
                    status, summary = "success", answer[:2000]
                else:
                    summary = "subagent returned no report"[:2000]
            except Exception as exc:  # noqa: BLE001
                summary = f"subagent did not complete: {type(exc).__name__}: {exc}"[:2000]
            finally:
                child_engine.stop()
                child_bridge.stop()
            receipts = len(child_store.all(run_id=child_session.run_id))
            session.record(
                "task_finished",
                {"task_run_id": child_session.run_id, "status": status, "summary": summary, "receipts": receipts},
                producer="task",
            )
            print(f"  [info] child {child_session.run_id}: {status}, {receipts} receipt(s)")
            print(f"  [info] child summary: {summary[:160]!r}")
            return {"task_run_id": child_session.run_id, "status": status, "summary": summary, "receipts": receipts}

        engine, bridge = _engine(root, session, spawn)
        bridge.start()
        engine.start(bridge)
        answer = engine.ask(
            "Delegate via openpilot_task: have a subagent read notes/secret2.txt and report "
            "the code it contains. Then relay that code to me exactly.",
            first_turn=True,
        )
        engine.stop()
        bridge.stop()
        events = [e.event_type for e in session.load_events()]
        checks = [
            ("parent model called openpilot_task", "task_spawned" in events),
            ("task_finished recorded", "task_finished" in events),
            ("answer carries the code", "SECRET-TWO-9042" in answer),
        ]
        print("answer:", answer[:220].replace("\n", " "))
        for check, ok in checks:
            print(f"  [{'ok' if ok else 'FAIL'}] {check}")
        return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
