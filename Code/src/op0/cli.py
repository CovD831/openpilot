"""op0 CLI: claude-code-style REPL over the Pi execution base.

Layering: admission gates writes and commands; receipts and closure are
evidence-driven; this CLI is a projection — everything it shows comes from
the trajectory, the registry, and the receipt store, and nothing it renders
can alter a recorded decision.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from op0 import ui
from op0.admission import AdmissionRegistry, Proposal
from op0.bridge import ReadOnlyToolBridge
from op0.contracts import TaskSpec
from op0.engine import Engine, EngineConfig
from op0.receipts import ReceiptStore, decide_closure, file_hash, record_validation
from op0.recovery import reconcile, resume_plan
from op0.session import Session


def _closure_summary(store: ReceiptStore, run_id: str, saw_model_response: bool) -> tuple[str, str]:
    return decide_closure(store.all(run_id=run_id), saw_model_response=saw_model_response)


def _apply_patch_receipt(store, session, registry, path, hash_before, hash_after, consent) -> None:
    receipt = store.write_patch_receipt(
        run_id=session.run_id,
        consent_id=consent.consent_id,
        proposal_id=consent.proposal_id,
        admission_id=consent.admission_id,
        path=path,
        hash_before=hash_before,
        hash_after=hash_after,
        validation_command=consent.validation_command,
        kind=consent.kind,
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


def _make_bridge(session, registry, store, project_root: str, *, goal_state: dict) -> ReadOnlyToolBridge:
    def authorize(raw_path: str, args: dict):
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
            kind = "patch" if "lineStart" in args else "write"
            diff = ui.make_diff_preview(kind, args, project_root)
            proposal = registry.propose(
                goal_state["goal"], canonical, (project_root,), kind=kind, diff_preview=diff
            )
            session.record(
                "patch_proposed",
                {
                    "proposal_id": proposal.proposal_id,
                    "kind": kind,
                    "path": canonical,
                    "write_paths": list(proposal.grant.write_paths),
                },
                producer="admission",
            )
            raise

    def authorize_cmd(command: str, args: dict):
        try:
            consent = registry.authorize_command(command, session.run_id)
            session.record(
                "command_authorized",
                {"command": command, "consent_id": consent.consent_id},
                producer="admission",
            )
            return consent
        except PermissionError:
            proposal = registry.propose_command(goal_state["goal"], command)
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
        on_request=lambda payload: (
            session.record(
                "tool_call", payload, producer="bridge", call_id=str(payload.get("toolCallId") or "")
            ),
            tool_state.append(payload),
        )[0],
        on_result=lambda payload: (
            session.record(
                "tool_result", payload, producer="bridge", call_id=str(payload.get("toolCallId") or "")
            ),
            tool_state.clear(),
        )[0],
    )


tool_state: list = []  # last in-flight tool call (projection only)


def _engine_config(spec: TaskSpec) -> EngineConfig:
    return EngineConfig(
        provider=str(os.environ.get("OP0_PI_PROVIDER") or ""),
        model=str(os.environ.get("OP0_PI_MODEL") or ""),
        cwd=spec.project_root,
        timeout_seconds=spec.timeout_seconds,
        enable_read_tool=True,
    )


def _run_task_with_spinner(engine: Engine, prompt: str, *, first_turn: bool) -> str:
    """Run one turn on a worker thread while a live status shows tool activity."""
    result: dict[str, str] = {}

    def worker() -> None:
        try:
            result["response"] = engine.ask(prompt, first_turn=first_turn)
        except Exception as exc:  # noqa: BLE001
            result["response"] = ""
            result["error"] = f"{type(exc).__name__}: {exc}"

    thread = threading.Thread(target=worker, name="op0-turn", daemon=True)
    thread.start()
    with ui.console.status("[dim]op0 working…[/dim]") as status:
        while thread.is_alive():
            if tool_state:
                latest = tool_state[-1]
                status.update(ui.tool_status_line(str(latest.get("toolName") or ""), json.dumps(latest.get("args") or {})))
            time.sleep(0.12)
        thread.join()
    if result.get("error"):
        ui.console.print(f"[red]turn error:[/red] {result['error']}")
    return result.get("response", "")


def _ask_and_show(engine: Engine, traj: Session, store: ReceiptStore, state: dict, text: str, *, first_turn: bool) -> None:
    traj.record("task_received", {"goal": text})
    response = _run_task_with_spinner(engine, text, first_turn=first_turn)
    if response:
        state["saw_response"] = True
    traj.record("run_finished", {"response_chars": len(response)})
    if engine.state.value == "crashed":
        ui.console.print("[yellow](engine crashed; restarting for next turn)[/yellow]")
    events = traj.load_events()
    turn_start = max(
        (i for i, e in enumerate(events) if e.event_type == "turn_started"), default=None
    )
    if turn_start is not None:
        ui.render_turn_tools(events[turn_start:], verbose=state["verbose"])
    ui.markdown_response(response)
    status, reason = _closure_summary(store, traj.run_id, state["saw_response"])
    ui.closure_line(status, reason)


def _handle_pending(registry: AdmissionRegistry, traj: Session, store: ReceiptStore, state: dict, prompt_session) -> str:
    """Show pending proposals and apply the answer.

    Returns "approved" | "denied" | "" — "approved" means the caller should
    re-run the pending task immediately (approval is the continue).
    """
    pending = registry.pending()
    if not pending:
        return ""
    ui.proposal_panel(pending[0])
    if len(pending) > 1:
        ui.console.print(f"[yellow]({len(pending)} proposals pending — 'a' approves all)[/yellow]")
    answer = prompt_session.prompt("[y/n/a] approve? ").strip().lower()
    try:
        if answer in ("y", "yes"):
            consent = registry.approve(pending[0].proposal_id, traj.run_id)
            traj.record(
                "consent_bound",
                {"consent_id": consent.consent_id, "proposal_id": consent.proposal_id, "run_id": consent.run_id},
                producer="admission",
            )
            ui.console.print(f"[green]approved[/green] {consent.consent_id}\n")
            return "approved"
        if answer in ("a", "all"):
            consent, ids = registry.approve_all(traj.run_id)
            traj.record(
                "consent_bound",
                {"consent_id": consent.consent_id, "proposal_ids": list(ids), "run_id": consent.run_id, "batch": True},
                producer="admission",
            )
            ui.console.print(f"[green]approved {len(ids)} proposal(s)[/green] as {consent.consent_id}\n")
            return "approved"
        if answer in ("n", "no"):
            denied = registry.deny(pending[0].proposal_id)
            traj.record("proposal_denied", {"proposal_id": denied.proposal_id}, producer="admission")
            ui.console.print(f"[red]denied[/red] {denied.proposal_id}")
            return "denied"
    except Exception as exc:  # noqa: BLE001
        ui.console.print(f"[red]approval failed:[/red] {exc}")
    return ""


def run_once_task(spec: TaskSpec) -> str:
    """Single-shot path (--once): read-only; writes need the REPL flow."""
    session = Session(spec.resolved_root())
    session.record("task_received", {"goal": spec.goal, "project_root": spec.project_root})
    registry = AdmissionRegistry(spec.project_root)
    store = ReceiptStore(spec.project_root)
    goal_state = {"goal": spec.goal}
    bridge = _make_bridge(session, registry, store, spec.project_root, goal_state=goal_state)
    bridge.start()
    engine = Engine(session, _engine_config(spec))
    try:
        return engine.run_once(spec, bridge=bridge)
    finally:
        if bridge is not None:
            bridge.stop()


def _validate_command(store: ReceiptStore, session: Session, command: str) -> None:
    pending = store.pending_for_run(session.run_id)
    if not pending:
        ui.console.print("(no pending receipt to validate in this run)")
        return
    receipt = pending[-1]
    try:
        updated, completed = record_validation(store, receipt, command=command, cwd=session.project_root)
    except subprocess.TimeoutExpired:
        ui.console.print("(validation timed out)")
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
    ui.console.print(
        f"validation [{'green' if updated.validation_status == 'passed' else 'red'}]{updated.validation_status}[/{updated.validation_status}]"
        f" (exit {completed.returncode}) for {updated.receipt_id}"
    )


def _recovery_report_to_str(store: ReceiptStore, run_id: str | None) -> str:
    """Recovery report rendered to an ANSI string (projection)."""
    import io

    reconciled = reconcile(store, run_id=run_id)
    if not reconciled:
        return ""
    status, actions = resume_plan(reconciled)
    width = ui.console.width
    from rich.console import Console as RichConsole

    buf = io.StringIO()
    previous = ui.console
    ui.console = RichConsole(file=buf, force_terminal=True, width=width)
    try:
        ui.recovery_report(reconciled, status, actions)
    finally:
        ui.console = previous
    return buf.getvalue()

def _run_repl(project_root: Path) -> int:
    from op0.tui import TuiSession

    traj = Session(project_root)
    traj.record("session_started", {"project_root": str(project_root)})
    registry = AdmissionRegistry(str(project_root))
    store = ReceiptStore(project_root)
    state = {"goal": "", "saw_response": False, "verbose": False}
    bridge = _make_bridge(traj, registry, store, str(project_root), goal_state=state)
    engine = Engine(traj, _engine_config(TaskSpec(goal="", project_root=str(project_root))))

    def handle_command(text: str) -> None:
        parts = text.split(maxsplit=1)
        cmd = parts[0]
        rest = parts[1].strip() if len(parts) > 1 else ""
        if cmd == "/help":
            tui.append_block(
                "[dim]reads free · writes/bash approved (y/n/a) · /validate <cmd> · "
                "/dismiss <id> · /recover /proposals /verbose /new /clear /exit[/dim]"
            )
        elif cmd == "/verbose":
            state["verbose"] = not state["verbose"]
            tui.append_block(f"[dim]verbose = {state['verbose']}[/dim]")
        elif cmd == "/new":
            traj.record("conversation_reset", {})
            tui.traj = Session(project_root)
            engine.session = tui.traj
            state["saw_response"] = False
            tui.append_block("[dim](new conversation)[/dim]")
        elif cmd == "/recover":
            report = _recovery_report_to_str(store, None)
            tui.append_block(report or "[dim](nothing to recover)[/dim]")
        elif cmd == "/proposals":
            pending = registry.pending()
            if not pending:
                tui.append_block("[dim](no pending proposals)[/dim]")
            for proposal in pending:
                tui.append_block(ui.render_proposal_to_str(proposal))
        elif cmd == "/approve" and rest:
            sub = rest.split(maxsplit=1)
            target, command = sub[0], (sub[1].strip() if len(sub) > 1 else "")
            try:
                if target == "all":
                    consent, ids = registry.approve_all(traj.run_id, validation_command=command)
                    traj.record(
                        "consent_bound",
                        {"consent_id": consent.consent_id, "proposal_ids": list(ids), "batch": True},
                        producer="admission",
                    )
                    tui.append_block(f"[green]approved {len(ids)} proposal(s)[/green] as {consent.consent_id}")
                else:
                    consent = registry.approve(target, traj.run_id, validation_command=command)
                    traj.record(
                        "consent_bound",
                        {"consent_id": consent.consent_id, "proposal_id": consent.proposal_id},
                        producer="admission",
                    )
                    tui.append_block(f"[green]approved[/green] {consent.consent_id}")
            except Exception as exc:  # noqa: BLE001
                tui.append_block(f"[red]approve failed:[/red] {exc}")
        elif cmd == "/deny" and rest:
            try:
                denied = registry.deny(rest)
                traj.record("proposal_denied", {"proposal_id": denied.proposal_id}, producer="admission")
                tui.append_block(f"[red]denied[/red] {rest}")
            except Exception as exc:  # noqa: BLE001
                tui.append_block(f"[red]deny failed:[/red] {exc}")
        elif cmd == "/validate" and rest:
            pending = store.pending_for_run(traj.run_id)
            if not pending:
                tui.append_block("[dim](no pending receipt to validate)[/dim]")
            else:
                try:
                    updated, completed = record_validation(
                        store, pending[-1], command=rest, cwd=traj.project_root
                    )
                    traj.record(
                        "validation_completed",
                        {"receipt_id": updated.receipt_id, "returncode": completed.returncode,
                         "status": updated.validation_status},
                        producer="receipts",
                    )
                    tui.append_block(
                        f"validation [{updated.validation_status}] exit {completed.returncode} for {updated.receipt_id}"
                    )
                except subprocess.TimeoutExpired:
                    tui.append_block("[yellow](validation timed out)[/yellow]")
        elif cmd == "/dismiss" and rest:
            receipt = store.load(rest)
            if receipt is None:
                tui.append_block(f"[red]unknown receipt:[/red] {rest}")
            else:
                retracted = type(receipt)(**{**receipt.__dict__, "validation_status": "dismissed"})
                store.save(retracted)
                traj.record("receipt_dismissed", {"receipt_id": rest, "path": receipt.path}, producer="receipts")
                tui.append_block(f"[dim]dismissed[/dim] {rest}")
        elif cmd == "/clear":
            tui.blocks.clear()
            tui.append_block(f"[dim]◆ op0 v{_version()} — project: {project_root}[/dim]")
        else:
            tui.append_block(f"[dim]unknown command: {cmd} — /help[/dim]")

    tui = TuiSession(
        project_root,
        traj,
        registry,
        store,
        bridge,
        engine,
        version=_version(),
        on_command=handle_command,
        state=state,
    )
    report = _recovery_report_to_str(store, None)
    if report:
        tui.append_block(report)
    engine.start(bridge)
    return tui.run()



def _version() -> str:
    from op0 import __version__

    return __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="op0", description="op0 L4 execution base")
    parser.add_argument("--once", help="run one read-only goal and exit")
    parser.add_argument("--project-path", default=".", help="project root for this task")
    args = parser.parse_args(argv)
    project_root = Path(args.project_path).expanduser().resolve(strict=False)

    if args.once:
        response = run_once_task(TaskSpec(goal=args.once, project_root=str(project_root)))
        ui.markdown_response(response)
        return 0 if response else 1
    return _run_repl(project_root)


if __name__ == "__main__":
    sys.exit(main())
