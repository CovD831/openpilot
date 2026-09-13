"""Real-provider smoke for PARALLEL subagent delegation (deepseek-v4-flash).

The parent model must autonomously call openpilot_tasks with two subtasks;
each child binds its OWN authorizer set (phase 3 separation), one child
works inside its own git worktree; verdicts come from declared validate
commands. Mirrors cli._spawn_tasks / cli._spawn_task construction."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code" / "src"))

from op0.admission import AdmissionRegistry  # noqa: E402
from op0.bridge import ReadOnlyToolBridge  # noqa: E402
from op0.cli import _bind_authorizers, dispose_worktree, make_worktree  # noqa: E402
from op0.engine import Engine, EngineConfig  # noqa: E402
from op0.receipts import ReceiptStore  # noqa: E402
from op0.session import Session  # noqa: E402


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


def _engine(root: Path, session: Session, spawner, tasks_spawner, authorize, cmd, patch_cb, bash_cb) -> tuple[Engine, ReadOnlyToolBridge]:
    config = EngineConfig(
        cwd=str(root),
        timeout_seconds=180.0,
        enable_read_tool=True,
        context_budget_tokens=0,
        observations_dir=str(root / ".openpilot" / "observations"),
    )
    engine = Engine(session, config)
    bridge = ReadOnlyToolBridge(
        (str(root),),
        observations_dir=str(root / ".openpilot" / "observations"),
        patch_authorizer=authorize,
        command_authorizer=cmd,
        on_patch_applied=patch_cb,
        on_bash_executed=bash_cb,
        task_spawner=spawner,
        tasks_spawner=tasks_spawner,
    )
    return engine, bridge


def main() -> int:
    _load_deepseek_key()
    with tempfile.TemporaryDirectory(prefix="op0-par-real-") as tmp:
        root = Path(tmp)
        # a real git repo: the worktree child needs one
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "README.md").write_text("smoke\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(root), "-c", "user.email=smoke@local", "-c",
                        "user.name=smoke", "commit", "-qm", "init"], check=True)
        (root / "notes").mkdir()
        (root / "notes" / "spec.txt").write_text("alpha code is ALPHA-111\nbeta code is BETA-222\n", encoding="utf-8")

        session = Session(root)
        store = ReceiptStore(root)
        registry = AdmissionRegistry(str(root))
        gate = {"fn": None}
        goal_state = {"goal": "parallel smoke", "approval_mode": "auto"}
        p_authorize, p_cmd, p_patch, p_bash = _bind_authorizers(
            session, store, registry, gate, str(root), goal_state
        )
        observations_dir = str(root / ".openpilot" / "observations")

        def spawn(task_prompt: str, validate_cmd: str = "", worktree: bool = False) -> dict:
            child_session = Session(root)
            child_store = ReceiptStore(root)
            c_authorize, c_cmd, c_patch, c_bash = _bind_authorizers(
                child_session, child_store, registry, gate, str(root), goal_state
            )
            wt_path, wt_branch = ("", "")
            base = str(root)
            if worktree:
                wt_path, wt_branch = make_worktree(str(root))
                base = wt_path
            config = EngineConfig(
                cwd=base,
                timeout_seconds=180.0,
                enable_read_tool=True,
                context_budget_tokens=0,
                observations_dir=observations_dir,
            )
            child_engine = Engine(child_session, config)
            child_bridge = ReadOnlyToolBridge(
                (base,),
                observations_dir=observations_dir,
                patch_authorizer=c_authorize,
                command_authorizer=c_cmd,
                on_patch_applied=c_patch,
                on_bash_executed=c_bash,
            )
            session.record(
                "task_spawned",
                {
                    "task_run_id": child_session.run_id,
                    "task": task_prompt[:200],
                    "depth": 1,
                    **({"worktree": wt_branch} if wt_branch else {}),
                },
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
            verified, exit_code = False, None
            if validate_cmd and status == "success":
                completed = subprocess.run(validate_cmd, shell=True, capture_output=True, text=True, cwd=base)
                exit_code, verified = completed.returncode, completed.returncode == 0
                child_session.record(
                    "task_validation",
                    {"command": validate_cmd, "exit_code": exit_code, "tail": (completed.stderr or "")[-200:]},
                    producer="task",
                )
                if verified:
                    summary = f"[validated] {summary}"[:2000]
                else:
                    status = "failed"
                    summary = f"validation failed (exit {exit_code}): {(completed.stderr or '')[:200]}"[:2000]
            kept = dispose_worktree(str(root), wt_path, wt_branch) if wt_branch else ""
            session.record(
                "task_finished",
                {
                    "task_run_id": child_session.run_id,
                    "status": status,
                    "summary": summary,
                    "receipts": receipts,
                    **({"verified": verified, "validation": f"exit {exit_code}"} if validate_cmd else {}),
                    **({"worktree": kept} if wt_branch else {}),
                },
                producer="task",
            )
            print(f"  [info] child {child_session.run_id[:16]}: {status}, verified={verified}, "
                  f"{receipts} receipt(s), wt={wt_branch or 'none'}")
            print(f"  [info] child summary: {summary[:140]!r}")
            return {"task_run_id": child_session.run_id, "status": status, "summary": summary,
                    "receipts": receipts, "verified": verified, "worktree": kept}

        def spawn_tasks(specs: list[dict]) -> list[dict]:
            with ThreadPoolExecutor(max_workers=min(4, len(specs))) as pool:
                futures = [
                    pool.submit(spawn, s["task"], s.get("validate", ""), s.get("worktree", False))
                    for s in specs
                ]
                return [f.result() for f in futures]

        engine, bridge = _engine(root, session, spawn, spawn_tasks, p_authorize, p_cmd, p_patch, p_bash)
        bridge.start()
        engine.start(bridge)
        answer = engine.ask(
            "Delegate via openpilot_tasks IN PARALLEL (both at once): task one - a subagent "
            "creates notes/result-a.txt containing exactly ALPHA-111, with a validate command; "
            "task two - a subagent creates notes/result-b.txt containing exactly BETA-222 "
            "inside its own git worktree, with a validate command. Relay both results.",
            first_turn=True,
        )
        engine.stop()
        bridge.stop()

        parent_types = {e.event_type for e in session.load_events()}
        ledgers = list((root / ".openpilot" / "trajectory").glob("run_*.jsonl"))
        spawned = [json.loads(l)["payload"]["task_run_id"]
                   for p in ledgers for l in p.read_text(encoding="utf-8").splitlines()
                   if '"task_spawned"' in l and '"record": "schema"' not in l]
        admission_in_children = 0
        for ledger in ledgers:
            text = ledger.read_text(encoding="utf-8")
            if "task_spawned" not in text:
                admission_in_children += sum(text.count(f'"{t}"') for t in
                                             ("patch_proposed", "consent_bound", "patch_authorized"))
        checks = [
            ("parent model called openpilot_tasks", "task_spawned" in parent_types),
            ("two children spawned", len(spawned) >= 2),
            ("children have distinct ledgers", len(ledgers) >= 3),  # parent + 2 children
            ("child admission events in child ledgers (phase 3)", admission_in_children > 0),
            ("no CHILD admission events leaked into parent ledger",
             "patch_proposed" not in parent_types),  # the delegation approval
            # itself (command_proposed/consent_bound) legitimately lives in
            # the parent ledger; only child WRITE proposals must not leak
            ("answer carries both codes", "ALPHA-111" in answer and "BETA-222" in answer),
        ]
        print("answer:", answer[:260].replace("\n", " "))
        for check, ok in checks:
            print(f"  [{'ok' if ok else 'FAIL'}] {check}")
        return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
