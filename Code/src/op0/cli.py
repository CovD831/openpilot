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
from rich.markup import escape
from op0 import skills as skills_mod
from op0 import skills as skills_mod
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


def _make_bridge(
    session,
    registry,
    store,
    project_root: str,
    *,
    goal_state: dict,
    gate_holder: dict | None = None,
    observations_dir: str | None = None,
    timeout_seconds: float = 180.0,
) -> ReadOnlyToolBridge:
    gate = gate_holder if gate_holder is not None else {"fn": None}

    def _auto_consent(proposal):
        """Auto mode: approved the moment it exists (still recorded; consent_bound carries auto: true)."""
        consent = registry.approve(proposal.proposal_id, session.run_id)
        session.record(
            "consent_bound",
            {"consent_id": consent.consent_id, "proposal_id": consent.proposal_id, "auto": True},
            producer="admission",
        )
        session.record(
            "patch_authorized",
            {"consent_id": consent.consent_id, "auto": True},
            producer="admission",
        )
        return consent

    def _gate_consent(proposal):
        """Tool-call-time approval (claude-code semantics): block the tool
        call until the human answers the card. "y"/"a" -> consent now and the
        same call executes; "n" -> refusal telling the model to adapt instead
        of retrying; "" (timeout) -> the proposal stays pending and the model
        is told to stop this turn, never denied behind the human's back."""
        answer = gate["fn"](proposal) if gate["fn"] else ""
        if answer in ("y", "a"):
            consent = registry.approve(proposal.proposal_id, session.run_id)
            session.record(
                "consent_bound",
                {"consent_id": consent.consent_id, "proposal_id": consent.proposal_id, "run_id": consent.run_id},
                producer="admission",
            )
            return consent
        if answer == "":
            session.record(
                "approval_timeout", {"proposal_id": proposal.proposal_id}, producer="admission"
            )
            raise PermissionError(
                "approval is still pending — the human has not answered the card; "
                "stop this turn and wait for their decision"
            )
        registry.deny(proposal.proposal_id)
        session.record(
            "proposal_denied",
            {"proposal_id": proposal.proposal_id, "gate": True},
            producer="admission",
        )
        raise PermissionError(
            "denied by the human — do not retry the same call; briefly "
            "acknowledge the denial and ask what to do differently"
        )

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
            if goal_state.get("approval_mode") == "auto":
                return _auto_consent(proposal)
            if gate["fn"] is not None:
                return _gate_consent(proposal)
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
            if goal_state.get("approval_mode") == "auto":
                return _auto_consent(proposal)
            if gate["fn"] is not None:
                return _gate_consent(proposal)
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

    def _spawn_task(task_prompt: str) -> dict:
        """Subagent: a full op0 run in a child context. Child carries its own
        ledger and engine; approvals surface on the SAME human gate (the
        registry is shared, keyed by run id); the child bridge has no
        spawner, so nesting is impossible by construction. KNOWN COMPROMISE:
        the child's admission events land in the parent ledger (the
        authorizers are shared closures); splitting them needs an
        authorizer-parameterization pass (phase 2)."""
        child_session = Session(Path(project_root))
        child_store = ReceiptStore(Path(project_root))
        child_bridge = ReadOnlyToolBridge(
            (project_root,),
            observations_dir=observations_dir,
            patch_authorizer=authorize,
            command_authorizer=authorize_cmd,
            on_patch_applied=on_patch_applied,
            on_bash_executed=on_bash_executed,
        )
        child_engine = Engine(
            child_session,
            EngineConfig(
                provider=str(os.environ.get("OP0_PI_PROVIDER") or ""),
                model=str(os.environ.get("OP0_PI_MODEL") or ""),
                cwd=project_root,
                timeout_seconds=timeout_seconds,
                enable_read_tool=True,
                context_budget_tokens=0,
                observations_dir=observations_dir,
            ),
        )
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
                "You are an op0 subagent running one delegated task. Complete it "
                "and report concisely; the parent decides what to do with your "
                "report. Task:\n" + task_prompt,
                first_turn=True,
            )
            # fail-closed: an empty report is an incomplete run, never success
            if answer.strip():
                status, summary = "success", answer[:2000]
            else:
                summary = "subagent returned no report"[:2000]
        except Exception as exc:  # noqa: BLE001 - a child failure must not kill the parent run
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
        return {
            "task_run_id": child_session.run_id,
            "status": status,
            "summary": summary,
            "receipts": receipts,
        }

    return ReadOnlyToolBridge(
        (project_root,),
        observations_dir=observations_dir,
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
        task_spawner=_spawn_task,
    )


