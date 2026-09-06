"""op0 CLI: claude-code-style REPL over the Pi execution base.

L1: patches are demand-driven admitted — no write without an approved consent.
L2: every applied patch yields a durable receipt (file hashes); a run closes
only on validation evidence. What the model says is never evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from op0.admission import AdmissionRegistry, Proposal
from op0.bridge import ReadOnlyToolBridge
from op0.contracts import TaskSpec
from op0.engine import Engine, EngineConfig
from op0.receipts import ReceiptStore, decide_closure, file_hash, record_validation
from op0.recovery import reconcile, resume_plan
from op0.session import Session


def _print_response(text: str) -> None:
    print()
    print(text if text else "(no model response observed)")
    print()


def _proposal_json(proposal: Proposal) -> str:
    payload: dict[str, object] = {
        "proposal_id": proposal.proposal_id,
        "task_id": proposal.grant.task_id,
        "kind": proposal.grant.kind,
        "goal": proposal.grant.goal,
        "write_paths": list(proposal.grant.write_paths),
        "read_roots": list(proposal.grant.read_roots),
        "status": proposal.status,
    }
    if proposal.grant.command:
        payload["command"] = proposal.grant.command
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _closure_summary(store: ReceiptStore, run_id: str, saw_model_response: bool) -> str:
    status, reason = decide_closure(store.all(run_id=run_id), saw_model_response=saw_model_response)
    return f"closure: {status} — {reason}"


def _apply_patch_receipt(
    store: ReceiptStore,
    session: Session,
    registry: AdmissionRegistry,
    path: str,
    hash_before: str,
    hash_after: str,
    consent,
) -> None:
    receipt = store.write_patch_receipt(
        run_id=session.run_id,
        consent_id=consent.consent_id,
        proposal_id=consent.proposal_id,
        admission_id=consent.admission_id,
        path=path,
        hash_before=hash_before,
        hash_after=hash_after,
        validation_command=consent.validation_command,
    )
    session.record(
        "patch_receipt_written",
        {
            "receipt_id": receipt.receipt_id,
            "path": path,
            "hash_before": hash_before,
            "hash_after": hash_after,
            "validation_status": receipt.validation_status,
        },
        producer="receipts",
    )
    if receipt.validation_command:
        updated, completed = record_validation(
            store, receipt, command=receipt.validation_command, cwd=registry.project_root
        )
        session.record(
            "validation_completed",
            {
                "receipt_id": updated.receipt_id,
                "command": updated.validation_command,
                "returncode": completed.returncode,
                "status": updated.validation_status,
            },
            producer="receipts",
        )


def _validate_command(store: ReceiptStore, session: Session, command: str) -> None:
    pending = store.pending_for_run(session.run_id)
    if not pending:
        print("(no pending receipt to validate in this run)")
        return
    receipt = pending[-1]
    try:
        updated, completed = record_validation(store, receipt, command=command, cwd=session.project_root)
    except subprocess.TimeoutExpired:
        print("(validation timed out)")
        return
    session.record(
        "validation_completed",
        {
            "receipt_id": updated.receipt_id,
            "command": command,
            "returncode": completed.returncode,
            "status": updated.validation_status,
        },
        producer="receipts",
    )
    print(f"validation {updated.validation_status} (exit {completed.returncode}) for {updated.receipt_id}")


def _print_recovery_report(store: ReceiptStore, run_id: str | None) -> None:
    """Startup recovery: classify durable receipts against disk; read-only."""
    reconciled = reconcile(store, run_id=run_id)
    if not reconciled:
        return
    status, actions = resume_plan(reconciled)
    print(f"— recovery: {len(reconciled)} durable receipt(s) found, state={status}")
    for item in reconciled:
        marker = {"applied": "on-disk", "reverted": "reverted", "missing": "missing", "mismatch": "changed"}[
            item.disk_state
        ]
        print(
            f"    {item.receipt.receipt_id} {marker} "
            f"validation={item.receipt.validation_status} path={Path(item.receipt.path).name}"
        )
    for action in actions:
        print(f"    -> {action}")
    print()


def run_once_task(spec: TaskSpec) -> str:
    """Single-shot path (--once): read-only only; patches need the REPL flow."""
    session = Session(spec.resolved_root())
    session.record("task_received", {"goal": spec.goal, "project_root": spec.project_root})
    registry = AdmissionRegistry(spec.project_root)
    store = ReceiptStore(spec.project_root)
    bridge = _make_bridge(session, registry, store, spec.project_root, current_goal=spec.goal)
    bridge.start()
    engine = Engine(session, _engine_config(spec))
    try:
        return engine.run_once(spec, bridge=bridge)
    finally:
        if bridge is not None:
            bridge.stop()


def _make_bridge(
    session: Session,
    registry: AdmissionRegistry,
    store: ReceiptStore,
    project_root: str,
    *,
    current_goal: str,
) -> ReadOnlyToolBridge:
    def authorize(raw_path: str):
        canonical = str(Path(raw_path).expanduser().resolve(strict=False))
        try:
            consent = registry.authorize_patch(canonical, session.run_id)
            session.record(
                "patch_authorized",
                {"path": canonical, "consent_id": consent.consent_id},
                producer="admission",
            )
            return consent
        except PermissionError:
            proposal = registry.propose(current_goal, raw_path, (project_root,))
            session.record(
                "patch_proposed",
                {
                    "proposal_id": proposal.proposal_id,
                    "kind": proposal.grant.kind,
                    "path": canonical,
                    "write_paths": list(proposal.grant.write_paths),
                },
                producer="admission",
            )
            raise

    def authorize_cmd(command: str):
        try:
            consent = registry.authorize_command(command, session.run_id)
            session.record(
                "command_authorized",
                {"command": command, "consent_id": consent.consent_id},
                producer="admission",
            )
            return consent
        except PermissionError:
            proposal = registry.propose_command(current_goal, command)
            session.record(
                "command_proposed",
                {"proposal_id": proposal.proposal_id, "command": command},
                producer="admission",
            )
            raise

    def on_patch_applied(path: str, hash_before: str, hash_after: str, consent) -> None:
        _apply_patch_receipt(store, session, registry, path, hash_before, hash_after, consent)

    def on_bash_executed(command: str, exit_code: int, output: str, consent) -> None:
        receipt = store.write_bash_receipt(
            run_id=session.run_id,
            consent_id=consent.consent_id,
            proposal_id=consent.proposal_id,
            admission_id=consent.admission_id,
            command=command,
            exit_code=exit_code,
            output_tail=output,
        )
        session.record(
            "bash_receipt_written",
            {
                "receipt_id": receipt.receipt_id,
                "command": command,
                "exit_code": exit_code,
                "validation_status": receipt.validation_status,
            },
            producer="receipts",
        )

    return ReadOnlyToolBridge(
        (project_root,),
        patch_authorizer=authorize,
        command_authorizer=authorize_cmd,
        on_patch_applied=on_patch_applied,
        on_bash_executed=on_bash_executed,
        on_request=lambda payload: session.record(
            "tool_call", payload, producer="bridge", call_id=str(payload.get("toolCallId") or "")
        ),
        on_result=lambda payload: session.record(
            "tool_result", payload, producer="bridge", call_id=str(payload.get("toolCallId") or "")
        ),
    )


def _engine_config(spec: TaskSpec) -> EngineConfig:
    return EngineConfig(
        provider=str(os.environ.get("OP0_PI_PROVIDER") or ""),
        model=str(os.environ.get("OP0_PI_MODEL") or ""),
        cwd=spec.project_root,
        timeout_seconds=spec.timeout_seconds,
        enable_read_tool=True,
    )


def _run_repl(project_root: Path) -> int:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.history import InMemoryHistory

    session: PromptSession[str] = PromptSession(
        history=InMemoryHistory(),
        auto_suggest=AutoSuggestFromHistory(),
    )
    print("op0 L4 - full tool surface, every side effect admitted and receipted. /help for commands.")

    traj = Session(project_root)
    traj.record("session_started", {"project_root": str(project_root)})
    registry = AdmissionRegistry(str(project_root))
    store = ReceiptStore(project_root)
    _print_recovery_report(store, None)
    engine = Engine(traj, _engine_config(TaskSpec(goal="", project_root=str(project_root))))

    state = {"goal": "", "saw_response": False}

    def authorize(raw_path: str):
        canonical = str(Path(raw_path).expanduser().resolve(strict=False))
        try:
            consent = registry.authorize_patch(canonical, traj.run_id)
            traj.record(
                "patch_authorized",
                {"path": canonical, "consent_id": consent.consent_id},
                producer="admission",
            )
            return consent
        except PermissionError:
            proposal = registry.propose(state["goal"], raw_path, (str(project_root),))
            traj.record(
                "patch_proposed",
                {
                    "proposal_id": proposal.proposal_id,
                    "kind": proposal.grant.kind,
                    "path": canonical,
                    "write_paths": list(proposal.grant.write_paths),
                },
                producer="admission",
            )
            raise

    def authorize_cmd(command: str):
        try:
            consent = registry.authorize_command(command, traj.run_id)
            traj.record(
                "command_authorized",
                {"command": command, "consent_id": consent.consent_id},
                producer="admission",
            )
            return consent
        except PermissionError:
            proposal = registry.propose_command(state["goal"], command)
            traj.record(
                "command_proposed",
                {"proposal_id": proposal.proposal_id, "command": command},
                producer="admission",
            )
            raise

    def on_patch_applied(path: str, hash_before: str, hash_after: str, consent) -> None:
        _apply_patch_receipt(store, traj, registry, path, hash_before, hash_after, consent)

    def on_bash_executed(command: str, exit_code: int, output: str, consent) -> None:
        receipt = store.write_bash_receipt(
            run_id=traj.run_id,
            consent_id=consent.consent_id,
            proposal_id=consent.proposal_id,
            admission_id=consent.admission_id,
            command=command,
            exit_code=exit_code,
            output_tail=output,
        )
        traj.record(
            "bash_receipt_written",
            {
                "receipt_id": receipt.receipt_id,
                "command": command,
                "exit_code": exit_code,
                "validation_status": receipt.validation_status,
            },
            producer="receipts",
        )

    bridge = ReadOnlyToolBridge(
        (str(project_root),),
        patch_authorizer=authorize,
        command_authorizer=authorize_cmd,
        on_patch_applied=on_patch_applied,
        on_bash_executed=on_bash_executed,
        on_request=lambda payload: traj.record(
            "tool_call", payload, producer="bridge", call_id=str(payload.get("toolCallId") or "")
        ),
        on_result=lambda payload: traj.record(
            "tool_result", payload, producer="bridge", call_id=str(payload.get("toolCallId") or "")
        ),
    )
    bridge.start()
    engine.start(bridge)
    first_turn = True
    try:
        while True:
            try:
                line = session.prompt("op0> ")
            except KeyboardInterrupt:
                print("\n(interrupted) type /exit to quit")
                continue
            except EOFError:
                print()
                return 0
            text = line.strip()
            if not text:
                continue
            if text in {"/exit", "/quit", "exit", "quit", ":q"}:
                return 0
            if text == "/help":
                print(
                    "Writes and bash need /approve <id> [validation command] or /approve all; "
                    "/validate <command> closes a receipt; /recover /proposals /new /clear /exit"
                )
                continue
            if text == "/recover":
                _print_recovery_report(store, None)
                continue
            if text == "/proposals":
                pending = registry.pending()
                if not pending:
                    print("(no pending proposals)")
                for proposal in pending:
                    print(_proposal_json(proposal))
                continue
            if text.startswith("/approve"):
                parts = text.split(maxsplit=2)
                target = parts[1] if len(parts) > 1 else ""
                command = parts[2].strip() if len(parts) > 2 else ""
                if target == "all":
                    try:
                        consent, approved_ids = registry.approve_all(traj.run_id, validation_command=command)
                    except Exception as exc:  # noqa: BLE001
                        print(f"approve failed: {exc}")
                        continue
                    traj.record(
                        "consent_bound",
                        {
                            "consent_id": consent.consent_id,
                            "proposal_ids": list(approved_ids),
                            "run_id": consent.run_id,
                            "batch": True,
                            "validation_command": consent.validation_command,
                        },
                        producer="admission",
                    )
                    print(f"approved {len(approved_ids)} proposal(s) as {consent.consent_id} — retry the task.")
                    continue
                proposal_id = target
                try:
                    consent = registry.approve(proposal_id, traj.run_id, validation_command=command)
                except Exception as exc:  # noqa: BLE001
                    print(f"approve failed: {exc}")
                    continue
                traj.record(
                    "consent_bound",
                    {
                        "consent_id": consent.consent_id,
                        "proposal_id": consent.proposal_id,
                        "run_id": consent.run_id,
                        "validation_command": consent.validation_command,
                    },
                    producer="admission",
                )
                hint = f" auto-validates with: {command}" if command else " (no validation yet — /validate closes it)"
                print(f"approved: {consent.consent_id} — retry the task.{hint}")
                continue
            if text.startswith("/validate"):
                parts = text.split(maxsplit=1)
                command = parts[1].strip() if len(parts) > 1 else ""
                if not command:
                    print("usage: /validate <command>")
                    continue
                _validate_command(store, traj, command)
                print(_closure_summary(store, traj.run_id, state["saw_response"]))
                continue
            if text.startswith("/deny"):
                parts = text.split()
                proposal_id = parts[1] if len(parts) > 1 else ""
                try:
                    denied = registry.deny(proposal_id)
                except Exception as exc:  # noqa: BLE001
                    print(f"deny failed: {exc}")
                    continue
                traj.record("proposal_denied", {"proposal_id": denied.proposal_id}, producer="admission")
                print(f"denied: {denied.proposal_id}")
                continue
            if text == "/new":
                traj.record("conversation_reset", {})
                traj = Session(project_root)
                engine.session = traj
                state["saw_response"] = False
                first_turn = True
                print("(new conversation)")
                continue
            if text == "/clear":
                print("\033[2J\033[H", end="")
                continue

            state["goal"] = text
            traj.record("task_received", {"goal": text})
            response = engine.ask(text, first_turn=first_turn)
            first_turn = False
            if response:
                state["saw_response"] = True
            traj.record("run_finished", {"response_chars": len(response)})
            if engine.state.value == "crashed":
                print("(engine crashed; restarting for next turn)")
                engine.start(bridge)
                first_turn = True
            _print_response(response)
            pending = registry.pending()
            for proposal in pending:
                print("— patch proposal (needs approval):")
                print(_proposal_json(proposal))
            if pending:
                print(f"/approve {pending[0].proposal_id} [validation command] then retry.\n")
            else:
                print(_closure_summary(store, traj.run_id, state["saw_response"]))
    finally:
        engine.stop()
        bridge.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="op0", description="op0 L2 execution base")
    parser.add_argument("--once", help="run one read-only goal and exit")
    parser.add_argument("--project-path", default=".", help="project root for this task")
    args = parser.parse_args(argv)
    project_root = Path(args.project_path).expanduser().resolve(strict=False)

    if args.once:
        response = run_once_task(TaskSpec(goal=args.once, project_root=str(project_root)))
        _print_response(response)
        return 0 if response else 1
    return _run_repl(project_root)


if __name__ == "__main__":
    sys.exit(main())