tool_state: list = []  # last in-flight tool call (projection only)


def _engine_config(spec: TaskSpec) -> EngineConfig:
    return EngineConfig(
        provider=str(os.environ.get("OP0_PI_PROVIDER") or ""),
        model=str(os.environ.get("OP0_PI_MODEL") or ""),
        cwd=spec.project_root,
        timeout_seconds=spec.timeout_seconds,
        enable_read_tool=True,
        context_budget_tokens=int(os.environ.get("OP0_CONTEXT_BUDGET_TOKENS") or 0),
        observations_dir=str(Path(spec.project_root) / ".openpilot" / "observations"),
    )


def run_once_task(spec: TaskSpec) -> str:
    """Single-shot path (--once): read-only; writes need the REPL flow."""
    session = Session(spec.resolved_root())
    session.record("task_received", {"goal": spec.goal, "project_root": spec.project_root})
    registry = AdmissionRegistry(spec.project_root)
    store = ReceiptStore(spec.project_root)
    goal_state = {"goal": spec.goal}
    bridge = _make_bridge(
        session, registry, store, spec.project_root, goal_state=goal_state,
        timeout_seconds=spec.timeout_seconds,
        observations_dir=str(Path(spec.project_root) / ".openpilot" / "observations"),
    )
    bridge.start()
    engine = Engine(session, _engine_config(spec))
    try:
        response = engine.run_once(spec, bridge=bridge)
        if not response:
            ui.console.print(ui.model_error_markup(session.last_model_error()))
        return response
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
    from rich.console import Console as RichConsole

    capture = RichConsole(
        file=io.StringIO(), force_terminal=True, color_system="truecolor", width=ui.console.width
    )
    ui.recovery_report(reconciled, status, actions, console=capture)
    return capture.file.getvalue()

def _run_repl(project_root: Path) -> int:
    from op0.tui import TuiSession

    traj = Session(project_root)
    traj.record("session_started", {"project_root": str(project_root)})
    registry = AdmissionRegistry(str(project_root))
    store = ReceiptStore(project_root)
    state = {"goal": "", "saw_response": False, "verbose": False, "approval_mode": "ask"}
    gate = {"fn": None}
    spec = TaskSpec(goal="", project_root=str(project_root))
    bridge = _make_bridge(
        traj, registry, store, str(project_root), goal_state=state, gate_holder=gate,
        observations_dir=str(project_root / ".openpilot" / "observations"),
        timeout_seconds=spec.timeout_seconds,
    )
    engine = Engine(traj, _engine_config(spec))

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
        elif cmd == "/skill":
            found = skills_mod.discover(registry.project_root)
            if not found:
                tui.append_block("[dim](no skills installed)[/dim]")
            for name, text, path in found:
                tui.append_block(f"[bold]{escape(name)}[/bold] — {escape(text)}\n[dim]{escape(str(path))}[/dim]")
        elif cmd == "/skill":
            found = skills_mod.discover(registry.project_root)
            if not found:
                tui.append_block("[dim](no skills installed)[/dim]")
            for name, text, path in found:
                tui.append_block(f"[bold]{escape(name)}[/bold] — {escape(text)}\n[dim]{escape(str(path))}[/dim]")
        elif cmd == "/proposals":
            pending = registry.pending()
            if not pending:
                tui.append_block("[dim](no pending proposals)[/dim]")
            for proposal in pending:
                tui._emit_ansi(ui.render_proposal_to_str(proposal))
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
                tui.append_block(f"[red]approve failed:[/red] {escape(exc)}")
        elif cmd == "/deny" and rest:
            try:
                denied = registry.deny(rest)
                traj.record("proposal_denied", {"proposal_id": denied.proposal_id}, producer="admission")
                tui.append_block(f"[red]denied[/red] {rest}")
            except Exception as exc:  # noqa: BLE001
                tui.append_block(f"[red]deny failed:[/red] {escape(exc)}")
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
        elif cmd == "/mode":
            new_mode = "auto" if state.get("approval_mode", "ask") == "ask" else "ask"
            state["approval_mode"] = new_mode
            traj.record("approval_mode_changed", {"mode": new_mode}, producer="tui")
            tui.append_block(f"[yellow]approval mode: {new_mode}[/yellow]")
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
    gate["fn"] = tui.approval_gate  # tool-call-time approvals (cc semantics)
    report = _recovery_report_to_str(store, None)
    if report:
        tui.append_block(report)
    bridge.start()
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
        if response:
            ui.markdown_response(response)
        return 0 if response else 1
    return _run_repl(project_root)


if __name__ == "__main__":
    sys.exit(main())
